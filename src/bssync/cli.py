"""Command-line entry point.

Dispatches to subcommand handlers (init, push, pull, ls, verify). If no
subcommand is given, defaults to push for backwards-compatible invocation
as a simple publisher.
"""

import argparse
import sys
from pathlib import Path

from bssync import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bssync",
        description="Sync local markdown files with a BookStack wiki.")
    parser.add_argument("-c", "--config", default="bookstack.yaml",
                        help="Config file path (default: bookstack.yaml)")
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

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    # Default to push if no subcommand given
    if args.command is None:
        args.command = "push"
        args.dry_run = False
        args.diff = False
        args.only = None
        args.force = False

    config_path = Path(args.config)

    # `init` runs before any config loading since it creates the config
    if args.command == "init":
        from bssync.init import cmd_init
        cmd_init(config_path, non_interactive=not sys.stdin.isatty())
        return

    # Lazy imports so `bssync init` / `bssync --help` stay fast
    from bssync.client import BookStackClient
    from bssync.config import load_config

    config = load_config(str(config_path))
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
        print("Failed to connect. Check URL and API credentials.")
        sys.exit(1)
    print("Connected.")

    if args.command == "verify":
        print("Connection verified.")
        return

    if args.command == "ls":
        from bssync.discovery import cmd_ls
        cmd_ls(client, config, args)
        return

    if args.command == "pull" and args.new:
        from bssync.discovery import cmd_pull_discover
        cmd_pull_discover(client, config, args)
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


def _run_push(client, entries, config_dir, args):
    from bssync.sync import publish_entry

    if args.dry_run:
        print(f"\n[DRY RUN] Would push {len(entries)} entries:\n")
    else:
        print(f"\nPushing {len(entries)} entries:\n")

    updated = unchanged = skipped = 0
    for entry in entries:
        print(f"  {entry['file']}")
        try:
            changed = publish_entry(client, entry, config_dir,
                                    show_diff=args.diff, force=args.force)
            if changed:
                updated += 1
            else:
                unchanged += 1
        except FileNotFoundError:
            print("    SKIP: file not found")
            skipped += 1
        except Exception as e:
            print(f"    ERROR: {e}")
            skipped += 1

    print(f"\nDone: {updated} pushed, {unchanged} unchanged, {skipped} skipped")


def _run_pull(client, entries, config_dir):
    from bssync.sync import pull_entry

    print(f"\nPulling {len(entries)} entries:\n")
    updated = unchanged = skipped = 0
    for entry in entries:
        print(f"  {entry['file']}")
        try:
            if pull_entry(client, entry, config_dir):
                updated += 1
            else:
                unchanged += 1
        except Exception as e:
            print(f"    ERROR: {e}")
            skipped += 1
    print(f"\nDone: {updated} pulled, {unchanged} unchanged, {skipped} skipped")


if __name__ == "__main__":
    main()
