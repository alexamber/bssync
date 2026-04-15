"""Tests for bssync.discovery — matching logic for tracked pages."""

from bssync.discovery import is_tracked, suggest_config_entry


def test_is_tracked_matches_book_and_title():
    page = {"book": "Engineering", "chapter": "Design",
            "name": "Architecture"}
    entries = [{"book": "Engineering", "chapter": "Design",
                "title": "Architecture"}]
    assert is_tracked(page, entries) is True


def test_is_tracked_is_case_insensitive():
    page = {"book": "Engineering", "chapter": None,
            "name": "Architecture"}
    entries = [{"book": "engineering", "title": "architecture"}]
    assert is_tracked(page, entries) is True


def test_is_tracked_tolerates_chapter_drift():
    # Page was moved to a different chapter on BookStack but still matches
    # by book + title.
    page = {"book": "Engineering", "chapter": "Archived",
            "name": "Architecture"}
    entries = [{"book": "Engineering", "chapter": "Design",
                "title": "Architecture"}]
    assert is_tracked(page, entries) is True


def test_is_tracked_requires_book_match():
    page = {"book": "Engineering", "chapter": None, "name": "Setup"}
    entries = [{"book": "Marketing", "title": "Setup"}]
    assert is_tracked(page, entries) is False


def test_is_tracked_without_title_falls_back_to_chapter():
    page = {"book": "Engineering", "chapter": "Design", "name": "Anything"}
    entries = [{"book": "Engineering", "chapter": "Design"}]
    assert is_tracked(page, entries) is True


def test_is_tracked_returns_false_when_no_match():
    page = {"book": "Engineering", "chapter": None, "name": "Unknown"}
    entries = [{"book": "Engineering", "title": "Something Else"}]
    assert is_tracked(page, entries) is False


def test_suggest_config_entry_uses_slugs():
    page = {"id": 42, "book": "Engineering", "chapter": "Getting Started",
            "name": "Installation Guide"}
    snippet = suggest_config_entry(page, existing_files=set())
    assert "book: Engineering" in snippet
    assert "chapter: Getting Started" in snippet
    assert "title: Installation Guide" in snippet
    assert "getting-started/installation-guide.md" in snippet


def test_suggest_config_entry_dedupes_filename_on_collision():
    page = {"id": 42, "book": "X", "chapter": None, "name": "README"}
    existing = {"../docs/readme.md"}
    snippet = suggest_config_entry(page, existing)
    assert "readme-42.md" in snippet
