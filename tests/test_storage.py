import pytest
from src.storage.db import build_db

import src.config as _cfg_module
from src.config import AppConfig


@pytest.fixture(autouse=True)
def reset_singleton():
    _cfg_module._instance = None
    yield
    _cfg_module._instance = None


@pytest.fixture
def cfg(tmp_path):
    return AppConfig(
        llm_provider="copilot",
        llm_model="gpt-4o",
        llm_api_key="x",
        vault_path=str(tmp_path),
        secret="s",
        _env_file=None,
    )


@pytest.mark.asyncio
async def test_db_initializes(cfg):
    db = build_db(cfg)
    await db.initialize()
    assert db.engine is not None
    await db.close()


@pytest.mark.asyncio
async def test_save_and_get_note(cfg):
    from src.storage.models import NoteRecord
    from src.storage.repository import NoteRepo

    db = build_db(cfg)
    await db.initialize()
    repo = NoteRepo(db)
    note = NoteRecord(
        path="Projects/Test.md",
        title="Test",
        note_type="project",
        tags='["work"]',
        content_hash="abc123",
        word_count=42,
    )
    await repo.save(note)
    result = await repo.get("Projects/Test.md")
    assert result is not None
    assert result.title == "Test"
    assert result.content_hash == "abc123"
    await db.close()


@pytest.mark.asyncio
async def test_note_upsert(cfg):
    from src.storage.models import NoteRecord
    from src.storage.repository import NoteRepo

    db = build_db(cfg)
    await db.initialize()
    repo = NoteRepo(db)
    note = NoteRecord(
        path="Test.md", title="V1", note_type="project", tags="[]", content_hash="h1", word_count=10
    )
    await repo.save(note)
    note2 = NoteRecord(
        path="Test.md", title="V2", note_type="project", tags="[]", content_hash="h2", word_count=20
    )
    await repo.save(note2)
    result = await repo.get("Test.md")
    assert result.title == "V2"
    await db.close()


@pytest.mark.asyncio
async def test_agent_run_idempotency(cfg):
    from src.storage.models import AgentRunRecord
    from src.storage.repository import AgentRunRepo

    db = build_db(cfg)
    await db.initialize()
    repo = AgentRunRepo(db)
    run = AgentRunRecord(note_path="Test.md", content_hash="abc", agent="librarian")
    await repo.save(run)
    assert await repo.exists("Test.md", "abc", "librarian")
    assert not await repo.exists("Test.md", "abc", "formatter")
    await db.close()


@pytest.mark.asyncio
async def test_agent_run_completed_agents(cfg):
    from src.storage.models import AgentRunRecord
    from src.storage.repository import AgentRunRepo

    db = build_db(cfg)
    await db.initialize()
    repo = AgentRunRepo(db)
    for agent in ["librarian", "formatter"]:
        await repo.save(AgentRunRecord(note_path="n.md", content_hash="x", agent=agent))
    completed = await repo.completed_agents("n.md", "x")
    assert completed == {"librarian", "formatter"}
    await db.close()


@pytest.mark.asyncio
async def test_all_hashes(cfg):
    from src.storage.models import NoteRecord
    from src.storage.repository import NoteRepo

    db = build_db(cfg)
    await db.initialize()
    repo = NoteRepo(db)
    await repo.save(NoteRecord(path="a.md", title="A", tags="[]", content_hash="h_a", word_count=1))
    await repo.save(NoteRecord(path="b.md", title="B", tags="[]", content_hash="h_b", word_count=1))
    hashes = await repo.all_hashes()
    assert hashes == {"a.md": "h_a", "b.md": "h_b"}
    await db.close()


@pytest.mark.asyncio
async def test_audit_log_write_and_query(cfg):
    from src.storage.repository import AuditLogRepo

    db = build_db(cfg)
    await db.initialize()
    repo = AuditLogRepo(db)
    await repo.write("formatter", "frontmatter_update", "added created field", "Projects/Test.md")
    entries = await repo.query(since="1d", limit=10)
    assert len(entries) == 1
    assert entries[0].agent == "formatter"
    assert entries[0].action == "frontmatter_update"
    await db.close()
