"""Interactive installer for the bssync MCP server.

Wraps the claude_desktop_config.json / `claude mcp add` dance in a single
command. Prompts for BookStack URL + API token, verifies the connection
before touching client config, then registers the server with the MCP
clients it finds installed.

Deliberately imports nothing from the `mcp` SDK: users who `pip install
bssync` without the `[mcp]` extra can still run `bssync mcp install` to
generate config — the installer warns if the server binary isn't found
but still produces a working snippet so the user can install the extra
afterward.
"""

import getpass
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from bssync import __version__, term
from bssync.client import BookStackClient


# ─── Input collection ───


def _prompt_creds(url_default: Optional[str] = None,
                  token_id_default: Optional[str] = None,
                  token_secret_default: Optional[str] = None
                  ) -> tuple[str, str, str]:
    """Prompt for URL + token ID + token secret. Empty input reuses the
    provided default (useful when the user already set env vars)."""
    print()
    print(term.bold("What you'll need:"))
    print("- Your BookStack URL (e.g. https://wiki.example.com)")
    print("- A BookStack API token:")
    print("    Profile → Edit Profile → API Tokens → "
          "Create Token")
    print("    Copy both the Token ID and the Token Secret "
          "(the secret is shown only once).")
    print()

    def _prompt(prompt: str, default: Optional[str],
                secret: bool = False) -> str:
        suffix = f" [{default}]" if default and not secret else ""
        while True:
            if secret:
                val = getpass.getpass(f"  {prompt}: ").strip()
            else:
                val = input(f"  {prompt}{suffix}: ").strip()
            if val:
                return val
            if default:
                return default
            print(term.warn("    Required."))

    url = _prompt("BookStack URL", url_default)
    token_id = _prompt("Token ID", token_id_default)
    token_secret = _prompt("Token Secret", token_secret_default, secret=True)
    return url, token_id, token_secret


# ─── Verification ───


def _verify(url: str, token_id: str, token_secret: str) -> bool:
    """Quick smoke test against the BookStack API. Prints a one-line status."""
    print(f"  Verifying connection to {url}... ", end="", flush=True)
    client = BookStackClient(url=url, token_id=token_id,
                             token_secret=token_secret,
                             dry_run=False, verbose=False)
    ok = client.verify_connection()
    print(term.ok("ok") if ok else term.err("failed"))
    return ok


# ─── Binary location ───


def _resolve_server_command() -> tuple[str, list[str], Optional[str]]:
    """Return (command, args, warning).

    Prefers the `bssync-mcp` console script when on PATH. Falls back to
    `python -m bssync.mcp.server` using the current interpreter, which
    works as long as this Python can still import the bssync package.
    """
    path = shutil.which("bssync-mcp")
    if path:
        return path, [], None
    warning = (
        "bssync-mcp not found on PATH — using this Python interpreter "
        "with `-m bssync.mcp.server` as a fallback. Install the server "
        "with `pip install 'bssync[mcp]'` for a standalone binary."
    )
    return sys.executable, ["-m", "bssync.mcp.server"], warning


# ─── Client detection ───


def _claude_code_path() -> Optional[str]:
    return shutil.which("claude")


def _desktop_config_path() -> Optional[Path]:
    """Return the claude_desktop_config.json path on this platform, or
    None if Claude Desktop isn't a thing on this OS."""
    if sys.platform == "darwin":
        return (Path.home() / "Library" / "Application Support"
                / "Claude" / "claude_desktop_config.json")
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if not appdata:
            return None
        return Path(appdata) / "Claude" / "claude_desktop_config.json"
    # Linux has no official Claude Desktop build at the moment.
    return None


# ─── Install targets ───


def _install_claude_code(command: str, args: list[str],
                         env: dict[str, str]) -> bool:
    """Shell out to `claude mcp add`. Returns True on success."""
    cmd = ["claude", "mcp", "add", "bssync", command, *args]
    for k, v in env.items():
        cmd.extend(["-e", f"{k}={v}"])
    print(f"  Running: {' '.join(cmd[:6])} ...")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        print(term.err("  `claude` not found on PATH. Install Claude Code "
                       "first, or use --target=print."))
        return False
    if result.returncode != 0:
        print(term.err(f"  claude mcp add failed "
                       f"(exit {result.returncode})"))
        if result.stderr:
            print(term.dim(f"    {result.stderr.strip()}"))
        return False
    print(term.ok("  Registered with Claude Code."))
    if result.stdout.strip():
        print(term.dim(f"    {result.stdout.strip()}"))
    return True


def _install_claude_desktop(config_path: Path, command: str,
                            args: list[str], env: dict[str, str]) -> bool:
    """Merge a bssync entry into claude_desktop_config.json. Preserves
    other mcpServers and top-level keys."""
    if config_path.exists():
        try:
            existing = json.loads(config_path.read_text() or "{}")
        except json.JSONDecodeError as e:
            print(term.err(f"  {config_path} is not valid JSON: {e}"))
            return False
    else:
        existing = {}
        config_path.parent.mkdir(parents=True, exist_ok=True)

    servers = existing.setdefault("mcpServers", {})
    servers["bssync"] = {
        "command": command,
        "args": args,
        "env": env,
    }
    config_path.write_text(json.dumps(existing, indent=2) + "\n")
    print(term.ok(f"  Wrote {config_path}"))
    print(term.dim("    (restart Claude Desktop to pick up the change)"))
    return True


def _print_instructions(command: str, args: list[str],
                        env: dict[str, str]):
    """Fallback: just echo what the user would need to run/paste."""
    print()
    print(term.bold("Claude Code:"))
    cmd = f"  claude mcp add bssync {command}"
    if args:
        cmd += " " + " ".join(args)
    for k, v in env.items():
        cmd += f" \\\n    -e {k}={v}"
    print(cmd)

    print()
    print(term.bold("Claude Desktop (paste into claude_desktop_config.json):"))
    snippet = {
        "mcpServers": {
            "bssync": {
                "command": command,
                "args": args,
                "env": env,
            }
        }
    }
    print(json.dumps(snippet, indent=2))


# ─── Entry point ───


def cmd_mcp_install(args) -> int:
    """Top-level handler. Returns exit code."""
    print(term.bold(f"bssync mcp install (v{__version__})"))
    print("  Connects bssync to Claude Code and/or Claude Desktop.")

    non_interactive = args.non_interactive or not sys.stdin.isatty()

    url = args.url or os.environ.get("BOOKSTACK_URL")
    token_id = args.token_id or os.environ.get("BOOKSTACK_TOKEN_ID")
    token_secret = args.token_secret or os.environ.get("BOOKSTACK_TOKEN_SECRET")

    if non_interactive:
        if not (url and token_id and token_secret):
            print(term.err(
                "Non-interactive mode requires --url, --token-id, and "
                "--token-secret (or the matching BOOKSTACK_* env vars)."))
            return 1
    else:
        url, token_id, token_secret = _prompt_creds(
            url, token_id, token_secret)

    if not _verify(url, token_id, token_secret):
        print(term.err("  Refusing to install with credentials that don't "
                       "work. Check URL and token, then retry."))
        return 1

    command, cmd_args, warning = _resolve_server_command()
    if warning:
        print(term.warn(f"  Note: {warning}"))

    env = {
        "BOOKSTACK_URL": url,
        "BOOKSTACK_TOKEN_ID": token_id,
        "BOOKSTACK_TOKEN_SECRET": token_secret,
    }
    if args.config_file:
        env["BSSYNC_CONFIG"] = str(Path(args.config_file).resolve())

    # Target selection
    target = args.target
    code_available = _claude_code_path() is not None
    desktop_path = _desktop_config_path()
    desktop_available = desktop_path is not None

    if target == "auto":
        if code_available and desktop_available and not non_interactive:
            print()
            print("  Detected both Claude Code and Claude Desktop.")
            print("  Install to: [c]ode, [d]esktop, [b]oth, [p]rint "
                  "config, [q]uit?")
            choice = input("  → ").strip().lower() or "c"
            target = {"c": "code", "d": "desktop", "b": "both",
                      "p": "print", "q": "quit"}.get(choice, "code")
        elif code_available:
            target = "code"
        elif desktop_available:
            target = "desktop"
        else:
            print(term.warn(
                "  Neither Claude Code (`claude` on PATH) nor Claude "
                "Desktop detected — printing config snippets instead."))
            target = "print"

    if target == "quit":
        print("  Aborted.")
        return 0

    print()
    ok = True
    if target in ("code", "both"):
        if not code_available:
            print(term.err("  Claude Code requested but `claude` not on PATH."))
            ok = False
        else:
            ok = _install_claude_code(command, cmd_args, env) and ok

    if target in ("desktop", "both"):
        if not desktop_path:
            print(term.err("  Claude Desktop config path not available on "
                           "this OS."))
            ok = False
        else:
            ok = _install_claude_desktop(
                desktop_path, command, cmd_args, env) and ok

    if target == "print":
        _print_instructions(command, cmd_args, env)

    if ok and target in ("code", "desktop", "both"):
        print()
        print(term.ok("Done.") + " Open a Claude session and try: "
              "\"list the books on my BookStack\"")
    return 0 if ok else 1
