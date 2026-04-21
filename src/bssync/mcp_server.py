"""MCP server entry point for bssync.

Exposes bssync's push/pull/ls/discover/verify functionality plus read-only
live access to BookStack (search, get page, list books/chapters/pages) and
guarded live writes for pages not tracked in the config's publish: list.

Transport: stdio (default for Claude Desktop and terminal MCP clients).

Any stdout from the existing sync orchestrators is captured per-tool and
returned in the tool result's `_log` field — stdio is the MCP protocol
channel, so stray prints would otherwise corrupt the stream.
"""

import asyncio
import contextlib
import io
import os
import sys
from pathlib import Path
from typing import Optional

try:
    from mcp.server.fastmcp import Context, FastMCP
    from mcp.server.session import ServerSession
except ImportError:
    sys.stderr.write(
        "bssync-mcp: the mcp SDK is not installed. "
        "Install with: pip install 'bssync[mcp]'\n"
    )
    sys.exit(1)

from bssync import __version__
from bssync.client import BookStackClient
from bssync.config import load_config
from bssync.content import normalized_hash
from bssync.discovery import (
    is_tracked,
    list_all_pages,
    suggest_config_entry,
)
from bssync.sync import publish_entry, pull_entry


mcp = FastMCP("bssync")

_config: dict = {}
_config_dir: Path = Path(".")
_config_error: Optional[str] = None


# ─── Helpers ───


def _config_error_response() -> dict:
    """Structured response returned by every tool when the server started
    without valid config. Claude sees this and surfaces the fix to the user
    — much better UX than Claude Desktop showing an opaque "server failed"
    because we sys.exit()'d at startup.
    """
    return {
        "status": "error",
        "reason": "config_invalid",
        "detail": _config_error or "bssync-mcp is not configured",
        "fix": (
            "Set BSSYNC_CONFIG to point to a valid bookstack.yaml, or set "
            "BOOKSTACK_URL + BOOKSTACK_TOKEN_ID + BOOKSTACK_TOKEN_SECRET "
            "env vars in your MCP client config. Restart the MCP server "
            "after fixing."
        ),
    }


def _new_client(dry_run: bool = False) -> BookStackClient:
    """Fresh client per tool call. Book/chapter caches live for one call —
    acceptable tradeoff for simpler dry_run handling and no cross-call
    state bleed."""
    bs = _config["bookstack"]
    return BookStackClient(
        url=bs["url"],
        token_id=bs["token_id"],
        token_secret=bs["token_secret"],
        dry_run=dry_run,
        verbose=False,
    )


def _capture_stdout(fn):
    """Run a sync callable with stdout captured. Returns (result, log).
    Used by push/pull loops where the async wrapper needs to iterate so
    progress notifications can fire between entries."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            result = fn()
        except Exception:
            sys.stderr.write(buf.getvalue())
            raise
    return result, buf.getvalue()


async def _run_captured(fn):
    """Run a sync function in a thread with stdout captured so progress
    prints from sync/discovery/client don't corrupt MCP's stdio channel.
    Captured log is attached to dict results as `_log`; on exception it's
    flushed to stderr so the operator can see it. Short-circuits with a
    structured config_invalid response when the server started without
    valid credentials — Claude surfaces this to the user instead of
    raising an opaque protocol error."""
    if _config_error:
        return _config_error_response()

    def wrapped():
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            try:
                result = fn()
            except Exception:
                sys.stderr.write(buf.getvalue())
                raise
        log = buf.getvalue()
        if isinstance(result, dict) and log:
            return {**result, "_log": log}
        return result
    return await asyncio.to_thread(wrapped)


def _filter_entries(only: Optional[str]) -> list:
    entries = _config.get("publish", []) or []
    if not only:
        return entries
    needle = only.lower()
    return [
        e for e in entries
        if needle in e.get("file", "").lower()
        or needle in (e.get("title") or "").lower()
    ]


def _require_one_identifier(page_id: Optional[int],
                            book: Optional[str],
                            title: Optional[str]) -> Optional[dict]:
    """Validate that exactly one page identifier form is provided: either
    page_id, or (book AND title). Returns an error dict when invalid, or
    None when the input is OK — intended to be used as an early return at
    the top of tool functions that accept both forms."""
    has_id = page_id is not None
    has_name = bool(book and title)
    if not has_id and not has_name:
        return {
            "status": "error",
            "reason": "missing_identifier",
            "detail": "provide either page_id, or both book and title",
        }
    if has_id and (book or title):
        return {
            "status": "error",
            "reason": "ambiguous_identifier",
            "detail": "provide either page_id, or (book + title) — not both",
        }
    return None


def _resolve_page(client: BookStackClient,
                  page_id: Optional[int],
                  book: Optional[str],
                  title: Optional[str]) -> dict:
    """Resolve (book, title) to a page_id. Returns {'page_id': int} on
    success or a structured error dict keyed on 'error'. Assumes
    `_require_one_identifier` has already validated the inputs."""
    if page_id is not None:
        return {"page_id": page_id}
    b = client.find_book(book)
    if not b:
        return {"error": "book_not_found",
                "status": "error",
                "reason": "book_not_found",
                "detail": f"book '{book}' not found on BookStack"}
    page = client.find_page_in_book(b["id"], title)
    if not page:
        return {"error": "page_not_found",
                "status": "error",
                "reason": "page_not_found",
                "detail": f"page '{title}' not found in book '{book}'"}
    return {"page_id": page["id"]}


def _tracking_match(book: str, title: str) -> Optional[dict]:
    """Return the config entry that tracks (book, title), or None.
    Reuses discovery.is_tracked so tracking logic stays in one place."""
    page_like = {"book": book, "chapter": "", "name": title}
    for entry in _config.get("publish", []) or []:
        if is_tracked(page_like, [entry]):
            return entry
    return None


# ─── Sync tools (parallel to the CLI) ───


@mcp.tool()
async def verify() -> dict:
    """Check that the BookStack API is reachable with current credentials."""
    def _run():
        client = _new_client()
        return {"connected": client.verify_connection(), "url": client.url}
    return await _run_captured(_run)


@mcp.tool()
async def push(
    only: Optional[str] = None,
    dry_run: bool = False,
    force: bool = False,
    refresh_uploads: bool = False,
    ctx: Optional[Context[ServerSession, None]] = None,
) -> dict:
    """Upload local markdown files to BookStack per the config's publish: list.

    On conflict (remote edited since last sync), the entry is skipped and
    reported in the result — re-run with force=true to overwrite. Long
    pushes emit per-entry progress notifications via the MCP Context so
    clients can show status instead of waiting silently.

    Args:
        only: Only push entries whose file path or title contains this
            substring (case-insensitive).
        dry_run: Preview changes without making API writes.
        force: Overwrite remote even if it was edited since last sync.
        refresh_uploads: Force re-upload of all images and attachments.
    """
    if _config_error:
        return _config_error_response()

    entries = _filter_entries(only)
    client = _new_client(dry_run=dry_run)

    results: list = []
    logs: list[str] = []
    updated = unchanged = skipped = 0
    total = len(entries)

    for i, entry in enumerate(entries):
        if ctx:
            await ctx.info(f"[{i + 1}/{total}] pushing {entry['file']}")
            await ctx.report_progress(progress=i, total=total)

        def _run_entry(entry=entry):
            print(f"  {entry['file']}")
            return publish_entry(
                client, entry, _config_dir,
                show_diff=False, force=force,
                refresh_uploads=refresh_uploads,
            )

        try:
            changed, log = await asyncio.to_thread(_capture_stdout, _run_entry)
            logs.append(log)
            if changed:
                updated += 1
                results.append({"file": entry["file"], "status": "updated"})
            else:
                unchanged += 1
                results.append({"file": entry["file"], "status": "unchanged"})
        except FileNotFoundError:
            skipped += 1
            results.append({"file": entry["file"], "status": "skipped",
                            "error": "file not found"})
        except Exception as e:
            skipped += 1
            results.append({"file": entry["file"], "status": "error",
                            "error": str(e)})

    if ctx:
        await ctx.report_progress(progress=total, total=total)

    return {
        "summary": {"updated": updated, "unchanged": unchanged,
                    "skipped": skipped, "total": total},
        "entries": results,
        "dry_run": dry_run,
        "_log": "".join(logs),
    }


@mcp.tool()
async def pull(
    only: Optional[str] = None,
    ctx: Optional[Context[ServerSession, None]] = None,
) -> dict:
    """Download BookStack page contents into local files per the config's
    publish: list.

    Non-interactive: if a local file differs from remote, the entry is
    reported as DIFFERS and left untouched — edit locally and run push, or
    delete the local file and pull again to overwrite. Emits per-entry
    progress notifications via the MCP Context.

    Args:
        only: Only pull entries whose file path or title contains this
            substring (case-insensitive).
    """
    if _config_error:
        return _config_error_response()

    entries = _filter_entries(only)
    client = _new_client()

    results: list = []
    logs: list[str] = []
    updated = unchanged = skipped = 0
    total = len(entries)

    for i, entry in enumerate(entries):
        if ctx:
            await ctx.info(f"[{i + 1}/{total}] pulling {entry['file']}")
            await ctx.report_progress(progress=i, total=total)

        def _run_entry(entry=entry):
            print(f"  {entry['file']}")
            return pull_entry(client, entry, _config_dir)

        try:
            changed, log = await asyncio.to_thread(_capture_stdout, _run_entry)
            logs.append(log)
            if changed:
                updated += 1
                results.append({"file": entry["file"], "status": "updated"})
            else:
                unchanged += 1
                results.append({"file": entry["file"], "status": "unchanged"})
        except Exception as e:
            skipped += 1
            results.append({"file": entry["file"], "status": "error",
                            "error": str(e)})

    if ctx:
        await ctx.report_progress(progress=total, total=total)

    return {
        "summary": {"updated": updated, "unchanged": unchanged,
                    "skipped": skipped, "total": total},
        "entries": results,
        "_log": "".join(logs),
    }


@mcp.tool()
async def ls(
    book: Optional[str] = None,
    chapter: Optional[str] = None,
    missing: bool = False,
) -> dict:
    """List pages on BookStack with their tracking state relative to the config.

    Args:
        book: Filter to pages in this book.
        chapter: Filter to pages in this chapter.
        missing: Only show pages NOT tracked in config.
    """
    def _run():
        client = _new_client()
        pages = list_all_pages(client, book, chapter)
        entries = _config.get("publish", []) or []
        result = []
        for p in pages:
            tracked = is_tracked(p, entries)
            if missing and tracked:
                continue
            result.append({**p, "tracked": tracked})
        return {"count": len(result), "pages": result}
    return await _run_captured(_run)


@mcp.tool()
async def discover(
    book: Optional[str] = None,
    chapter: Optional[str] = None,
) -> dict:
    """Find pages on BookStack that are NOT yet tracked in the config's
    publish: list. Returns ready-to-paste YAML snippets.

    Args:
        book: Scope discovery to this book.
        chapter: Scope discovery to this chapter.
    """
    def _run():
        client = _new_client()
        entries = _config.get("publish", []) or []
        existing_files = {e.get("file") for e in entries}
        pages = list_all_pages(client, book, chapter)
        untracked = [p for p in pages if not is_tracked(p, entries)]
        snippets = [suggest_config_entry(p, existing_files) for p in untracked]
        return {
            "count": len(untracked),
            "untracked": untracked,
            "yaml_snippets": snippets,
        }
    return await _run_captured(_run)


# ─── Read-only live tools ───


@mcp.tool()
async def list_books() -> dict:
    """List all books on the BookStack instance."""
    def _run():
        client = _new_client()
        books = client.list_books()
        return {
            "count": len(books),
            "books": [
                {"id": b["id"], "name": b["name"],
                 "slug": b.get("slug", ""),
                 "description": b.get("description", "")}
                for b in books
            ],
        }
    return await _run_captured(_run)


@mcp.tool()
async def list_chapters(book: str) -> dict:
    """List chapters in a book.

    Args:
        book: Book name or numeric book id (as a string).
    """
    def _run():
        client = _new_client()
        if book.isdigit():
            book_id = int(book)
            b = next((x for x in client.list_books() if x["id"] == book_id),
                     None)
        else:
            b = client.find_book(book)
        if not b:
            return {"error": f"book not found: {book}"}
        chapters = client.list_chapters(b["id"])
        return {
            "book": {"id": b["id"], "name": b["name"]},
            "count": len(chapters),
            "chapters": [
                {"id": c["id"], "name": c["name"], "slug": c.get("slug", "")}
                for c in chapters
            ],
        }
    return await _run_captured(_run)


@mcp.tool()
async def list_pages_in(
    book: Optional[str] = None,
    chapter: Optional[str] = None,
) -> dict:
    """List pages on BookStack, optionally scoped to a book and/or chapter.

    Args:
        book: Book name filter.
        chapter: Chapter name filter.
    """
    def _run():
        client = _new_client()
        pages = list_all_pages(client, book, chapter)
        return {"count": len(pages), "pages": pages}
    return await _run_captured(_run)


@mcp.tool()
async def search_pages(query: str, count: int = 20) -> dict:
    """Search BookStack for pages matching a query.

    Args:
        query: Search query passed to BookStack's search API.
        count: Max number of results (default 20).
    """
    def _run():
        client = _new_client()
        hits = client.search(query, type="page", count=count)
        return {
            "count": len(hits),
            "results": [
                {
                    "id": h.get("id"),
                    "name": h.get("name"),
                    "book_id": h.get("book_id"),
                    "chapter_id": h.get("chapter_id"),
                    "url": h.get("url"),
                    "preview_html": h.get("preview_html", {}),
                }
                for h in hits
            ],
        }
    return await _run_captured(_run)


@mcp.tool()
async def get_page(
    page_id: Optional[int] = None,
    book: Optional[str] = None,
    title: Optional[str] = None,
) -> dict:
    """Fetch a BookStack page's full markdown and metadata.

    Identify the page by either `page_id` directly, or by `(book, title)`
    — the second form saves an extra search step when you already know
    the book/title from the conversation. Pass exactly one form.

    The returned `content_hash` can be passed back to `update_page` as
    `expected_hash` for optimistic concurrency.

    Args:
        page_id: Numeric page id.
        book: Book name (used with `title`).
        title: Page title (used with `book`).
    """
    err = _require_one_identifier(page_id, book, title)
    if err:
        return err

    def _run():
        client = _new_client()
        resolved = _resolve_page(client, page_id, book, title)
        if "error" in resolved:
            return resolved
        page = client.get_page(resolved["page_id"])
        md = page.get("markdown", "")
        return {
            "id": page.get("id"),
            "name": page.get("name"),
            "book_id": page.get("book_id"),
            "chapter_id": page.get("chapter_id"),
            "slug": page.get("slug"),
            "markdown": md,
            "tags": page.get("tags", []),
            "updated_at": page.get("updated_at"),
            "content_hash": normalized_hash(md) if md else "",
        }
    return await _run_captured(_run)


# ─── Live write tools (untracked pages only) ───


@mcp.tool()
async def create_page(
    book: str,
    title: str,
    markdown: str,
    chapter: Optional[str] = None,
) -> dict:
    """Create a new page on BookStack directly (no local file).

    Guardrail: refuses if (book, title) would collide with a page tracked
    in the config's publish: list — those must go through local files + push.

    Args:
        book: Book name (created if it doesn't exist).
        title: Page title.
        markdown: Page body as markdown.
        chapter: Chapter name (created if missing; page goes in book root if
            omitted).
    """
    tracked = _tracking_match(book, title)
    if tracked:
        return {
            "status": "refused",
            "reason": "page_is_tracked",
            "detail": (
                f"A config entry already tracks this page "
                f"(file={tracked.get('file')}). Edit the local file and run "
                f"push instead of using live writes."
            ),
        }

    def _run():
        client = _new_client()
        b = client.find_book(book) or client.create_book(book)
        chapter_id = None
        if chapter:
            ch = (client.find_chapter(b["id"], chapter)
                  or client.create_chapter(b["id"], chapter))
            chapter_id = ch["id"]
        existing = client.find_page_in_book(b["id"], title)
        if existing:
            return {"status": "exists", "page_id": existing["id"],
                    "detail": "a page with this title already exists in the book"}
        result = client.create_page(
            title, markdown,
            book_id=b["id"], chapter_id=chapter_id,
            tags=[{"name": "source", "value": "bssync-mcp-live"}],
        )
        return {
            "status": "created",
            "page_id": result.get("id"),
            "title": result.get("name"),
        }
    return await _run_captured(_run)


@mcp.tool()
async def update_page(
    markdown: str,
    page_id: Optional[int] = None,
    book: Optional[str] = None,
    title: Optional[str] = None,
    new_title: Optional[str] = None,
    expected_hash: Optional[str] = None,
) -> dict:
    """Update a BookStack page directly (no local file).

    Identify the page by `page_id`, or by `(book, title)` for lookup by
    name. Pass exactly one form. Note: `title` here means "find the page
    with this title"; use `new_title` to rename the page.

    Guardrail: refuses if the page is tracked in the config's publish: list.
    Optional optimistic concurrency via `expected_hash` — pass the hash
    from a prior `get_page` call; the update fails with status=conflict
    if the stored markdown has changed since.

    Args:
        markdown: New page body.
        page_id: Numeric page id.
        book: Book name (used with `title`).
        title: Page title for lookup (used with `book`).
        new_title: Optional new title (omit to keep existing).
        expected_hash: If set, refuse the update when the current stored
            markdown hashes to a different value.
    """
    err = _require_one_identifier(page_id, book, title)
    if err:
        return err

    def _run():
        client = _new_client()
        resolved = _resolve_page(client, page_id, book, title)
        if "error" in resolved:
            return resolved
        resolved_id = resolved["page_id"]

        page = client.get_page(resolved_id)
        current_title = page.get("name", "")
        book_id = page.get("book_id")
        book_lookup = next(
            (b for b in client.list_books() if b["id"] == book_id), None)
        book_name = book_lookup["name"] if book_lookup else ""

        tracked = _tracking_match(book_name, current_title)
        if tracked:
            return {
                "status": "refused",
                "reason": "page_is_tracked",
                "detail": (
                    f"Page {resolved_id} is tracked by config entry "
                    f"file={tracked.get('file')}. Edit the local file and "
                    f"run push."
                ),
            }

        if expected_hash:
            actual = normalized_hash(page.get("markdown", ""))
            if actual != expected_hash:
                return {
                    "status": "conflict",
                    "reason": "hash_mismatch",
                    "expected_hash": expected_hash,
                    "actual_hash": actual,
                }

        page_title = new_title or current_title
        result = client.update_page(resolved_id, page_title, markdown)
        return {
            "status": "updated",
            "page_id": result.get("id", resolved_id),
            "title": result.get("name", page_title),
            "content_hash": normalized_hash(markdown),
        }
    return await _run_captured(_run)


# ─── Resources ───
# Exposed as bookstack:// URIs so MCP clients can surface wiki pages as
# context attachments (in Claude Desktop, users can @-mention them).


@mcp.resource("bookstack://page/{page_id}")
async def page_by_id_resource(page_id: str) -> str:
    """Fetch a BookStack page's markdown content by numeric id."""
    if _config_error:
        return f"Error: bssync-mcp is not configured — {_config_error}"
    try:
        pid = int(page_id)
    except ValueError:
        return f"Error: page_id must be an integer, got {page_id!r}"

    def _run():
        client = _new_client()
        page = client.get_page(pid)
        name = page.get("name", f"page {pid}")
        md = page.get("markdown", "")
        if md:
            return f"# {name}\n\n{md}"
        return (f"# {name}\n\n(This page has no stored markdown — it may "
                f"have been edited only in BookStack's WYSIWYG editor, "
                f"which stores HTML.)")
    return await asyncio.to_thread(_run)


@mcp.resource("bookstack://page/by-title/{book}/{title}")
async def page_by_title_resource(book: str, title: str) -> str:
    """Fetch a BookStack page's markdown by (book name, page title)."""
    if _config_error:
        return f"Error: bssync-mcp is not configured — {_config_error}"

    def _run():
        client = _new_client()
        b = client.find_book(book)
        if not b:
            return f"Error: book '{book}' not found on BookStack"
        lookup = client.find_page_in_book(b["id"], title)
        if not lookup:
            return f"Error: page '{title}' not found in book '{book}'"
        page = client.get_page(lookup["id"])
        md = page.get("markdown", "")
        if md:
            return f"# {title}\n\n{md}"
        return f"# {title}\n\n(empty markdown — WYSIWYG-only page)"
    return await asyncio.to_thread(_run)


# ─── Prompts ───
# Reusable templates that appear in Claude Desktop's slash-command picker.
# Kept minimal — two high-utility templates; users compose the rest via
# natural conversation.


@mcp.prompt()
def summarize_page(
    page_id: Optional[int] = None,
    book: Optional[str] = None,
    title: Optional[str] = None,
) -> str:
    """Summarize a BookStack page in 3-5 bullets using bssync tools."""
    if page_id is not None:
        ref = f"the BookStack page with id {page_id}"
    elif book and title:
        ref = f"the BookStack page titled \"{title}\" in book \"{book}\""
    else:
        ref = "a BookStack page (use search_pages or list_pages_in to find one)"
    return (
        f"Fetch {ref} via the bssync MCP tools (get_page) and summarize "
        f"its contents in 3-5 bullet points focused on the key takeaways. "
        f"Lead with the page title as a heading. If the page is long, "
        f"also call out anything that looks outdated or action-required."
    )


@mcp.prompt()
def find_docs(query: str) -> str:
    """Find BookStack pages matching a topic and report back with links."""
    return (
        f"Use the bssync search_pages tool to find wiki pages related to: "
        f"{query}\n\n"
        f"For each relevant result, report: the page title, its book, a "
        f"one-sentence summary of what the page covers, and the BookStack "
        f"URL. If nothing obvious matches, try a few related search terms "
        f"before giving up."
    )


# ─── Entry point ───


def main():
    global _config, _config_dir, _config_error

    # --version short-circuits config loading so binary smoke-tests (and
    # install verification) work without credentials.
    if "--version" in sys.argv or "-V" in sys.argv:
        print(f"bssync-mcp {__version__}")
        return

    config_path = Path(os.environ.get("BSSYNC_CONFIG", "bookstack.yaml"))

    # Any stdout from load_config / verify_connection must go to stderr —
    # Claude Desktop's MCP protocol owns stdout from this point onward.
    # Don't exit on config failures: Claude Desktop would just show an
    # opaque "server disconnected". Start anyway and let every tool return
    # a structured config_invalid error instead.
    with contextlib.redirect_stdout(sys.stderr):
        try:
            _config = load_config(str(config_path))
            _config_dir = config_path.parent.resolve()

            bs = _config["bookstack"]
            probe = BookStackClient(
                url=bs["url"], token_id=bs["token_id"],
                token_secret=bs["token_secret"], dry_run=False, verbose=False,
            )
            if not probe.verify_connection():
                raise RuntimeError(
                    f"failed to connect to {bs['url']} — check credentials "
                    f"and network"
                )

            sys.stderr.write(
                f"bssync-mcp v{__version__}: connected to {bs['url']}, "
                f"{len(_config.get('publish') or [])} tracked entries. "
                f"Serving on stdio.\n"
            )
        except SystemExit:
            _config_error = (
                "configuration failed to load — no bookstack.yaml found "
                "and BOOKSTACK_URL / BOOKSTACK_TOKEN_ID / "
                "BOOKSTACK_TOKEN_SECRET env vars are not all set"
            )
            sys.stderr.write(
                f"bssync-mcp: {_config_error}\n"
                f"bssync-mcp: server will start; tool calls will return a "
                f"config_invalid error until this is fixed.\n"
            )
        except Exception as e:
            _config_error = str(e)
            sys.stderr.write(
                f"bssync-mcp: startup failed: {e}\n"
                f"bssync-mcp: server will start; tool calls will return a "
                f"config_invalid error until this is fixed.\n"
            )

    mcp.run()


if __name__ == "__main__":
    main()
