"""Tests for bssync.sync — high-level push/pull flows with a mocked client."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from bssync.sync import publish_entry, pull_entry


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


def test_publish_entry_moves_page_when_chapter_changed(mock_client,
                                                        tmp_path: Path):
    """Issue #1: yaml declares a chapter but BookStack page is at book root —
    push should move the page into the declared chapter, not just update content.
    """
    local_file = tmp_path / "example.md"
    local_file.write_text("# Example Page\n\nBody content.")

    # Simulate chapter exists on BookStack
    mock_client.find_chapter.return_value = {"id": 42, "name": "MyChapter"}

    # Existing page is at book root (chapter_id=0)
    mock_client.find_page_in_book.return_value = {
        "id": 99, "name": "Example Page",
    }
    mock_client.get_page.return_value = {
        "id": 99,
        "name": "Example Page",
        "markdown": "Body content.",
        "tags": [],
        "chapter_id": 0,
        "book_id": 1,
    }
    # update_page returns the same markdown so hash reconciliation no-ops
    mock_client.update_page.return_value = {
        "id": 99, "name": "Example Page", "markdown": "Body content.",
    }

    entry = {
        "file": "example.md",
        "book": "Docs",
        "chapter": "MyChapter",
        "title": "Example Page",
    }

    changed = publish_entry(mock_client, entry, tmp_path)

    assert changed is True
    # Must have called update_page with chapter_id=42 (the move)
    call_kwargs = mock_client.update_page.call_args_list[0].kwargs
    assert call_kwargs.get("chapter_id") == 42


def test_publish_entry_no_move_when_chapter_matches(mock_client,
                                                     tmp_path: Path):
    """If the page is already in the declared chapter and content is identical,
    nothing is sent — no spurious move."""
    local_file = tmp_path / "example.md"
    # Content that stays identical after strip_title + round-trip
    local_file.write_text("# Example\n\nBody.")

    mock_client.find_chapter.return_value = {"id": 42, "name": "Ch"}
    mock_client.find_page_in_book.return_value = {"id": 99, "name": "Example"}

    # Page already in chapter 42; content hash matches both local and stored
    from bssync.content import normalized_hash, strip_title
    remote_md = strip_title("# Example\n\nBody.")
    h = normalized_hash(remote_md)
    mock_client.get_page.return_value = {
        "id": 99,
        "name": "Example",
        "markdown": remote_md,
        "tags": [{"name": "content_hash", "value": h}],
        "chapter_id": 42,
        "book_id": 1,
    }

    entry = {
        "file": "example.md", "book": "Docs",
        "chapter": "Ch", "title": "Example",
    }

    changed = publish_entry(mock_client, entry, tmp_path)
    assert changed is False
    mock_client.update_page.assert_not_called()
