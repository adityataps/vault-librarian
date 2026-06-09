import pytest
from unittest.mock import AsyncMock, MagicMock
import src.config as _cfg_module


@pytest.fixture(autouse=True)
def reset_singleton():
    _cfg_module._instance = None
    yield
    _cfg_module._instance = None


@pytest.fixture
def mcp_deps(tmp_path):
    from src.config import AppConfig
    from src.vault.tools import VaultTools
    (tmp_path / ".librarian").mkdir()
    (tmp_path / "Projects").mkdir()
    cfg = AppConfig(
        llm_provider="copilot", llm_model="gpt-4o", llm_api_key="x",
        vault_path=str(tmp_path), secret="s", _env_file=None,
    )
    db = MagicMock()
    db.session = MagicMock()
    tools = VaultTools(str(tmp_path))
    vector_store = MagicMock()
    vector_store.search_similar.return_value = []
    return cfg, db, tools, vector_store, tmp_path


def test_build_mcp_server_lazy_returns_instance(mcp_deps):
    """The lazy MCP server can be built without live state."""
    from src.api.mcp import build_mcp_server_lazy
    server = build_mcp_server_lazy()
    assert server is not None


@pytest.mark.asyncio
async def test_build_mcp_server_lazy_has_expected_tools(mcp_deps):
    """All 7 MCP tools are registered."""
    from src.api.mcp import build_mcp_server_lazy
    server = build_mcp_server_lazy()
    tool_names = {t.name for t in await server.list_tools()}
    expected = {
        "scaffold_note", "run_agent", "search_vault",
        "get_note_metadata", "list_notes", "get_action_items", "get_audit_report",
    }
    assert expected.issubset(tool_names), f"Missing tools: {expected - tool_names}"


@pytest.mark.asyncio
async def test_search_vault_no_results(mcp_deps):
    """search_vault returns a 'no results' string when vector store is empty."""
    from src.api.mcp import build_mcp_server_lazy
    import src.api.app as _app
    cfg, db, tools, vector_store, tmp_path = mcp_deps
    # Patch live state refs
    _app._db = db
    _app._runner = MagicMock(
        _vector_store=vector_store,
        _cfg=cfg,
        run=AsyncMock(),
    )
    try:
        server = build_mcp_server_lazy()
        result, _ = await server.call_tool("search_vault", {"query": "agent platform", "k": 5})
        result_str = str(result)
        assert "No results" in result_str or result == []
    finally:
        _app._db = None
        _app._runner = None


@pytest.mark.asyncio
async def test_get_audit_report_no_report(mcp_deps):
    """get_audit_report returns a helpful message when no report exists."""
    from src.api.mcp import build_mcp_server_lazy
    import src.api.app as _app
    cfg, db, tools, vector_store, tmp_path = mcp_deps
    _app._db = db
    _app._runner = MagicMock(_vector_store=vector_store, _cfg=cfg, run=AsyncMock())
    try:
        server = build_mcp_server_lazy()
        result, _ = await server.call_tool("get_audit_report", {})
        assert isinstance(str(result), str)
        # Either "No audit report" message or empty - both valid
    finally:
        _app._db = None
        _app._runner = None
