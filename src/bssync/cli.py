"""Command-line entry point.

Dispatches to subcommand handlers (init, push, pull, ls, verify). With no
subcommand, prints help.
"""

import argparse
import os
import sys
from pathlib import Path

from bssync import __version__
from bssync import term


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bssync",
        description="Sync local markdown files with a BookStack wiki.")
    default_config = os.environ.get("BSSYNC_CONFIG", "bookstack.yaml")
    parser.add_argument("-c", "--config", default=default_config,
                        help="Config file path (default: $BSSYNC_CONFIG or "
                             "bookstack.yaml)")
    parser.add_argument("--verbose", action="store_true",
                        help="Show API request details")
    parser.add_argument("-V", "--version", action="version",
                        version=f"bssync {__version__}")

    subs = parser.add_subparsers(dest="command")

    subs.add_parser("init", help="Interactive config setup")

    push = subs.add_parser("push", help="Upload local → BookStack")
    push.add_argument("--dry-run", action="store_true",
                      help="Preview changes without making API writes")
    push.add_argument("--diff", action="store_true",
                      help="Show content diff for updated pages")
    push.add_argument("--only", type=str,
                      help="Only push entries matching this string")
    push.add_argument("--force", action="store_true",
                      help="Skip conflict check; overwrite remote")
    push.add_argument("--refresh-uploads", action="store_true",
                      help="Unconditionally re-upload all images and "
                           "attachments, ignoring stored content hashes")

    pull = subs.add_parser("pull", help="Download BookStack → local")
    pull.add_argument("--only", type=str,
                      help="Only pull entries matching this string")
    pull.add_argument("--new", action="store_true",
                      help="Discovery mode: list untracked pages")
    pull.add_argument("--book", type=str,
                      help="Scope by book name (for --new)")
    pull.add_argument("--chapter", type=str,
                      help="Scope by chapter name (for --new)")

    ls = subs.add_parser("ls", help="List pages on BookStack")
    ls.add_argument("--book", type=str, help="Filter by book name")
    ls.add_argument("--chapter", type=str, help="Filter by chapter name")
    ls.add_argument("--missing", action="store_true",
                    help="Only show pages not tracked in config")

    subs.add_parser("verify", help="Test API connection")

    comp = subs.add_parser("completions",
                           help="Print shell completion script to stdout")
    comp.add_argument("shell", choices=["bash", "zsh", "fish"],
                      help="Target shell")

    mcp = subs.add_parser("mcp",
                          help="MCP server helpers (install, configure)")
    mcp_subs = mcp.add_subparsers(dest="mcp_command", required=True)
    mcp_install = mcp_subs.add_parser(
        "install",
        help="Register the bssync MCP server with Claude Code / Desktop")
    mcp_install.add_argument(
        "--target",
        choices=["auto", "code", "desktop", "both", "print"],
        default="auto",
        help="Which client to install into. "
             "`auto` detects and prompts if both are present; "
             "`print` just emits config snippets.")
    mcp_install.add_argument("--url",
                             help="BookStack URL (else prompted or from "
                                  "BOOKSTACK_URL)")
    mcp_install.add_argument("--token-id", dest="token_id",
                             help="API token ID (else prompted or from "
                                  "BOOKSTACK_TOKEN_ID)")
    mcp_install.add_argument("--token-secret", dest="token_secret",
                             help="API token secret (else prompted or "
                                  "from BOOKSTACK_TOKEN_SECRET)")
    mcp_install.add_argument("--config-file", dest="config_file",
                             help="Optional bookstack.yaml path for "
                                  "push/pull support")
    mcp_install.add_argument("--non-interactive", action="store_true",
                             help="Skip prompts; require flags/env vars")

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return

    # `completions` is pure stdout — no config needed
    if args.command == "completions":
        from bssync.completions import cmd_completions
        cmd_completions(args.shell)
        return

    # `mcp install` configures the MCP server against Claude clients; it
    # does its own connection verification and shouldn't need a
    # bookstack.yaml to exist first.
    if args.command == "mcp":
        if args.mcp_command == "install":
            from bssync.mcp_install import cmd_mcp_install
            sys.exit(cmd_mcp_install(args))
        return  # argparse enforces a subcommand via required=True

    config_path = Path(args.config)

    # `init` runs before any config loading since it creates the config
    if args.command == "init":
        from bssync.init import cmd_init
        cmd_init(config_path, non_interactive=not sys.stdin.isatty())
        return

    # Lazy imports so `bssync init` / `bssync --help` stay fast
    from bssync.client import BookStackClient
    from bssync.config import ConfigError, load_config

    try:
        config = load_config(str(config_path))
    except ConfigError as e:
        print(term.err(f"Error: {e.message}"))
        if e.fix:
            print(f"  {e.fix}")
        sys.exit(1)
    config_dir = config_path.parent

    bs = config["bookstack"]
    client = BookStackClient(
        url=bs["url"],
        token_id=bs["token_id"],
        token_secret=bs["token_secret"],
        dry_run=getattr(args, "dry_run", False),
        verbose=args.verbose,
    )

    print(f"Connecting to {bs['url']}...")
    if not client.verify_connection():
        print(term.err("Failed to connect. Check URL and API credentials."))
        sys.exit(1)
    print(term.dim("Connected."))

    if args.command == "verify":
        print("Connection verified.")
        return

    if args.command == "ls":
        from bssync.discovery import cmd_ls
        cmd_ls(client, config, args, config_dir)
        return

    if args.command == "pull" and args.new:
        from bssync.discovery import cmd_pull_discover
        cmd_pull_discover(client, config, args, config_dir)
        return

    # push or pull with config entries
    entries = config.get("publish", [])
    if getattr(args, "only", None):
        entries = [
            e for e in entries
            if args.only.lower() in e.get("file", "").lower()
            or args.only.lower() in (e.get("title") or "").lower()
        ]
        if not entries:
            print(f"No entries matching '{args.only}'")
            return

    if args.command == "pull":
        _run_pull(client, entries, config_dir)
    else:
        _run_push(client, entries, config_dir, args)


def _render_result(result):
    """Render one EntryResult line under the `  <file>` heading that was
    already printed above. Colors + label follow the pre-refactor UX."""
    from bssync.sync import SyncStatus
    s = result.status
    if s is SyncStatus.UPDATED:
        extra = ""
        if result.diff_added is not None and result.diff_removed is not None:
            extra = (f" ({term.ok(f'+{result.diff_added}')}/"
                     f"{term.err(f'-{result.diff_removed}')})")
        page_info = f" (page {result.page_id})" if result.page_id else ""
        print(f"    {term.ok('UPDATED')}: {result.title}{page_info}{extra}")
    elif s is SyncStatus.CREATED:
        page_info = f" (page {result.page_id})" if result.page_id else ""
        detail = f" → {result.detail}" if result.detail else ""
        print(f"    {term.ok('CREATED')}: {result.title}{page_info}{detail}")
    elif s is SyncStatus.MOVED:
        print(f"    {term.ok('MOVED')}: {result.title} {result.detail}")
        if result.content_updated:
            print(f"    {term.ok('UPDATED')}: {result.title} "
                  f"(page {result.page_id})")
    elif s is SyncStatus.PULLED:
        print(f"    {term.ok('PULLED')}: {result.title} → {result.detail}")
    elif s is SyncStatus.UNCHANGED:
        print(f"    {term.dim('UNCHANGED')}: {result.title}")
    elif s is SyncStatus.CONFLICT:
        added, removed = result.diff_added or 0, result.diff_removed or 0
        print(f"    {term.warn('CONFLICT')}: \"{result.title}\" was modified "
              f"on BookStack since last publish "
              f"({term.ok(f'+{added}')}/{term.err(f'-{removed}')} lines). "
              f"Use --force to overwrite.")
    elif s is SyncStatus.DIFFERS:
        added, removed = result.diff_added or 0, result.diff_removed or 0
        print(f"    {term.warn('DIFFERS')}: \"{result.title}\" differs from "
              f"remote ({term.ok(f'+{added}')}/{term.err(f'-{removed}')}). "
              f"Run interactively to overwrite.")
    elif s is SyncStatus.SKIPPED:
        tail = f": {result.detail}" if result.detail else ""
        print(f"    {term.warn('SKIP')}{tail}")


def _on_progress_print(msg: str) -> None:
    """Callback for sync orchestrators to emit per-file sub-events. Matches
    the previous pre-refactor indentation; uppercase for backward-looking
    visual parity with the UPDATED/UPLOADED/UNCHANGED labels."""
    print(f"    {msg.upper()}")


def _run_push(client, entries, config_dir, args):
    from bssync.sync import SyncStatus, publish_entry

    if args.dry_run:
        print(f"\n[DRY RUN] Would push {len(entries)} entries:\n")
    else:
        print(f"\nPushing {len(entries)} entries:\n")

    updated = unchanged = skipped = 0
    for entry in entries:
        print(f"  {entry['file']}")
        try:
            result = publish_entry(
                client, entry, config_dir,
                show_diff=args.diff, force=args.force,
                refresh_uploads=args.refresh_uploads,
                on_progress=_on_progress_print)
            _render_result(result)
            if result.changed:
                updated += 1
            elif result.status in (SyncStatus.CONFLICT, SyncStatus.SKIPPED):
                skipped += 1
            else:
                unchanged += 1
        except Exception as e:
            print(f"    {term.err('ERROR')}: {e}")
            skipped += 1

    print(f"\nDone: {term.ok(f'{updated} pushed')}, "
          f"{term.dim(f'{unchanged} unchanged')}, "
          f"{term.warn(f'{skipped} skipped')}")


def _run_pull(client, entries, config_dir):
    from bssync.sync import SyncStatus, pull_entry

    print(f"\nPulling {len(entries)} entries:\n")
    updated = unchanged = skipped = 0
    for entry in entries:
        print(f"  {entry['file']}")
        try:
            result = pull_entry(client, entry, config_dir,
                                on_progress=_on_progress_print)
            _render_result(result)
            if result.changed:
                updated += 1
            elif result.status in (SyncStatus.DIFFERS, SyncStatus.SKIPPED):
                skipped += 1
            else:
                unchanged += 1
        except Exception as e:
            print(f"    {term.err('ERROR')}: {e}")
            skipped += 1
    print(f"\nDone: {term.ok(f'{updated} pulled')}, "
          f"{term.dim(f'{unchanged} unchanged')}, "
          f"{term.warn(f'{skipped} skipped')}")


if __name__ == "__main__":
    main()
