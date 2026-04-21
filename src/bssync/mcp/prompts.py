"""MCP prompts — reusable slash-picker templates in Claude Desktop.

Prompts don't hit BookStack; they produce a string that nudges Claude to
use the bssync tools with the right arguments. No context needed.
"""

from typing import Optional

from bssync.mcp.server import mcp


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
        ref = f'the BookStack page titled "{title}" in book "{book}"'
    else:
        ref = ("a BookStack page (use search_pages or list_pages_in to "
               "find one)")
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
