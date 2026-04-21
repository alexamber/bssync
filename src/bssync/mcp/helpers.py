"""Shared helpers for MCP tools / resources / prompts.

Holds the `ServerContext` dataclass that lifespan yields and every tool
reads, plus small utilities for page lookup, tracking guardrails, and the
structured config-error response used whenever the server started without
valid credentials.
"""

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from bssync.client import BookStackClient
from bssync.discovery import is_tracked


@dataclass
class ServerContext:
    """Lifespan-scoped state passed to every tool via Context.

    `config_error` is set by `load_at_startup` when config loading or the
    connection probe failed. Tools short-circuit with a structured
    response when it's set, so Claude surfaces a clear error to the user
    instead of the MCP client showing an opaque 'server disconnected'.
    """
    config: dict
    config_dir: Path
    config_error: Optional[str] = None


def new_client(sc: ServerContext, dry_run: bool = False) -> BookStackClient:
    """Fresh client per tool call — book/chapter caches live for one call
    only, which is fine and avoids cross-call dry_run state bleed."""
    bs = sc.config["bookstack"]
    return BookStackClient(
        url=bs["url"], token_id=bs["token_id"],
        token_secret=bs["token_secret"],
        dry_run=dry_run, verbose=False,
    )


def config_error_response(err: str) -> dict:
    return {
        "status": "error",
        "reason": "config_invalid",
        "detail": err,
        "fix": (
            "Set BSSYNC_CONFIG to point to a valid bookstack.yaml, or set "
            "BOOKSTACK_URL + BOOKSTACK_TOKEN_ID + BOOKSTACK_TOKEN_SECRET "
            "env vars in your MCP client config. Restart the MCP server "
            "after fixing."
        ),
    }


def filter_entries(sc: ServerContext, only: Optional[str]) -> list:
    entries = sc.config.get("publish", []) or []
    if not only:
        return entries
    needle = only.lower()
    return [
        e for e in entries
        if needle in e.get("file", "").lower()
        or needle in (e.get("title") or "").lower()
    ]


def tracking_match(sc: ServerContext, book: str,
                   title: str) -> Optional[dict]:
    """Return the config entry tracking (book, title), or None.
    Reuses discovery.is_tracked so tracking logic stays in one place."""
    page_like = {"book": book, "chapter": "", "name": title}
    for entry in sc.config.get("publish", []) or []:
        if is_tracked(page_like, [entry]):
            return entry
    return None


def require_one_identifier(page_id: Optional[int],
                           book: Optional[str],
                           title: Optional[str]) -> Optional[dict]:
    """Validate that a page-addressable tool received exactly one of
    (page_id) or (book AND title). Returns an error dict when invalid,
    None when OK."""
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


def resolve_page(client: BookStackClient,
                 page_id: Optional[int],
                 book: Optional[str],
                 title: Optional[str]) -> dict:
    """Resolve (book, title) to {"page_id": int}, or pass page_id through.
    Returns a structured error dict when lookup fails. Assumes
    `require_one_identifier` already validated the inputs."""
    if page_id is not None:
        return {"page_id": page_id}
    b = client.find_book(book)
    if not b:
        return {"error": "book_not_found",
                "status": "error", "reason": "book_not_found",
                "detail": f"book '{book}' not found on BookStack"}
    page = client.find_page_in_book(b["id"], title)
    if not page:
        return {"error": "page_not_found",
                "status": "error", "reason": "page_not_found",
                "detail": f"page '{title}' not found in book '{book}'"}
    return {"page_id": page["id"]}


async def run_in_thread(ctx, fn: Callable):
    """Short-circuit with a structured config_invalid response if the
    lifespan context carries a config_error; otherwise run `fn` in a
    thread so blocking HTTP calls don't jam the event loop."""
    sc: ServerContext = ctx.request_context.lifespan_context
    if sc.config_error:
        return config_error_response(sc.config_error)
    return await asyncio.to_thread(fn)
