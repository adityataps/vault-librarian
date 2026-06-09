import pytest
from unittest.mock import AsyncMock, MagicMock
import src.config as _cfg_module


@pytest.fixture(autouse=True)
def reset_singleton():
    _cfg_module._instance = None
    yield
    _cfg_module._instance = None


@pytest.fixture
def setup(tmp_path):
    from src.config import AppConfig
    (tmp_path / "Librarian").mkdir()
    cfg = AppConfig(
        llm_provider="copilot", llm_model="gpt-4o", llm_api_key="x",
        vault_path=str(tmp_path), secret="s", _env_file=None,
    )
    db = MagicMock()
    return cfg, db, tmp_path


@pytest.mark.asyncio
async def test_daily_brief_creates_note(setup, monkeypatch):
    from src.agents.daily_brief import run_daily_brief
    from src.vault.tools import VaultTools
    cfg, db, tmp_path = setup

    monkeypatch.setattr("src.agents.daily_brief.NoteRepo",
        MagicMock(return_value=MagicMock(all_hashes=AsyncMock(return_value={}))))
    monkeypatch.setattr("src.agents.daily_brief.ActionItemRepo",
        MagicMock(return_value=MagicMock(unresolved=AsyncMock(return_value=[]))))
    monkeypatch.setattr("src.agents.daily_brief.AuditLogRepo",
        MagicMock(return_value=MagicMock(query=AsyncMock(return_value=[]))))

    llm = MagicMock()
    llm.invoke.return_value.content = "Daily summary content."
    tools = VaultTools(str(tmp_path))
    await run_daily_brief(cfg, db, tools, llm)

    from datetime import date
    today = date.today().isoformat()
    brief = tmp_path / "Librarian" / f"Daily Brief — {today}.md"
    assert brief.exists()
    assert today in brief.read_text()


@pytest.mark.asyncio
async def test_daily_brief_fallback_on_llm_failure(setup, monkeypatch):
    from src.agents.daily_brief import run_daily_brief
    from src.vault.tools import VaultTools
    cfg, db, tmp_path = setup

    monkeypatch.setattr("src.agents.daily_brief.NoteRepo",
        MagicMock(return_value=MagicMock(all_hashes=AsyncMock(return_value={}))))
    monkeypatch.setattr("src.agents.daily_brief.ActionItemRepo",
        MagicMock(return_value=MagicMock(unresolved=AsyncMock(return_value=[]))))
    monkeypatch.setattr("src.agents.daily_brief.AuditLogRepo",
        MagicMock(return_value=MagicMock(query=AsyncMock(return_value=[]))))

    llm = MagicMock()
    llm.invoke.side_effect = Exception("API down")
    tools = VaultTools(str(tmp_path))
    await run_daily_brief(cfg, db, tools, llm)  # must not raise

    from datetime import date
    brief = tmp_path / "Librarian" / f"Daily Brief — {date.today().isoformat()}.md"
    assert brief.exists()


@pytest.mark.asyncio
async def test_weekly_review_creates_note(setup, monkeypatch):
    from src.agents.weekly_review import run_weekly_review
    from src.vault.tools import VaultTools
    cfg, db, tmp_path = setup

    monkeypatch.setattr("src.agents.weekly_review.NoteRepo",
        MagicMock(return_value=MagicMock(all_hashes=AsyncMock(return_value={}))))
    monkeypatch.setattr("src.agents.weekly_review.ActionItemRepo",
        MagicMock(return_value=MagicMock(unresolved=AsyncMock(return_value=[]))))
    monkeypatch.setattr("src.agents.weekly_review.AuditLogRepo",
        MagicMock(return_value=MagicMock(query=AsyncMock(return_value=[]))))

    llm = MagicMock()
    llm.invoke.return_value.content = "Week in review."
    tools = VaultTools(str(tmp_path))
    await run_weekly_review(cfg, db, tools, llm)

    from datetime import date
    today = date.today()
    iso_year, iso_week, _ = today.isocalendar()
    week = f"{iso_year}-W{iso_week:02d}"
    note = tmp_path / "Librarian" / f"Weekly Review — {week}.md"
    assert note.exists()
    assert week in note.read_text()
