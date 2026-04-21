"""Push and pull orchestrators.

Both `publish_entry` and `pull_entry` return a structured `EntryResult`;
per-file progress messages (image/attachment upload activity) are emitted
via an optional `on_progress` callback. The orchestrators never print to
stdout themselves, so they're safe to drive from the CLI renderer, the
MCP server, or a test harness without any stdout-capture gymnastics.
"""

import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

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
    file_hash,
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


IMG_HASH_TAG_PREFIX = "bssync.img_hash."
ATT_HASH_TAG_PREFIX = "bssync.att_hash."

_MANAGED_TAG_NAMES = {"source", "source_file", "content_hash"}


# ─── Result types ───


class SyncStatus(str, Enum):
    CREATED = "created"
    UPDATED = "updated"
    MOVED = "moved"
    UNCHANGED = "unchanged"
    SKIPPED = "skipped"
    CONFLICT = "conflict"      # push: remote edited since last sync
    DIFFERS = "differs"        # pull: local differs, non-interactive
    PULLED = "pulled"          # push-conflict resolved by pulling


@dataclass
class EntryResult:
    """Structured result of a single publish_entry / pull_entry call.

    `status` is the primary outcome. `content_updated` disambiguates the
    MOVED case (a page can be moved without any content change, or moved
    and updated in the same call). `diff_added` / `diff_removed` are only
    populated when relevant (conflict/differs/pulled). `dry_run` is True
    when the orchestrator ran against a dry-run client.
    """
    status: SyncStatus
    file: str
    title: str = ""
    detail: str = ""
    page_id: Optional[int] = None
    diff_added: Optional[int] = None
    diff_removed: Optional[int] = None
    dry_run: bool = False
    content_updated: bool = False

    @property
    def changed(self) -> bool:
        """True if this result represents a mutation. Used by summary counts."""
        return self.status in {
            SyncStatus.CREATED, SyncStatus.UPDATED,
            SyncStatus.MOVED, SyncStatus.PULLED,
        }


OnProgress = Callable[[str], None]


def _emit(on_progress: Optional[OnProgress], msg: str) -> None:
    if on_progress is not None:
        on_progress(msg)


# ─── Tag helpers ───


def _is_bssync_managed_tag(name: str) -> bool:
    """True for tags that bssync owns and is free to rewrite. User-added
    tags (labels, categories, anything from the BookStack UI) must be
    preserved across pushes."""
    return name in _MANAGED_TAG_NAMES or name.startswith("bssync.")


def _merge_preserving_user_tags(existing_tags: list,
                                managed_tags: list) -> list:
    """Keep user-added tags from `existing_tags`, overlay fresh
    `managed_tags`. Without this, update_page replaces the entire tag set
    and wipes tags the user added in the BookStack UI."""
    preserved = [{"name": t["name"], "value": t["value"]}
                 for t in existing_tags
                 if not _is_bssync_managed_tag(t.get("name", ""))]
    return preserved + managed_tags


# ─── Push ───


def publish_entry(client: BookStackClient, entry: dict, config_dir: Path,
                  *,
                  show_diff: bool = False, force: bool = False,
                  refresh_uploads: bool = False,
                  on_progress: Optional[OnProgress] = None) -> EntryResult:
    """Push a single config entry to BookStack.

    Conflict guard: if the BookStack page's current hash differs from the
    content_hash tag set by our last push, we prompt the user (when
    interactive) or return CONFLICT (non-interactive). `force=True`
    bypasses the check.
    """
    file_path = resolve_file_path(entry["file"], config_dir)
    title = entry.get("title") or file_path.stem
    if not file_path.exists():
        return EntryResult(
            status=SyncStatus.SKIPPED, file=entry["file"], title=title,
            detail=f"file not found: {file_path}")

    content = read_markdown(file_path)
    title = entry.get("title") or extract_title(content, file_path.stem)

    if entry.get("strip_title", True):
        content = strip_title(content)

    book_name = entry.get("book", "Documentation")
    book = client.find_book(book_name)
    if not book:
        _emit(on_progress, f"book '{book_name}' not found — creating")
        book = client.create_book(book_name)

    if client.dry_run and book["id"] == -1:
        # Book would be created; emit dry-run detail but don't proceed.
        local_images = find_local_images(content, file_path.parent)
        for _, path in local_images:
            _emit(on_progress, f"[dry-run] would upload image: {path.name}")
        for att in entry.get("attachments", []):
            _emit(on_progress, f"[dry-run] would upload attachment: {att}")
        return EntryResult(
            status=SyncStatus.CREATED, file=entry["file"], title=title,
            detail="(dry-run) would publish", dry_run=True)

    book_id = book["id"]

    chapter_id = None
    chapter_name = entry.get("chapter")
    if chapter_name:
        chapter = client.find_chapter(book_id, chapter_name)
        if not chapter:
            _emit(on_progress,
                  f"chapter '{chapter_name}' not found — creating")
            chapter = client.create_chapter(book_id, chapter_name)
        if not client.dry_run:
            chapter_id = chapter["id"]

    existing = client.find_page_in_book(book_id, title)

    local_images = find_local_images(content, file_path.parent)
    local_file_links = find_local_file_links(content, file_path.parent)
    config_attachment_paths = [
        resolve_file_path(rel_path, config_dir)
        for rel_path in entry.get("attachments", [])
    ]
    all_attachment_paths = list({p: p for _, p in local_file_links}.values())
    for p in config_attachment_paths:
        if p not in all_attachment_paths:
            all_attachment_paths.append(p)

    if existing:
        return _update_existing(
            client, entry, file_path, content, title, existing,
            local_images, local_file_links, all_attachment_paths,
            show_diff, force, book_id, chapter_id, refresh_uploads,
            on_progress)
    return _create_new(
        client, entry, content, title, book_id, chapter_id,
        local_images, local_file_links, all_attachment_paths, on_progress)


def _update_existing(client, entry, file_path, content, title, existing,
                     local_images, local_file_links, all_attachment_paths,
                     show_diff, force, target_book_id, target_chapter_id,
                     refresh_uploads, on_progress) -> EntryResult:
    """Update an existing BookStack page. Handles conflict detection,
    attachment uploads, URL rewriting, post-push hash reconciliation, and
    reconciling chapter moves when the yaml's chapter differs from where
    the page currently lives."""
    page_id = existing["id"]

    page_detail = client.get_page(page_id)
    existing_tags = page_detail.get("tags", [])
    last_sync_hash = extract_tag(existing_tags, "content_hash", "")
    remote_markdown = page_detail.get("markdown", "")
    current_remote_hash = (normalized_hash(remote_markdown)
                           if remote_markdown else "")

    current_chapter_id = page_detail.get("chapter_id", 0) or 0
    target_chapter_norm = target_chapter_id or 0
    chapter_unresolved = (bool(entry.get("chapter"))
                          and target_chapter_id is None)
    needs_move = (not chapter_unresolved
                  and current_chapter_id != target_chapter_norm)

    # Conflict check — only meaningful when we've synced before and both
    # sides have comparable hashes.
    if (not force and not client.dry_run and last_sync_hash
            and current_remote_hash
            and last_sync_hash != current_remote_hash):
        added, removed = diff_summary(content, remote_markdown)
        if not is_interactive():
            return EntryResult(
                status=SyncStatus.CONFLICT, file=entry["file"], title=title,
                page_id=page_id,
                diff_added=added, diff_removed=removed,
                detail="remote modified since last push; use --force to "
                       "overwrite")
        action = prompt_conflict_action(
            title, remote_markdown, content, added, removed)
        if action == "skip":
            return EntryResult(
                status=SyncStatus.SKIPPED, file=entry["file"], title=title,
                page_id=page_id, detail="user skipped on conflict")
        if action == "quit":
            # CLI-only escape hatch; MCP never reaches here (non-interactive).
            sys.exit(1)
        if action == "pull":
            local_form = (restore_h1(remote_markdown, title)
                          if entry.get("strip_title", True)
                          else remote_markdown)
            _write_pulled_content(file_path, local_form)
            set_sync_tag(client, page_detail, current_remote_hash,
                         source_file=str(entry["file"]))
            return EntryResult(
                status=SyncStatus.PULLED, file=entry["file"], title=title,
                page_id=page_id, detail=str(file_path))
        # action == "overwrite" — proceed

    # Upload images + rewrite refs.
    image_hash_tags: list = []
    images_changed = False
    if local_images:
        image_replacements, image_hash_tags, images_changed = (
            upload_images_for_page(client, page_id, local_images,
                                   existing_tags=existing_tags,
                                   refresh=refresh_uploads,
                                   on_progress=on_progress))
        content = replace_image_refs(content, image_replacements)

    # Upload attachments + rewrite file link refs.
    attachment_hash_tags: list = []
    attachments_changed = False
    if all_attachment_paths:
        att_url_map, attachment_hash_tags, attachments_changed = (
            upload_attachments_for_page(client, page_id, all_attachment_paths,
                                        existing_tags=existing_tags,
                                        refresh=refresh_uploads,
                                        on_progress=on_progress))
        link_replacements = {}
        for local_ref, local_path in local_file_links:
            if local_path.name in att_url_map:
                link_replacements[local_ref] = att_url_map[local_path.name]
        if link_replacements:
            content = replace_file_link_refs(content, link_replacements)

    local_normalized_hash = normalized_hash(content)
    content_unchanged = (last_sync_hash == current_remote_hash
                         == local_normalized_hash)
    uploads_changed = images_changed or attachments_changed
    if content_unchanged and not needs_move and not uploads_changed:
        return EntryResult(
            status=SyncStatus.UNCHANGED, file=entry["file"], title=title,
            page_id=page_id, dry_run=client.dry_run)

    managed_tags = [
        {"name": "source", "value": "auto-sync"},
        {"name": "source_file", "value": str(entry["file"])},
        {"name": "content_hash", "value": local_normalized_hash},
        *image_hash_tags,
        *attachment_hash_tags,
    ]
    tags = _merge_preserving_user_tags(existing_tags, managed_tags)

    diff_added = diff_removed = None
    if show_diff and not client.dry_run and remote_markdown:
        diff_added, diff_removed = diff_summary(remote_markdown, content)

    move_kwargs = {}
    if needs_move:
        if target_chapter_norm:
            move_kwargs["chapter_id"] = target_chapter_norm
        else:
            move_kwargs["book_id"] = target_book_id

    resp = client.update_page(page_id, title, content, tags=tags, **move_kwargs)
    _reconcile_stored_hash(client, resp, local_normalized_hash, tags,
                           on_progress)

    if needs_move:
        target_label = entry.get("chapter") or "(book root)"
        return EntryResult(
            status=SyncStatus.MOVED, file=entry["file"], title=title,
            page_id=page_id, detail=f"→ {target_label}",
            content_updated=(not content_unchanged or uploads_changed),
            diff_added=diff_added, diff_removed=diff_removed,
            dry_run=client.dry_run)

    return EntryResult(
        status=SyncStatus.UPDATED, file=entry["file"], title=title,
        page_id=page_id,
        diff_added=diff_added, diff_removed=diff_removed,
        dry_run=client.dry_run)


def _create_new(client, entry, content, title, book_id, chapter_id,
                local_images, local_file_links, all_attachment_paths,
                on_progress) -> EntryResult:
    """Create a new BookStack page with content, images, and attachments."""
    tags = [
        {"name": "source", "value": "auto-sync"},
        {"name": "source_file", "value": str(entry["file"])},
    ]

    needs_rewrite = (local_images or local_file_links) and not client.dry_run

    if needs_rewrite:
        result = client.create_page(
            title, content, book_id=book_id, chapter_id=chapter_id, tags=tags)
        page_id = result.get("id", -1)

        image_hash_tags: list = []
        if local_images:
            image_replacements, image_hash_tags, _ = upload_images_for_page(
                client, page_id, local_images, on_progress=on_progress)
            content = replace_image_refs(content, image_replacements)

        attachment_hash_tags: list = []
        if all_attachment_paths:
            att_url_map, attachment_hash_tags, _ = upload_attachments_for_page(
                client, page_id, all_attachment_paths, on_progress=on_progress)
            link_replacements = {}
            for local_ref, local_path in local_file_links:
                if local_path.name in att_url_map:
                    link_replacements[local_ref] = att_url_map[local_path.name]
            if link_replacements:
                content = replace_file_link_refs(content, link_replacements)

        local_hash = normalized_hash(content)
        tags.append({"name": "content_hash", "value": local_hash})
        tags.extend(image_hash_tags)
        tags.extend(attachment_hash_tags)
        resp = client.update_page(page_id, title, content, tags=tags)
        _reconcile_stored_hash(client, resp, local_hash, tags, on_progress)
    else:
        local_hash = normalized_hash(content)
        tags.append({"name": "content_hash", "value": local_hash})
        resp = client.create_page(
            title, content, book_id=book_id, chapter_id=chapter_id, tags=tags)
        page_id = resp.get("id", -1)

        if all_attachment_paths and not client.dry_run:
            _, attachment_hash_tags, _ = upload_attachments_for_page(
                client, page_id, all_attachment_paths, on_progress=on_progress)
            if attachment_hash_tags:
                tags.extend(attachment_hash_tags)
                client.update_page(page_id, title, content, tags=tags)

        _reconcile_stored_hash(client, resp, local_hash, tags, on_progress)

    return EntryResult(
        status=SyncStatus.CREATED, file=entry["file"], title=title,
        page_id=page_id, dry_run=client.dry_run)


def _reconcile_stored_hash(client: BookStackClient, response: dict,
                           expected_hash: str, tags: list,
                           on_progress: Optional[OnProgress] = None) -> None:
    """If BookStack normalized the stored markdown differently from us,
    the content_hash tag we set won't match what the next conflict check
    would compute on remote. Update the tag to reflect the true stored
    hash — one extra API call only when needed."""
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
        _emit(on_progress, f"warning: hash reconciliation failed: {e}")


# ─── Pull ───


def pull_entry(client: BookStackClient, entry: dict, config_dir: Path,
               *,
               on_progress: Optional[OnProgress] = None) -> EntryResult:
    """Pull a single config entry from BookStack to local."""
    file_path = resolve_file_path(entry["file"], config_dir)

    book_name = entry.get("book", "Documentation")
    book = client.find_book(book_name)
    if not book:
        return EntryResult(
            status=SyncStatus.SKIPPED, file=entry["file"],
            detail=f"book '{book_name}' not found on BookStack")

    title = entry.get("title")
    if not title and file_path.exists():
        title = extract_title(read_markdown(file_path), file_path.stem)
    if not title:
        title = file_path.stem

    page = client.find_page_in_book(book["id"], title)
    if not page:
        return EntryResult(
            status=SyncStatus.SKIPPED, file=entry["file"], title=title,
            detail=f"page '{title}' not found in book '{book_name}'")

    page_detail = client.get_page(page["id"])
    remote_markdown = page_detail.get("markdown", "")
    if not remote_markdown:
        return EntryResult(
            status=SyncStatus.SKIPPED, file=entry["file"], title=title,
            page_id=page["id"],
            detail="page has empty markdown (edited in BookStack's WYSIWYG "
                   "editor — only HTML stored)")

    remote_hash = normalized_hash(remote_markdown)

    local_form = (restore_h1(remote_markdown, title)
                  if entry.get("strip_title", True) else remote_markdown)

    local_content = read_markdown(file_path) if file_path.exists() else ""

    if normalized_hash(local_form) == normalized_hash(local_content):
        return EntryResult(
            status=SyncStatus.UNCHANGED, file=entry["file"], title=title,
            page_id=page["id"])

    added, removed = diff_summary(local_content, local_form)

    if not file_path.exists():
        _write_pulled_content(file_path, local_form)
        set_sync_tag(client, page_detail, remote_hash,
                     source_file=str(entry["file"]))
        return EntryResult(
            status=SyncStatus.CREATED, file=entry["file"], title=title,
            page_id=page["id"], detail=str(file_path),
            diff_added=added, diff_removed=removed)

    if not is_interactive():
        return EntryResult(
            status=SyncStatus.DIFFERS, file=entry["file"], title=title,
            page_id=page["id"],
            detail="local differs from remote; run interactively to overwrite",
            diff_added=added, diff_removed=removed)

    action = prompt_pull_overwrite(title, local_content, local_form,
                                   added, removed)
    if action == "skip":
        return EntryResult(
            status=SyncStatus.SKIPPED, file=entry["file"], title=title,
            page_id=page["id"], detail="user skipped on pull overwrite")
    if action == "quit":
        sys.exit(1)

    _write_pulled_content(file_path, local_form)
    set_sync_tag(client, page_detail, remote_hash,
                 source_file=str(entry["file"]))
    return EntryResult(
        status=SyncStatus.UPDATED, file=entry["file"], title=title,
        page_id=page["id"], detail=str(file_path),
        diff_added=added, diff_removed=removed)


def _write_pulled_content(file_path: Path, content: str) -> None:
    """Write pulled content to a local file, creating parent dirs as needed."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content)


# ─── Image and attachment upload helpers ───


def upload_images_for_page(client: BookStackClient, page_id: int,
                           local_images: list,
                           existing_tags: list = None,
                           refresh: bool = False,
                           on_progress: Optional[OnProgress] = None
                           ) -> tuple[dict[str, str], list[dict], bool]:
    """Upload or replace local images on a page.

    Compares each local image's SHA256 against a per-image hash stored on
    the page as a `bssync.img_hash.<stem>` tag. When the hash differs (or
    `refresh=True`), the gallery entry is replaced in place — ID and URL
    preserved.

    Returns (url_map, hash_tags, any_changed).
    """
    existing_tags = existing_tags or []
    stored_hashes = {t["name"]: t["value"] for t in existing_tags
                     if t.get("name", "").startswith(IMG_HASH_TAG_PREFIX)}
    existing_images = {img["name"]: img
                       for img in client.list_page_images(page_id)}

    replacements: dict[str, str] = {}
    hash_tags: list[dict] = []
    any_changed = False

    for local_ref, img_path in local_images:
        img_name = img_path.stem
        tag_name = f"{IMG_HASH_TAG_PREFIX}{img_name}"
        local_h = file_hash(img_path)

        if img_name in existing_images:
            existing_img = existing_images[img_name]
            stored_h = stored_hashes.get(tag_name, "")
            if not refresh and stored_h == local_h:
                replacements[local_ref] = existing_img["url"]
                _emit(on_progress, f"image unchanged: {img_path.name}")
            else:
                result = client.update_image(
                    existing_img["id"], img_path, name=img_name)
                replacements[local_ref] = (result.get("url")
                                           or existing_img["url"])
                _emit(on_progress, f"image updated: {img_path.name}")
                any_changed = True
        else:
            result = client.upload_image(page_id, img_path, name=img_name)
            replacements[local_ref] = result["url"]
            _emit(on_progress, f"image uploaded: {img_path.name}")
            any_changed = True

        hash_tags.append({"name": tag_name, "value": local_h})

    return replacements, hash_tags, any_changed


def upload_attachments_for_page(client: BookStackClient, page_id: int,
                                file_paths: list,
                                existing_tags: list = None,
                                refresh: bool = False,
                                on_progress: Optional[OnProgress] = None
                                ) -> tuple[dict[str, str], list[dict], bool]:
    """Upload or replace file attachments on a page.

    Compares each local file's SHA256 against a per-file hash stored on
    the page as a `bssync.att_hash.<filename>` tag. When the hash differs
    (or `refresh=True`), the attachment is replaced in place — attachment
    ID and download URL preserved so external links don't break.

    Returns (url_map, hash_tags, any_changed).
    """
    existing_tags = existing_tags or []
    stored_hashes = {t["name"]: t["value"] for t in existing_tags
                     if t.get("name", "").startswith(ATT_HASH_TAG_PREFIX)}
    existing = {a["name"]: a for a in client.list_page_attachments(page_id)}

    url_map: dict[str, str] = {}
    hash_tags: list[dict] = []
    any_changed = False

    for file_path in file_paths:
        if not file_path.exists():
            _emit(on_progress, f"attachment not found: {file_path}")
            continue

        display_name = file_path.name
        tag_name = f"{ATT_HASH_TAG_PREFIX}{display_name}"
        local_h = file_hash(file_path)

        if display_name in existing:
            att = existing[display_name]
            att_id = att["id"]
            stored_h = stored_hashes.get(tag_name, "")
            if not refresh and stored_h == local_h:
                url_map[display_name] = f"{client.url}/attachments/{att_id}"
                _emit(on_progress, f"attachment unchanged: {display_name}")
            else:
                client.update_attachment(att_id, file_path, name=display_name)
                url_map[display_name] = f"{client.url}/attachments/{att_id}"
                _emit(on_progress, f"attachment updated: {display_name}")
                any_changed = True
        else:
            result = client.upload_attachment(
                page_id, file_path, name=display_name)
            att_id = result.get("id")
            url_map[display_name] = f"{client.url}/attachments/{att_id}"
            _emit(on_progress, f"attachment uploaded: {display_name}")
            any_changed = True

        hash_tags.append({"name": tag_name, "value": local_h})

    return url_map, hash_tags, any_changed
