"""Config loading and path resolution."""

import os
from pathlib import Path

import yaml


class ConfigError(Exception):
    """Raised by load_config when the config is missing or malformed.

    Carries a human-readable `fix` alongside the message so callers (CLI,
    MCP server, mcp_install wizard) can format the guidance appropriately
    for their UI instead of each one reconstructing it.
    """
    def __init__(self, message: str, fix: str = ""):
        super().__init__(message)
        self.message = message
        self.fix = fix


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
        raise ConfigError(
            f"config file not found: {path}",
            fix="Run `bssync init` to create one, point to an existing "
                "config via --config PATH or BSSYNC_CONFIG, or set "
                "BOOKSTACK_URL + BOOKSTACK_TOKEN_ID + BOOKSTACK_TOKEN_SECRET "
                "env vars.",
        )

    bs = config.get("bookstack") or {}
    # Env vars override yaml. Documented contract; matches CLI convention
    # (aws, kubectl, gh, docker, npm) and keeps CI/MCP safe — tokens in
    # env take precedence over anything stale in a checked-in yaml.
    url = env_url or bs.get("url")
    token_id = env_token_id or bs.get("token_id")
    token_secret = env_token_secret or bs.get("token_secret")

    if not url:
        raise ConfigError(
            "bookstack.url is required",
            fix="Set it in the config file, or set BOOKSTACK_URL env var.",
        )

    if not token_id or not token_secret:
        raise ConfigError(
            "BookStack API token required",
            fix="Set bookstack.token_id / token_secret in the config file, "
                "or set BOOKSTACK_TOKEN_ID / BOOKSTACK_TOKEN_SECRET env vars.",
        )

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
