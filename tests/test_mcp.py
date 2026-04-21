"""Tests for the MCP server helpers and tool-level invariants.

Exercises the pieces that are easy to reason about unit-test: the
config-error short-circuit, identifier validation, page resolution by
name, and the tracking guardrail on live writes. Full tool invocations
aren't tested here — they'd need to drive the FastMCP request pipeline —
but the core logic each tool relies on is covered.
"""

from pathlib import Path
from unittest.mock import MagicMock

# helpers.py has no mcp SDK imports — it's safe to test without the
# [mcp] extra installed.
from bssync.mcp.helpers import (
    ServerContext,
    config_error_response,
    filter_entries,
    require_one_identifier,
    resolve_page,
    tracking_match,
)


def _sc_with_publish(entries: list) -> ServerContext:
    return ServerContext(
        config={"bookstack": {"url": "https://x", "token_id": "i",
                              "token_secret": "s"},
                "publish": entries},
        config_dir=Path("."),
        config_error=None,
    )


# ─── config_error_response ───


def test_config_error_response_shape():
    resp = config_error_response("bad things happened")
    assert resp["status"] == "error"
    assert resp["reason"] == "config_invalid"
    assert "bad things happened" in resp["detail"]
    assert "BSSYNC_CONFIG" in resp["fix"]


# ─── filter_entries ───


def test_filter_entries_no_only_returns_all():
    sc = _sc_with_publish([{"file": "a.md"}, {"file": "b.md"}])
    assert len(filter_entries(sc, None)) == 2


def test_filter_entries_matches_file_substring():
    sc = _sc_with_publish([{"file": "docs/onboarding.md"},
                           {"file": "docs/arch.md"}])
    result = filter_entries(sc, "onboard")
    assert len(result) == 1
    assert result[0]["file"] == "docs/onboarding.md"


def test_filter_entries_matches_title_substring():
    sc = _sc_with_publish([{"file": "a.md", "title": "Getting Started"},
                           {"file": "b.md", "title": "Architecture"}])
    result = filter_entries(sc, "gettin")
    assert len(result) == 1
    assert result[0]["file"] == "a.md"


def test_filter_entries_empty_config_safe():
    sc = ServerContext(config={}, config_dir=Path("."), config_error=None)
    assert filter_entries(sc, None) == []


# ─── tracking_match ───


def test_tracking_match_matches_book_and_title():
    sc = _sc_with_publish([
        {"file": "a.md", "book": "Docs", "title": "Intro"},
        {"file": "b.md", "book": "Docs", "title": "Arch"},
    ])
    m = tracking_match(sc, "Docs", "Arch")
    assert m is not None
    assert m["file"] == "b.md"


def test_tracking_match_case_insensitive():
    sc = _sc_with_publish([{"file": "a.md", "book": "Docs", "title": "Intro"}])
    assert tracking_match(sc, "docs", "INTRO") is not None


def test_tracking_match_no_match():
    sc = _sc_with_publish([{"file": "a.md", "book": "Docs", "title": "Intro"}])
    assert tracking_match(sc, "Other", "Intro") is None
    assert tracking_match(sc, "Docs", "Missing") is None


def test_tracking_match_empty_config_safe():
    sc = ServerContext(config={}, config_dir=Path("."), config_error=None)
    assert tracking_match(sc, "Docs", "Intro") is None


# ─── require_one_identifier ───


def test_require_one_identifier_accepts_page_id():
    assert require_one_identifier(page_id=42, book=None, title=None) is None


def test_require_one_identifier_accepts_book_and_title():
    assert require_one_identifier(page_id=None, book="Docs",
                                  title="Intro") is None


def test_require_one_identifier_rejects_neither():
    err = require_one_identifier(page_id=None, book=None, title=None)
    assert err is not None
    assert err["reason"] == "missing_identifier"


def test_require_one_identifier_rejects_both():
    err = require_one_identifier(page_id=42, book="Docs", title="Intro")
    assert err is not None
    assert err["reason"] == "ambiguous_identifier"


def test_require_one_identifier_rejects_partial_name():
    # Only book without title shouldn't validate
    err = require_one_identifier(page_id=None, book="Docs", title=None)
    assert err is not None
    assert err["reason"] == "missing_identifier"


# ─── resolve_page ───


def test_resolve_page_passthrough_id():
    client = MagicMock()
    assert resolve_page(client, page_id=42, book=None, title=None) == {
        "page_id": 42}
    client.find_book.assert_not_called()


def test_resolve_page_by_book_and_title():
    client = MagicMock()
    client.find_book.return_value = {"id": 7, "name": "Docs"}
    client.find_page_in_book.return_value = {"id": 99, "name": "Intro"}
    assert resolve_page(client, page_id=None, book="Docs",
                        title="Intro") == {"page_id": 99}


def test_resolve_page_book_not_found():
    client = MagicMock()
    client.find_book.return_value = None
    err = resolve_page(client, page_id=None, book="Missing", title="X")
    assert err["reason"] == "book_not_found"


def test_resolve_page_page_not_found():
    client = MagicMock()
    client.find_book.return_value = {"id": 7, "name": "Docs"}
    client.find_page_in_book.return_value = None
    err = resolve_page(client, page_id=None, book="Docs", title="Missing")
    assert err["reason"] == "page_not_found"
