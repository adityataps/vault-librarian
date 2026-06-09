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
    result = formatter_node(state, llm=mock_llm_with_fix, tools=tools, cfg=cfg)
    updated = note.read_text()
    assert "```dataview" in updated


def test_formatter_supervised_proposes(mock_llm_with_fix, tmp_path):
    from src.config import AppConfig
    from src.vault.tools import VaultTools

    (tmp_path / ".librarian").mkdir()
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
    result = formatter_node(state, llm=mock_llm_with_fix, tools=tools, cfg=cfg)
    # File not modified, proposal written
    assert "proposed" in " ".join(result["changes"]).lower()
    assert note.read_text() == "---\ntags: []\n---\n# Note"  # unchanged
