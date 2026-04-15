"""Tests for bssync.content — pure functions, no network or disk state."""

from pathlib import Path

import pytest

from bssync.content import (
    extract_title,
    find_local_file_links,
    find_local_images,
    normalize_markdown,
    normalized_hash,
    read_markdown,
    replace_file_link_refs,
    replace_image_refs,
    restore_h1,
    strip_title,
)


# ─── Title handling ───


def test_extract_title_uses_first_h1():
    content = "# My Page\n\nBody."
    assert extract_title(content, "fallback") == "My Page"


def test_extract_title_falls_back_when_no_h1():
    content = "No heading here."
    assert extract_title(content, "fallback") == "fallback"


def test_extract_title_ignores_h2_and_below():
    content = "## Subheading\nBody."
    assert extract_title(content, "fallback") == "fallback"


def test_strip_title_removes_first_h1():
    content = "# Title\n\nBody."
    assert strip_title(content) == "Body."


def test_strip_title_only_removes_first_h1():
    content = "# First\n\n# Second\n\nBody."
    stripped = strip_title(content)
    assert stripped.startswith("# Second")


def test_restore_h1_adds_heading():
    content = "Body without title."
    restored = restore_h1(content, "My Title")
    assert restored.startswith("# My Title\n\n")
    assert "Body without title." in restored


def test_restore_h1_replaces_existing_h1():
    content = "# Old Title\n\nBody."
    restored = restore_h1(content, "New Title")
    assert "# New Title" in restored
    assert "# Old Title" not in restored


# ─── Normalization ───


def test_normalize_strips_trailing_whitespace():
    assert normalize_markdown("line  \n") == "line\n"


def test_normalize_handles_crlf():
    assert normalize_markdown("a\r\nb\r\n") == "a\nb\n"


def test_normalize_removes_trailing_empty_lines():
    assert normalize_markdown("body\n\n\n") == "body\n"


def test_normalize_is_idempotent():
    text = "foo\nbar \r\n\n"
    once = normalize_markdown(text)
    twice = normalize_markdown(once)
    assert once == twice


def test_normalized_hash_is_stable_across_whitespace():
    a = "hello\nworld\n"
    b = "hello   \nworld\n\n\n"
    assert normalized_hash(a) == normalized_hash(b)


def test_normalized_hash_differs_on_content_change():
    a = "hello"
    b = "goodbye"
    assert normalized_hash(a) != normalized_hash(b)


# ─── Frontmatter ───


def test_read_markdown_strips_frontmatter(tmp_path: Path):
    p = tmp_path / "doc.md"
    p.write_text("---\ntitle: Foo\n---\n\n# Foo\n\nBody.")
    assert read_markdown(p) == "# Foo\n\nBody."


def test_read_markdown_preserves_content_without_frontmatter(tmp_path: Path):
    p = tmp_path / "doc.md"
    p.write_text("# Foo\n\nBody.")
    assert read_markdown(p) == "# Foo\n\nBody."


# ─── Image reference discovery ───


def test_find_local_images(tmp_path: Path):
    img = tmp_path / "pic.png"
    img.write_bytes(b"\x89PNG\r\n")  # minimal valid-looking png header
    content = f"![alt](pic.png)\n![remote](https://example.com/x.png)"
    result = find_local_images(content, tmp_path)
    assert len(result) == 1
    assert result[0][0] == "pic.png"
    assert result[0][1].name == "pic.png"


def test_find_local_images_skips_data_uris(tmp_path: Path):
    content = "![inline](data:image/png;base64,AAAA)"
    assert find_local_images(content, tmp_path) == []


def test_replace_image_refs():
    content = "See ![x](local.png) here."
    result = replace_image_refs(content, {"local.png": "https://cdn/x.png"})
    assert "https://cdn/x.png" in result
    assert "local.png" not in result


# ─── File link discovery ───


def test_find_local_file_links(tmp_path: Path):
    f = tmp_path / "schema.sql"
    f.write_text("CREATE TABLE x;")
    content = "See [schema](schema.sql) and [docs](https://example.com)."
    result = find_local_file_links(content, tmp_path)
    assert len(result) == 1
    assert result[0][0] == "schema.sql"


def test_find_local_file_links_skips_images(tmp_path: Path):
    # The regex uses negative lookbehind to skip `![img](...)`
    img = tmp_path / "pic.png"
    img.write_bytes(b"\x89PNG")
    content = "![pic](pic.png)"
    assert find_local_file_links(content, tmp_path) == []


def test_find_local_file_links_skips_anchors(tmp_path: Path):
    content = "[section](#intro)"
    assert find_local_file_links(content, tmp_path) == []


def test_replace_file_link_refs():
    content = "[sql](db.sql) [text](db.sql)"
    result = replace_file_link_refs(
        content, {"db.sql": "https://x/attachments/5"})
    assert result.count("https://x/attachments/5") == 2
    assert "db.sql" not in result
