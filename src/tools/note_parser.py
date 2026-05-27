"""Note parsing utilities — frontmatter, wikilinks, headings, word count, hash."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import frontmatter as fm


# ── Regex patterns ─────────────────────────────────────────────────────────────

_WIKILINK_RE = re.compile(r"\[\[([^\[\]|#]+)(?:[|#][^\[\]]*)?\]\]")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
_CODE_BLOCK_RE = re.compile(r"```(\w*)\n(.*?)```", re.DOTALL)
_TAG_RE = re.compile(r"(?<!\S)#([A-Za-z][A-Za-z0-9_/-]*)")
_WORD_RE = re.compile(r"\b\w+\b")


@dataclass
class ParsedNote:
    """Result of parsing a markdown note file."""

    path: str                            # Relative path from vault root
    title: str
    folder: str                          # Immediate parent folder name
    raw_content: str
    frontmatter: dict[str, Any] = field(default_factory=dict)
    body: str = ""                       # Content with frontmatter stripped
    wikilinks: list[str] = field(default_factory=list)   # Target paths/titles
    headings: list[tuple[int, str]] = field(default_factory=list)  # (level, text)
    inline_tags: list[str] = field(default_factory=list)  # #tags in body
    code_blocks: list[tuple[str, str]] = field(default_factory=list)  # (lang, code)
    word_count: int = 0
    content_hash: str = ""

    # Convenience properties sourced from frontmatter
    @property
    def note_type(self) -> str | None:
        return self.frontmatter.get("type") or self.frontmatter.get("note_type")

    @property
    def status(self) -> str | None:
        return self.frontmatter.get("status")

    @property
    def tags(self) -> list[str]:
        """Merge frontmatter tags + inline #tags, deduplicated."""
        fm_tags: list[str] = []
        raw = self.frontmatter.get("tags", [])
        if isinstance(raw, list):
            fm_tags = [str(t).lstrip("#") for t in raw]
        elif isinstance(raw, str):
            fm_tags = [t.strip().lstrip("#") for t in raw.split(",") if t.strip()]
        combined = fm_tags + self.inline_tags
        seen: set[str] = set()
        result: list[str] = []
        for t in combined:
            if t.lower() not in seen:
                seen.add(t.lower())
                result.append(t)
        return result


def parse_note(file_path: Path, vault_root: Path) -> ParsedNote:
    """Parse a markdown note and return a ParsedNote.

    Args:
        file_path: Absolute path to the .md file.
        vault_root: Absolute path to the vault root (for relative path calculation).
    """
    raw_content = file_path.read_text(encoding="utf-8")
    relative_path = str(file_path.relative_to(vault_root))
    folder = _get_folder(file_path, vault_root)

    # Parse frontmatter
    post = fm.loads(raw_content)
    metadata: dict[str, Any] = dict(post.metadata)
    body: str = post.content

    # Title: prefer frontmatter, fall back to first H1, then filename
    title = (
        metadata.get("title")
        or _extract_first_h1(body)
        or file_path.stem
    )

    parsed = ParsedNote(
        path=relative_path,
        title=str(title),
        folder=folder,
        raw_content=raw_content,
        frontmatter=metadata,
        body=body,
    )

    parsed.wikilinks = extract_wikilinks(body)
    parsed.headings = extract_headings(body)
    parsed.inline_tags = extract_inline_tags(body)
    parsed.code_blocks = extract_code_blocks(body)
    parsed.word_count = count_words(body)
    parsed.content_hash = compute_hash(raw_content)

    return parsed


def parse_note_content(
    content: str,
    relative_path: str,
    vault_root: Path | None = None,
) -> ParsedNote:
    """Parse note from raw content string (useful for testing or in-memory processing)."""
    path = Path(relative_path)
    folder = path.parent.name or "root"

    post = fm.loads(content)
    metadata: dict[str, Any] = dict(post.metadata)
    body: str = post.content

    title = (
        metadata.get("title")
        or _extract_first_h1(body)
        or path.stem
    )

    parsed = ParsedNote(
        path=relative_path,
        title=str(title),
        folder=folder,
        raw_content=content,
        frontmatter=metadata,
        body=body,
    )
    parsed.wikilinks = extract_wikilinks(body)
    parsed.headings = extract_headings(body)
    parsed.inline_tags = extract_inline_tags(body)
    parsed.code_blocks = extract_code_blocks(body)
    parsed.word_count = count_words(body)
    parsed.content_hash = compute_hash(content)
    return parsed


def extract_wikilinks(text: str) -> list[str]:
    """Extract all [[wikilink]] targets from text, ignoring aliases/anchors."""
    return [m.group(1).strip() for m in _WIKILINK_RE.finditer(text)]


def extract_headings(text: str) -> list[tuple[int, str]]:
    """Return list of (level, heading_text) from markdown headings."""
    return [(len(m.group(1)), m.group(2).strip()) for m in _HEADING_RE.finditer(text)]


def extract_inline_tags(text: str) -> list[str]:
    """Extract #hashtags from body text (not inside code blocks)."""
    # Strip code blocks first to avoid matching tags inside them
    cleaned = _CODE_BLOCK_RE.sub("", text)
    return [m.group(1) for m in _TAG_RE.finditer(cleaned)]


def extract_code_blocks(text: str) -> list[tuple[str, str]]:
    """Return list of (language, code) pairs from fenced code blocks."""
    return [(m.group(1), m.group(2)) for m in _CODE_BLOCK_RE.finditer(text)]


def count_words(text: str) -> int:
    """Count words in text, excluding frontmatter and code blocks."""
    cleaned = _CODE_BLOCK_RE.sub("", text)
    return len(_WORD_RE.findall(cleaned))


def compute_hash(content: str) -> str:
    """Compute SHA-256 hash of note content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def update_frontmatter(file_path: Path, updates: dict[str, Any]) -> str:
    """Update frontmatter fields in a note file, preserving all other content.

    Returns the updated content (does NOT write to disk — caller decides).
    """
    raw = file_path.read_text(encoding="utf-8")
    post = fm.loads(raw)
    for key, value in updates.items():
        post.metadata[key] = value
    return fm.dumps(post)


# ── Private helpers ────────────────────────────────────────────────────────────

def _extract_first_h1(body: str) -> str | None:
    """Return the text of the first # H1 heading, if present."""
    for level, text in extract_headings(body):
        if level == 1:
            return text
    return None


def _get_folder(file_path: Path, vault_root: Path) -> str:
    """Return the immediate parent folder name relative to vault root."""
    rel = file_path.relative_to(vault_root)
    # If file is directly in vault root, folder is "root"
    return rel.parent.name if rel.parent != Path(".") else "root"
