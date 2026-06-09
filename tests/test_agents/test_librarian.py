from unittest.mock import MagicMock

import pytest

from src.agents.librarian import librarian_node
from src.agents.state import make_state


@pytest.fixture
def filing_decision():
    from pydantic import BaseModel

    class FilingDecision(BaseModel):
        note_type: str
        target_folder: str
        reasoning: str

    return FilingDecision(note_type="meeting", target_folder="Meetings", reasoning="test")


@pytest.fixture
def mock_llm(filing_decision):
    llm = MagicMock()
    llm.with_structured_output.return_value.invoke.return_value = filing_decision
    return llm


def test_librarian_full_autonomy_moves_note(mock_llm, tmp_path):
    from src.config import AppConfig
    from src.vault.tools import VaultTools

    (tmp_path / "Meetings").mkdir()
    (tmp_path / "standup.md").write_text("# Standup\n\nMeeting notes.")
    cfg = AppConfig(
        llm_provider="copilot",
        llm_model="gpt-4o",
        llm_api_key="x",
        vault_path=str(tmp_path),
        secret="s",
        _env_file=None,
        autonomy_overrides={"librarian": "full"},
    )
    tools = VaultTools(str(tmp_path))
    state = make_state("standup.md", "# Standup\n\nMeeting notes.", {})
    result = librarian_node(state, llm=mock_llm, tools=tools, cfg=cfg)
    assert result["note_type"] == "meeting"
    assert (tmp_path / "Meetings" / "standup.md").exists()
    assert any("Moved" in c or "meeting" in c.lower() for c in result["changes"])


def test_librarian_supervised_proposes(mock_llm, tmp_path):
    from unittest.mock import patch

    from src.config import AppConfig
    from src.vault.tools import VaultTools

    (tmp_path / "Librarian").mkdir()
    (tmp_path / "standup.md").write_text("# Standup\n\nNotes.")
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
    tools = VaultTools(str(tmp_path))
    state = make_state("standup.md", "# Standup\n\nNotes.", {})
    with patch("src.agents.librarian.LibrarianInbox") as mock_inbox_cls:
        mock_inbox = mock_inbox_cls.return_value
        result = librarian_node(state, llm=mock_llm, tools=tools, cfg=cfg)
    assert result["note_type"] == "meeting"
    assert (tmp_path / "standup.md").exists()
    assert any("Proposed" in c for c in result["changes"])
    mock_inbox.propose.assert_called_once()


def test_librarian_skips_move_if_already_in_correct_folder(mock_llm, tmp_path):
    from pydantic import BaseModel

    from src.config import AppConfig
    from src.vault.tools import VaultTools

    class FilingDecision(BaseModel):
        note_type: str
        target_folder: str
        reasoning: str

    # LLM says target_folder = "Meetings", note is already in Meetings/
    mock_llm.with_structured_output.return_value.invoke.return_value = FilingDecision(
        note_type="meeting", target_folder="Meetings", reasoning="already correct"
    )
    (tmp_path / "Meetings").mkdir()
    (tmp_path / "Meetings" / "standup.md").write_text("# Standup")
    cfg = AppConfig(
        llm_provider="copilot",
        llm_model="gpt-4o",
        llm_api_key="x",
        vault_path=str(tmp_path),
        secret="s",
        _env_file=None,
        autonomy_overrides={"librarian": "full"},
    )
    tools = VaultTools(str(tmp_path))
    state = make_state("Meetings/standup.md", "# Standup", {})
    result = librarian_node(state, llm=mock_llm, tools=tools, cfg=cfg)
    # Still classified, but no move
    assert result["note_type"] == "meeting"
    assert not any("Moved" in c for c in result["changes"])


def test_librarian_handles_llm_failure(tmp_path):
    from src.config import AppConfig
    from src.vault.tools import VaultTools

    llm = MagicMock()
    llm.with_structured_output.return_value.invoke.side_effect = Exception("API error")
    cfg = AppConfig(
        llm_provider="copilot",
        llm_model="gpt-4o",
        llm_api_key="x",
        vault_path=str(tmp_path),
        secret="s",
        _env_file=None,
    )
    tools = VaultTools(str(tmp_path))
    state = make_state("note.md", "content", {})
    result = librarian_node(state, llm=llm, tools=tools, cfg=cfg)
    # Should return gracefully with a skipped change entry
    assert any("skipped" in c.lower() or "failed" in c.lower() for c in result["changes"])
