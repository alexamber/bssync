"""MCP resources — `bookstack://` URIs that surface wiki pages as
context. In Claude Desktop these appear as @-mentionable attachments."""

import asyncio

from mcp.server.fastmcp import Context
from mcp.server.session import ServerSession

from bssync.mcp.helpers import ServerContext, new_client
from bssync.mcp.server import mcp


@mcp.resource("bookstack://page/{page_id}")
async def page_by_id(
    page_id: str,
    ctx: Context[ServerSession, ServerContext],
) -> str:
    """Fetch a BookStack page's markdown content by numeric id."""
    sc: ServerContext = ctx.request_context.lifespan_context
    if sc.config_error:
        return f"Error: bssync-mcp is not configured — {sc.config_error}"
    try:
        pid = int(page_id)
    except ValueError:
        return f"Error: page_id must be an integer, got {page_id!r}"

    def _run():
        client = new_client(sc)
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
async def page_by_title(
    book: str,
    title: str,
    ctx: Context[ServerSession, ServerContext],
) -> str:
    """Fetch a BookStack page's markdown by (book name, page title)."""
    sc: ServerContext = ctx.request_context.lifespan_context
    if sc.config_error:
        return f"Error: bssync-mcp is not configured — {sc.config_error}"

    def _run():
        client = new_client(sc)
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
