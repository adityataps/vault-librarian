from __future__ import annotations

from pathlib import Path

import pytest

from vault_librarian.git_safety import GitSafetyNet


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    return tmp_path


async def test_init_creates_repo_and_gitignore(vault: Path):
    GitSafetyNet(vault, ignore_paths=["Attachments/"])
    assert (vault / ".git").exists()
    gitignore = (vault / ".gitignore").read_text()
    assert "Attachments/" in gitignore
    assert ".obsidian/" in gitignore


async def test_commit_paths_creates_commit(vault: Path):
    safety = GitSafetyNet(vault)
    note = vault / "Note.md"
    note.write_text("hello\n", encoding="utf-8")
    sha = await safety.commit_paths([note], "vault-librarian: format — Note.md")
    assert sha is not None
    history = await safety.log_history(note)
    assert len(history) == 1
    assert history[0]["author"] == "Vault Librarian"


async def test_commit_paths_returns_none_when_nothing_changed(vault: Path):
    safety = GitSafetyNet(vault)
    note = vault / "Note.md"
    note.write_text("hello\n", encoding="utf-8")
    await safety.commit_paths([note], "first commit")
    sha = await safety.commit_paths([note], "no-op commit")
    assert sha is None


async def test_rollback_reverts_to_prior_commit(vault: Path):
    safety = GitSafetyNet(vault)
    note = vault / "Note.md"
    note.write_text("version one\n", encoding="utf-8")
    await safety.commit_paths([note], "v1")
    note.write_text("version two\n", encoding="utf-8")
    await safety.commit_paths([note], "v2")

    await safety.rollback(note)
    assert note.read_text() == "version one\n"


async def test_recover_dirty_tree_commits_uncommitted_changes(vault: Path):
    safety = GitSafetyNet(vault)
    note = vault / "Note.md"
    note.write_text("uncommitted\n", encoding="utf-8")
    sha = await safety.recover_dirty_tree()
    assert sha is not None
    assert not safety.repo.is_dirty(untracked_files=True)


async def test_recover_dirty_tree_noop_when_clean(vault: Path):
    safety = GitSafetyNet(vault)
    # The seeded .gitignore is committed as part of repo init itself, so a fresh repo is
    # already clean at this point.
    sha = await safety.recover_dirty_tree()
    assert sha is None
