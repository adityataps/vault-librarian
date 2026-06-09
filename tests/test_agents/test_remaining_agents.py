"""Tests for Linker, MOC Maintainer, Inline Directive, and Scaffolder agents."""

from unittest.mock import MagicMock

from src.agents.state import make_state

# ── Linker ─────────────────────────────────────────────────────────────────────


class FakeLinkDecision:
    related_paths = ["Projects/Agent Platform.md"]
    reasoning = "related"


def test_linker_injects_related_section(tmp_path):
    from src.agents.linker import linker_node
    from src.config import AppConfig
    from src.vault.tools import VaultTools

    (tmp_path / "Projects").mkdir()
    (tmp_path / "Projects" / "Test.md").write_text("# Test\n\nContent.")
    llm = MagicMock()
    llm.with_structured_output.return_value.invoke.return_value = FakeLinkDecision()
    vector_store = MagicMock()
    vector_store.search_similar.return_value = ["Projects/Agent Platform.md"]
    cfg = AppConfig(
        llm_provider="copilot",
        llm_model="gpt-4o",
        llm_api_key="x",
        vault_path=str(tmp_path),
        secret="s",
        _env_file=None,
        autonomy_overrides={"linker": "full"},
    )
    tools = VaultTools(str(tmp_path))
    state = make_state("Projects/Test.md", "# Test\n\nContent.", {})
    result = linker_node(state, llm=llm, tools=tools, vector_store=vector_store, cfg=cfg)
    assert any("backlink" in c.lower() for c in result["changes"])
    assert "## Related" in (tmp_path / "Projects" / "Test.md").read_text()


def test_linker_skips_on_empty_search(tmp_path):
    from src.agents.linker import linker_node
    from src.config import AppConfig
    from src.vault.tools import VaultTools

    (tmp_path / "note.md").write_text("# Note")
    vector_store = MagicMock()
    vector_store.search_similar.return_value = []
    cfg = AppConfig(
        llm_provider="copilot",
        llm_model="gpt-4o",
        llm_api_key="x",
        vault_path=str(tmp_path),
        secret="s",
        _env_file=None,
    )
    state = make_state("note.md", "# Note", {})
    result = linker_node(
        state, llm=MagicMock(), tools=VaultTools(str(tmp_path)), vector_store=vector_store, cfg=cfg
    )
    assert result["changes"] == []


# ── MOC Maintainer ─────────────────────────────────────────────────────────────


def test_moc_maintainer_skips_unknown_folder(tmp_path):
    from src.agents.moc_maintainer import moc_maintainer_node
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
    state = make_state("Personal/note.md", "# Note", {})
    result = moc_maintainer_node(state, llm=MagicMock(), tools=VaultTools(str(tmp_path)), cfg=cfg)
    assert result["changes"] == []


def test_moc_maintainer_adds_to_moc(tmp_path):
    from src.agents.moc_maintainer import moc_maintainer_node
    from src.config import AppConfig
    from src.vault.tools import VaultTools

    (tmp_path / "Projects").mkdir()
    (tmp_path / "Projects" / "NewProject.md").write_text("# New Project")
    (tmp_path / "Work MOC.md").write_text(
        "# Work MOC\n\n## 🏗 Active Projects\n\n| [[Existing]] | |\n\n## 🎫 Jira Tickets\n\n"
    )
    cfg = AppConfig(
        llm_provider="copilot",
        llm_model="gpt-4o",
        llm_api_key="x",
        vault_path=str(tmp_path),
        secret="s",
        _env_file=None,
        autonomy_overrides={"moc_maintainer": "full"},
    )
    tools = VaultTools(str(tmp_path))
    state = make_state("Projects/NewProject.md", "# New Project", {})
    result = moc_maintainer_node(state, llm=MagicMock(), tools=tools, cfg=cfg)
    assert any("NewProject" in c for c in result["changes"])
    moc_content = (tmp_path / "Work MOC.md").read_text()
    assert "[[NewProject]]" in moc_content


# ── Inline Directive ───────────────────────────────────────────────────────────


def test_inline_directive_resolves_scaffold(tmp_path):
    from src.agents.inline_directive import inline_directive_node
    from src.config import AppConfig
    from src.vault.tools import VaultTools

    content = "# Note\n\n<agent-scaffold>list key features</agent-scaffold>"
    (tmp_path / "note.md").write_text(content)
    llm = MagicMock()
    llm.invoke.return_value.content = "- Feature A\n- Feature B"
    vector_store = MagicMock()
    vector_store.search_similar.return_value = []
    cfg = AppConfig(
        llm_provider="copilot",
        llm_model="gpt-4o",
        llm_api_key="x",
        vault_path=str(tmp_path),
        secret="s",
        _env_file=None,
        autonomy_overrides={"inline_directive": "full"},
    )
    tools = VaultTools(str(tmp_path))
    state = make_state("note.md", content, {})
    result = inline_directive_node(state, llm=llm, tools=tools, vector_store=vector_store, cfg=cfg)
    assert any("resolved" in c.lower() for c in result["changes"])
    updated = (tmp_path / "note.md").read_text()
    assert "Feature A" in updated
    assert "<agent-scaffold>" not in updated


def test_inline_directive_no_op_without_tags(tmp_path):
    from src.agents.inline_directive import inline_directive_node
    from src.config import AppConfig
    from src.vault.tools import VaultTools

    (tmp_path / "note.md").write_text("# Note\n\nNo directives here.")
    cfg = AppConfig(
        llm_provider="copilot",
        llm_model="gpt-4o",
        llm_api_key="x",
        vault_path=str(tmp_path),
        secret="s",
        _env_file=None,
    )
    state = make_state("note.md", "# Note\n\nNo directives here.", {})
    result = inline_directive_node(
        state, llm=MagicMock(), tools=VaultTools(str(tmp_path)), vector_store=MagicMock(), cfg=cfg
    )
    assert result["changes"] == []
    assert result["directives"] == []


# ── Scaffolder ─────────────────────────────────────────────────────────────────


def test_scaffolder_creates_note(tmp_path):
    from src.agents.scaffolder import run_scaffolder
    from src.config import AppConfig
    from src.vault.tools import VaultTools

    (tmp_path / "Projects").mkdir()
    llm = MagicMock()
    llm.invoke.return_value.content = (
        "---\ntype: project\ncreated: 2026-06-08\n---\n# New Project\n"
    )
    cfg = AppConfig(
        llm_provider="copilot",
        llm_model="gpt-4o",
        llm_api_key="x",
        vault_path=str(tmp_path),
        secret="s",
        _env_file=None,
    )
    tools = VaultTools(str(tmp_path))
    rel = run_scaffolder("New Project", "project", "", llm, tools, cfg)
    assert rel == "Projects/New Project.md"
    assert (tmp_path / "Projects" / "New Project.md").exists()


def test_scaffolder_fallback_on_llm_failure(tmp_path):
    from src.agents.scaffolder import run_scaffolder
    from src.config import AppConfig
    from src.vault.tools import VaultTools

    (tmp_path / "Meetings").mkdir()
    llm = MagicMock()
    llm.invoke.side_effect = Exception("API down")
    cfg = AppConfig(
        llm_provider="copilot",
        llm_model="gpt-4o",
        llm_api_key="x",
        vault_path=str(tmp_path),
        secret="s",
        _env_file=None,
    )
    tools = VaultTools(str(tmp_path))
    rel = run_scaffolder("Standup", "meeting", "", llm, tools, cfg)
    assert (tmp_path / "Meetings" / "Standup.md").exists()
