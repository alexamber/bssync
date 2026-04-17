"""Conflict detection, diff display, and interactive prompts.

Sync state is stored on BookStack itself as a `content_hash` tag on each
page — no local state file. When pushing, we compare the stored hash
against the current remote content's hash to detect external edits.
"""

import difflib
import sys

from bssync import term
from bssync.client import BookStackClient
from bssync.content import normalize_markdown


# ─── Diff helpers ───


def diff_summary(old: str, new: str) -> tuple[int, int]:
    """Return (lines_added, lines_removed) between old and new text."""
    old_lines = normalize_markdown(old).splitlines()
    new_lines = normalize_markdown(new).splitlines()
    matcher = difflib.SequenceMatcher(None, old_lines, new_lines)
    added = removed = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "replace":
            removed += i2 - i1
            added += j2 - j1
        elif tag == "delete":
            removed += i2 - i1
        elif tag == "insert":
            added += j2 - j1
    return added, removed


def print_unified_diff(old: str, new: str, from_label: str, to_label: str,
                       max_lines: int = 80):
    """Print a unified diff, truncated to max_lines."""
    old_lines = normalize_markdown(old).splitlines(keepends=True)
    new_lines = normalize_markdown(new).splitlines(keepends=True)
    diff = list(difflib.unified_diff(
        old_lines, new_lines, fromfile=from_label, tofile=to_label, n=3))
    if not diff:
        print(term.dim("    (no textual diff — only whitespace or normalization)"))
        return
    for line in diff[:max_lines]:
        text = line.rstrip()
        if text.startswith("+++") or text.startswith("---"):
            print(f"    {term.bold(text)}")
        elif text.startswith("@@"):
            print(f"    {term.info(text)}")
        elif text.startswith("+"):
            print(f"    {term.ok(text)}")
        elif text.startswith("-"):
            print(f"    {term.err(text)}")
        else:
            print(f"    {text}")
    if len(diff) > max_lines:
        print(term.dim(f"    ... ({len(diff) - max_lines} more lines)"))


# ─── Interactive prompts ───


def is_interactive() -> bool:
    """Return True if stdin/stdout are connected to a TTY."""
    return sys.stdin.isatty() and sys.stdout.isatty()


def prompt_conflict_action(title: str, remote_md: str, local_md: str,
                           added: int, removed: int) -> str:
    """Prompt for action on a push conflict.

    Returns one of: 'overwrite', 'skip', 'pull', 'quit'.
    """
    print(f"  {term.warn(term.bold('⚠ CONFLICT'))}: \"{title}\" modified on "
          f"BookStack since last publish")
    print(f"    Remote diff vs last sync: "
          f"{term.ok(f'+{added}')} / {term.err(f'-{removed}')} lines")
    while True:
        print("    [o] overwrite remote   [s] skip   [d] show diff   "
              "[p] pull remote first   [q] quit")
        try:
            choice = input("    → ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return "quit"
        if choice in ("o", "overwrite"):
            return "overwrite"
        if choice in ("s", "skip", "n"):
            return "skip"
        if choice in ("d", "diff"):
            print_unified_diff(local_md, remote_md, "local (last)",
                               "remote (now)")
        elif choice in ("p", "pull"):
            return "pull"
        elif choice in ("q", "quit"):
            return "quit"
        else:
            print("    Please enter one of: o, s, d, p, q")


def prompt_pull_overwrite(title: str, local_md: str, remote_md: str,
                          added: int, removed: int) -> str:
    """Prompt whether to overwrite a local file on pull.

    Returns one of: 'overwrite', 'skip', 'quit'.
    """
    print(f"  Remote changes for \"{title}\": "
          f"{term.ok(f'+{added}')} / {term.err(f'-{removed}')} lines")
    while True:
        print("    [y] overwrite local   [n] skip   [d] show diff   [q] quit")
        try:
            choice = input("    → ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return "quit"
        if choice in ("y", "yes", "o"):
            return "overwrite"
        if choice in ("n", "no", "s"):
            return "skip"
        if choice in ("d", "diff"):
            print_unified_diff(local_md, remote_md, "local", "remote")
        elif choice in ("q", "quit"):
            return "quit"
        else:
            print("    Please enter one of: y, n, d, q")


# ─── Sync tag helpers ───


def extract_tag(tags: list, name: str, default: str = "") -> str:
    """Read a tag value from a BookStack page's tag list."""
    for t in tags or []:
        if t.get("name") == name:
            return t.get("value", default)
    return default


def set_sync_tag(client: BookStackClient, page_detail: dict,
                 content_hash_value: str, source_file: str = None):
    """Update the content_hash tag on a page without changing its content.

    Used after a pull (to record what we just synced) and when the user
    chooses 'pull remote first' during a push conflict. One API call.
    """
    existing_tags = page_detail.get("tags", []) or []
    new_tags = [{"name": t["name"], "value": t["value"]}
                for t in existing_tags if t.get("name") != "content_hash"]
    if source_file and not any(t["name"] == "source_file" for t in new_tags):
        new_tags.append({"name": "source_file", "value": source_file})
    if not any(t["name"] == "source" for t in new_tags):
        new_tags.append({"name": "source", "value": "auto-sync"})
    new_tags.append({"name": "content_hash", "value": content_hash_value})

    try:
        client.update_page(page_detail["id"], page_detail["name"],
                           page_detail.get("markdown", ""), tags=new_tags)
    except Exception as e:
        print(f"    warning: could not update sync tag: {e}")
