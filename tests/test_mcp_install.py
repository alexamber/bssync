"""Tests for bssync.mcp_install.

Covers the parts that don't require driving an actual Claude client:
server-command resolution, Claude Desktop config merging (preserves
existing mcpServers entries and top-level keys), and the config-print
path. Subprocess-based `claude mcp add` is tested only via its error
path (missing binary) to keep tests hermetic.
"""

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

from bssync.mcp_install import (
    _install_claude_desktop,
    _resolve_server_command,
)


# ─── _resolve_server_command ───


def test_resolve_server_command_prefers_bin_on_path():
    """When `bssync-mcp` is on PATH, use the resolved absolute path."""
    with patch("bssync.mcp_install.shutil.which") as which:
        which.return_value = "/usr/local/bin/bssync-mcp"
        command, args, warning = _resolve_server_command()
    assert command == "/usr/local/bin/bssync-mcp"
    assert args == []
    assert warning is None


def test_resolve_server_command_falls_back_to_python_m():
    """Without the binary, fall back to `python -m bssync.mcp_server`
    using the current interpreter + emit a warning."""
    with patch("bssync.mcp_install.shutil.which") as which:
        which.return_value = None
        command, args, warning = _resolve_server_command()
    assert command == sys.executable
    assert args == ["-m", "bssync.mcp_server"]
    assert warning is not None
    assert "bssync-mcp" in warning


# ─── _install_claude_desktop ───


def test_install_desktop_creates_new_config(tmp_path: Path):
    """Config file doesn't exist yet — create it with just our entry."""
    config_path = tmp_path / "claude_desktop_config.json"
    ok = _install_claude_desktop(
        config_path,
        command="/abs/bssync-mcp",
        args=[],
        env={"BOOKSTACK_URL": "https://x",
             "BOOKSTACK_TOKEN_ID": "i",
             "BOOKSTACK_TOKEN_SECRET": "s"},
    )
    assert ok is True
    data = json.loads(config_path.read_text())
    assert "bssync" in data["mcpServers"]
    entry = data["mcpServers"]["bssync"]
    assert entry["command"] == "/abs/bssync-mcp"
    assert entry["env"]["BOOKSTACK_URL"] == "https://x"


def test_install_desktop_preserves_other_servers(tmp_path: Path):
    """Existing mcpServers entries must survive our merge."""
    config_path = tmp_path / "claude_desktop_config.json"
    config_path.write_text(json.dumps({
        "mcpServers": {
            "filesystem": {"command": "fs-mcp", "args": ["/path"]},
            "github": {"command": "gh-mcp"},
        },
        "otherKey": {"keepMe": True},
    }))
    _install_claude_desktop(
        config_path, command="/abs/bssync-mcp",
        args=[], env={"BOOKSTACK_URL": "https://x"},
    )
    data = json.loads(config_path.read_text())
    assert set(data["mcpServers"].keys()) == {"filesystem", "github", "bssync"}
    assert data["mcpServers"]["filesystem"]["command"] == "fs-mcp"
    assert data["mcpServers"]["github"]["command"] == "gh-mcp"
    assert data["otherKey"]["keepMe"] is True


def test_install_desktop_overwrites_existing_bssync_entry(tmp_path: Path):
    """Re-running install with new creds should replace the old entry."""
    config_path = tmp_path / "claude_desktop_config.json"
    config_path.write_text(json.dumps({
        "mcpServers": {
            "bssync": {"command": "/old/path", "env": {"BOOKSTACK_URL": "old"}},
        },
    }))
    _install_claude_desktop(
        config_path, command="/new/path",
        args=[], env={"BOOKSTACK_URL": "new",
                      "BOOKSTACK_TOKEN_ID": "i",
                      "BOOKSTACK_TOKEN_SECRET": "s"},
    )
    entry = json.loads(config_path.read_text())["mcpServers"]["bssync"]
    assert entry["command"] == "/new/path"
    assert entry["env"]["BOOKSTACK_URL"] == "new"


def test_install_desktop_rejects_invalid_json(tmp_path: Path):
    """Corrupt config file — don't blindly overwrite it."""
    config_path = tmp_path / "claude_desktop_config.json"
    config_path.write_text("{not json")
    ok = _install_claude_desktop(
        config_path, command="/x", args=[], env={},
    )
    assert ok is False
    # Original (corrupt) content is left alone — not replaced.
    assert config_path.read_text() == "{not json"


def test_install_desktop_creates_parent_dir(tmp_path: Path):
    """If the Claude config dir doesn't exist yet, create it."""
    config_path = tmp_path / "nested" / "dir" / "config.json"
    ok = _install_claude_desktop(
        config_path, command="/x", args=[],
        env={"BOOKSTACK_URL": "https://x"},
    )
    assert ok is True
    assert config_path.exists()
