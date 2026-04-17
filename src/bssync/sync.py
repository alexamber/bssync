"""Push and pull orchestrators.

`publish_entry` uploads a local markdown file (plus its referenced images
and attachments) to BookStack, creating or updating the page as needed,
and guards against overwriting edits made externally on BookStack.

`pull_entry` is the inverse: downloads a BookStack page's markdown to a
local file, diffing and prompting on conflicts.
"""

import sys
from pathlib import Path

from bssync import term
from bssync.client import BookStackClient
from bssync.config import resolve_file_path
from bssync.conflict import (
    diff_summary,
    extract_tag,
    is_interactive,
    prompt_conflict_action,
    prompt_pull_overwrite,
    set_sync_tag,
)
from bssync.content import (
    find_local_file_links,
    find_local_images,
    extract_title,
    normalized_hash,
    read_markdown,
    replace_file_link_refs,
    replace_image_refs,
    restore_h1,
    strip_title,
)


# ─── Push ───


def publish_entry(client: BookStackClient, entry: dict, config_dir: Path,
                  show_diff: bool = False, force: bool = False) -> bool:
    """Push a single config entry to BookStack. Returns True if changes
    were made, False for no-op.

    Conflict guard: if the BookStack page's current hash differs from the
    content_hash tag set by our last push, we prompt the user (when
    interactive) or skip the entry (non-interactive). `force=True`
    bypasses the check.
    """
    file_path = resolve_file_path(entry["file"], config_dir)
    if not file_path.exists():
        print(f"  {term.warn('SKIP')}: file not found: {file_path}")
        return False

    content = read_markdown(file_path)
    title = entry.get("title") or extract_title(content, file_path.stem)

    if entry.get("strip_title", True):
        content = strip_title(content)

    book_name = entry.get("book", "Documentation")
    book = client.find_book(book_name)
    if not book:
        print(f"  Book '{book_name}' not found — creating")
        book = client.create_book(book_name)

    if client.dry_run and book["id"] == -1:
        print(f"  [dry-run] Would publish: {title}")
        local_images = find_local_images(content, file_path.parent)
        for _, path in local_images:
            print(f"  [dry-run] Would upload image: {path.name}")
        for att in entry.get("attachments", []):
            print(f"  [dry-run] Would upload attachment: {att}")
        return True

    book_id = book["id"]

    chapter_id = None
    chapter_name = entry.get("chapter")
    if chapter_name:
        chapter = client.find_chapter(book_id, chapter_name)
        if not chapter:
            print(f"  Chapter '{chapter_name}' not found — creating")
            chapter = client.create_chapter(book_id, chapter_name)
        if not client.dry_run:
            chapter_id = chapter["id"]

    existing = client.find_page_in_book(book_id, title)

    # Collect files referenced inline and in config
    local_images = find_local_images(content, file_path.parent)
    local_file_links = find_local_file_links(content, file_path.parent)

    config_attachment_paths = [
        resolve_file_path(rel_path, config_dir)
        for rel_path in entry.get("attachments", [])
    ]

    # Merge: content-linked files + config attachments (dedupe by path)
    all_attachment_paths = list({p: p for _, p in local_file_links}.values())
    for p in config_attachment_paths:
        if p not in all_attachment_paths:
            all_attachment_paths.append(p)

    if existing:
        return _update_existing(
            client, entry, file_path, content, title, existing,
            local_images, local_file_links, all_attachment_paths,
            show_diff, force)
    else:
        return _create_new(
            client, entry, content, title, book_id, chapter_id,
            local_images, local_file_links, all_attachment_paths)


def _update_existing(client, entry, file_path, content, title, existing,
                     local_images, local_file_links, all_attachment_paths,
                     show_diff, force) -> bool:
    """Update an existing BookStack page. Handles conflict detection,
    attachment uploads, URL rewriting, and post-push hash reconciliation.
    """
    page_id = existing["id"]

    page_detail = client.get_page(page_id)
    existing_tags = page_detail.get("tags", [])
    last_sync_hash = extract_tag(existing_tags, "content_hash", "")
    remote_markdown = page_detail.get("markdown", "")
    current_remote_hash = (normalized_hash(remote_markdown)
                           if remote_markdown else "")

    # Conflict check
    if (not force and not client.dry_run and last_sync_hash
            and current_remote_hash
            and last_sync_hash != current_remote_hash):
        added, removed = diff_summary(content, remote_markdown)
        if not is_interactive():
            print(f"  {term.warn('CONFLICT')}: \"{title}\" was modified on "
                  f"BookStack since last publish "
                  f"({term.ok(f'+{added}')}/{term.err(f'-{removed}')} lines). "
                  f"Use --force to overwrite.")
            return False
        action = prompt_conflict_action(
            title, remote_markdown, content, added, removed)
        if action == "skip":
            print(f"  {term.warn('SKIPPED')}: {title}")
            return False
        if action == "quit":
            print(term.err("Aborted by user."))
            sys.exit(1)
        if action == "pull":
            local_form = (restore_h1(remote_markdown, title)
                          if entry.get("strip_title", True)
                          else remote_markdown)
            _write_pulled_content(file_path, local_form)
            set_sync_tag(client, page_detail, current_remote_hash,
                         source_file=str(entry["file"]))
            print(f"  {term.ok('PULLED')}: {title} → {file_path}")
            return True
        # action == "overwrite" — proceed with push

    # Upload images + rewrite refs. Listing is a safe GET; upload_image
    # no-ops on dry-run (returns placeholder URLs).
    if local_images:
        image_replacements = upload_images_for_page(
            client, page_id, local_images)
        content = replace_image_refs(content, image_replacements)

    # Upload attachments + rewrite file link refs
    if all_attachment_paths:
        att_url_map = upload_attachments_for_page(
            client, page_id, all_attachment_paths)
        link_replacements = {}
        for local_ref, local_path in local_file_links:
            if local_path.name in att_url_map:
                link_replacements[local_ref] = att_url_map[local_path.name]
        if link_replacements:
            content = replace_file_link_refs(content, link_replacements)

    local_normalized_hash = normalized_hash(content)
    if last_sync_hash == current_remote_hash == local_normalized_hash:
        print(f"  {term.dim('UNCHANGED')}: {title}")
        return False

    tags = [
        {"name": "source", "value": "auto-sync"},
        {"name": "source_file", "value": str(entry["file"])},
        {"name": "content_hash", "value": local_normalized_hash},
    ]

    if show_diff and not client.dry_run and remote_markdown:
        added, removed = diff_summary(remote_markdown, content)
        print(f"  {term.info('DIFF')}: {title}: "
              f"{term.ok(f'+{added}')} / {term.err(f'-{removed}')} lines")

    resp = client.update_page(page_id, title, content, tags=tags)
    _reconcile_stored_hash(client, resp, local_normalized_hash, tags)
    print(f"  {term.ok('UPDATED')}: {title} (page {page_id})")
    return True


def _create_new(client, entry, content, title, book_id, chapter_id,
                local_images, local_file_links, all_attachment_paths) -> bool:
    """Create a new BookStack page with content, images, and attachments."""
    tags = [
        {"name": "source", "value": "auto-sync"},
        {"name": "source_file", "value": str(entry["file"])},
    ]

    needs_rewrite = (local_images or local_file_links) and not client.dry_run

    if needs_rewrite:
        # Create first to get page_id, then upload and rewrite URLs
        result = client.create_page(
            title, content, book_id=book_id, chapter_id=chapter_id, tags=tags)
        page_id = result.get("id", -1)

        if local_images:
            image_replacements = upload_images_for_page(
                client, page_id, local_images)
            content = replace_image_refs(content, image_replacements)

        if all_attachment_paths:
            att_url_map = upload_attachments_for_page(
                client, page_id, all_attachment_paths)
            link_replacements = {}
            for local_ref, local_path in local_file_links:
                if local_path.name in att_url_map:
                    link_replacements[local_ref] = att_url_map[local_path.name]
            if link_replacements:
                content = replace_file_link_refs(content, link_replacements)

        local_hash = normalized_hash(content)
        tags.append({"name": "content_hash", "value": local_hash})
        resp = client.update_page(page_id, title, content, tags=tags)
        _reconcile_stored_hash(client, resp, local_hash, tags)
    else:
        local_hash = normalized_hash(content)
        tags.append({"name": "content_hash", "value": local_hash})
        resp = client.create_page(
            title, content, book_id=book_id, chapter_id=chapter_id, tags=tags)
        page_id = resp.get("id", -1)

        if all_attachment_paths and not client.dry_run:
            upload_attachments_for_page(
                client, page_id, all_attachment_paths)

        _reconcile_stored_hash(client, resp, local_hash, tags)

    print(f"  {term.ok('CREATED')}: {title} (page {page_id})")
    return True


def _reconcile_stored_hash(client: BookStackClient, response: dict,
                           expected_hash: str, tags: list):
    """If BookStack normalized the stored markdown differently from us,
    the content_hash tag we set won't match what the next conflict check
    would compute on remote. Update the tag to reflect the true stored
    hash — one extra API call only when needed.
    """
    if not response or response.get("id", -1) < 0:
        return
    stored_md = response.get("markdown")
    if not stored_md:
        return
    true_hash = normalized_hash(stored_md)
    if true_hash == expected_hash:
        return
    try:
        new_tags = [{"name": t["name"], "value": t["value"]}
                    for t in tags if t.get("name") != "content_hash"]
        new_tags.append({"name": "content_hash", "value": true_hash})
        client.update_page(response["id"], response["name"], stored_md,
                           tags=new_tags)
    except Exception as e:
        print(f"    warning: hash reconciliation failed: {e}")


# ─── Pull ───


def pull_entry(client: BookStackClient, entry: dict, config_dir: Path) -> bool:
    """Pull a single config entry from BookStack to local. Returns True if
    the local file was created or updated."""
    file_path = resolve_file_path(entry["file"], config_dir)

    book_name = entry.get("book", "Documentation")
    book = client.find_book(book_name)
    if not book:
        print(f"  {term.warn('SKIP')}: book '{book_name}' not found on BookStack")
        return False

    # Determine title — config override, then local H1, then filename
    title = entry.get("title")
    if not title and file_path.exists():
        title = extract_title(read_markdown(file_path), file_path.stem)
    if not title:
        title = file_path.stem

    page = client.find_page_in_book(book["id"], title)
    if not page:
        print(f"  {term.warn('SKIP')}: page '{title}' not found in book "
              f"'{book_name}'")
        return False

    page_detail = client.get_page(page["id"])
    remote_markdown = page_detail.get("markdown", "")
    if not remote_markdown:
        print(f"  {term.warn('SKIP')}: page '{title}' has empty markdown "
              f"(may have been edited in BookStack's WYSIWYG editor — only "
              f"HTML stored)")
        return False

    # Remote hash is computed on what BookStack actually stores (no H1)
    remote_hash = normalized_hash(remote_markdown)

    # For local file, restore H1 if we strip it on push
    local_form = (restore_h1(remote_markdown, title)
                  if entry.get("strip_title", True) else remote_markdown)

    local_content = read_markdown(file_path) if file_path.exists() else ""

    if normalized_hash(local_form) == normalized_hash(local_content):
        print(f"  {term.dim('UNCHANGED')}: {title}")
        return False

    added, removed = diff_summary(local_content, local_form)

    if not file_path.exists():
        _write_pulled_content(file_path, local_form)
        print(f"  {term.ok('CREATED')}: {title} → {file_path} "
              f"({term.ok(f'+{added}')} lines)")
        set_sync_tag(client, page_detail, remote_hash,
                     source_file=str(entry["file"]))
        return True

    if not is_interactive():
        print(f"  {term.warn('DIFFERS')}: \"{title}\" differs from remote "
              f"({term.ok(f'+{added}')}/{term.err(f'-{removed}')}). "
              f"Run interactively to overwrite.")
        return False

    action = prompt_pull_overwrite(title, local_content, local_form,
                                   added, removed)
    if action == "skip":
        print(f"  {term.warn('SKIPPED')}: {title}")
        return False
    if action == "quit":
        print(term.err("Aborted by user."))
        sys.exit(1)

    _write_pulled_content(file_path, local_form)
    set_sync_tag(client, page_detail, remote_hash,
                 source_file=str(entry["file"]))
    print(f"  {term.ok('UPDATED')}: {title} → {file_path} "
          f"({term.ok(f'+{added}')}/{term.err(f'-{removed}')})")
    return True


def _write_pulled_content(file_path: Path, content: str):
    """Write pulled content to a local file, creating parent dirs as needed."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content)


# ─── Image and attachment upload helpers ───


def upload_images_for_page(client: BookStackClient, page_id: int,
                           local_images: list) -> dict[str, str]:
    """Upload local images to BookStack, returning {local_ref: remote_url}."""
    replacements = {}
    existing = {img["name"]: img for img in client.list_page_images(page_id)}

    for local_ref, img_path in local_images:
        img_name = img_path.stem
        if img_name in existing:
            replacements[local_ref] = existing[img_name]["url"]
            print(f"    IMAGE EXISTS: {img_path.name}")
        else:
            result = client.upload_image(page_id, img_path, name=img_name)
            replacements[local_ref] = result["url"]
            print(f"    IMAGE UPLOADED: {img_path.name}")

    return replacements


def upload_attachments_for_page(client: BookStackClient, page_id: int,
                                file_paths: list) -> dict[str, str]:
    """Upload file attachments to a page. Returns {filename: download_url}."""
    existing = {a["name"]: a for a in client.list_page_attachments(page_id)}
    url_map = {}

    for file_path in file_paths:
        if not file_path.exists():
            print(f"    ATTACHMENT NOT FOUND: {file_path}")
            continue

        display_name = file_path.name
        if display_name in existing:
            att_id = existing[display_name]["id"]
            url_map[display_name] = f"{client.url}/attachments/{att_id}"
            print(f"    ATTACHMENT EXISTS: {display_name}")
        else:
            result = client.upload_attachment(
                page_id, file_path, name=display_name)
            att_id = result.get("id")
            url_map[display_name] = f"{client.url}/attachments/{att_id}"
            print(f"    ATTACHMENT UPLOADED: {display_name}")

    return url_map
