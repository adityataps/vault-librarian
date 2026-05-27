"""Integration test for the new-note workflow using SQLite (no Postgres required)."""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def vault_dir(tmp_path: Path) -> Path:
    """Create a minimal temp vault with a few markdown notes."""
    (tmp_path / "Inbox").mkdir()
    (tmp_path / "Work").mkdir()

    (tmp_path / "Inbox" / "hello.md").write_text(
        "---\ntitle: Hello World\ntags: [test]\n---\n# Hello World\n\nThis is a test note.\n",
        encoding="utf-8",
    )
    (tmp_path / "Work" / "project.md").write_text(
        "---\ntitle: Project Alpha\ntype: project\ntags: [work, alpha]\n---\n# Project Alpha\n\nSee also [[hello]].\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.mark.asyncio
async def test_vault_scanner_finds_notes(vault_dir: Path) -> None:
    """VaultScanner should find all markdown files and parse them."""
    from src.watcher.scanner import VaultScanner

    scanner = VaultScanner(vault_root=vault_dir, excluded_folders=[], excluded_files=[])
    result = scanner.scan()

    assert result.error_count == 0, f"Parse errors: {result.errors}"
    assert result.success_count == 2

    paths = {n.path for n in result.parsed}
    assert "Inbox/hello.md" in paths
    assert "Work/project.md" in paths


@pytest.mark.asyncio
async def test_sqlite_storage_roundtrip(vault_dir: Path) -> None:
    """SQLiteStorage should store and retrieve a note without errors."""
    import os
    os.environ.setdefault("OBSIDIAN_VAULT_PATH", str(vault_dir))
    os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_vault.db")

    from src.config import Settings
    from src.storage.sqlite import SQLiteStorage
    from src.storage.models import NoteCreate
    import uuid
    import datetime

    storage = SQLiteStorage(db_path=":memory:")
    await storage.initialize()

    note = NoteCreate(
        path="Inbox/hello.md",
        title="Hello World",
        folder="Inbox",
        tags=["test"],
        content_hash="abc123",
        word_count=10,
        last_modified=datetime.datetime.utcnow(),
    )
    saved = await storage.save_note(note)
    assert saved.id is not None

    fetched = await storage.get_note_by_path("Inbox/hello.md")
    assert fetched is not None
    assert fetched.title == "Hello World"
    assert "test" in fetched.tags

    await storage.close()
    # in-memory database closes cleanly; nothing to remove


@pytest.mark.asyncio
async def test_note_parser_extracts_metadata(vault_dir: Path) -> None:
    """note_parser should extract frontmatter, wikilinks, and word count."""
    from src.tools.note_parser import parse_note

    parsed = parse_note(vault_dir / "Work" / "project.md", vault_root=vault_dir)

    assert parsed.title == "Project Alpha"
    assert "work" in parsed.tags
    assert "alpha" in parsed.tags
    assert parsed.note_type == "project"
    assert parsed.word_count > 0

    links = parsed.wikilinks  # list[str] of target titles
    assert "hello" in links


@pytest.mark.asyncio
async def test_scanner_iter_notes(vault_dir: Path) -> None:
    """iter_notes should yield ParsedNote objects one by one."""
    from src.watcher.scanner import VaultScanner

    scanner = VaultScanner(vault_root=vault_dir, excluded_folders=[], excluded_files=[])
    notes = list(scanner.iter_notes())

    assert len(notes) == 2
    for n in notes:
        assert n.content_hash  # hashes computed
        assert n.word_count >= 0
