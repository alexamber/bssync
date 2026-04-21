"""Tests for bssync.discovery — matching logic for tracked pages."""

from pathlib import Path

from bssync.discovery import (
    is_tracked,
    resolve_entries,
    resolve_entry_title,
    suggest_config_entry,
)


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


def test_is_tracked_ignores_title_less_entries():
    """The old chapter-fallback was removed: a title-less entry no longer
    matches random pages sharing a book/chapter. Callers should pass
    resolve_entries() output to populate titles from local files."""
    page = {"book": "Engineering", "chapter": "Design", "name": "Anything"}
    entries = [{"book": "Engineering", "chapter": "Design"}]
    assert is_tracked(page, entries) is False


def test_resolve_entry_title_prefers_explicit_title(tmp_path: Path):
    (tmp_path / "a.md").write_text("# From H1\n\nBody.")
    entry = {"file": "a.md", "title": "Explicit"}
    assert resolve_entry_title(entry, tmp_path) == "Explicit"


def test_resolve_entry_title_falls_back_to_h1(tmp_path: Path):
    (tmp_path / "a.md").write_text("# From H1\n\nBody.")
    entry = {"file": "a.md"}
    assert resolve_entry_title(entry, tmp_path) == "From H1"


def test_resolve_entry_title_falls_back_to_stem_when_file_missing(tmp_path: Path):
    entry = {"file": "ghost.md"}
    assert resolve_entry_title(entry, tmp_path) == "ghost"


def test_resolve_entry_title_falls_back_to_stem_when_no_h1(tmp_path: Path):
    (tmp_path / "readme.md").write_text("No heading in here.\n")
    entry = {"file": "readme.md"}
    assert resolve_entry_title(entry, tmp_path) == "readme"


def test_resolve_entries_populates_title(tmp_path: Path):
    (tmp_path / "a.md").write_text("# Alpha\n")
    entries = [{"file": "a.md", "book": "Docs"},
               {"file": "b.md", "book": "Docs", "title": "Beta"}]
    resolved = resolve_entries(entries, tmp_path)
    assert resolved[0]["title"] == "Alpha"
    assert resolved[1]["title"] == "Beta"
    # Originals untouched — resolve_entries returns shallow copies.
    assert "title" not in entries[0]


def test_is_tracked_after_resolve_matches_h1_title(tmp_path: Path):
    (tmp_path / "a.md").write_text("# Architecture\n\nBody.")
    page = {"book": "Engineering", "chapter": None, "name": "Architecture"}
    entries = resolve_entries(
        [{"file": "a.md", "book": "Engineering"}], tmp_path)
    assert is_tracked(page, entries) is True


def test_is_tracked_after_resolve_does_not_match_wrong_title(tmp_path: Path):
    """Primary regression: a title-less entry in the same book used to
    match every page via chapter fallback. Now it only matches its own
    resolved title."""
    (tmp_path / "intro.md").write_text("# Intro\n")
    page = {"book": "Engineering", "chapter": None,
            "name": "Architecture"}
    entries = resolve_entries(
        [{"file": "intro.md", "book": "Engineering"}], tmp_path)
    assert is_tracked(page, entries) is False


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
