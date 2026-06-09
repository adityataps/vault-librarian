import pytest

import src.config as _cfg_module
from src.autonomy.inbox import LibrarianInbox
from src.config import AppConfig
from src.vault.tools import VaultTools


@pytest.fixture(autouse=True)
def reset_singleton():
    _cfg_module._instance = None
    yield
    _cfg_module._instance = None


@pytest.fixture
def setup(tmp_path):
    (tmp_path / ".librarian").mkdir()
    cfg = AppConfig(
        llm_provider="copilot",
        llm_model="gpt-4o",
        llm_api_key="x",
        vault_path=str(tmp_path),
        secret="s",
        _env_file=None,
    )
    tools = VaultTools(str(tmp_path))
    return cfg, tools, tmp_path


def test_propose_creates_inbox(setup):
    cfg, tools, tmp_path = setup
    inbox = LibrarianInbox(cfg, tools)
    inbox.propose("Move `orphan.md` → `Personal/`")
    content = (tmp_path / ".librarian" / "Inbox.md").read_text()
    assert "Move `orphan.md`" in content
    assert "- [ ]" in content


def test_propose_appends_to_existing(setup):
    cfg, tools, tmp_path = setup
    inbox_path = tmp_path / ".librarian" / "Inbox.md"
    inbox_path.write_text("# Librarian Inbox\n\n- [ ] Existing item\n")
    inbox = LibrarianInbox(cfg, tools)
    inbox.propose("New item")
    content = inbox_path.read_text()
    assert "Existing item" in content
    assert "New item" in content


def test_execute_checked_move(setup):
    cfg, tools, tmp_path = setup
    (tmp_path / "orphan.md").write_text("# Orphan")
    (tmp_path / "Personal").mkdir()
    inbox_path = tmp_path / ".librarian" / "Inbox.md"
    inbox_path.write_text(
        "# Librarian Inbox\n\n- [x] Move `orphan.md` → `Personal/orphan.md`\n- [ ] Another item\n"
    )
    inbox = LibrarianInbox(cfg, tools)
    executed = inbox.execute_checked()
    assert len(executed) == 1
    content = inbox_path.read_text()
    assert "✅ Executed" in content
    assert "- [ ] Another item" in content
    assert (tmp_path / "Personal" / "orphan.md").exists()


def test_execute_checked_non_executable_item(setup):
    cfg, tools, tmp_path = setup
    inbox_path = tmp_path / ".librarian" / "Inbox.md"
    inbox_path.write_text("# Librarian Inbox\n\n- [x] Review this note manually\n")
    inbox = LibrarianInbox(cfg, tools)
    executed = inbox.execute_checked()
    assert executed == []
    content = inbox_path.read_text()
    # Non-auto-executable item is preserved unchanged (still checked, not marked executed)
    assert "- [x] Review this note manually" in content
    assert "✅ Executed" not in content


def test_inbox_empty_initially(setup):
    cfg, tools, tmp_path = setup
    inbox = LibrarianInbox(cfg, tools)
    executed = inbox.execute_checked()
    assert executed == []
