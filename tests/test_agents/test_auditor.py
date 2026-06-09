import pytest
from unittest.mock import patch
from src.agents.state import make_state
from src.agents.auditor import auditor_quick_node


def test_auditor_quick_no_broken_links(tmp_path):
    from src.config import AppConfig
    from src.vault.tools import VaultTools
    (tmp_path / "Projects").mkdir()
    (tmp_path / "Projects" / "Agent Platform.md").write_text("# Agent Platform")
    content = "# Note\n\nSee [[Agent Platform]] for details."
    cfg = AppConfig(
        llm_provider="copilot", llm_model="gpt-4o", llm_api_key="x",
        vault_path=str(tmp_path), secret="s", _env_file=None,
    )
    tools = VaultTools(str(tmp_path))
    state = make_state("Projects/Test.md", content, {})
    result = auditor_quick_node(state, tools=tools, cfg=cfg)
    assert result["changes"] == []


def test_auditor_quick_detects_broken_link_supervised(tmp_path):
    from src.config import AppConfig
    from src.vault.tools import VaultTools
    (tmp_path / "Librarian").mkdir()
    content = "# Note\n\nSee [[MissingNote]] for context."
    cfg = AppConfig(
        llm_provider="copilot", llm_model="gpt-4o", llm_api_key="x",
        vault_path=str(tmp_path), secret="s", _env_file=None,
        autonomy_default="supervised", autonomy_overrides={},
    )
    tools = VaultTools(str(tmp_path))
    state = make_state("note.md", content, {})
    with patch("src.agents.auditor.LibrarianInbox") as mock_cls:
        result = auditor_quick_node(state, tools=tools, cfg=cfg)
    assert any("MissingNote" in c for c in result["changes"])
    mock_cls.return_value.propose.assert_called_once()


def test_auditor_quick_creates_stub_full_mode(tmp_path):
    from src.config import AppConfig
    from src.vault.tools import VaultTools
    (tmp_path / "Reference").mkdir()
    content = "# Note\n\nSee [[NewConcept]] for more."
    cfg = AppConfig(
        llm_provider="copilot", llm_model="gpt-4o", llm_api_key="x",
        vault_path=str(tmp_path), secret="s", _env_file=None,
        autonomy_overrides={"auditor": "full"},
    )
    tools = VaultTools(str(tmp_path))
    state = make_state("note.md", content, {})
    result = auditor_quick_node(state, tools=tools, cfg=cfg)
    assert (tmp_path / "Reference" / "NewConcept.md").exists()
    assert any("stub" in c.lower() for c in result["changes"])


def test_auditor_quick_no_false_positive_for_existing_note(tmp_path):
    from src.config import AppConfig
    from src.vault.tools import VaultTools
    (tmp_path / "ExistingNote.md").write_text("# Existing")
    content = "# Note\n\nSee [[ExistingNote]] here."
    cfg = AppConfig(
        llm_provider="copilot", llm_model="gpt-4o", llm_api_key="x",
        vault_path=str(tmp_path), secret="s", _env_file=None,
    )
    state = make_state("note.md", content, {})
    result = auditor_quick_node(state, tools=VaultTools(str(tmp_path)), cfg=cfg)
    assert result["changes"] == []
