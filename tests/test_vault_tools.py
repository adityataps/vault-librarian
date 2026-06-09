import pytest

from src.vault.parser import parse_note


@pytest.fixture
def vault(tmp_path):
    (tmp_path / "Projects").mkdir()
    return tmp_path


def test_parse_note_with_frontmatter(vault):
    note = vault / "Projects" / "Test.md"
    note.write_text("---\ntags:\n  - work\ntype: project\n---\n# Test\n\nSome content here.")
    meta = parse_note(str(note), str(vault))
    assert meta.title == "Test"
    assert meta.note_type == "project"
    assert "work" in meta.tags
    assert meta.folder == "Projects"
    assert len(meta.content_hash) == 64


def test_parse_note_no_frontmatter(vault):
    note = vault / "bare.md"
    note.write_text("# Bare Note\n\nJust content.")
    meta = parse_note(str(note), str(vault))
    assert meta.title == "Bare Note"
    assert meta.note_type is None
    assert meta.tags == []


def test_parse_note_word_count(vault):
    note = vault / "words.md"
    note.write_text("---\n---\none two three four five")
    meta = parse_note(str(note), str(vault))
    assert meta.word_count == 5


def test_parse_note_root_folder(vault):
    note = vault / "rootnote.md"
    note.write_text("# Root\n\nContent.")
    meta = parse_note(str(note), str(vault))
    assert meta.folder == ""


def test_parse_note_string_tags(vault):
    note = vault / "Projects" / "Single.md"
    note.write_text("---\ntags: work\n---\n# Single tag")
    meta = parse_note(str(note), str(vault))
    assert meta.tags == ["work"]


# ---------------------------------------------------------------------------
# Task 6: VaultTools
# ---------------------------------------------------------------------------

import hashlib

import pytest

from src.vault.tools import ConflictError, VaultTools


def test_write_note_atomic(vault):
    tools = VaultTools(str(vault))
    tools.write_note("Projects/New.md", "# New\n\nContent.")
    assert (vault / "Projects" / "New.md").read_text() == "# New\n\nContent."


def test_write_note_conflict_detection(vault):
    note = vault / "Projects" / "Test.md"
    note.write_text("original content")
    tools = VaultTools(str(vault))
    with pytest.raises(ConflictError):
        tools.write_note("Projects/Test.md", "agent write", dispatch_hash="stale_hash")


def test_write_note_no_conflict_when_hash_matches(vault):
    note = vault / "Projects" / "Test.md"
    note.write_text("original")
    correct_hash = hashlib.sha256("original".encode()).hexdigest()
    tools = VaultTools(str(vault))
    tools.write_note("Projects/Test.md", "updated", dispatch_hash=correct_hash)
    assert (vault / "Projects" / "Test.md").read_text() == "updated"


def test_move_note(vault):
    src = vault / "orphan.md"
    src.write_text("# Orphan")
    (vault / "Personal").mkdir()
    tools = VaultTools(str(vault))
    tools.move_note("orphan.md", "Personal/orphan.md")
    assert (vault / "Personal" / "orphan.md").exists()
    assert not src.exists()


def test_update_frontmatter(vault):
    note = vault / "Projects" / "Test.md"
    note.write_text("---\ntags:\n  - work\n---\n# Test\n\nBody.")
    tools = VaultTools(str(vault))
    tools.update_frontmatter("Projects/Test.md", {"type": "project", "created": "2026-06-08"})
    from src.vault.parser import parse_note

    meta = parse_note(str(vault / "Projects" / "Test.md"), str(vault))
    assert meta.frontmatter["type"] == "project"
    assert meta.frontmatter["created"] == "2026-06-08"
    assert meta.frontmatter["tags"] == ["work"]


def test_has_directive_tags(vault):
    note = vault / "Projects" / "Test.md"
    note.write_text("# Test\n\n<agent-scaffold>fill this in</agent-scaffold>")
    tools = VaultTools(str(vault))
    assert tools.has_directive_tags("Projects/Test.md")
    note.write_text("# Test\n\nno directives here")
    assert not tools.has_directive_tags("Projects/Test.md")


# ---------------------------------------------------------------------------
# Task 7: VaultScanner
# ---------------------------------------------------------------------------

from unittest.mock import MagicMock

from src.vault.scanner import VaultScanner


def _make_cfg(vault_path: str) -> MagicMock:
    cfg = MagicMock()
    cfg.vault_path = vault_path
    cfg.vault_excluded_folders = [".obsidian", ".git", ".librarian", "Librarian", "Attachments"]
    cfg.vault_excluded_files = ["CLAUDE.md"]
    return cfg


def test_scanner_scan_returns_all_notes(vault):
    (vault / "note1.md").write_text("# Note 1\n\nContent.")
    (vault / "Projects" / "note2.md").write_text("# Note 2\n\nContent.")
    scanner = VaultScanner(_make_cfg(str(vault)))
    result = scanner.scan()
    paths = [n.path for n in result.notes]
    assert result.total == 2
    assert result.errors == 0
    assert any("note1.md" in p for p in paths)
    assert any("note2.md" in p for p in paths)


def test_scanner_excludes_folders(vault):
    (vault / ".obsidian").mkdir()
    (vault / ".obsidian" / "hidden.md").write_text("# Hidden")
    (vault / "visible.md").write_text("# Visible")
    scanner = VaultScanner(_make_cfg(str(vault)))
    result = scanner.scan()
    paths = [n.path for n in result.notes]
    assert all(".obsidian" not in p for p in paths)
    assert result.total == 1


def test_scanner_iter_notes(vault):
    (vault / "a.md").write_text("# A\n\nContent.")
    (vault / "b.md").write_text("# B\n\nContent.")
    scanner = VaultScanner(_make_cfg(str(vault)))
    notes = list(scanner.iter_notes())
    assert len(notes) == 2
    titles = {n.title for n in notes}
    assert titles == {"A", "B"}
