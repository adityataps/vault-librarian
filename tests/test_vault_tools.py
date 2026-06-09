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
