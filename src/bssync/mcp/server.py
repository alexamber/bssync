"""FastMCP server instance, lifespan, and entry point.

The `mcp` object is constructed here with a lifespan that loads
bookstack.yaml (or the BOOKSTACK_* env vars) and probes the BookStack
API. On failure we still hand a `ServerContext` with a filled-in
`config_error` back to FastMCP — so Claude Desktop sees a healthy server
rather than an opaque 'disconnected', and every tool returns a
structured {"status": "error", "reason": "config_invalid"} response the
LLM can surface to the user.

Importing this module triggers tool/resource/prompt registration on the
shared `mcp` instance via side-effect imports at the bottom of the file.
"""

import contextlib
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    sys.stderr.write(
        "bssync-mcp: the mcp SDK is not installed. "
        "Install with: pip install 'bssync[mcp]'\n"
    )
    sys.exit(1)

from bssync import __version__
from bssync.client import BookStackClient
from bssync.config import ConfigError, load_config
from bssync.mcp.helpers import ServerContext


def _load_at_startup(config_path: Path) -> ServerContext:
    """Load config + probe the API. Any failure becomes a config_error
    string; we never raise past this point because that would terminate
    the server before MCP's handshake."""
    try:
        config = load_config(str(config_path))
        config_dir = config_path.parent.resolve()
        bs = config["bookstack"]
        probe = BookStackClient(
            url=bs["url"], token_id=bs["token_id"],
            token_secret=bs["token_secret"],
            dry_run=False, verbose=False,
        )
        if not probe.verify_connection():
            return ServerContext(
                config=config, config_dir=config_dir,
                config_error=(f"failed to connect to {bs['url']} — check "
                              f"credentials and network"),
            )
        return ServerContext(
            config=config, config_dir=config_dir, config_error=None)
    except ConfigError as e:
        return ServerContext(
            config={}, config_dir=Path("."),
            config_error=f"{e.message}. {e.fix}" if e.fix else e.message,
        )
    except Exception as e:
        return ServerContext(
            config={}, config_dir=Path("."), config_error=str(e))


@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncIterator[ServerContext]:
    config_path = Path(os.environ.get("BSSYNC_CONFIG", "bookstack.yaml"))
    # load_config + verify_connection don't print anymore, but keeping
    # the redirect is cheap insurance: anything that does sneak through
    # (a third-party library log, say) goes to stderr where Claude
    # Desktop's log file captures it, not to stdout where MCP protocol
    # frames live.
    with contextlib.redirect_stdout(sys.stderr):
        sc = _load_at_startup(config_path)
        if sc.config_error:
            sys.stderr.write(
                f"bssync-mcp: config error: {sc.config_error}\n"
                f"bssync-mcp: server will start; tool calls will return a "
                f"config_invalid error until this is fixed.\n"
            )
        else:
            sys.stderr.write(
                f"bssync-mcp v{__version__}: connected to "
                f"{sc.config['bookstack']['url']}, "
                f"{len(sc.config.get('publish') or [])} tracked entries. "
                f"Serving on stdio.\n"
            )
    yield sc


mcp = FastMCP("bssync", lifespan=lifespan)


# Register tools/resources/prompts. These imports have import-time side
# effects: each module's @mcp.tool() / @mcp.resource() / @mcp.prompt()
# decorators attach the function to the `mcp` instance defined above.
# Kept at module level (not inside main()) so PyInstaller's static
# import analysis finds them without needing extra --hidden-import flags.
from bssync.mcp.tools import sync as _tools_sync  # noqa: F401, E402
from bssync.mcp.tools import live_read as _tools_live_read  # noqa: F401, E402
from bssync.mcp.tools import live_write as _tools_live_write  # noqa: F401, E402
from bssync.mcp import resources as _resources  # noqa: F401, E402
from bssync.mcp import prompts as _prompts  # noqa: F401, E402


def main():
    # --version short-circuits so install smoke tests work without creds.
    if "--version" in sys.argv or "-V" in sys.argv:
        print(f"bssync-mcp {__version__}")
        return
    mcp.run()


if __name__ == "__main__":
    main()
