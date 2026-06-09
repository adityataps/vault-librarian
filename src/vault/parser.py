from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import frontmatter


@dataclass
class NoteMetadata:
    path: str  # relative to vault root
    abs_path: str
    title: str
    folder: str
    note_type: str | None
    tags: list[str]
    content_hash: str
    word_count: int
    frontmatter: dict
    raw_content: str


def parse_note(abs_path: str, vault_root: str) -> NoteMetadata:
    text = Path(abs_path).read_text(encoding="utf-8")
    post = frontmatter.loads(text)
    fm = dict(post.metadata)
    body = post.content

    rel = str(Path(abs_path).relative_to(vault_root))
    parent = Path(rel).parent
    folder = "" if str(parent) == "." else str(parent)

    title_match = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else Path(abs_path).stem

    tags = fm.get("tags", [])
    if isinstance(tags, str):
        tags = [tags]

    note_type = fm.get("type") or fm.get("note_type") or None
    content_hash = hashlib.sha256(text.encode()).hexdigest()
    word_count = len(body.split())

    return NoteMetadata(
        path=rel,
        abs_path=abs_path,
        title=title,
        folder=folder,
        note_type=note_type,
        tags=tags,
        content_hash=content_hash,
        word_count=word_count,
        frontmatter=fm,
        raw_content=text,
    )
