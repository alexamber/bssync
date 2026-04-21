"""Config loading and path resolution."""

import os
import sys
from pathlib import Path

import yaml

from bssync import term


def load_config(path: str) -> dict:
    """Load and validate a bssync YAML config file.

    Exits the process with a clear message on validation failure. URL and
    API tokens can come from the config file or from environment variables
    (BOOKSTACK_URL, BOOKSTACK_TOKEN_ID, BOOKSTACK_TOKEN_SECRET). If all
    three env vars are set, the config file becomes optional — useful for
    MCP server usage where users may want to configure purely via the
    Claude Desktop / Claude Code env block, no yaml file involved.
    """
    env_url = os.environ.get("BOOKSTACK_URL")
    env_token_id = os.environ.get("BOOKSTACK_TOKEN_ID")
    env_token_secret = os.environ.get("BOOKSTACK_TOKEN_SECRET")

    p = Path(path)
    if p.exists():
        with open(p) as f:
            config = yaml.safe_load(f) or {}
    elif env_url and env_token_id and env_token_secret:
        # Config-less mode: every required value comes from the environment.
        # No publish list means push/pull are no-ops but live/read tools work.
        config = {"bookstack": {}, "publish": []}
    else:
        print(term.err(f"Error: config file not found: {path}"))
        print(f"  Run {term.bold('`bssync init`')} to create one, point to "
              f"an existing config with {term.bold('--config PATH')} or "
              f"{term.bold('BSSYNC_CONFIG')},")
        print(f"  or set {term.bold('BOOKSTACK_URL')} + "
              f"{term.bold('BOOKSTACK_TOKEN_ID')} + "
              f"{term.bold('BOOKSTACK_TOKEN_SECRET')} env vars.")
        sys.exit(1)

    bs = config.get("bookstack") or {}
    url = bs.get("url") or env_url
    token_id = bs.get("token_id") or env_token_id
    token_secret = bs.get("token_secret") or env_token_secret

    if not url:
        print(term.err("Error: bookstack.url is required in config "
                       "(or set BOOKSTACK_URL env var)"))
        sys.exit(1)

    if not token_id or not token_secret:
        print(term.err("Error: API token required. Set in config file or "
                       "via environment:"))
        print("  BOOKSTACK_TOKEN_ID=xxx BOOKSTACK_TOKEN_SECRET=yyy")
        sys.exit(1)

    config["bookstack"] = {
        **bs,
        "url": url,
        "token_id": token_id,
        "token_secret": token_secret,
    }

    if not config.get("publish"):
        # Allow empty publish list — user might only run `ls`, `pull --new`,
        # or use the MCP server's live tools.
        config["publish"] = []

    return config


def resolve_file_path(file_path: str, config_dir: Path) -> Path:
    """Resolve a config-relative path to an absolute Path."""
    p = Path(file_path)
    if p.is_absolute():
        return p
    return (config_dir / p).resolve()
