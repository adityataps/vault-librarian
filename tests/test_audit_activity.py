import pytest
from pathlib import Path
from src.audit.activity import ActivityLog
from src.config import AppConfig
from src.vault.tools import VaultTools
import src.config as _cfg_module


@pytest.fixture(autouse=True)
def reset_singleton():
    _cfg_module._instance = None
    yield
    _cfg_module._instance = None


@pytest.fixture
def setup(tmp_path):
    (tmp_path / "Librarian").mkdir()
    cfg = AppConfig(
        llm_provider="copilot", llm_model="gpt-4o", llm_api_key="x",
        vault_path=str(tmp_path), secret="s", _env_file=None,
    )
    tools = VaultTools(str(tmp_path))
    return cfg, tools, tmp_path


def test_activity_log_creates_file(setup):
    cfg, tools, tmp_path = setup
    log = ActivityLog(cfg, tools)
    log.append("Librarian", ["Moved `note.md` → `Projects/`"], "executed")
    content = (tmp_path / "Librarian" / "Activity.md").read_text()
    assert "> [!success] Librarian" in content
    assert "Moved `note.md`" in content


def test_activity_log_appends_to_existing(setup):
    cfg, tools, tmp_path = setup
    activity_path = tmp_path / "Librarian" / "Activity.md"
    activity_path.write_text("# Librarian Activity\n\n## 2026-01-01\n\n> [!info] Formatter\n> old entry\n")
    log = ActivityLog(cfg, tools)
    log.append("Auditor", ["Proposed: create stub"], "proposed")
    content = activity_path.read_text()
    assert "old entry" in content
    assert "> [!warning] Auditor" in content


def test_activity_log_no_op_on_empty_changes(setup):
    cfg, tools, tmp_path = setup
    log = ActivityLog(cfg, tools)
    log.append("Formatter", [], "info")
    assert not (tmp_path / "Librarian" / "Activity.md").exists()


def test_activity_log_callout_mapping(setup):
    cfg, tools, tmp_path = setup
    log = ActivityLog(cfg, tools)
    cases = [
        ("executed", "success"),
        ("proposed", "warning"),
        ("error", "failure"),
        ("enriched", "tip"),
        ("info", "info"),
    ]
    for outcome, expected in cases:
        (tmp_path / "Librarian" / "Activity.md").unlink(missing_ok=True)
        log.append("Agent", ["some change"], outcome)
        content = (tmp_path / "Librarian" / "Activity.md").read_text()
        assert f"[!{expected}]" in content, f"Expected [!{expected}] for outcome={outcome}"
