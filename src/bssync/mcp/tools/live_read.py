"""Read-only live tools — browse BookStack directly, no local files."""

from typing import Optional

from mcp.server.fastmcp import Context
from mcp.server.session import ServerSession

from bssync.content import normalized_hash
from bssync.discovery import list_all_pages
from bssync.mcp.helpers import (
    ServerContext,
    new_client,
    require_one_identifier,
    resolve_page,
    run_in_thread,
)
from bssync.mcp.server import mcp


@mcp.tool()
async def list_books(
    ctx: Context[ServerSession, ServerContext],
) -> dict:
    """List all books on the BookStack instance."""
    def _run():
        sc: ServerContext = ctx.request_context.lifespan_context
        client = new_client(sc)
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
    return await run_in_thread(ctx, _run)


@mcp.tool()
async def list_chapters(
    ctx: Context[ServerSession, ServerContext],
    book: str,
) -> dict:
    """List chapters in a book.

    Args:
        book: Book name or numeric book id (as a string).
    """
    def _run():
        sc: ServerContext = ctx.request_context.lifespan_context
        client = new_client(sc)
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
                {"id": c["id"], "name": c["name"],
                 "slug": c.get("slug", "")}
                for c in chapters
            ],
        }
    return await run_in_thread(ctx, _run)


@mcp.tool()
async def list_pages_in(
    ctx: Context[ServerSession, ServerContext],
    book: Optional[str] = None,
    chapter: Optional[str] = None,
) -> dict:
    """List pages on BookStack, optionally scoped to a book and/or chapter.

    Args:
        book: Book name filter.
        chapter: Chapter name filter.
    """
    def _run():
        sc: ServerContext = ctx.request_context.lifespan_context
        client = new_client(sc)
        pages = list_all_pages(client, book, chapter)
        return {"count": len(pages), "pages": pages}
    return await run_in_thread(ctx, _run)


@mcp.tool()
async def search_pages(
    ctx: Context[ServerSession, ServerContext],
    query: str,
    count: int = 20,
) -> dict:
    """Search BookStack for pages matching a query.

    Args:
        query: Search query passed to BookStack's search API.
        count: Max number of results (default 20).
    """
    def _run():
        sc: ServerContext = ctx.request_context.lifespan_context
        client = new_client(sc)
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
    return await run_in_thread(ctx, _run)


@mcp.tool()
async def get_page(
    ctx: Context[ServerSession, ServerContext],
    page_id: Optional[int] = None,
    book: Optional[str] = None,
    title: Optional[str] = None,
) -> dict:
    """Fetch a BookStack page's full markdown and metadata.

    Identify the page by either `page_id`, or by `(book, title)` — the
    second form saves an extra search step when you already know the
    names. Pass exactly one form.

    The returned `content_hash` can be passed back to `update_page` as
    `expected_hash` for optimistic concurrency.

    Args:
        page_id: Numeric page id.
        book: Book name (used with `title`).
        title: Page title (used with `book`).
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
    return await run_in_thread(ctx, _run)
