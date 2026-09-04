"""Integration test: dispatcher batched pipeline end-to-end against a fixture vault, with the
watcher/debounce layer bypassed (call `Dispatcher._process` directly on a "settled" file)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from vault_librarian.config import ConfigManager
from vault_librarian.dispatcher import Dispatcher
from vault_librarian.git_safety import GitSafetyNet
from vault_librarian.jobs.store import JobStore
from vault_librarian.llm.factory import LLMFactory

FIXTURE_VAULT = Path(__file__).parent.parent / "fixtures" / "vault"


@pytest.fixture
async def vault(tmp_path: Path) -> Path:
    dest = tmp_path / "vault"
    shutil.copytree(FIXTURE_VAULT, dest)
    return dest


async def _make_dispatcher(vault: Path, dry_run: bool = False) -> tuple[Dispatcher, JobStore, GitSafetyNet]:
    config_manager = ConfigManager(vault)
    git_safety = GitSafetyNet(vault, ignore_paths=config_manager.config.ignore_paths)
    job_store = JobStore(vault / "jobs.db")
    await job_store.init()
    llm_factory = LLMFactory(config_manager.config.models)
    dispatcher = Dispatcher(vault, config_manager, git_safety, job_store, llm_factory, dry_run=dry_run)
    return dispatcher, job_store, git_safety


async def test_dirty_note_is_formatted_and_committed(vault: Path):
    note = vault / "Sample Note.md"
    dirty = note.read_text().replace("# Sample Note", "# Sample Note   ") + "\n\n\n\nextra\n"
    note.write_text(dirty, encoding="utf-8")

    dispatcher, job_store, git_safety = await _make_dispatcher(vault)
    await dispatcher._process(note)

    cleaned = note.read_text()
    assert "# Sample Note   " not in cleaned
    assert "\n\n\n\n" not in cleaned

    history = await git_safety.log_history(note)
    assert len(history) == 1
    assert history[0]["author"] == "Vault Librarian"

    activity_log = vault / "Librarian" / "Activity Log.md"
    assert activity_log.exists()
    assert "Sample Note.md" in activity_log.read_text()

    await job_store.close()


async def test_frontmatter_disabled_note_is_left_alone(vault: Path):
    note = vault / "Sample Note.md"
    text = note.read_text().replace("enabled: true", "enabled: false")
    text = text.replace("# Sample Note", "# Sample Note   ")  # would otherwise be reformatted
    note.write_text(text, encoding="utf-8")
    original = note.read_text()

    dispatcher, job_store, _ = await _make_dispatcher(vault)
    await dispatcher._process(note)

    assert note.read_text() == original
    await job_store.close()


async def test_frontmatter_skip_list_is_respected(vault: Path):
    note = vault / "Sample Note.md"
    text = note.read_text().replace(
        "vault-librarian:\n  enabled: true",
        "vault-librarian:\n  enabled: true\n  skip: [format]",
    )
    text = text.replace("# Sample Note", "# Sample Note   ")
    note.write_text(text, encoding="utf-8")

    dispatcher, job_store, _ = await _make_dispatcher(vault)
    await dispatcher._process(note)

    # format is skipped, so the trailing whitespace we injected should survive...
    assert "# Sample Note   " in note.read_text()
    await job_store.close()


async def test_conflict_markers_prevent_processing(vault: Path):
    note = vault / "Sample Note.md"
    text = note.read_text() + "\n<<<<<<< HEAD\nmine\n=======\ntheirs\n>>>>>>> branch\n"
    note.write_text(text, encoding="utf-8")
    original = note.read_text()

    dispatcher, job_store, _ = await _make_dispatcher(vault)
    await dispatcher._process(note)

    assert note.read_text() == original
    await job_store.close()


async def test_dry_run_does_not_write_or_commit(vault: Path):
    note = vault / "Sample Note.md"
    text = note.read_text().replace("# Sample Note", "# Sample Note   ")
    note.write_text(text, encoding="utf-8")
    original = note.read_text()

    dispatcher, job_store, git_safety = await _make_dispatcher(vault, dry_run=True)
    await dispatcher._process(note)

    assert note.read_text() == original
    history = await git_safety.log_history(note)
    assert len(history) == 0
    await job_store.close()


async def test_revert_detection_does_not_refight_the_user(vault: Path):
    note = vault / "Sample Note.md"
    text = note.read_text().replace("# Sample Note", "# Sample Note   ")
    note.write_text(text, encoding="utf-8")

    dispatcher, job_store, _ = await _make_dispatcher(vault)
    await dispatcher._process(note)
    formatted = note.read_text()
    assert "# Sample Note   " not in formatted

    # User reverts the formatting fix back to the pre-transform (dirty) state.
    note.write_text(text, encoding="utf-8")
    await dispatcher._process(note)

    # The revert should be honored: format is not silently reapplied this run.
    assert "# Sample Note   " in note.read_text()
    await job_store.close()
