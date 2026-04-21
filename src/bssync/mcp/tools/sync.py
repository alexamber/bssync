"""Sync tools — mirror the bssync CLI's push / pull / ls / discover /
verify, but non-interactive and returning structured results.

Conflicts don't prompt; they come back as status=skipped with a
conflict reason so the LLM can tell the user, who can re-run with
force=true. Long runs emit per-entry progress via the MCP Context.
"""

import asyncio
from dataclasses import asdict
from typing import Optional

from mcp.server.fastmcp import Context
from mcp.server.session import ServerSession

from bssync.discovery import (
    is_tracked,
    list_all_pages,
    resolve_entries,
    suggest_config_entry,
)
from bssync.mcp.helpers import (
    ServerContext,
    config_error_response,
    filter_entries,
    new_client,
    run_in_thread,
)
from bssync.mcp.server import mcp
from bssync.sync import SyncStatus, publish_entry, pull_entry


def _result_to_dict(result) -> dict:
    """Serialize an EntryResult for JSON. The status enum becomes its
    string value."""
    d = asdict(result)
    d["status"] = result.status.value
    d["changed"] = result.changed
    return d


@mcp.tool()
async def verify(ctx: Context[ServerSession, ServerContext]) -> dict:
    """Check that the BookStack API is reachable with the current
    credentials. Returns {connected: bool, url: str}."""
    def _run():
        sc: ServerContext = ctx.request_context.lifespan_context
        client = new_client(sc)
        return {"connected": client.verify_connection(), "url": client.url}
    return await run_in_thread(ctx, _run)


@mcp.tool()
async def push(
    ctx: Context[ServerSession, ServerContext],
    only: Optional[str] = None,
    dry_run: bool = False,
    force: bool = False,
    refresh_uploads: bool = False,
) -> dict:
    """Upload local markdown files to BookStack per the config's publish: list.

    Conflicts (remote edited since last sync) come back as entries with
    status=conflict; retry with force=true to overwrite. Long pushes
    emit per-entry progress via the MCP Context.

    Args:
        only: Only push entries whose file path or title contains this
            substring (case-insensitive).
        dry_run: Preview changes without making API writes.
        force: Overwrite remote even if it was edited since last sync.
        refresh_uploads: Force re-upload of all images and attachments.
    """
    sc: ServerContext = ctx.request_context.lifespan_context
    if sc.config_error:
        return config_error_response(sc.config_error)

    entries = filter_entries(sc, only)
    client = new_client(sc, dry_run=dry_run)

    results: list = []
    updated = unchanged = skipped = 0
    total = len(entries)

    for i, entry in enumerate(entries):
        await ctx.info(f"[{i + 1}/{total}] pushing {entry['file']}")
        await ctx.report_progress(progress=i, total=total)

        def _run_entry(entry=entry):
            return publish_entry(
                client, entry, sc.config_dir,
                show_diff=False, force=force,
                refresh_uploads=refresh_uploads,
            )

        try:
            result = await asyncio.to_thread(_run_entry)
        except Exception as e:
            skipped += 1
            results.append({"file": entry["file"], "status": "error",
                            "error": str(e)})
            continue

        if result.changed:
            updated += 1
        elif result.status in (SyncStatus.CONFLICT, SyncStatus.SKIPPED):
            skipped += 1
        else:
            unchanged += 1
        results.append(_result_to_dict(result))

    await ctx.report_progress(progress=total, total=total)

    return {
        "summary": {"updated": updated, "unchanged": unchanged,
                    "skipped": skipped, "total": total},
        "entries": results,
        "dry_run": dry_run,
    }


@mcp.tool()
async def pull(
    ctx: Context[ServerSession, ServerContext],
    only: Optional[str] = None,
) -> dict:
    """Download BookStack page contents into local files per the
    config's publish: list.

    Non-interactive: if a local file differs from remote, the entry is
    reported with status=differs and left untouched — edit locally and
    run push, or delete the local file and pull again.

    Args:
        only: Only pull entries whose file path or title contains this
            substring (case-insensitive).
    """
    sc: ServerContext = ctx.request_context.lifespan_context
    if sc.config_error:
        return config_error_response(sc.config_error)

    entries = filter_entries(sc, only)
    client = new_client(sc)

    results: list = []
    updated = unchanged = skipped = 0
    total = len(entries)

    for i, entry in enumerate(entries):
        await ctx.info(f"[{i + 1}/{total}] pulling {entry['file']}")
        await ctx.report_progress(progress=i, total=total)

        def _run_entry(entry=entry):
            return pull_entry(client, entry, sc.config_dir)

        try:
            result = await asyncio.to_thread(_run_entry)
        except Exception as e:
            skipped += 1
            results.append({"file": entry["file"], "status": "error",
                            "error": str(e)})
            continue

        if result.changed:
            updated += 1
        elif result.status in (SyncStatus.DIFFERS, SyncStatus.SKIPPED):
            skipped += 1
        else:
            unchanged += 1
        results.append(_result_to_dict(result))

    await ctx.report_progress(progress=total, total=total)

    return {
        "summary": {"updated": updated, "unchanged": unchanged,
                    "skipped": skipped, "total": total},
        "entries": results,
    }


@mcp.tool()
async def ls(
    ctx: Context[ServerSession, ServerContext],
    book: Optional[str] = None,
    chapter: Optional[str] = None,
    missing: bool = False,
) -> dict:
    """List pages on BookStack with tracking state relative to the config.

    Args:
        book: Filter to pages in this book.
        chapter: Filter to pages in this chapter.
        missing: Only show pages NOT tracked in config.
    """
    def _run():
        sc: ServerContext = ctx.request_context.lifespan_context
        client = new_client(sc)
        pages = list_all_pages(client, book, chapter)
        entries = resolve_entries(
            sc.config.get("publish", []) or [], sc.config_dir)
        result = []
        for p in pages:
            tracked = is_tracked(p, entries)
            if missing and tracked:
                continue
            result.append({**p, "tracked": tracked})
        return {"count": len(result), "pages": result}
    return await run_in_thread(ctx, _run)


@mcp.tool()
async def discover(
    ctx: Context[ServerSession, ServerContext],
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
        sc: ServerContext = ctx.request_context.lifespan_context
        client = new_client(sc)
        raw_entries = sc.config.get("publish", []) or []
        entries = resolve_entries(raw_entries, sc.config_dir)
        existing_files = {e.get("file") for e in raw_entries}
        pages = list_all_pages(client, book, chapter)
        untracked = [p for p in pages if not is_tracked(p, entries)]
        snippets = [suggest_config_entry(p, existing_files)
                    for p in untracked]
        return {
            "count": len(untracked),
            "untracked": untracked,
            "yaml_snippets": snippets,
        }
    return await run_in_thread(ctx, _run)
