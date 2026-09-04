from __future__ import annotations

from pathlib import Path

from vault_librarian.workflows import backlink as backlink_wf


def _make_vault(tmp_path: Path) -> Path:
    (tmp_path / "Project Alpha.md").write_text("# Project Alpha\n", encoding="utf-8")
    (tmp_path / "Attachments").mkdir()
    (tmp_path / "Attachments" / "Project Alpha.md").write_text("decoy", encoding="utf-8")
    return tmp_path


def test_links_first_mention_of_another_note_title(tmp_path: Path):
    vault = _make_vault(tmp_path)
    note = vault / "Note.md"
    note.write_text("Discussed with the team about Project Alpha today.\n", encoding="utf-8")
    text = note.read_text()
    new_text, changed = backlink_wf.run(text, vault, note, ignore_paths=["Attachments/"])
    assert changed
    assert "[[Project Alpha]]" in new_text


def test_does_not_relink_a_title_already_linked_elsewhere(tmp_path: Path):
    vault = _make_vault(tmp_path)
    note = vault / "Note.md"
    # Once a title is linked anywhere in the file, later plain mentions are left alone —
    # avoids redundant repeated links to the same target (design: "first mention" wins).
    text = "Already linked to [[Project Alpha]] here, and mentioned Project Alpha again.\n"
    new_text, changed = backlink_wf.run(text, vault, note, ignore_paths=["Attachments/"])
    assert not changed
    assert new_text == text


def test_skips_headings(tmp_path: Path):
    vault = _make_vault(tmp_path)
    note = vault / "Note.md"
    text = "# Project Alpha\n\nBody text with no other mention.\n"
    new_text, changed = backlink_wf.run(text, vault, note, ignore_paths=["Attachments/"])
    assert not changed
    assert new_text == text


def test_ignores_titles_in_ignored_paths(tmp_path: Path):
    vault = _make_vault(tmp_path)
    note = vault / "Note.md"
    text = "No mention of the decoy title here.\n"
    new_text, changed = backlink_wf.run(text, vault, note, ignore_paths=["Attachments/"])
    assert not changed
    assert new_text == text


def test_no_candidate_titles_is_noop(tmp_path: Path):
    note = tmp_path / "Solo.md"
    text = "Just a note with nothing to link.\n"
    new_text, changed = backlink_wf.run(text, tmp_path, note, ignore_paths=[])
    assert not changed
    assert new_text == text
