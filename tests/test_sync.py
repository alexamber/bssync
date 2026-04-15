"""Tests for bssync.sync — high-level push/pull flows with a mocked client."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from bssync.sync import pull_entry


@pytest.fixture
def mock_client():
    """Construct a BookStackClient-shaped MagicMock with sane defaults."""
    client = MagicMock()
    client.url = "https://example.com"
    client.dry_run = False
    client.find_book.return_value = {"id": 1, "name": "Docs"}
    return client


def test_pull_entry_creates_file_when_missing(mock_client, tmp_path: Path):
    mock_client.find_page_in_book.return_value = {"id": 10, "name": "Intro"}
    mock_client.get_page.return_value = {
        "id": 10,
        "name": "Intro",
        "markdown": "This is the body.",
        "tags": [],
    }

    local_file = tmp_path / "intro.md"
    entry = {"file": "intro.md", "book": "Docs", "title": "Intro"}

    changed = pull_entry(mock_client, entry, tmp_path)

    assert changed is True
    assert local_file.exists()
    content = local_file.read_text()
    assert content.startswith("# Intro")
    assert "This is the body." in content


def test_pull_entry_skips_when_book_not_found(mock_client, tmp_path: Path):
    mock_client.find_book.return_value = None
    entry = {"file": "x.md", "book": "Missing", "title": "X"}

    assert pull_entry(mock_client, entry, tmp_path) is False


def test_pull_entry_skips_when_page_not_found(mock_client, tmp_path: Path):
    mock_client.find_page_in_book.return_value = None
    entry = {"file": "x.md", "book": "Docs", "title": "X"}

    assert pull_entry(mock_client, entry, tmp_path) is False


def test_pull_entry_skips_when_remote_markdown_empty(mock_client, tmp_path: Path):
    mock_client.find_page_in_book.return_value = {"id": 10, "name": "X"}
    mock_client.get_page.return_value = {
        "id": 10, "name": "X", "markdown": "", "tags": []
    }
    entry = {"file": "x.md", "book": "Docs", "title": "X"}

    assert pull_entry(mock_client, entry, tmp_path) is False


def test_pull_entry_unchanged_when_local_matches_remote(mock_client, tmp_path: Path):
    mock_client.find_page_in_book.return_value = {"id": 10, "name": "Intro"}
    mock_client.get_page.return_value = {
        "id": 10,
        "name": "Intro",
        "markdown": "Body.",
        "tags": [],
    }

    local_file = tmp_path / "intro.md"
    # Local has H1 + body matching what we'd generate on pull
    local_file.write_text("# Intro\n\nBody.")

    entry = {"file": "intro.md", "book": "Docs", "title": "Intro"}

    changed = pull_entry(mock_client, entry, tmp_path)
    assert changed is False
