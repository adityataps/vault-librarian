from unittest.mock import MagicMock

import pytest

from src.agents.formatter import formatter_node
from src.agents.state import make_state


@pytest.fixture
def mock_llm_with_fix():
    from src.agents.formatter import FrontmatterFix

    llm = MagicMock()
    llm.with_structured_output.return_value.invoke.return_value = FrontmatterFix(
        fields_to_add={"created": "2026-06-08", "modified": "2026-06-08"},
        reasoning="Missing date fields",
    )
    return llm


@pytest.fixture
def mock_llm_no_fix():
    from src.agents.formatter import FrontmatterFix

    llm = MagicMock()
    llm.with_structured_output.return_value.invoke.return_value = FrontmatterFix(
        fields_to_add={},
        reasoning="Nothing to fix",
    )
    return llm


def test_formatter_adds_missing_fields(mock_llm_with_fix, tmp_path):
    from src.config import AppConfig
    from src.vault.tools import VaultTools

    note = tmp_path / "Projects" / "Test.md"
    note.parent.mkdir()
    note.write_text("---\ntags:\n  - work\n---\n# Test\n\nBody.")
    cfg = AppConfig(
        llm_provider="copilot",
        llm_model="gpt-4o",
        llm_api_key="x",
        vault_path=str(tmp_path),
        secret="s",
        _env_file=None,
        autonomy_overrides={"formatter": "full"},
    )
    tools = VaultTools(str(tmp_path))
    state = make_state("Projects/Test.md", note.read_text(), {"tags": ["work"]}, "project")
    result = formatter_node(state, llm=mock_llm_with_fix, tools=tools, cfg=cfg)
    assert len(result["changes"]) > 0
    updated = (tmp_path / "Projects" / "Test.md").read_text()
    assert "created" in updated


def test_formatter_no_op_when_nothing_needed(mock_llm_no_fix, tmp_path):
    from src.config import AppConfig
    from src.vault.tools import VaultTools

    note = tmp_path / "note.md"
    note.write_text("---\ntags: []\n---\n# Note")
    cfg = AppConfig(
        llm_provider="copilot",
        llm_model="gpt-4o",
        llm_api_key="x",
        vault_path=str(tmp_path),
        secret="s",
        _env_file=None,
        autonomy_overrides={"formatter": "full"},
    )
    tools = VaultTools(str(tmp_path))
    state = make_state("note.md", note.read_text(), {})
    result = formatter_node(state, llm=mock_llm_no_fix, tools=tools, cfg=cfg)
    assert result["changes"] == []


def test_formatter_preserves_dataview_blocks(mock_llm_with_fix, tmp_path):
    from src.config import AppConfig
    from src.vault.tools import VaultTools

    content = '---\ntags: []\n---\n# Note\n\n```dataview\nTABLE status FROM "Jira"\n```\n'
    note = tmp_path / "note.md"
    note.write_text(content)
    cfg = AppConfig(
        llm_provider="copilot",
        llm_model="gpt-4o",
        llm_api_key="x",
        vault_path=str(tmp_path),
        secret="s",
        _env_file=None,
        autonomy_overrides={"formatter": "full"},
    )
    tools = VaultTools(str(tmp_path))
    state = make_state("note.md", content, {})
    formatter_node(state, llm=mock_llm_with_fix, tools=tools, cfg=cfg)
    # Verify the LLM received stripped content (dataview SQL not in prompt)
    invoke_call = mock_llm_with_fix.with_structured_output.return_value.invoke
    called_messages = invoke_call.call_args[0][0]
    all_content = " ".join(m.content for m in called_messages)
    assert 'TABLE status FROM "Jira"' not in all_content
    assert "[preserved]" in all_content
    # File should still have the original dataview block
    assert "```dataview" in note.read_text()


def test_formatter_supervised_proposes(mock_llm_with_fix, tmp_path):
    from unittest.mock import patch

    from src.config import AppConfig
    from src.vault.tools import VaultTools

    (tmp_path / "Librarian").mkdir()
    note = tmp_path / "note.md"
    note.write_text("---\ntags: []\n---\n# Note")
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
    state = make_state("note.md", note.read_text(), {})
    with patch("src.agents.formatter.LibrarianInbox") as mock_inbox_cls:
        mock_inbox = mock_inbox_cls.return_value
        result = formatter_node(state, llm=mock_llm_with_fix, tools=tools, cfg=cfg)
    assert "proposed" in " ".join(result["changes"]).lower()
    assert note.read_text() == "---\ntags: []\n---\n# Note"
    mock_inbox.propose.assert_called_once()
