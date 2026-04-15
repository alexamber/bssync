"""Config loading and path resolution."""

import os
import sys
from pathlib import Path

import yaml


def load_config(path: str) -> dict:
    """Load and validate a bssync YAML config file.

    Exits the process with a clear message on validation failure. API
    tokens can come from the config file directly or from environment
    variables (BOOKSTACK_TOKEN_ID, BOOKSTACK_TOKEN_SECRET).
    """
    p = Path(path)
    if not p.exists():
        print(f"Error: config file not found: {path}")
        sys.exit(1)

    with open(p) as f:
        config = yaml.safe_load(f)

    bs = config.get("bookstack", {})
    if not bs.get("url"):
        print("Error: bookstack.url is required in config")
        sys.exit(1)

    token_id = bs.get("token_id") or os.environ.get("BOOKSTACK_TOKEN_ID")
    token_secret = (bs.get("token_secret")
                    or os.environ.get("BOOKSTACK_TOKEN_SECRET"))

    if not token_id or not token_secret:
        print("Error: API token required. Set in config file or via environment:")
        print("  BOOKSTACK_TOKEN_ID=xxx BOOKSTACK_TOKEN_SECRET=yyy")
        sys.exit(1)

    config["bookstack"]["token_id"] = token_id
    config["bookstack"]["token_secret"] = token_secret

    if not config.get("publish"):
        # Allow empty publish list — user might only run `ls` or `pull --new`
        config["publish"] = []

    return config


def resolve_file_path(file_path: str, config_dir: Path) -> Path:
    """Resolve a config-relative path to an absolute Path."""
    p = Path(file_path)
    if p.is_absolute():
        return p
    return (config_dir / p).resolve()
