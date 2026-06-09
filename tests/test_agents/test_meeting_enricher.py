from unittest.mock import MagicMock, patch

import pytest

from src.agents.meeting_enricher import MeetingAnalysis, meeting_enricher_node
from src.agents.state import make_state


@pytest.fixture
def mock_llm():
    llm = MagicMock()
    llm.with_structured_output.return_value.invoke.return_value = MeetingAnalysis(
        action_items=["Set up local topology", "Write runbook"],
        linked_project="Agent Platform",
        missing_fields={"date": "2026-06-08"},
    )
    return llm


def test_enricher_skips_non_meeting(mock_llm, tmp_path):
    from src.config import AppConfig
    from src.vault.tools import VaultTools

    cfg = AppConfig(
        llm_provider="copilot",
        llm_model="gpt-4o",
        llm_api_key="x",
        vault_path=str(tmp_path),
        secret="s",
        _env_file=None,
    )
    state = make_state("Projects/Alpha.md", "# Alpha", {}, note_type="project")
    result = meeting_enricher_node(state, llm=mock_llm, tools=VaultTools(str(tmp_path)), cfg=cfg)
    assert result["changes"] == []
    mock_llm.with_structured_output.assert_not_called()


def test_enricher_extracts_action_items(mock_llm, tmp_path):
    from src.config import AppConfig
    from src.vault.tools import VaultTools

    (tmp_path / "Meetings").mkdir()
    (tmp_path / "Meetings" / "Standup.md").write_text("# Standup\n\nDiscussed agent platform.\n")
    (tmp_path / "Projects").mkdir()
    (tmp_path / "Projects" / "Agent Platform.md").write_text("# Agent Platform\n\n## Work\n")
    cfg = AppConfig(
        llm_provider="copilot",
        llm_model="gpt-4o",
        llm_api_key="x",
        vault_path=str(tmp_path),
        secret="s",
        _env_file=None,
        autonomy_overrides={"meeting_enricher": "full"},
    )
    state = make_state(
        "Meetings/Standup.md", "# Standup\n\nDiscussed agent platform.", {}, note_type="meeting"
    )
    result = meeting_enricher_node(state, llm=mock_llm, tools=VaultTools(str(tmp_path)), cfg=cfg)
    assert "Set up local topology" in result["action_items"]
    content = (tmp_path / "Projects" / "Agent Platform.md").read_text()
    assert "Set up local topology" in content


def test_enricher_supervised_proposes(mock_llm, tmp_path):
    from src.config import AppConfig
    from src.vault.tools import VaultTools

    (tmp_path / "Librarian").mkdir()
    (tmp_path / "Projects").mkdir()
    (tmp_path / "Projects" / "Agent Platform.md").write_text("# Agent Platform\n")
    cfg = AppConfig(
        llm_provider="copilot",
        llm_model="gpt-4o",
        llm_api_key="x",
        vault_path=str(tmp_path),
        secret="s",
        _env_file=None,
        autonomy_default="supervised",
        autonomy_overrides={},
    )
    state = make_state("Meetings/Standup.md", "# Standup", {}, note_type="meeting")
    with patch("src.agents.meeting_enricher.LibrarianInbox") as mock_cls:
        result = meeting_enricher_node(
            state, llm=mock_llm, tools=VaultTools(str(tmp_path)), cfg=cfg
        )
    assert any("proposed" in c.lower() for c in result["changes"])
    mock_cls.return_value.propose.assert_called_once()
