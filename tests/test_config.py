"""Tests for bssync.config — ConfigError scenarios and env-var fallback."""

from pathlib import Path

import pytest

from bssync.config import ConfigError, load_config


@pytest.fixture(autouse=True)
def clear_env(monkeypatch):
    """Every test starts with a clean environment for BOOKSTACK_* vars."""
    for k in ("BOOKSTACK_URL", "BOOKSTACK_TOKEN_ID", "BOOKSTACK_TOKEN_SECRET"):
        monkeypatch.delenv(k, raising=False)


def _write_config(path: Path, content: str) -> str:
    path.write_text(content)
    return str(path)


def test_missing_file_and_no_env_raises(tmp_path: Path):
    with pytest.raises(ConfigError) as ei:
        load_config(str(tmp_path / "does-not-exist.yaml"))
    assert "config file not found" in ei.value.message
    assert "BOOKSTACK_URL" in ei.value.fix


def test_missing_file_but_env_vars_set_succeeds(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("BOOKSTACK_URL", "https://wiki.example.com")
    monkeypatch.setenv("BOOKSTACK_TOKEN_ID", "id")
    monkeypatch.setenv("BOOKSTACK_TOKEN_SECRET", "secret")
    cfg = load_config(str(tmp_path / "does-not-exist.yaml"))
    assert cfg["bookstack"]["url"] == "https://wiki.example.com"
    assert cfg["bookstack"]["token_id"] == "id"
    assert cfg["bookstack"]["token_secret"] == "secret"
    assert cfg["publish"] == []


def test_yaml_url_only_with_env_tokens(tmp_path: Path, monkeypatch):
    path = _write_config(
        tmp_path / "cfg.yaml",
        "bookstack:\n  url: https://docs.example.com\n",
    )
    monkeypatch.setenv("BOOKSTACK_TOKEN_ID", "id")
    monkeypatch.setenv("BOOKSTACK_TOKEN_SECRET", "secret")
    cfg = load_config(path)
    assert cfg["bookstack"]["url"] == "https://docs.example.com"
    assert cfg["bookstack"]["token_id"] == "id"


def test_missing_url_raises(tmp_path: Path):
    path = _write_config(
        tmp_path / "cfg.yaml",
        "bookstack:\n  token_id: x\n  token_secret: y\n",
    )
    with pytest.raises(ConfigError) as ei:
        load_config(path)
    assert "url" in ei.value.message.lower()


def test_missing_tokens_raises(tmp_path: Path):
    path = _write_config(
        tmp_path / "cfg.yaml",
        "bookstack:\n  url: https://docs.example.com\n",
    )
    with pytest.raises(ConfigError) as ei:
        load_config(path)
    assert "token" in ei.value.message.lower()


def test_env_vars_override_yaml_tokens(tmp_path: Path, monkeypatch):
    """Documented contract: env vars win over yaml. Useful for CI and
    MCP client env: blocks where secrets shouldn't be shadowed by
    checked-in config values."""
    path = _write_config(
        tmp_path / "cfg.yaml",
        "bookstack:\n"
        "  url: https://yaml.example.com\n"
        "  token_id: yaml_id\n"
        "  token_secret: yaml_secret\n",
    )
    monkeypatch.setenv("BOOKSTACK_URL", "https://env.example.com")
    monkeypatch.setenv("BOOKSTACK_TOKEN_ID", "env_id")
    monkeypatch.setenv("BOOKSTACK_TOKEN_SECRET", "env_secret")
    cfg = load_config(path)
    assert cfg["bookstack"]["url"] == "https://env.example.com"
    assert cfg["bookstack"]["token_id"] == "env_id"
    assert cfg["bookstack"]["token_secret"] == "env_secret"


def test_yaml_values_used_when_env_absent(tmp_path: Path):
    """With no env vars set, the yaml values are the source."""
    path = _write_config(
        tmp_path / "cfg.yaml",
        "bookstack:\n"
        "  url: https://yaml.example.com\n"
        "  token_id: yaml_id\n"
        "  token_secret: yaml_secret\n",
    )
    cfg = load_config(path)
    assert cfg["bookstack"]["url"] == "https://yaml.example.com"
    assert cfg["bookstack"]["token_id"] == "yaml_id"


def test_empty_publish_list_allowed(tmp_path: Path):
    path = _write_config(
        tmp_path / "cfg.yaml",
        "bookstack:\n"
        "  url: https://docs.example.com\n"
        "  token_id: x\n"
        "  token_secret: y\n",
    )
    cfg = load_config(path)
    assert cfg["publish"] == []


def test_publish_list_preserved(tmp_path: Path):
    path = _write_config(
        tmp_path / "cfg.yaml",
        "bookstack:\n"
        "  url: https://docs.example.com\n"
        "  token_id: x\n"
        "  token_secret: y\n"
        "publish:\n"
        "  - file: a.md\n"
        "    book: Docs\n",
    )
    cfg = load_config(path)
    assert len(cfg["publish"]) == 1
    assert cfg["publish"][0]["file"] == "a.md"
