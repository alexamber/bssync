"""Markdown content processing: reading, title extraction, normalization,
hashing, and image/attachment link discovery.

These are all pure functions that don't touch the network or filesystem
state beyond reading the input file. Easy to test in isolation.
"""

import hashlib
import re
from pathlib import Path

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp"}


# ─── Reading & title extraction ───


def read_markdown(path: Path) -> str:
    """Read a markdown file, stripping any YAML frontmatter block."""
    with open(path) as f:
        content = f.read()

    if content.startswith("---"):
        end = content.find("---", 3)
        if end != -1:
            content = content[end + 3:].lstrip("\n")

    return content


def extract_title(content: str, fallback: str) -> str:
    """Return the first H1 heading in content, or fallback if none found."""
    match = re.match(r"^#\s+(.+)$", content, re.MULTILINE)
    if match:
        return match.group(1).strip()
    return fallback


def strip_title(content: str) -> str:
    """Remove the first H1 heading from content.

    BookStack displays the page name as the title, so we strip it from
    the body on push to avoid duplication.
    """
    return re.sub(r"^#\s+.+\n+", "", content, count=1)


def restore_h1(content: str, title: str) -> str:
    """Prepend `# {title}` to content, first stripping any pre-existing H1
    to avoid duplication (BookStack WYSIWYG may produce one on round-trip)."""
    stripped = strip_title(content)
    return f"# {title}\n\n{stripped.lstrip()}"


# ─── Normalization & hashing ───


def normalize_markdown(text: str) -> str:
    """Normalize markdown for stable hashing across push/pull round-trips.

    BookStack may reformat markdown slightly (line endings, trailing
    whitespace). Normalizing both sides before hashing avoids false-positive
    conflicts. The hashing function is only used for change/conflict
    detection, so the normalization doesn't need to be reversible.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.split("\n")]
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines) + "\n"


def normalized_hash(text: str) -> str:
    """Short SHA-256 hash of normalized markdown. Used as content_hash tag."""
    return hashlib.sha256(normalize_markdown(text).encode()).hexdigest()[:16]


def file_hash(path: Path) -> str:
    """Short SHA-256 hash of a file's raw bytes. Used to detect when a local
    image or attachment has been edited since its last upload.
    """
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


# ─── Inline image references ───


def find_local_images(content: str, file_dir: Path) -> list[tuple[str, Path]]:
    """Find markdown image references that point to local files.

    Returns list of (markdown_ref, resolved_path) tuples. Remote URLs and
    data URIs are skipped. Paths that don't exist print a warning.
    """
    images = []
    for match in re.finditer(r"!\[([^\]]*)\]\(([^)]+)\)", content):
        img_ref = match.group(2)
        if img_ref.startswith(("http://", "https://", "data:")):
            continue
        img_path = (file_dir / img_ref).resolve()
        if img_path.exists() and img_path.suffix.lower() in IMAGE_EXTENSIONS:
            images.append((img_ref, img_path))
        else:
            print(f"  WARNING: Local image not found or unsupported: {img_ref}")
    return images


def replace_image_refs(content: str, replacements: dict[str, str]) -> str:
    """Replace local image paths with BookStack URLs in markdown content."""
    for local_ref, remote_url in replacements.items():
        content = content.replace(f"]({local_ref})", f"]({remote_url})")
    return content


# ─── Inline file links ───


def find_local_file_links(content: str,
                          file_dir: Path) -> list[tuple[str, Path]]:
    """Find markdown links pointing to local files (not images, not URLs).

    Matches `[text](local/path.ext)` but not `![img](path)` or
    `[text](http...)`. Returns (markdown_ref, resolved_path) tuples.
    """
    links = []
    for match in re.finditer(r"(?<!!)\[([^\]]*)\]\(([^)]+)\)", content):
        link_ref = match.group(2)
        if link_ref.startswith(("http://", "https://", "data:", "#", "mailto:")):
            continue
        link_path = (file_dir / link_ref).resolve()
        if link_path.exists() and link_path.is_file():
            links.append((link_ref, link_path))
    return links


def replace_file_link_refs(content: str, replacements: dict[str, str]) -> str:
    """Replace local file link paths with BookStack attachment URLs."""
    for local_ref, remote_url in replacements.items():
        content = content.replace(f"]({local_ref})", f"]({remote_url})")
    return content
