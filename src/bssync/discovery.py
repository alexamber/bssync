"""Discovery commands: `ls` (list BookStack tree) and `pull --new`
(find pages not yet in config)."""

import re
from pathlib import Path

from bssync.client import BookStackClient
from bssync.config import resolve_file_path
from bssync.content import extract_title, read_markdown


def list_all_pages(client: BookStackClient, book_filter: str = None,
                   chapter_filter: str = None) -> list:
    """Fetch all pages with their book/chapter context. Optional filters."""
    pages = client.list_pages()
    books = {b["id"]: b for b in client.list_books()}
    chapters = {}
    for b_id in books:
        for ch in client.list_chapters(b_id):
            chapters[ch["id"]] = ch

    result = []
    for p in pages:
        book_id = p.get("book_id")
        chapter_id = p.get("chapter_id")
        book_name = books.get(book_id, {}).get("name", "(?)")
        chapter_name = (chapters.get(chapter_id, {}).get("name")
                        if chapter_id else None)
        if book_filter and book_filter.lower() != book_name.lower():
            continue
        if chapter_filter:
            if not chapter_name or chapter_filter.lower() != chapter_name.lower():
                continue
        result.append({
            "id": p["id"],
            "name": p["name"],
            "book": book_name,
            "chapter": chapter_name,
            "slug": p.get("slug", ""),
        })
    return result


def resolve_entry_title(entry: dict, config_dir: Path) -> str:
    """Return the title a publish entry would sync under.

    Mirrors the resolution `publish_entry` performs at push time: explicit
    `title:` wins, else the first H1 in the local file, else the file
    stem. Keeps `is_tracked` aligned with what actually gets synced so a
    title-less entry matches the specific page it targets rather than
    every page in its book/chapter.
    """
    title = entry.get("title")
    if title:
        return title
    file_ref = entry.get("file", "")
    if not file_ref:
        return ""
    file_path = resolve_file_path(file_ref, config_dir)
    if file_path.exists():
        return extract_title(read_markdown(file_path), file_path.stem)
    return file_path.stem


def resolve_entries(entries: list, config_dir: Path) -> list:
    """Return a shallow copy of `entries` with `title` populated on every
    entry. Callers pass the output to `is_tracked` instead of the raw
    config list, so `is_tracked` can rely on titles being present."""
    return [{**e, "title": resolve_entry_title(e, config_dir)}
            for e in entries]


def is_tracked(page: dict, entries: list) -> bool:
    """Check if a BookStack page is tracked by a config entry.

    Match on (book + title) only — no fuzzy fallback. Entries with an
    empty resolved title (no file, file missing, no H1) never match,
    which is the safe default: a malformed entry shouldn't silently
    claim pages.

    Callers that accept title-less config entries must pass
    `resolve_entries(entries, config_dir)` first; otherwise a legitimate
    entry with no explicit `title:` in the yaml won't be recognized.
    """
    page_title = page["name"].lower()
    for e in entries:
        if e.get("book", "").lower() != page["book"].lower():
            continue
        entry_title = (e.get("title") or "").lower()
        if entry_title and entry_title == page_title:
            return True
    return False


def cmd_ls(client, config, args, config_dir: Path):
    """Print the BookStack tree, marking which pages are tracked in config."""
    entries = resolve_entries(config.get("publish", []), config_dir)
    pages = list_all_pages(client, args.book, args.chapter)

    tree: dict = {}
    for p in pages:
        tree.setdefault(p["book"], {}).setdefault(
            p["chapter"] or "(no chapter)", []).append(p)

    shown = 0
    for book_name in sorted(tree):
        book_pages = tree[book_name]
        print(f"\n{book_name}")
        for chapter_name in sorted(book_pages):
            print(f"  {chapter_name}")
            for p in sorted(book_pages[chapter_name], key=lambda x: x["name"]):
                tracked = is_tracked(p, entries)
                if args.missing and tracked:
                    continue
                marker = "\u2713" if tracked else "\u00b7"
                print(f"    {marker} {p['name']}  (id {p['id']})")
                shown += 1

    print(f"\n{shown} page(s) shown. "
          f"\u2713 = tracked in config, \u00b7 = not tracked.")


def suggest_config_entry(page: dict, existing_files: set) -> str:
    """Generate a YAML snippet for a new config entry, using slugs of
    the chapter/page names for the suggested local file path."""
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", page["name"].lower()).strip("-")
    if page["chapter"]:
        chapter_slug = re.sub(r"[^a-zA-Z0-9_-]+", "-",
                              page["chapter"].lower()).strip("-")
        suggested = f"../docs/{chapter_slug}/{slug}.md"
    else:
        suggested = f"../docs/{slug}.md"
    if suggested in existing_files:
        suggested = suggested.replace(".md", f"-{page['id']}.md")

    lines = [
        f"  - file: {suggested}",
        f"    book: {page['book']}",
    ]
    if page["chapter"]:
        lines.append(f"    chapter: {page['chapter']}")
    lines.append(f"    title: {page['name']}")
    return "\n".join(lines)


def cmd_pull_discover(client, config, args, config_dir: Path):
    """Discovery mode: find pages on BookStack not yet in config and
    print ready-to-paste YAML snippets."""
    raw_entries = config.get("publish", [])
    entries = resolve_entries(raw_entries, config_dir)
    existing_files = {e.get("file") for e in raw_entries}
    pages = list_all_pages(client, args.book, args.chapter)
    untracked = [p for p in pages if not is_tracked(p, entries)]

    if not untracked:
        print("No untracked pages found in this scope.")
        return

    print(f"\nFound {len(untracked)} untracked page(s). "
          f"Copy these into the `publish:` list in your config to track "
          f"them:\n")
    for p in untracked:
        print(suggest_config_entry(p, existing_files))
        print()
