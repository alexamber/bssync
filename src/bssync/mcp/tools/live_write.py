"""Live write tools — create/update BookStack pages directly.

Guardrail: both tools refuse pages tracked in the config's publish: list,
preserving bssync's "local markdown is the source of truth" invariant.
Tracked pages must be edited locally and pushed.
"""

from typing import Optional

from mcp.server.fastmcp import Context
from mcp.server.session import ServerSession

from bssync.content import normalized_hash
from bssync.mcp.helpers import (
    ServerContext,
    new_client,
    require_one_identifier,
    resolve_page,
    run_in_thread,
    tracking_match,
)
from bssync.mcp.server import mcp


@mcp.tool()
async def create_page(
    ctx: Context[ServerSession, ServerContext],
    book: str,
    title: str,
    markdown: str,
    chapter: Optional[str] = None,
) -> dict:
    """Create a new page on BookStack directly (no local file).

    Guardrail: refuses if (book, title) would collide with a page
    tracked in the config's publish: list — those must go through local
    files + push.

    Args:
        book: Book name (created if it doesn't exist).
        title: Page title.
        markdown: Page body as markdown.
        chapter: Chapter name (created if missing; page goes in book
            root if omitted).
    """
    sc: ServerContext = ctx.request_context.lifespan_context
    if sc.config_error:
        from bssync.mcp.helpers import config_error_response
        return config_error_response(sc.config_error)

    tracked = tracking_match(sc, book, title)
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
        client = new_client(sc)
        b = client.find_book(book) or client.create_book(book)
        chapter_id = None
        if chapter:
            ch = (client.find_chapter(b["id"], chapter)
                  or client.create_chapter(b["id"], chapter))
            chapter_id = ch["id"]
        existing = client.find_page_in_book(b["id"], title)
        if existing:
            return {"status": "exists", "page_id": existing["id"],
                    "detail": "a page with this title already exists "
                              "in the book"}
        result = client.create_page(
            title, markdown,
            book_id=b["id"], chapter_id=chapter_id,
            tags=[{"name": "source", "value": "bssync-mcp-live"}],
        )
        page_id = result.get("id")
        # Re-fetch so content_hash reflects BookStack's stored form
        # rather than what we sent. BookStack can normalize markdown on
        # save (whitespace, list formatting); callers chaining
        # update_page with expected_hash would otherwise hit spurious
        # hash_mismatch conflicts. CLI's _reconcile_stored_hash does the
        # equivalent for the sync path; this brings live writes in line.
        stored_md = ""
        if page_id is not None and page_id >= 0:
            try:
                stored_md = client.get_page(page_id).get("markdown", "")
            except Exception:
                stored_md = markdown  # fall back to what we sent
        return {
            "status": "created",
            "page_id": page_id,
            "title": result.get("name"),
            "content_hash": normalized_hash(stored_md) if stored_md else "",
        }
    return await run_in_thread(ctx, _run)


@mcp.tool()
async def update_page(
    ctx: Context[ServerSession, ServerContext],
    markdown: str,
    page_id: Optional[int] = None,
    book: Optional[str] = None,
    title: Optional[str] = None,
    new_title: Optional[str] = None,
    expected_hash: Optional[str] = None,
) -> dict:
    """Update a BookStack page directly (no local file).

    Identify the page by `page_id`, or by `(book, title)`. Pass exactly
    one form. Note: `title` here means "find the page with this title";
    use `new_title` to rename the page.

    Guardrail: refuses if the page is tracked in the config's publish:
    list. Optional optimistic concurrency via `expected_hash` — pass the
    hash from a prior `get_page` call; the update fails with
    status=conflict if the stored markdown has changed since.

    Args:
        markdown: New page body.
        page_id: Numeric page id.
        book: Book name (used with `title`).
        title: Page title for lookup (used with `book`).
        new_title: Optional new title (omit to keep existing).
        expected_hash: If set, refuse the update when the current stored
            markdown hashes to a different value.
    """
    err = require_one_identifier(page_id, book, title)
    if err:
        return err

    def _run():
        sc: ServerContext = ctx.request_context.lifespan_context
        client = new_client(sc)
        resolved = resolve_page(client, page_id, book, title)
        if "error" in resolved:
            return resolved
        resolved_id = resolved["page_id"]

        page = client.get_page(resolved_id)
        current_title = page.get("name", "")
        book_id = page.get("book_id")
        book_lookup = next(
            (b for b in client.list_books() if b["id"] == book_id), None)
        book_name = book_lookup["name"] if book_lookup else ""

        tracked = tracking_match(sc, book_name, current_title)
        if tracked:
            return {
                "status": "refused",
                "reason": "page_is_tracked",
                "detail": (
                    f"Page {resolved_id} is tracked by config entry "
                    f"file={tracked.get('file')}. Edit the local file "
                    f"and run push."
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
        # See create_page above — re-fetch so content_hash matches the
        # stored form, not the sent form.
        try:
            stored_md = client.get_page(resolved_id).get("markdown", "")
        except Exception:
            stored_md = markdown
        return {
            "status": "updated",
            "page_id": result.get("id", resolved_id),
            "title": result.get("name", page_title),
            "content_hash": normalized_hash(stored_md) if stored_md else "",
        }
    return await run_in_thread(ctx, _run)
