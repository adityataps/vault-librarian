# Vault Librarian — Core Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a working vault-librarian service that watches an Obsidian vault, dispatches LangGraph agent pipelines on file events, and applies Librarian, Formatter, Meeting Enricher, Linker, MOC Maintainer, Inline Directive, and Scaffolder agents — all committed back to git with full idempotency and restart resilience.

**Architecture:** Single Python service (FastAPI + Typer CLI) built on LangGraph for agent orchestration and LangChain for LLM provider abstraction. A debounced file watcher feeds a per-file-locked dispatcher; agents share typed `VaultState` through a conditional LangGraph graph; SQLite tracks note metadata and agent run history; ChromaDB handles semantic search.

**Tech Stack:** Python 3.11+, LangGraph, LangChain (OpenAI/Anthropic/Ollama), FastAPI, Watchdog, SQLAlchemy + SQLite, ChromaDB, sentence-transformers, python-frontmatter, GitPython, Typer, Rich, uv

---

## File Structure

```
src/
  config.py                  # AppConfig (pydantic-settings)
  main.py                    # CLI entrypoint (Typer)
  storage/
    __init__.py
    models.py                # SQLAlchemy ORM models
    db.py                    # engine, session factory, initialize()
    repository.py            # NoteRepo, AgentRunRepo, ActionItemRepo, AuditLogRepo
  vault/
    __init__.py
    parser.py                # parse_note() → NoteMetadata + content_hash
    tools.py                 # VaultTools: read/write/move/frontmatter/git/create/list
    scanner.py               # VaultScanner: scan(), iter_notes()
  vector/
    __init__.py
    store.py                 # VectorStore: upsert(), search_similar(), delete()
  llm/
    __init__.py
    factory.py               # build_llm(), build_embedder()
  dispatcher/
    __init__.py
    debounce.py              # DebounceMap: schedule(), cancel()
    locks.py                 # FileLockMap: async context manager per path
    watcher.py               # VaultWatcher (watchdog)
    dispatcher.py            # Dispatcher: on_event(), reconcile()
  agents/
    __init__.py
    state.py                 # VaultState TypedDict, Directive dataclass
    base.py                  # build_agent_node() helper, AGENT_PIPELINE_MAP
    librarian.py             # librarian_node()
    formatter.py             # formatter_node()
    meeting_enricher.py      # meeting_enricher_node()
    linker.py                # linker_node()
    moc_maintainer.py        # moc_maintainer_node()
    inline_directive.py      # inline_directive_node()
    scaffolder.py            # run_scaffolder()
  pipeline/
    __init__.py
    builder.py               # build_pipeline(note_type, enrolled) → compiled graph
    runner.py                # PipelineRunner: run(), idempotency check, optimistic lock
  api/
    __init__.py
    app.py                   # create_app() FastAPI factory
tests/
  conftest.py                # tmp_vault fixture, in-memory SQLite, mock LLM
  test_storage.py
  test_vault_tools.py
  test_dispatcher.py
  test_pipeline.py
  test_agents/
    __init__.py
    test_librarian.py
    test_formatter.py
    test_meeting_enricher.py
    test_linker.py
    test_moc_maintainer.py
    test_inline_directive.py
```

---

## Phase 1 — Project Foundation

### Task 1: Scaffold project structure and dependencies

**Files:**
- Rewrite: `pyproject.toml`
- Create: `src/__init__.py`, `src/storage/__init__.py`, `src/vault/__init__.py`, `src/vector/__init__.py`, `src/llm/__init__.py`, `src/dispatcher/__init__.py`, `src/agents/__init__.py`, `src/pipeline/__init__.py`, `src/api/__init__.py`
- Create: `.env.example`
- Create: `tests/__init__.py`, `tests/test_agents/__init__.py`

- [ ] **Delete all existing `src/` content** — blank slate, nothing carries forward
```bash
rm -rf src/ tests/ alembic/ main.py
mkdir -p src/{storage,vault,vector,llm,dispatcher,agents,pipeline,api}
mkdir -p tests/test_agents
touch src/__init__.py src/storage/__init__.py src/vault/__init__.py
touch src/vector/__init__.py src/llm/__init__.py src/dispatcher/__init__.py
touch src/agents/__init__.py src/pipeline/__init__.py src/api/__init__.py
touch tests/__init__.py tests/test_agents/__init__.py
```

- [ ] **Rewrite `pyproject.toml`**
```toml
[project]
name = "vault-librarian"
version = "0.1.0"
description = "Autonomous multi-agent Obsidian vault librarian"
requires-python = ">=3.11"
dependencies = [
    "langgraph>=0.2.0",
    "langchain-core>=0.3.0",
    "langchain-openai>=0.2.0",
    "langchain-anthropic>=0.3.0",
    "langchain-community>=0.3.0",
    "langchain-chroma>=0.1.4",
    "chromadb>=0.5.0",
    "sentence-transformers>=3.0.0",
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.32.0",
    "sqlalchemy>=2.0.35",
    "aiosqlite>=0.20.0",
    "alembic>=1.14.0",
    "watchdog>=6.0.0",
    "apscheduler>=3.10.4",
    "python-frontmatter>=1.1.0",
    "pydantic>=2.10.0",
    "pydantic-settings>=2.6.0",
    "python-dotenv>=1.0.1",
    "gitpython>=3.1.0",
    "typer>=0.15.0",
    "rich>=13.9.0",
    "mcp>=1.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.3.0",
    "pytest-asyncio>=0.24.0",
    "pytest-mock>=3.14.0",
    "ruff>=0.8.0",
    "mypy>=1.13.0",
]

[project.scripts]
vault-librarian = "src.main:app"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src"]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "N", "W"]
ignore = ["E501"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Create `.env.example`**
```bash
# LLM provider: copilot | anthropic | ollama
LIBRARIAN_LLM_PROVIDER=copilot
LIBRARIAN_LLM_MODEL=gpt-4o
LIBRARIAN_LLM_API_KEY=your-github-token-here

# Vault
LIBRARIAN_VAULT_PATH=/Users/you/Documents/Obsidian Vault

# Service
LIBRARIAN_SECRET=change-me
LIBRARIAN_LOG_LEVEL=INFO

# Optional Anthropic
# LIBRARIAN_LLM_API_KEY=sk-ant-...
```

- [ ] **Install dependencies**
```bash
uv sync
```
Expected: resolves and installs all packages without error.

- [ ] **Commit**
```bash
git add pyproject.toml .env.example src/ tests/
git commit -m "chore: scaffold vault-librarian project structure"
```

---

### Task 2: AppConfig

**Files:**
- Create: `src/config.py`
- Create: `tests/test_config.py`

- [ ] **Write failing test**
```python
# tests/test_config.py
import os
import pytest
from src.config import AppConfig

def test_config_loads_from_env(monkeypatch):
    monkeypatch.setenv("LIBRARIAN_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("LIBRARIAN_LLM_MODEL", "claude-sonnet-4-6")
    monkeypatch.setenv("LIBRARIAN_LLM_API_KEY", "sk-test")
    monkeypatch.setenv("LIBRARIAN_VAULT_PATH", "/tmp/vault")
    monkeypatch.setenv("LIBRARIAN_SECRET", "secret")
    cfg = AppConfig()
    assert cfg.llm_provider == "anthropic"
    assert cfg.llm_model == "claude-sonnet-4-6"
    assert cfg.vault_path == "/tmp/vault"

def test_config_default_autonomy():
    cfg = AppConfig(
        llm_provider="copilot", llm_model="gpt-4o",
        llm_api_key="x", vault_path="/tmp", secret="s"
    )
    assert cfg.autonomy_default == "supervised"
    assert cfg.autonomy_overrides.get("formatter") == "full"

def test_config_enrolled_agents_default():
    cfg = AppConfig(
        llm_provider="copilot", llm_model="gpt-4o",
        llm_api_key="x", vault_path="/tmp", secret="s"
    )
    assert "librarian" in cfg.enrolled_agents
    assert "formatter" in cfg.enrolled_agents
```

- [ ] **Run to confirm failure**
```bash
uv run pytest tests/test_config.py -v
```
Expected: `ModuleNotFoundError: No module named 'src.config'`

- [ ] **Implement `src/config.py`**
```python
from __future__ import annotations
from pydantic import PrivateAttr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LIBRARIAN_", env_file=".env", extra="ignore")

    # LLM
    llm_provider: str = "copilot"
    llm_model: str = "gpt-4o"
    llm_api_key: str = ""

    # Vault
    vault_path: str = ""
    vault_excluded_folders: list[str] = [".obsidian", ".git", ".librarian", "Attachments"]
    vault_excluded_files: list[str] = ["CLAUDE.md"]

    # Service
    secret: str = "change-me"
    log_level: str = "INFO"
    debounce_standard: float = 3.0
    debounce_directive: float = 0.5

    # Agent enrollment (comma-separated env var or list in config)
    enrolled_agents: list[str] = [
        "librarian", "formatter", "meeting_enricher", "linker",
        "moc_maintainer", "inline_directive", "scaffolder", "auditor",
        "daily_brief", "weekly_review",
    ]

    # Autonomy
    autonomy_default: str = "supervised"
    autonomy_overrides: dict[str, str] = {
        "formatter": "full",
        "inline_directive": "full",
        "meeting_enricher": "full",
    }

    # Schedules (cron expressions)
    auditor_schedule: str = "0 2 * * *"
    daily_brief_schedule: str = "0 7 * * *"
    weekly_review_schedule: str = "0 18 * * 0"

    # Stale threshold (days)
    stale_days: int = 60

    @field_validator("enrolled_agents", mode="before")
    @classmethod
    def parse_agents(cls, v: object) -> list[str]:
        if isinstance(v, str):
            return [a.strip() for a in v.split(",") if a.strip()]
        return v

    def get_autonomy(self, agent: str) -> str:
        return self.autonomy_overrides.get(agent, self.autonomy_default)

    # Natural-language instructions loaded from .librarian/config.md at runtime
    _agent_instructions: dict[str, str] = PrivateAttr(default_factory=dict)

    def get_agent_instructions(self, agent: str) -> str:
        return self._agent_instructions.get(agent, "")

    def update_agent_instructions(self, instructions: dict[str, str]) -> None:
        self._agent_instructions = instructions


_instance: AppConfig | None = None


def get_config() -> AppConfig:
    global _instance
    if _instance is None:
        _instance = AppConfig()
    return _instance
```

- [ ] **Run tests to confirm pass**
```bash
uv run pytest tests/test_config.py -v
```
Expected: 3 passed.

- [ ] **Commit**
```bash
git add src/config.py tests/test_config.py
git commit -m "feat: add AppConfig with pydantic-settings"
```

---

### Task 3: CLI skeleton

**Files:**
- Create: `src/main.py`

- [ ] **Write `src/main.py`**
```python
"""vault-librarian CLI entrypoint."""
from __future__ import annotations
import logging
import typer
from rich.console import Console
from rich.logging import RichHandler

app = typer.Typer(name="vault-librarian", no_args_is_help=True)
console = Console()


def _setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=level, format="%(message)s", datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True, markup=True)],
    )
    for noisy in ("httpx", "watchdog", "apscheduler", "chromadb"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", "--host"),
    port: int = typer.Option(8000, "--port"),
    reload: bool = typer.Option(False, "--reload"),
    agents: str = typer.Option("", "--agents", help="Comma-separated agent override"),
) -> None:
    """Start the vault-librarian service."""
    import uvicorn
    from src.config import get_config
    _setup_logging()
    cfg = get_config()
    if agents:
        cfg.enrolled_agents = [a.strip() for a in agents.split(",")]
    console.print(f"[bold green]vault-librarian[/] — vault: [cyan]{cfg.vault_path}[/]")
    uvicorn.run("src.api.app:create_app", factory=True, host=host, port=port, reload=reload)


@app.command()
def scan() -> None:
    """Scan vault and print note summary."""
    from src.config import get_config
    from src.vault.scanner import VaultScanner
    _setup_logging()
    cfg = get_config()
    scanner = VaultScanner(cfg)
    result = scanner.scan()
    console.print(f"Found [bold]{result.total}[/] notes, [red]{result.errors}[/] errors")


@app.command()
def index(force: bool = typer.Option(False, "--force")) -> None:
    """Reconcile all vault notes into storage."""
    import asyncio
    from src.config import get_config
    from src.storage.db import build_db
    from src.vault.scanner import VaultScanner
    from src.pipeline.runner import reconcile_all
    _setup_logging()
    cfg = get_config()
    asyncio.run(reconcile_all(cfg, force=force))


@app.command()
def status() -> None:
    """Check service health."""
    from src.config import get_config
    _setup_logging()
    cfg = get_config()
    console.print(f"Vault: [cyan]{cfg.vault_path}[/]")
    console.print(f"Provider: [cyan]{cfg.llm_provider}/{cfg.llm_model}[/]")
    console.print(f"Agents: [cyan]{', '.join(cfg.enrolled_agents)}[/]")


@app.command()
def log(
    agent: str = typer.Option("", "--agent"),
    since: str = typer.Option("7d", "--since"),
    limit: int = typer.Option(50, "--limit"),
) -> None:
    """Query agent audit log."""
    import asyncio
    from src.storage.db import build_db
    from src.storage.repository import AuditLogRepo
    from src.config import get_config
    _setup_logging()
    cfg = get_config()

    async def _run() -> None:
        db = build_db(cfg)
        await db.initialize()
        repo = AuditLogRepo(db)
        entries = await repo.query(agent=agent or None, since=since, limit=limit)
        for e in entries:
            console.print(f"[dim]{e.timestamp}[/] [bold]{e.agent}[/] {e.action} — {e.detail}")

    asyncio.run(_run())


@app.command("install-hooks")
def install_hooks() -> None:
    """Install git post-commit hook into vault .git/hooks/."""
    from pathlib import Path
    from src.config import get_config
    cfg = get_config()
    hook_path = Path(cfg.vault_path) / ".git" / "hooks" / "post-commit"
    hook_path.parent.mkdir(parents=True, exist_ok=True)
    hook_path.write_text(
        "#!/bin/sh\ncurl -s -X POST http://localhost:8000/webhook/git "
        f"-H 'X-Librarian-Secret: {cfg.secret}' || true\n"
    )
    hook_path.chmod(0o755)
    console.print(f"[green]✓[/] Hook installed at {hook_path}")


if __name__ == "__main__":
    app()
```

- [ ] **Verify CLI loads**
```bash
uv run vault-librarian --help
```
Expected: lists serve, scan, index, status, log, install-hooks commands.

- [ ] **Commit**
```bash
git add src/main.py
git commit -m "feat: add CLI skeleton (serve, scan, index, status, log, install-hooks)"
```

---

## Phase 2 — Storage Layer

### Task 4: SQLAlchemy models and DB setup

**Files:**
- Create: `src/storage/models.py`
- Create: `src/storage/db.py`
- Create: `tests/test_storage.py`

- [ ] **Write failing tests**
```python
# tests/test_storage.py
import pytest
from src.storage.db import build_db
from src.config import AppConfig


@pytest.fixture
def cfg(tmp_path):
    return AppConfig(
        llm_provider="copilot", llm_model="gpt-4o",
        llm_api_key="x", vault_path=str(tmp_path), secret="s",
        _env_file=None,
    )


@pytest.mark.asyncio
async def test_db_initializes(cfg):
    db = build_db(cfg)
    await db.initialize()
    assert db.engine is not None


@pytest.mark.asyncio
async def test_save_and_get_note(cfg):
    from src.storage.repository import NoteRepo
    from src.storage.models import NoteRecord
    db = build_db(cfg)
    await db.initialize()
    repo = NoteRepo(db)
    note = NoteRecord(
        path="Projects/Test.md", title="Test", note_type="project",
        tags='["work"]', content_hash="abc123", word_count=42,
    )
    await repo.save(note)
    result = await repo.get("Projects/Test.md")
    assert result is not None
    assert result.title == "Test"
    assert result.content_hash == "abc123"


@pytest.mark.asyncio
async def test_agent_run_idempotency(cfg):
    from src.storage.repository import AgentRunRepo
    from src.storage.models import AgentRunRecord
    db = build_db(cfg)
    await db.initialize()
    repo = AgentRunRepo(db)
    run = AgentRunRecord(note_path="Test.md", content_hash="abc", agent="librarian")
    await repo.save(run)
    assert await repo.exists("Test.md", "abc", "librarian")
    assert not await repo.exists("Test.md", "abc", "formatter")
```

- [ ] **Run to confirm failure**
```bash
uv run pytest tests/test_storage.py -v
```
Expected: `ModuleNotFoundError`

- [ ] **Implement `src/storage/models.py`**
```python
from __future__ import annotations
from datetime import datetime, timezone
from sqlalchemy import String, Integer, Text, DateTime, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


class NoteRecord(Base):
    __tablename__ = "notes"
    path: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str | None] = mapped_column(String)
    note_type: Mapped[str | None] = mapped_column(String)
    tags: Mapped[str] = mapped_column(Text, default="[]")  # JSON array
    content_hash: Mapped[str] = mapped_column(String, default="")
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    indexed_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    last_modified: Mapped[datetime | None] = mapped_column(DateTime)


class AgentRunRecord(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (UniqueConstraint("note_path", "content_hash", "agent"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    note_path: Mapped[str] = mapped_column(String, index=True)
    content_hash: Mapped[str] = mapped_column(String)
    agent: Mapped[str] = mapped_column(String)
    completed_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class ActionItemRecord(Base):
    __tablename__ = "action_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_note: Mapped[str] = mapped_column(String, index=True)
    content: Mapped[str] = mapped_column(Text)
    due_date: Mapped[str | None] = mapped_column(String)
    resolved: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class AuditLogRecord(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent: Mapped[str] = mapped_column(String)
    note_path: Mapped[str | None] = mapped_column(String)
    action: Mapped[str] = mapped_column(String)
    detail: Mapped[str] = mapped_column(Text, default="")
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=_now)
```

- [ ] **Implement `src/storage/db.py`**
```python
from __future__ import annotations
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from src.config import AppConfig
from src.storage.models import Base


class Database:
    def __init__(self, url: str) -> None:
        self.url = url
        self.engine: AsyncEngine | None = None
        self._session_factory = None

    async def initialize(self) -> None:
        self.engine = create_async_engine(self.url, echo=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self._session_factory = sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )

    def session(self) -> AsyncSession:
        return self._session_factory()

    async def close(self) -> None:
        if self.engine:
            await self.engine.dispose()


def build_db(cfg: AppConfig) -> Database:
    librarian_dir = Path(cfg.vault_path) / ".librarian"
    librarian_dir.mkdir(exist_ok=True)
    db_path = librarian_dir / "librarian.db"
    return Database(f"sqlite+aiosqlite:///{db_path}")
```

- [ ] **Implement `src/storage/repository.py`**
```python
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, delete
from src.storage.db import Database
from src.storage.models import NoteRecord, AgentRunRecord, ActionItemRecord, AuditLogRecord


class NoteRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def save(self, note: NoteRecord) -> None:
        async with self._db.session() as s:
            await s.merge(note)
            await s.commit()

    async def get(self, path: str) -> NoteRecord | None:
        async with self._db.session() as s:
            return await s.get(NoteRecord, path)

    async def all_hashes(self) -> dict[str, str]:
        async with self._db.session() as s:
            rows = await s.execute(select(NoteRecord.path, NoteRecord.content_hash))
            return {r[0]: r[1] for r in rows}

    async def delete(self, path: str) -> None:
        async with self._db.session() as s:
            await s.execute(delete(NoteRecord).where(NoteRecord.path == path))
            await s.commit()


class AgentRunRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def save(self, run: AgentRunRecord) -> None:
        async with self._db.session() as s:
            s.add(run)
            try:
                await s.commit()
            except Exception:
                await s.rollback()

    async def exists(self, path: str, content_hash: str, agent: str) -> bool:
        async with self._db.session() as s:
            q = select(AgentRunRecord).where(
                AgentRunRecord.note_path == path,
                AgentRunRecord.content_hash == content_hash,
                AgentRunRecord.agent == agent,
            )
            return (await s.execute(q)).first() is not None

    async def completed_agents(self, path: str, content_hash: str) -> set[str]:
        async with self._db.session() as s:
            q = select(AgentRunRecord.agent).where(
                AgentRunRecord.note_path == path,
                AgentRunRecord.content_hash == content_hash,
            )
            rows = await s.execute(q)
            return {r[0] for r in rows}


class ActionItemRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def save(self, item: ActionItemRecord) -> None:
        async with self._db.session() as s:
            s.add(item)
            await s.commit()

    async def unresolved(self) -> list[ActionItemRecord]:
        async with self._db.session() as s:
            q = select(ActionItemRecord).where(ActionItemRecord.resolved == 0)
            return list((await s.execute(q)).scalars())


class AuditLogRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def write(self, agent: str, action: str, detail: str = "", note_path: str | None = None) -> None:
        async with self._db.session() as s:
            s.add(AuditLogRecord(agent=agent, action=action, detail=detail, note_path=note_path))
            await s.commit()

    async def query(self, agent: str | None = None, since: str = "7d", limit: int = 50) -> list[AuditLogRecord]:
        days = int(since.rstrip("d")) if since.endswith("d") else 7
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        async with self._db.session() as s:
            q = select(AuditLogRecord).where(AuditLogRecord.timestamp >= cutoff).limit(limit)
            if agent:
                q = q.where(AuditLogRecord.agent == agent)
            return list((await s.execute(q)).scalars())
```

- [ ] **Run tests**
```bash
uv run pytest tests/test_storage.py -v
```
Expected: 3 passed.

- [ ] **Commit**
```bash
git add src/storage/ tests/test_storage.py
git commit -m "feat: add SQLite storage layer (models, db, repositories)"
```

---

## Phase 3 — Vault Tools

### Task 5: Note parser

**Files:**
- Create: `src/vault/parser.py`
- Create: `tests/test_vault_tools.py` (partial)

- [ ] **Write failing tests**
```python
# tests/test_vault_tools.py
import pytest
from pathlib import Path
from src.vault.parser import parse_note, NoteMetadata


@pytest.fixture
def vault(tmp_path):
    (tmp_path / "Projects").mkdir()
    return tmp_path


def test_parse_note_with_frontmatter(vault):
    note = vault / "Projects" / "Test.md"
    note.write_text("---\ntags:\n  - work\ntype: project\n---\n# Test\n\nSome content here.")
    meta = parse_note(str(note), str(vault))
    assert meta.title == "Test"
    assert meta.note_type == "project"
    assert "work" in meta.tags
    assert meta.folder == "Projects"
    assert len(meta.content_hash) == 64  # sha256 hex


def test_parse_note_no_frontmatter(vault):
    note = vault / "bare.md"
    note.write_text("# Bare Note\n\nJust content.")
    meta = parse_note(str(note), str(vault))
    assert meta.title == "Bare Note"
    assert meta.note_type is None
    assert meta.tags == []


def test_parse_note_word_count(vault):
    note = vault / "words.md"
    note.write_text("---\n---\none two three four five")
    meta = parse_note(str(note), str(vault))
    assert meta.word_count == 5
```

- [ ] **Run to confirm failure**
```bash
uv run pytest tests/test_vault_tools.py -v
```
Expected: `ModuleNotFoundError`

- [ ] **Implement `src/vault/parser.py`**
```python
from __future__ import annotations
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
import frontmatter


@dataclass
class NoteMetadata:
    path: str           # relative to vault root
    abs_path: str
    title: str
    folder: str
    note_type: str | None
    tags: list[str]
    content_hash: str
    word_count: int
    frontmatter: dict
    raw_content: str


def parse_note(abs_path: str, vault_root: str) -> NoteMetadata:
    text = Path(abs_path).read_text(encoding="utf-8")
    post = frontmatter.loads(text)
    fm = dict(post.metadata)
    body = post.content

    rel = str(Path(abs_path).relative_to(vault_root))
    folder = str(Path(rel).parent) if str(Path(rel).parent) != "." else ""

    # Title: first H1 or stem
    title_match = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else Path(abs_path).stem

    tags = fm.get("tags", [])
    if isinstance(tags, str):
        tags = [tags]

    note_type = fm.get("type") or fm.get("note_type") or None

    content_hash = hashlib.sha256(text.encode()).hexdigest()
    word_count = len(body.split())

    return NoteMetadata(
        path=rel,
        abs_path=abs_path,
        title=title,
        folder=folder,
        note_type=note_type,
        tags=tags,
        content_hash=content_hash,
        word_count=word_count,
        frontmatter=fm,
        raw_content=text,
    )
```

- [ ] **Run tests**
```bash
uv run pytest tests/test_vault_tools.py -v
```
Expected: 3 passed.

- [ ] **Commit**
```bash
git add src/vault/parser.py tests/test_vault_tools.py
git commit -m "feat: add note parser with frontmatter, hash, word count"
```

---

### Task 6: VaultTools (read/write/move/frontmatter/git)

**Files:**
- Create: `src/vault/tools.py`
- Extend: `tests/test_vault_tools.py`

- [ ] **Append tests to `tests/test_vault_tools.py`**
```python
from src.vault.tools import VaultTools


def test_write_note_atomic(vault):
    tools = VaultTools(str(vault))
    tools.write_note("Projects/New.md", "# New\n\nContent.")
    assert (vault / "Projects" / "New.md").read_text() == "# New\n\nContent."


def test_write_note_conflict_detection(vault):
    note = vault / "Projects" / "Test.md"
    note.write_text("original")
    tools = VaultTools(str(vault))
    # Simulate: dispatch_hash taken before human edit
    dispatch_hash = "stale_hash"
    with pytest.raises(ConflictError):
        tools.write_note("Projects/Test.md", "agent write", dispatch_hash=dispatch_hash)


def test_move_note(vault):
    src = vault / "orphan.md"
    src.write_text("# Orphan")
    (vault / "Personal").mkdir()
    tools = VaultTools(str(vault))
    tools.move_note("orphan.md", "Personal/orphan.md")
    assert (vault / "Personal" / "orphan.md").exists()
    assert not src.exists()


def test_update_frontmatter(vault):
    note = vault / "Projects" / "Test.md"
    note.write_text("---\ntags:\n  - work\n---\n# Test\n\nBody.")
    tools = VaultTools(str(vault))
    tools.update_frontmatter("Projects/Test.md", {"type": "project", "created": "2026-06-08"})
    from src.vault.parser import parse_note
    meta = parse_note(str(vault / "Projects" / "Test.md"), str(vault))
    assert meta.frontmatter["type"] == "project"
    assert meta.frontmatter["created"] == "2026-06-08"
    assert meta.frontmatter["tags"] == ["work"]  # preserved
```

- [ ] **Implement `src/vault/tools.py`**
```python
from __future__ import annotations
import hashlib
import os
import re
import shutil
import tempfile
from pathlib import Path

import frontmatter
import git


class ConflictError(Exception):
    """Raised when a note was modified by a human during agent processing."""


class VaultTools:
    def __init__(self, vault_root: str) -> None:
        self.root = Path(vault_root)
        try:
            self._repo = git.Repo(vault_root)
        except git.InvalidGitRepositoryError:
            self._repo = None

    def abs(self, rel: str) -> Path:
        return self.root / rel

    def read_note(self, rel: str) -> str:
        return self.abs(rel).read_text(encoding="utf-8")

    def current_hash(self, rel: str) -> str:
        text = self.read_note(rel)
        return hashlib.sha256(text.encode()).hexdigest()

    def write_note(self, rel: str, content: str, dispatch_hash: str | None = None) -> None:
        target = self.abs(rel)
        if dispatch_hash is not None and target.exists():
            if self.current_hash(rel) != dispatch_hash:
                raise ConflictError(f"{rel} was modified during processing")
        target.parent.mkdir(parents=True, exist_ok=True)
        # atomic write via temp file + rename
        fd, tmp = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
            os.replace(tmp, target)
        except Exception:
            os.unlink(tmp)
            raise

    def move_note(self, src_rel: str, dst_rel: str) -> None:
        src = self.abs(src_rel)
        dst = self.abs(dst_rel)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))

    def update_frontmatter(self, rel: str, fields: dict) -> None:
        text = self.read_note(rel)
        post = frontmatter.loads(text)
        post.metadata.update(fields)
        updated = frontmatter.dumps(post)
        self.write_note(rel, updated)

    def create_note(self, rel: str, content: str) -> None:
        self.write_note(rel, content)

    def list_notes(self, folder: str = "", note_type: str | None = None) -> list[str]:
        base = self.root / folder if folder else self.root
        return [
            str(p.relative_to(self.root))
            for p in base.rglob("*.md")
            if not any(part.startswith(".") for part in p.parts)
        ]

    def git_commit(self, message: str) -> None:
        if self._repo is None:
            return
        self._repo.git.add(A=True)
        if self._repo.is_dirty(index=True):
            self._repo.index.commit(
                message,
                author=git.Actor("vault-librarian[bot]", "librarian@local"),
            )

    def has_directive_tags(self, rel: str) -> bool:
        try:
            return "<agent-" in self.read_note(rel)
        except FileNotFoundError:
            return False
```

- [ ] **Run tests**
```bash
uv run pytest tests/test_vault_tools.py -v
```
Expected: 7 passed.

- [ ] **Commit**
```bash
git add src/vault/tools.py
git commit -m "feat: add VaultTools (atomic write, conflict detection, move, frontmatter, git)"
```

---

### Task 7: VaultScanner

**Files:**
- Create: `src/vault/scanner.py`

- [ ] **Append tests to `tests/test_vault_tools.py`**
```python
from src.vault.scanner import VaultScanner
from src.config import AppConfig


def test_scanner_finds_notes(vault, monkeypatch):
    (vault / "Projects" / "Alpha.md").write_text("# Alpha")
    (vault / "Meetings" / "Standup.md").write_text("# Standup")
    (vault / ".obsidian").mkdir()
    (vault / ".obsidian" / "config.json").write_text("{}")
    cfg = AppConfig(
        llm_provider="copilot", llm_model="gpt-4o",
        llm_api_key="x", vault_path=str(vault), secret="s",
    )
    scanner = VaultScanner(cfg)
    result = scanner.scan()
    paths = [n.path for n in result.notes]
    assert any("Alpha.md" in p for p in paths)
    assert not any(".obsidian" in p for p in paths)
```

- [ ] **Implement `src/vault/scanner.py`**
```python
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from src.config import AppConfig
from src.vault.parser import NoteMetadata, parse_note


@dataclass
class ScanResult:
    notes: list[NoteMetadata]
    total: int
    errors: int


class VaultScanner:
    def __init__(self, cfg: AppConfig) -> None:
        self.root = Path(cfg.vault_path)
        self.excluded = set(cfg.vault_excluded_folders)
        self.excluded_files = set(cfg.vault_excluded_files)

    def _is_excluded(self, path: Path) -> bool:
        return any(part in self.excluded for part in path.relative_to(self.root).parts)

    def iter_notes(self):
        for md in self.root.rglob("*.md"):
            if self._is_excluded(md):
                continue
            if md.name in self.excluded_files:
                continue
            try:
                yield parse_note(str(md), str(self.root))
            except Exception:
                pass

    def scan(self) -> ScanResult:
        notes, errors = [], 0
        for md in self.root.rglob("*.md"):
            if self._is_excluded(md):
                continue
            try:
                notes.append(parse_note(str(md), str(self.root)))
            except Exception:
                errors += 1
        return ScanResult(notes=notes, total=len(notes), errors=errors)
```

- [ ] **Run tests**
```bash
uv run pytest tests/test_vault_tools.py -v
```
Expected: all pass.

- [ ] **Commit**
```bash
git add src/vault/scanner.py
git commit -m "feat: add VaultScanner"
```

---

## Phase 4 — Vector Store & LLM Abstraction

### Task 8: ChromaDB vector store and LLM factory

**Files:**
- Create: `src/vector/store.py`
- Create: `src/llm/factory.py`

- [ ] **Implement `src/vector/store.py`**
```python
from __future__ import annotations
from pathlib import Path
import chromadb
from langchain_chroma import Chroma
from langchain_core.embeddings import Embeddings


class VectorStore:
    def __init__(self, vault_root: str, embedder: Embeddings) -> None:
        persist_dir = str(Path(vault_root) / ".librarian" / "chroma")
        client = chromadb.PersistentClient(path=persist_dir)
        self._store = Chroma(
            client=client,
            collection_name="vault",
            embedding_function=embedder,
        )

    def upsert(self, path: str, content: str) -> None:
        self._store.add_texts(texts=[content], ids=[path], metadatas=[{"path": path}])

    def search_similar(self, content: str, k: int = 5) -> list[str]:
        results = self._store.similarity_search(content, k=k)
        return [doc.metadata["path"] for doc in results]

    def delete(self, path: str) -> None:
        self._store.delete(ids=[path])
```

- [ ] **Implement `src/llm/factory.py`**
```python
from __future__ import annotations
from langchain_core.language_models import BaseChatModel
from langchain_core.embeddings import Embeddings
from src.config import AppConfig


def build_llm(cfg: AppConfig) -> BaseChatModel:
    match cfg.llm_provider:
        case "copilot":
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(
                base_url="https://models.inference.ai.azure.com",
                api_key=cfg.llm_api_key,
                model=cfg.llm_model,
            )
        case "anthropic":
            from langchain_anthropic import ChatAnthropic
            return ChatAnthropic(model=cfg.llm_model, api_key=cfg.llm_api_key)
        case "ollama":
            from langchain_community.chat_models import ChatOllama
            return ChatOllama(model=cfg.llm_model)
        case _:
            raise ValueError(f"Unknown LLM provider: {cfg.llm_provider}")


def build_embedder(cfg: AppConfig) -> Embeddings:
    from langchain_community.embeddings import HuggingFaceEmbeddings
    return HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
```

- [ ] **Verify imports**
```bash
uv run python -c "from src.vector.store import VectorStore; from src.llm.factory import build_llm; print('OK')"
```
Expected: `OK`

- [ ] **Commit**
```bash
git add src/vector/ src/llm/
git commit -m "feat: add ChromaDB vector store and LLM factory"
```

---

## Phase 5 — File Watcher & Dispatcher

### Task 9: Debounce map and file locks

**Files:**
- Create: `src/dispatcher/debounce.py`
- Create: `src/dispatcher/locks.py`
- Create: `tests/test_dispatcher.py`

- [ ] **Write failing tests**
```python
# tests/test_dispatcher.py
import asyncio
import pytest
from src.dispatcher.debounce import DebounceMap
from src.dispatcher.locks import FileLockMap


@pytest.mark.asyncio
async def test_debounce_fires_after_delay():
    fired = []
    dm = DebounceMap(default_delay=0.05)
    dm.schedule("a.md", lambda: fired.append("a"), delay=0.05)
    await asyncio.sleep(0.12)
    assert fired == ["a"]


@pytest.mark.asyncio
async def test_debounce_resets_on_repeat():
    fired = []
    dm = DebounceMap(default_delay=0.1)
    dm.schedule("b.md", lambda: fired.append("b"), delay=0.1)
    await asyncio.sleep(0.05)
    dm.schedule("b.md", lambda: fired.append("b"), delay=0.1)
    await asyncio.sleep(0.05)
    assert fired == []  # hasn't fired yet
    await asyncio.sleep(0.1)
    assert len(fired) == 1  # fired exactly once


@pytest.mark.asyncio
async def test_file_lock_serializes():
    locks = FileLockMap()
    order = []
    async def task(name):
        async with locks.acquire("same.md"):
            order.append(f"start-{name}")
            await asyncio.sleep(0.02)
            order.append(f"end-{name}")
    await asyncio.gather(task("a"), task("b"))
    assert order.index("end-a") < order.index("start-b") or \
           order.index("end-b") < order.index("start-a")
```

- [ ] **Run to confirm failure**
```bash
uv run pytest tests/test_dispatcher.py -v
```
Expected: `ModuleNotFoundError`

- [ ] **Implement `src/dispatcher/debounce.py`**
```python
from __future__ import annotations
import asyncio
from collections import defaultdict
from typing import Callable


class DebounceMap:
    def __init__(self, default_delay: float = 3.0) -> None:
        self.default_delay = default_delay
        self._handles: dict[str, asyncio.TimerHandle] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    def _get_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is None:
            self._loop = asyncio.get_event_loop()
        return self._loop

    def schedule(self, path: str, callback: Callable[[], None], delay: float | None = None) -> None:
        d = delay if delay is not None else self.default_delay
        loop = self._get_loop()
        if path in self._handles:
            self._handles[path].cancel()
        self._handles[path] = loop.call_later(d, lambda: self._fire(path, callback))

    def _fire(self, path: str, callback: Callable[[], None]) -> None:
        self._handles.pop(path, None)
        callback()

    def cancel(self, path: str) -> None:
        if handle := self._handles.pop(path, None):
            handle.cancel()
```

- [ ] **Implement `src/dispatcher/locks.py`**
```python
from __future__ import annotations
import asyncio
from contextlib import asynccontextmanager


class FileLockMap:
    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}

    def _get(self, path: str) -> asyncio.Lock:
        if path not in self._locks:
            self._locks[path] = asyncio.Lock()
        return self._locks[path]

    @asynccontextmanager
    async def acquire(self, path: str):
        async with self._get(path):
            yield
```

- [ ] **Run tests**
```bash
uv run pytest tests/test_dispatcher.py -v
```
Expected: 3 passed.

- [ ] **Commit**
```bash
git add src/dispatcher/debounce.py src/dispatcher/locks.py tests/test_dispatcher.py
git commit -m "feat: add debounce map and per-file async locks"
```

---

### Task 10: File watcher and dispatcher

**Files:**
- Create: `src/dispatcher/watcher.py`
- Create: `src/dispatcher/dispatcher.py`

- [ ] **Implement `src/dispatcher/watcher.py`**
```python
from __future__ import annotations
from pathlib import Path
from typing import Callable
from watchdog.events import FileSystemEventHandler, FileSystemEvent
from watchdog.observers import Observer


class _Handler(FileSystemEventHandler):
    def __init__(self, callback: Callable[[str, str], None], excluded: set[str]) -> None:
        self._cb = callback
        self._excluded = excluded

    def _excluded_path(self, path: str) -> bool:
        return any(part in self._excluded for part in Path(path).parts)

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory and str(event.src_path).endswith(".md"):
            if not self._excluded_path(event.src_path):
                self._cb(event.src_path, "created")

    def on_modified(self, event: FileSystemEvent) -> None:
        if not event.is_directory and str(event.src_path).endswith(".md"):
            if not self._excluded_path(event.src_path):
                self._cb(event.src_path, "modified")


class VaultWatcher:
    def __init__(self, vault_root: str, excluded: set[str], callback: Callable[[str, str], None]) -> None:
        self.root = vault_root
        self._observer = Observer()
        handler = _Handler(callback, excluded)
        self._observer.schedule(handler, vault_root, recursive=True)

    def start(self) -> None:
        self._observer.start()

    def stop(self) -> None:
        self._observer.stop()
        self._observer.join()
```

- [ ] **Implement `src/dispatcher/dispatcher.py`**
```python
from __future__ import annotations
import asyncio
import logging
from pathlib import Path
from src.config import AppConfig
from src.dispatcher.debounce import DebounceMap
from src.dispatcher.locks import FileLockMap
from src.vault.tools import VaultTools
from src.storage.db import Database
from src.storage.repository import NoteRepo, AgentRunRepo

log = logging.getLogger(__name__)

# Config file path — never dispatched to agents
_CONFIG_REL = ".librarian/config.md"


class Dispatcher:
    def __init__(
        self,
        cfg: AppConfig,
        db: Database,
        tools: VaultTools,
        pipeline_runner,  # PipelineRunner injected to avoid circular import
    ) -> None:
        self._cfg = cfg
        self._db = db
        self._tools = tools
        self._runner = pipeline_runner
        self._debounce = DebounceMap(default_delay=cfg.debounce_standard)
        self._locks = FileLockMap()

    def on_file_event(self, abs_path: str, event_type: str) -> None:
        rel = str(Path(abs_path).relative_to(self._cfg.vault_path))
        if rel == _CONFIG_REL:
            self._schedule_config_reload()
            return
        has_directive = self._tools.has_directive_tags(rel)
        delay = self._cfg.debounce_directive if has_directive else self._cfg.debounce_standard
        self._debounce.schedule(rel, lambda r=rel: self._dispatch(r), delay=delay)

    def _schedule_config_reload(self) -> None:
        self._debounce.schedule(_CONFIG_REL, self._reload_config, delay=0.5)

    def _reload_config(self) -> None:
        try:
            from src.vault_config.loader import VaultConfigLoader
            loader = VaultConfigLoader(self._cfg)
            loader.apply()
            log.info("Config reloaded from .librarian/config.md")
        except Exception as exc:
            log.warning("Config reload failed: %s", exc)

    def _dispatch(self, rel: str) -> None:
        asyncio.get_event_loop().create_task(self._run_pipeline(rel))

    async def _run_pipeline(self, rel: str) -> None:
        async with self._locks.acquire(rel):
            try:
                await self._runner.run(rel)
            except Exception as exc:
                log.exception("Pipeline failed for %s: %s", rel, exc)

    async def reconcile(self) -> None:
        """On startup: queue notes that haven't been fully processed."""
        note_repo = NoteRepo(self._db)
        run_repo = AgentRunRepo(self._db)
        stored_hashes = await note_repo.all_hashes()

        from src.vault.scanner import VaultScanner
        scanner = VaultScanner(self._cfg)
        for meta in scanner.iter_notes():
            stored_hash = stored_hashes.get(meta.path)
            completed = await run_repo.completed_agents(meta.path, meta.content_hash)
            enrolled = set(self._cfg.enrolled_agents) - {"scaffolder", "daily_brief", "weekly_review"}
            if meta.content_hash != stored_hash or not enrolled.issubset(completed):
                log.info("Reconcile: queuing %s", meta.path)
                self._debounce.schedule(meta.path, lambda r=meta.path: self._dispatch(r), delay=0.1)
```

- [ ] **Run existing tests (smoke check)**
```bash
uv run pytest tests/ -v
```
Expected: all existing tests still pass.

- [ ] **Commit**
```bash
git add src/dispatcher/watcher.py src/dispatcher/dispatcher.py
git commit -m "feat: add file watcher and dispatcher with debounce and reconciliation"
```

---

## Phase 6 — Agent Foundation & Pipeline

### Task 11: VaultState and pipeline builder

**Files:**
- Create: `src/agents/state.py`
- Create: `src/pipeline/builder.py`
- Create: `src/pipeline/runner.py`
- Create: `tests/test_pipeline.py`

- [ ] **Write failing tests**
```python
# tests/test_pipeline.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.agents.state import VaultState, make_state
from src.pipeline.builder import build_pipeline


def test_make_state_defaults():
    state = make_state("Projects/Test.md", "# Test\n\nContent", {}, "project")
    assert state["note_path"] == "Projects/Test.md"
    assert state["note_type"] == "project"
    assert state["changes"] == []
    assert state["directives"] == []


def test_build_pipeline_returns_compiled_graph():
    # Use a minimal agent set; nodes are no-ops here
    from langgraph.graph import END
    pipeline = build_pipeline(note_type="project", enrolled=["formatter"])
    assert pipeline is not None
```

- [ ] **Implement `src/agents/state.py`**
```python
from __future__ import annotations
from dataclasses import dataclass
from typing import TypedDict, Annotated
import operator


@dataclass
class Directive:
    tag: str    # scaffold | fill | context
    prompt: str
    start: int  # char offset in original content
    end: int    # char offset in original content


class VaultState(TypedDict):
    note_path: str
    note_content: str
    frontmatter: dict
    note_type: str | None
    directives: list[Directive]
    action_items: list[str]
    related_notes: list[str]
    dispatch_hash: str           # content hash at dispatch time for conflict detection
    changes: Annotated[list[str], operator.add]  # accumulated by all nodes


def make_state(
    note_path: str,
    note_content: str,
    frontmatter: dict,
    note_type: str | None = None,
    dispatch_hash: str = "",
) -> VaultState:
    return VaultState(
        note_path=note_path,
        note_content=note_content,
        frontmatter=frontmatter,
        note_type=note_type,
        directives=[],
        action_items=[],
        related_notes=[],
        dispatch_hash=dispatch_hash,
        changes=[],
    )
```

- [ ] **Implement `src/pipeline/builder.py`**
```python
from __future__ import annotations
from langgraph.graph import StateGraph, END
from src.agents.state import VaultState

# Registry maps agent name → node function factory
# Each factory receives (llm, tools, vector_store, cfg) and returns a node fn
_AGENT_REGISTRY: dict[str, str] = {
    "librarian": "src.agents.librarian:librarian_node",
    "formatter": "src.agents.formatter:formatter_node",
    "meeting_enricher": "src.agents.meeting_enricher:meeting_enricher_node",
    "linker": "src.agents.linker:linker_node",
    "moc_maintainer": "src.agents.moc_maintainer:moc_maintainer_node",
    "inline_directive": "src.agents.inline_directive:inline_directive_node",
}

# Fixed pipeline order for file-event agents
PIPELINE_ORDER = [
    "librarian",
    "formatter",
    "inline_directive",
    "meeting_enricher",
    "linker",
    "moc_maintainer",
]


def _import_node(dotpath: str):
    module, name = dotpath.rsplit(":", 1)
    import importlib
    mod = importlib.import_module(module)
    return getattr(mod, name)


def build_pipeline(note_type: str | None, enrolled: list[str], context: dict | None = None):
    """
    Build and compile a LangGraph pipeline for the given note type.
    context = {llm, tools, vector_store, cfg} injected into nodes.
    """
    ctx = context or {}
    active = [a for a in PIPELINE_ORDER if a in enrolled]

    # meeting_enricher only runs for meeting notes
    if note_type != "meeting" and "meeting_enricher" in active:
        active.remove("meeting_enricher")

    graph = StateGraph(VaultState)

    for name in active:
        node_fn = _import_node(_AGENT_REGISTRY[name])
        # Pass context via closure
        def make_node(fn, c=ctx):
            def node(state: VaultState) -> dict:
                return fn(state, **c)
            node.__name__ = fn.__name__
            return node
        graph.add_node(name, make_node(node_fn))

    if not active:
        graph.add_node("noop", lambda s: {})
        graph.set_entry_point("noop")
        graph.add_edge("noop", END)
        return graph.compile()

    graph.set_entry_point(active[0])
    for i in range(len(active) - 1):
        graph.add_edge(active[i], active[i + 1])
    graph.add_edge(active[-1], END)

    # Conditional: linker only runs if content changed significantly (>10% word delta)
    # This is handled inside linker_node via early return

    return graph.compile()
```

- [ ] **Implement `src/pipeline/runner.py`**
```python
from __future__ import annotations
import hashlib
import logging
from pathlib import Path
from src.config import AppConfig
from src.storage.db import Database
from src.storage.models import NoteRecord, AgentRunRecord
from src.storage.repository import NoteRepo, AgentRunRepo, AuditLogRepo
from src.vault.parser import parse_note
from src.vault.tools import VaultTools, ConflictError
from src.agents.state import make_state

log = logging.getLogger(__name__)


class PipelineRunner:
    def __init__(self, cfg: AppConfig, db: Database, tools: VaultTools, llm, vector_store) -> None:
        self._cfg = cfg
        self._db = db
        self._tools = tools
        self._llm = llm
        self._vector_store = vector_store

    async def run(self, rel: str) -> None:
        abs_path = str(Path(self._cfg.vault_path) / rel)
        if not Path(abs_path).exists():
            return

        try:
            meta = parse_note(abs_path, self._cfg.vault_path)
        except Exception as exc:
            log.warning("Could not parse %s: %s", rel, exc)
            return

        dispatch_hash = meta.content_hash
        run_repo = AgentRunRepo(self._db)
        note_repo = NoteRepo(self._db)
        audit_repo = AuditLogRepo(self._db)

        # Upsert note record
        await note_repo.save(NoteRecord(
            path=meta.path, title=meta.title, note_type=meta.note_type,
            tags=str(meta.tags), content_hash=meta.content_hash,
            word_count=meta.word_count,
        ))

        enrolled = self._cfg.enrolled_agents
        completed = await run_repo.completed_agents(rel, dispatch_hash)
        needed = [a for a in enrolled if a not in completed and a in self._pipeline_agents()]

        if not needed:
            log.debug("All agents already ran for %s@%s", rel, dispatch_hash[:8])
            return

        context = {
            "llm": self._llm,
            "tools": self._tools,
            "vector_store": self._vector_store,
            "cfg": self._cfg,
            "db": self._db,
        }

        from src.pipeline.builder import build_pipeline
        pipeline = build_pipeline(meta.note_type, needed, context)

        state = make_state(
            note_path=meta.path,
            note_content=meta.raw_content,
            frontmatter=meta.frontmatter,
            note_type=meta.note_type,
            dispatch_hash=dispatch_hash,
        )

        try:
            result = await pipeline.ainvoke(state)
        except ConflictError as exc:
            log.warning("Conflict on %s — requeuing: %s", rel, exc)
            return  # dispatcher will re-fire when file watcher picks up new version

        # Record completed agents
        for agent in needed:
            await run_repo.save(AgentRunRecord(
                note_path=rel, content_hash=dispatch_hash, agent=agent
            ))
            for change in result.get("changes", []):
                await audit_repo.write(agent, "change", change, rel)

        # Commit to git
        if result.get("changes"):
            self._tools.git_commit(
                f"[librarian] {rel}: {', '.join(result['changes'][:3])}"
            )

    def _pipeline_agents(self) -> list[str]:
        from src.pipeline.builder import PIPELINE_ORDER
        return PIPELINE_ORDER


async def reconcile_all(cfg: AppConfig, force: bool = False) -> None:
    from src.storage.db import build_db
    from src.llm.factory import build_llm, build_embedder
    from src.vector.store import VectorStore
    db = build_db(cfg)
    await db.initialize()
    llm = build_llm(cfg)
    embedder = build_embedder(cfg)
    vector_store = VectorStore(cfg.vault_path, embedder)
    tools = VaultTools(cfg.vault_path)
    runner = PipelineRunner(cfg, db, tools, llm, vector_store)
    from src.vault.scanner import VaultScanner
    scanner = VaultScanner(cfg)
    for meta in scanner.iter_notes():
        if force:
            from src.storage.repository import AgentRunRepo
            # clear runs so all agents re-run
            pass
        await runner.run(meta.path)
    await db.close()
```

- [ ] **Run tests**
```bash
uv run pytest tests/test_pipeline.py -v
```
Expected: 2 passed.

- [ ] **Commit**
```bash
git add src/agents/state.py src/pipeline/ tests/test_pipeline.py
git commit -m "feat: add VaultState, pipeline builder, and PipelineRunner"
```

---

## Phase 7 — Core Agents

### Task 12: Librarian agent

**Files:**
- Create: `src/agents/librarian.py`
- Create: `tests/test_agents/test_librarian.py`

- [ ] **Write failing tests**
```python
# tests/test_agents/test_librarian.py
import pytest
from unittest.mock import MagicMock, patch
from src.agents.state import make_state
from src.agents.librarian import librarian_node


@pytest.fixture
def mock_llm():
    from pydantic import BaseModel
    class FilingDecision(BaseModel):
        note_type: str
        target_folder: str
        reasoning: str
    llm = MagicMock()
    llm.with_structured_output.return_value.invoke.return_value = FilingDecision(
        note_type="meeting",
        target_folder="Meetings",
        reasoning="Contains meeting content",
    )
    return llm


@pytest.fixture
def mock_tools(tmp_path):
    from src.vault.tools import VaultTools
    (tmp_path / "Meetings").mkdir()
    tools = VaultTools(str(tmp_path))
    return tools


@pytest.fixture
def full_auto_cfg():
    from src.config import AppConfig
    cfg = AppConfig(
        llm_provider="copilot", llm_model="gpt-4o",
        llm_api_key="x", vault_path="/tmp", secret="s",
        autonomy_overrides={"librarian": "full"},
    )
    return cfg


def test_librarian_classifies_note(mock_llm, mock_tools, full_auto_cfg, tmp_path):
    (tmp_path / "standup.md").write_text("# Standup\n\nQuick meeting notes.")
    full_auto_cfg.vault_path = str(tmp_path)
    mock_tools = __import__("src.vault.tools", fromlist=["VaultTools"]).VaultTools(str(tmp_path))
    state = make_state("standup.md", "# Standup\n\nQuick meeting notes.", {})
    result = librarian_node(state, llm=mock_llm, tools=mock_tools, cfg=full_auto_cfg)
    assert result["note_type"] == "meeting"
    assert any("Meetings" in c for c in result["changes"])


def test_librarian_supervised_proposes(mock_llm, mock_tools, tmp_path):
    from src.config import AppConfig
    cfg = AppConfig(
        llm_provider="copilot", llm_model="gpt-4o",
        llm_api_key="x", vault_path=str(tmp_path), secret="s",
        autonomy_default="supervised",
        autonomy_overrides={},
    )
    (tmp_path / "standup.md").write_text("# Standup\n\nNotes.")
    state = make_state("standup.md", "# Standup\n\nNotes.", {})
    result = librarian_node(state, llm=mock_llm, tools=mock_tools, cfg=cfg)
    assert result["note_type"] == "meeting"
    assert any("Proposed" in c for c in result["changes"])
```

- [ ] **Run to confirm failure**
```bash
uv run pytest tests/test_agents/test_librarian.py -v
```
Expected: `ModuleNotFoundError`

- [ ] **Implement `src/agents/librarian.py`**
```python
from __future__ import annotations
import logging
from pathlib import Path
from pydantic import BaseModel
from langchain_core.messages import SystemMessage, HumanMessage
from src.agents.state import VaultState
from src.config import AppConfig
from src.vault.tools import VaultTools

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are the Librarian agent for an Obsidian vault. Your job is to:
1. Classify the note type (meeting, project, jira, tech_note, career, reference, personal)
2. Decide which folder the note belongs in

Vault folder taxonomy (use these exact names):
- Projects/ — active work with deliverables
- Career/ — interview prep, retrospectives, STAR stories
- Meetings/ — any meeting, desk check, sprint demo
- Jira/ — ticket notes matching AICOE-* or similar patterns
- Tech Notes/ — reference material, how-tos, technical docs
- Reference/ — glossary, definitions, reference material
- Personal/ — anything non-work related

Rules:
- Notes already in the correct folder: set target_folder to their current folder
- Notes at vault root: always assign a folder
- Prefer Projects/ over Career/ for AI platform work
"""


class FilingDecision(BaseModel):
    note_type: str
    target_folder: str
    reasoning: str


def librarian_node(state: VaultState, llm, tools: VaultTools, cfg: AppConfig, **_) -> dict:
    instructions = cfg.get_agent_instructions("librarian")
    system = _SYSTEM_PROMPT + (f"\n\nAdditional instructions:\n{instructions}" if instructions else "")

    structured = llm.with_structured_output(FilingDecision)
    try:
        decision: FilingDecision = structured.invoke([
            SystemMessage(content=system),
            HumanMessage(content=f"Note path: {state['note_path']}\n\n{state['note_content'][:2000]}"),
        ])
    except Exception as exc:
        log.warning("Librarian LLM call failed for %s: %s", state["note_path"], exc)
        return {"changes": [f"Librarian skipped: {exc}"]}

    current_folder = str(Path(state["note_path"]).parent)
    target = decision.target_folder.rstrip("/")

    changes = [f"Classified as {decision.note_type}"]

    if current_folder != target:
        filename = Path(state["note_path"]).name
        dst_rel = f"{target}/{filename}"
        if cfg.get_autonomy("librarian") == "full":
            try:
                tools.move_note(state["note_path"], dst_rel)
                changes.append(f"Moved to {target}/")
            except Exception as exc:
                log.warning("Move failed: %s", exc)
                changes.append(f"Move to {target}/ failed: {exc}")
        else:
            _propose_move(tools, state["note_path"], dst_rel, cfg)
            changes.append(f"Proposed: move to {target}/")

    return {"note_type": decision.note_type, "changes": changes}


def _propose_move(tools: VaultTools, src: str, dst: str, cfg: AppConfig) -> None:
    from src.autonomy.inbox import LibrarianInbox
    inbox = LibrarianInbox(cfg, tools)
    inbox.propose(f"Move `{src}` → `{dst}`")
```

- [ ] **Run tests**
```bash
uv run pytest tests/test_agents/test_librarian.py -v
```
Expected: 2 passed.

- [ ] **Commit**
```bash
git add src/agents/librarian.py tests/test_agents/test_librarian.py
git commit -m "feat: add Librarian agent with full/supervised autonomy"
```

---

### Task 13: Formatter agent

**Files:**
- Create: `src/agents/formatter.py`
- Create: `tests/test_agents/test_formatter.py`

- [ ] **Write failing tests**
```python
# tests/test_agents/test_formatter.py
import pytest
from unittest.mock import MagicMock
from src.agents.state import make_state
from src.agents.formatter import formatter_node


@pytest.fixture
def mock_llm():
    from pydantic import BaseModel
    class FrontmatterFix(BaseModel):
        fields_to_add: dict
        reasoning: str
    llm = MagicMock()
    llm.with_structured_output.return_value.invoke.return_value = FrontmatterFix(
        fields_to_add={"created": "2026-06-08", "modified": "2026-06-08"},
        reasoning="Missing date fields",
    )
    return llm


def test_formatter_adds_missing_fields(mock_llm, tmp_path):
    from src.config import AppConfig
    from src.vault.tools import VaultTools
    note = tmp_path / "Projects" / "Test.md"
    note.parent.mkdir()
    note.write_text("---\ntags:\n  - work\n---\n# Test\n\nBody.")
    cfg = AppConfig(
        llm_provider="copilot", llm_model="gpt-4o",
        llm_api_key="x", vault_path=str(tmp_path), secret="s",
        autonomy_overrides={"formatter": "full"},
    )
    tools = VaultTools(str(tmp_path))
    state = make_state("Projects/Test.md", note.read_text(), {"tags": ["work"]}, "project")
    result = formatter_node(state, llm=mock_llm, tools=tools, cfg=cfg)
    assert any("Formatter" in c for c in result["changes"])
    updated = (tmp_path / "Projects" / "Test.md").read_text()
    assert "created" in updated


def test_formatter_preserves_dataview_blocks(mock_llm, tmp_path):
    from src.config import AppConfig
    from src.vault.tools import VaultTools
    content = "---\ntags: []\n---\n# Note\n\n```dataview\nTABLE status FROM \"Jira\"\n```\n"
    note = tmp_path / "note.md"
    note.write_text(content)
    cfg = AppConfig(
        llm_provider="copilot", llm_model="gpt-4o",
        llm_api_key="x", vault_path=str(tmp_path), secret="s",
        autonomy_overrides={"formatter": "full"},
    )
    tools = VaultTools(str(tmp_path))
    state = make_state("note.md", content, {})
    result = formatter_node(state, llm=mock_llm, tools=tools, cfg=cfg)
    updated = note.read_text()
    assert "```dataview" in updated  # dataview block preserved
```

- [ ] **Implement `src/agents/formatter.py`**
```python
from __future__ import annotations
import logging
import re
from datetime import date
from pydantic import BaseModel
from langchain_core.messages import SystemMessage, HumanMessage
from src.agents.state import VaultState
from src.config import AppConfig
from src.vault.tools import VaultTools

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are the Formatter agent for an Obsidian vault. Audit the note's frontmatter and suggest missing or incorrect fields.

Rules:
- Never modify content inside ```dataview ... ``` blocks
- Always suggest `created` and `modified` dates if missing (use today's date: {today})
- Normalize tag casing to lowercase-hyphenated
- For meeting notes: ensure `date` field exists
- Only suggest fields that are genuinely missing or wrong
- Return an empty fields_to_add dict if nothing needs fixing
"""


class FrontmatterFix(BaseModel):
    fields_to_add: dict
    reasoning: str


def _strip_dataview(content: str) -> str:
    return re.sub(r"```dataview.*?```", "```dataview[preserved]```", content, flags=re.DOTALL)


def formatter_node(state: VaultState, llm, tools: VaultTools, cfg: AppConfig, **_) -> dict:
    instructions = cfg.get_agent_instructions("formatter")
    today = date.today().isoformat()
    system = _SYSTEM_PROMPT.format(today=today)
    if instructions:
        system += f"\n\nAdditional instructions:\n{instructions}"

    safe_content = _strip_dataview(state["note_content"])
    structured = llm.with_structured_output(FrontmatterFix)
    try:
        fix: FrontmatterFix = structured.invoke([
            SystemMessage(content=system),
            HumanMessage(content=f"Note path: {state['note_path']}\nFrontmatter: {state['frontmatter']}\n\n{safe_content[:1500]}"),
        ])
    except Exception as exc:
        log.warning("Formatter LLM failed for %s: %s", state["note_path"], exc)
        return {"changes": [f"Formatter skipped: {exc}"]}

    if not fix.fields_to_add:
        return {"changes": []}

    if cfg.get_autonomy("formatter") == "full":
        try:
            tools.update_frontmatter(state["note_path"], fix.fields_to_add)
            return {"changes": [f"Formatter: added {list(fix.fields_to_add.keys())}"]}
        except Exception as exc:
            log.warning("Formatter write failed: %s", exc)
            return {"changes": [f"Formatter write failed: {exc}"]}
    else:
        from src.autonomy.inbox import LibrarianInbox
        inbox = LibrarianInbox(cfg, tools)
        inbox.propose(f"Update frontmatter on `{state['note_path']}`: add {fix.fields_to_add}")
        return {"changes": [f"Formatter: proposed frontmatter update for {state['note_path']}"]}
```

- [ ] **Run tests**
```bash
uv run pytest tests/test_agents/test_formatter.py -v
```
Expected: 2 passed.

- [ ] **Commit**
```bash
git add src/agents/formatter.py tests/test_agents/test_formatter.py
git commit -m "feat: add Formatter agent with dataview preservation"
```

---

### Task 14: Remaining pipeline agents

**Files:**
- Create: `src/agents/meeting_enricher.py`
- Create: `src/agents/linker.py`
- Create: `src/agents/moc_maintainer.py`
- Create: `src/agents/inline_directive.py`
- Create: `src/agents/scaffolder.py`
- Create: `tests/test_agents/test_meeting_enricher.py`

- [ ] **Implement `src/agents/meeting_enricher.py`**
```python
from __future__ import annotations
import logging
import re
from datetime import date
from pydantic import BaseModel
from langchain_core.messages import SystemMessage, HumanMessage
from src.agents.state import VaultState
from src.config import AppConfig
from src.vault.tools import VaultTools

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are the Meeting Enricher agent. Extract action items from this meeting note and identify the linked project.

Return action items as plain strings (no markdown). Each is a concrete task someone needs to do.
If no project is clearly referenced, return an empty linked_project string.
If no action items exist, return an empty list.
"""


class MeetingAnalysis(BaseModel):
    action_items: list[str]
    linked_project: str
    missing_fields: dict  # e.g. {"date": "2026-06-08"} if date frontmatter missing


def meeting_enricher_node(state: VaultState, llm, tools: VaultTools, cfg: AppConfig, db=None, **_) -> dict:
    if state.get("note_type") != "meeting":
        return {"changes": []}

    instructions = cfg.get_agent_instructions("meeting_enricher")
    system = _SYSTEM_PROMPT + (f"\n\n{instructions}" if instructions else "")

    structured = llm.with_structured_output(MeetingAnalysis)
    try:
        analysis: MeetingAnalysis = structured.invoke([
            SystemMessage(content=system),
            HumanMessage(content=state["note_content"][:2000]),
        ])
    except Exception as exc:
        log.warning("MeetingEnricher failed: %s", exc)
        return {"changes": [f"MeetingEnricher skipped: {exc}"]}

    changes = []

    # Enforce missing frontmatter fields
    if analysis.missing_fields and cfg.get_autonomy("meeting_enricher") == "full":
        tools.update_frontmatter(state["note_path"], analysis.missing_fields)
        changes.append(f"Meeting: added {list(analysis.missing_fields.keys())}")

    # Append action items to linked project note
    if analysis.action_items and analysis.linked_project:
        items_md = "\n".join(
            f"- [ ] {item} ([[{state['note_path']}]])" for item in analysis.action_items
        )
        project_rel = f"Projects/{analysis.linked_project}.md"
        try:
            existing = tools.read_note(project_rel)
            if "## Action Items" not in existing:
                updated = existing.rstrip() + f"\n\n## Action Items\n{items_md}\n"
            else:
                updated = existing.rstrip() + f"\n{items_md}\n"
            if cfg.get_autonomy("meeting_enricher") == "full":
                tools.write_note(project_rel, updated)
                changes.append(f"Meeting: appended {len(analysis.action_items)} action items to {project_rel}")
        except FileNotFoundError:
            log.debug("Linked project note not found: %s", project_rel)

    return {"action_items": analysis.action_items, "changes": changes}
```

- [ ] **Implement `src/agents/linker.py`**
```python
from __future__ import annotations
import logging
import re
from pydantic import BaseModel
from langchain_core.messages import SystemMessage, HumanMessage
from src.agents.state import VaultState
from src.config import AppConfig
from src.vault.tools import VaultTools

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are the Linker agent. Given a note and a list of potentially related notes, 
decide which ones are genuinely related and should appear in a Related section.

Return only paths that are meaningfully related (not just superficially). Max 5 results.
Exclude the note itself from results.
"""


class LinkDecision(BaseModel):
    related_paths: list[str]
    reasoning: str


def linker_node(state: VaultState, llm, tools: VaultTools, vector_store, cfg: AppConfig, **_) -> dict:
    # Skip if content hasn't changed enough (word count heuristic handled by runner)
    instructions = cfg.get_agent_instructions("linker")

    try:
        candidates = vector_store.search_similar(state["note_content"], k=8)
        candidates = [c for c in candidates if c != state["note_path"]]
    except Exception as exc:
        log.warning("Vector search failed: %s", exc)
        return {"changes": []}

    if not candidates:
        return {"changes": []}

    structured = llm.with_structured_output(LinkDecision)
    try:
        decision: LinkDecision = structured.invoke([
            SystemMessage(content=_SYSTEM_PROMPT + (f"\n\n{cfg.get_agent_instructions('linker')}" if instructions else "")),
            HumanMessage(content=f"Note: {state['note_path']}\n\nCandidates:\n" + "\n".join(candidates)),
        ])
    except Exception as exc:
        log.warning("Linker LLM failed: %s", exc)
        return {"changes": []}

    if not decision.related_paths:
        return {"related_notes": [], "changes": []}

    links = " · ".join(f"[[{p.removesuffix('.md')}]]" for p in decision.related_paths)
    content = state["note_content"]

    # Replace or add Related section
    related_section = f"\n\n## Related\n{links}\n"
    if "## Related" in content:
        content = re.sub(r"\n## Related\n.*?(?=\n##|\Z)", related_section, content, flags=re.DOTALL)
    else:
        content = content.rstrip() + related_section

    if cfg.get_autonomy("linker") == "full":
        tools.write_note(state["note_path"], content, dispatch_hash=state.get("dispatch_hash"))
        changes = [f"Linker: added {len(decision.related_paths)} backlinks"]
    else:
        from src.autonomy.inbox import LibrarianInbox
        LibrarianInbox(cfg, tools).propose(f"Add Related section to `{state['note_path']}`")
        changes = [f"Linker: proposed {len(decision.related_paths)} backlinks"]

    # Upsert embedding
    try:
        vector_store.upsert(state["note_path"], state["note_content"])
    except Exception as exc:
        log.debug("Vector upsert failed: %s", exc)

    return {"related_notes": decision.related_paths, "changes": changes}
```

- [ ] **Implement `src/agents/moc_maintainer.py`**
```python
from __future__ import annotations
import logging
import re
from pathlib import Path
from pydantic import BaseModel
from langchain_core.messages import SystemMessage, HumanMessage
from src.agents.state import VaultState
from src.config import AppConfig
from src.vault.tools import VaultTools

log = logging.getLogger(__name__)

# Which MOC to update for each folder
_FOLDER_MOC: dict[str, str] = {
    "Projects": "Work MOC.md",
    "Jira": "Work MOC.md",
    "Meetings": "Work MOC.md",
    "Tech Notes": "Work MOC.md",
}


def moc_maintainer_node(state: VaultState, tools: VaultTools, cfg: AppConfig, **_) -> dict:
    folder = str(Path(state["note_path"]).parent)
    moc_rel = _FOLDER_MOC.get(folder)
    if not moc_rel:
        return {"changes": []}

    title = Path(state["note_path"]).stem
    link = f"[[{title}]]"

    try:
        moc_content = tools.read_note(moc_rel)
    except FileNotFoundError:
        return {"changes": [f"MOC not found: {moc_rel}"]}

    # Skip if already in MOC
    if link in moc_content:
        # Check if Jira status needs updating
        if folder == "Jira":
            status = state["frontmatter"].get("status", "")
            if status:
                moc_content = _update_jira_status(moc_content, title, status)
                if cfg.get_autonomy("moc_maintainer") == "full":
                    tools.write_note(moc_rel, moc_content)
                    return {"changes": [f"MOC: updated {title} status → {status}"]}
        return {"changes": []}

    # Add entry to appropriate section
    section_map = {
        "Projects": "## 🏗 Active Projects",
        "Jira": "## 🎫 Jira Tickets",
        "Meetings": "## 📋 Meetings",
        "Tech Notes": "## 📚 Tech Notes",
    }
    section = section_map.get(folder, "## Notes")
    entry = f"| {link} | |\n" if folder in ("Projects", "Jira") else f"- {link}\n"
    updated = _insert_into_section(moc_content, section, entry)

    if cfg.get_autonomy("moc_maintainer") == "full":
        tools.write_note(moc_rel, updated)
        return {"changes": [f"MOC: added {title} to {section}"]}
    else:
        from src.autonomy.inbox import LibrarianInbox
        LibrarianInbox(cfg, tools).propose(f"Add `{title}` to {moc_rel} under {section}")
        return {"changes": [f"MOC: proposed adding {title}"]}


def _insert_into_section(content: str, section: str, entry: str) -> str:
    if section not in content:
        return content + f"\n{section}\n\n{entry}"
    parts = content.split(section, 1)
    after = parts[1]
    lines = after.split("\n")
    insert_at = 2  # skip blank line after heading
    lines.insert(insert_at, entry.rstrip())
    return parts[0] + section + "\n".join(lines)


def _update_jira_status(content: str, title: str, status: str) -> str:
    status_icons = {
        "In Progress": "🟡", "Planning": "🔵", "Backlog": "⚪",
        "Blocked": "🔴", "Done": "✅",
    }
    icon = status_icons.get(status, "⬜")
    return re.sub(
        rf"(\| \[\[{re.escape(title)}\]\][^|]*\|[^|]*\|)[^\n]*",
        rf"\1 {icon} {status} |",
        content,
    )
```

- [ ] **Implement `src/agents/inline_directive.py`**
```python
from __future__ import annotations
import logging
import re
from dataclasses import dataclass
from pydantic import BaseModel
from langchain_core.messages import SystemMessage, HumanMessage
from src.agents.state import VaultState, Directive
from src.config import AppConfig
from src.vault.tools import VaultTools

log = logging.getLogger(__name__)

_TAG_RE = re.compile(
    r"<agent-(scaffold|context)>(.*?)</agent-\1>|<agent-fill\s*/>",
    re.DOTALL,
)


def _find_directives(content: str) -> list[Directive]:
    directives = []
    for m in _TAG_RE.finditer(content):
        tag = m.group(1) or "fill"
        prompt = (m.group(2) or "").strip()
        directives.append(Directive(tag=tag, prompt=prompt, start=m.start(), end=m.end()))
    return directives


def inline_directive_node(state: VaultState, llm, tools: VaultTools, vector_store, cfg: AppConfig, **_) -> dict:
    directives = _find_directives(state["note_content"])
    if not directives:
        return {"directives": [], "changes": []}

    content = state["note_content"]
    changes = []
    offset = 0

    for d in directives:
        context_notes = ""
        if d.tag == "context":
            try:
                similar = vector_store.search_similar(d.prompt, k=3)
                context_notes = "\n\n".join(
                    f"From {p}:\n{tools.read_note(p)[:500]}" for p in similar
                )
            except Exception:
                pass

        system = "You are an inline content generator for an Obsidian vault note. Generate concise, well-formatted markdown content based on the user's prompt and surrounding note context. Do not include the prompt itself in your output."
        user_prompt = f"Note: {state['note_path']}\nSurrounding context:\n{content[max(0, d.start+offset-300):d.start+offset]}\n\nDirective ({d.tag}): {d.prompt}"
        if context_notes:
            user_prompt += f"\n\nRelated vault content:\n{context_notes}"

        try:
            response = llm.invoke([SystemMessage(content=system), HumanMessage(content=user_prompt)])
            generated = response.content.strip()
        except Exception as exc:
            log.warning("Inline directive LLM failed: %s", exc)
            continue

        comment = f"<!-- agent-{d.tag}: {d.prompt[:80]} -->\n" if d.prompt else ""
        replacement = comment + generated
        start = d.start + offset
        end = d.end + offset
        content = content[:start] + replacement + content[end:]
        offset += len(replacement) - (d.end - d.start)
        changes.append(f"Inline directive ({d.tag}) resolved")

    if changes:
        tools.write_note(state["note_path"], content, dispatch_hash=state.get("dispatch_hash"))

    return {"directives": directives, "changes": changes}
```

- [ ] **Implement `src/agents/scaffolder.py`**
```python
from __future__ import annotations
import logging
from datetime import date
from pathlib import Path
from langchain_core.messages import SystemMessage, HumanMessage
from src.config import AppConfig
from src.vault.tools import VaultTools

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are the Scaffolder agent. Generate a well-structured Obsidian note stub.

Rules:
- Include YAML frontmatter with tags, type, created, modified
- Follow the template structure if provided
- Pre-fill any fields you can infer from the title and context
- Leave genuinely unknown fields as empty strings or blank bullet points
- Do not add placeholder text like "[Description here]" — use empty fields
"""


def run_scaffolder(
    title: str,
    note_type: str,
    context: str,
    llm,
    tools: VaultTools,
    cfg: AppConfig,
) -> str:
    """Generate a note stub and write it to the vault. Returns the created path."""
    today = date.today().isoformat()

    # Read template if available
    template_content = ""
    try:
        template_rel = f"Templates/{note_type.replace('_', ' ').title()} Template.md"
        template_content = tools.read_note(template_rel)
    except FileNotFoundError:
        pass

    prompt = f"Title: {title}\nType: {note_type}\nDate: {today}"
    if context:
        prompt += f"\nContext: {context}"
    if template_content:
        prompt += f"\n\nTemplate to follow:\n{template_content[:1500]}"

    try:
        response = llm.invoke([
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ])
        content = response.content.strip()
    except Exception as exc:
        log.warning("Scaffolder LLM failed: %s", exc)
        content = f"---\ntitle: {title}\ntype: {note_type}\ncreated: {today}\n---\n# {title}\n"

    # Determine target folder
    folder_map = {
        "meeting": "Meetings", "project": "Projects", "jira": "Jira",
        "tech_note": "Tech Notes", "career": "Career", "reference": "Reference",
    }
    folder = folder_map.get(note_type, "")
    safe_title = title.replace("/", "-").replace(":", "-")
    rel = f"{folder}/{safe_title}.md" if folder else f"{safe_title}.md"

    tools.create_note(rel, content)
    log.info("Scaffolded %s", rel)
    return rel
```

- [ ] **Write and run meeting enricher test**
```python
# tests/test_agents/test_meeting_enricher.py
import pytest
from unittest.mock import MagicMock
from src.agents.state import make_state
from src.agents.meeting_enricher import meeting_enricher_node


@pytest.fixture
def mock_llm():
    from src.agents.meeting_enricher import MeetingAnalysis
    llm = MagicMock()
    llm.with_structured_output.return_value.invoke.return_value = MeetingAnalysis(
        action_items=["Set up local topology", "Write runbook"],
        linked_project="Agent Platform",
        missing_fields={"date": "2026-06-08"},
    )
    return llm


def test_meeting_enricher_skips_non_meeting(mock_llm, tmp_path):
    from src.config import AppConfig
    from src.vault.tools import VaultTools
    cfg = AppConfig(
        llm_provider="copilot", llm_model="gpt-4o",
        llm_api_key="x", vault_path=str(tmp_path), secret="s",
    )
    state = make_state("Projects/Alpha.md", "# Alpha", {}, note_type="project")
    result = meeting_enricher_node(state, llm=mock_llm, tools=VaultTools(str(tmp_path)), cfg=cfg)
    assert result["changes"] == []
    mock_llm.with_structured_output.assert_not_called()


def test_meeting_enricher_extracts_action_items(mock_llm, tmp_path):
    from src.config import AppConfig
    from src.vault.tools import VaultTools
    (tmp_path / "Projects").mkdir()
    (tmp_path / "Projects" / "Agent Platform.md").write_text("# Agent Platform\n\n## Work\n")
    cfg = AppConfig(
        llm_provider="copilot", llm_model="gpt-4o",
        llm_api_key="x", vault_path=str(tmp_path), secret="s",
        autonomy_overrides={"meeting_enricher": "full"},
    )
    state = make_state("Meetings/Standup.md", "# Standup\n\nDiscussed agent platform setup.", {}, note_type="meeting")
    result = meeting_enricher_node(state, llm=mock_llm, tools=VaultTools(str(tmp_path)), cfg=cfg)
    assert "Set up local topology" in result["action_items"]
    project_content = (tmp_path / "Projects" / "Agent Platform.md").read_text()
    assert "Set up local topology" in project_content
```

```bash
uv run pytest tests/test_agents/ -v
```
Expected: all pass.

- [ ] **Commit**
```bash
git add src/agents/ tests/test_agents/
git commit -m "feat: add Meeting Enricher, Linker, MOC Maintainer, Inline Directive, Scaffolder agents"
```

---

## Phase 8 — Autonomy Inbox

### Task 15: Librarian Inbox

**Files:**
- Create: `src/autonomy/__init__.py`
- Create: `src/autonomy/inbox.py`
- Create: `tests/test_autonomy.py`

- [ ] **Write failing tests**
```python
# tests/test_autonomy.py
import pytest
from pathlib import Path
from src.autonomy.inbox import LibrarianInbox
from src.config import AppConfig
from src.vault.tools import VaultTools


@pytest.fixture
def setup(tmp_path):
    (tmp_path / ".librarian").mkdir()
    cfg = AppConfig(
        llm_provider="copilot", llm_model="gpt-4o",
        llm_api_key="x", vault_path=str(tmp_path), secret="s",
    )
    tools = VaultTools(str(tmp_path))
    return cfg, tools, tmp_path


def test_propose_creates_inbox(setup):
    cfg, tools, tmp_path = setup
    inbox = LibrarianInbox(cfg, tools)
    inbox.propose("Move `orphan.md` → `Personal/`")
    content = (tmp_path / ".librarian" / "Inbox.md").read_text()
    assert "Move `orphan.md`" in content
    assert "- [ ]" in content


def test_propose_appends_to_existing_inbox(setup):
    cfg, tools, tmp_path = setup
    inbox_path = tmp_path / ".librarian" / "Inbox.md"
    inbox_path.write_text("# Librarian Inbox\n\n- [ ] Existing item\n")
    inbox = LibrarianInbox(cfg, tools)
    inbox.propose("New item")
    content = inbox_path.read_text()
    assert "Existing item" in content
    assert "New item" in content


def test_execute_checked_items(setup):
    cfg, tools, tmp_path = setup
    (tmp_path / "orphan.md").write_text("# Orphan")
    (tmp_path / "Personal").mkdir()
    inbox_path = tmp_path / ".librarian" / "Inbox.md"
    inbox_path.write_text("# Librarian Inbox\n\n- [x] Move `orphan.md` → `Personal/orphan.md`\n- [ ] Another item\n")
    inbox = LibrarianInbox(cfg, tools)
    executed = inbox.execute_checked()
    assert len(executed) == 1
    content = inbox_path.read_text()
    assert "✅ Executed" in content
    assert "- [ ] Another item" in content
```

- [ ] **Implement `src/autonomy/inbox.py`**
```python
from __future__ import annotations
import logging
import re
from datetime import date
from pathlib import Path
from src.config import AppConfig
from src.vault.tools import VaultTools

log = logging.getLogger(__name__)

_INBOX_REL = ".librarian/Inbox.md"
_CHECKED_RE = re.compile(r"^- \[x\] (.+)$", re.MULTILINE)
_MOVE_RE = re.compile(r"Move `(.+?)` → `(.+?)`")


class LibrarianInbox:
    def __init__(self, cfg: AppConfig, tools: VaultTools) -> None:
        self._cfg = cfg
        self._tools = tools

    def _read(self) -> str:
        try:
            return self._tools.read_note(_INBOX_REL)
        except FileNotFoundError:
            return "# Librarian Inbox\n\n<!-- Check items to execute, then save -->\n\n"

    def _write(self, content: str) -> None:
        self._tools.create_note(_INBOX_REL, content)

    def propose(self, action: str) -> None:
        content = self._read()
        content = content.rstrip() + f"\n- [ ] {action}\n"
        self._write(content)

    def execute_checked(self) -> list[str]:
        content = self._read()
        executed = []
        today = date.today().isoformat()

        def _execute_and_mark(m: re.Match) -> str:
            item = m.group(1)
            success = self._try_execute(item)
            if success:
                executed.append(item)
                return f"- ✅ Executed {today} — {item}"
            return m.group(0)  # leave unchanged if execution failed

        updated = _CHECKED_RE.sub(_execute_and_mark, content)
        self._write(updated)
        return executed

    def _try_execute(self, item: str) -> bool:
        if m := _MOVE_RE.search(item):
            src, dst = m.group(1), m.group(2)
            try:
                self._tools.move_note(src, dst)
                log.info("Inbox executed move: %s → %s", src, dst)
                return True
            except Exception as exc:
                log.warning("Inbox move failed: %s", exc)
                return False
        log.info("Inbox item not auto-executable (manual): %s", item)
        return False
```

- [ ] **Create `src/autonomy/__init__.py`** (empty)

- [ ] **Run tests**
```bash
uv run pytest tests/test_autonomy.py -v
```
Expected: 3 passed.

- [ ] **Commit**
```bash
git add src/autonomy/ tests/test_autonomy.py
git commit -m "feat: add LibrarianInbox for supervised agent proposals"
```

---

## Phase 9 — Vault Config Loader

### Task 16: Vault config file loader

**Files:**
- Create: `src/vault_config/__init__.py`
- Create: `src/vault_config/loader.py`
- Create: `tests/test_vault_config.py`

- [ ] **Write failing tests**
```python
# tests/test_vault_config.py
import pytest
from pathlib import Path
from src.vault_config.loader import VaultConfigLoader
from src.config import AppConfig


@pytest.fixture
def cfg_with_vault(tmp_path):
    (tmp_path / ".librarian").mkdir()
    return AppConfig(
        llm_provider="copilot", llm_model="gpt-4o",
        llm_api_key="x", vault_path=str(tmp_path), secret="s",
    ), tmp_path


def test_loader_reads_frontmatter(cfg_with_vault):
    cfg, vault = cfg_with_vault
    config_file = vault / ".librarian" / "config.md"
    config_file.write_text(
        "---\nautonomy_default: full\nstale_days: 45\n---\n\n## Formatter\n\nAlways add company tag.\n"
    )
    loader = VaultConfigLoader(cfg)
    loader.apply()
    assert cfg.autonomy_default == "full"
    assert cfg.stale_days == 45


def test_loader_reads_agent_instructions(cfg_with_vault):
    cfg, vault = cfg_with_vault
    config_file = vault / ".librarian" / "config.md"
    config_file.write_text(
        "---\n---\n\n## Librarian\n\nPrefer Tech Notes/ for homelab content.\n\n## Formatter\n\nNormalize all dates to ISO 8601.\n"
    )
    loader = VaultConfigLoader(cfg)
    loader.apply()
    assert "homelab" in cfg.get_agent_instructions("librarian")
    assert "ISO 8601" in cfg.get_agent_instructions("formatter")


def test_loader_handles_missing_file_gracefully(cfg_with_vault):
    cfg, vault = cfg_with_vault
    loader = VaultConfigLoader(cfg)
    loader.apply()  # should not raise
```

- [ ] **Implement `src/vault_config/loader.py`**
```python
from __future__ import annotations
import logging
import re
from pathlib import Path
import frontmatter
from src.config import AppConfig

log = logging.getLogger(__name__)

_CONFIG_REL = ".librarian/config.md"
_SECTION_RE = re.compile(r"^##\s+(\w[\w\s]*)\s*$", re.MULTILINE)


class VaultConfigLoader:
    def __init__(self, cfg: AppConfig) -> None:
        self._cfg = cfg
        self._path = Path(cfg.vault_path) / _CONFIG_REL

    def apply(self) -> None:
        if not self._path.exists():
            return
        try:
            text = self._path.read_text(encoding="utf-8")
        except Exception as exc:
            log.warning("Could not read vault config: %s", exc)
            return

        post = frontmatter.loads(text)
        self._apply_frontmatter(dict(post.metadata))
        self._apply_instructions(post.content)

    def _apply_frontmatter(self, fm: dict) -> None:
        settable = {
            "autonomy_default", "stale_days", "debounce_standard",
            "debounce_directive", "auditor_schedule", "daily_brief_schedule",
            "weekly_review_schedule",
        }
        for key, value in fm.items():
            if key in settable:
                setattr(self._cfg, key, value)

        if "agents" in fm and isinstance(fm["agents"], dict):
            agents_cfg = fm["agents"]
            if "autonomy" in agents_cfg:
                self._cfg.autonomy_default = agents_cfg["autonomy"]
            if "overrides" in agents_cfg:
                self._cfg.autonomy_overrides.update(agents_cfg["overrides"])
            if "enabled" in agents_cfg:
                self._cfg.enrolled_agents = agents_cfg["enabled"]

    def _apply_instructions(self, body: str) -> None:
        sections = _SECTION_RE.split(body)
        instructions: dict[str, str] = {}
        # sections alternates: [pre-first-heading, heading1, body1, heading2, body2, ...]
        i = 1
        while i < len(sections) - 1:
            heading = sections[i].strip().lower().replace(" ", "_")
            content = sections[i + 1].strip()
            if content:
                instructions[heading] = content
            i += 2
        self._cfg.update_agent_instructions(instructions)
```

- [ ] **Create `src/vault_config/__init__.py`** (empty)

- [ ] **Run tests**
```bash
uv run pytest tests/test_vault_config.py -v
```
Expected: 3 passed.

- [ ] **Commit**
```bash
git add src/vault_config/ tests/test_vault_config.py
git commit -m "feat: add VaultConfigLoader with hot-reload support"
```

---

## Phase 10 — FastAPI App & Serve Command

### Task 17: FastAPI app factory and serve command wire-up

**Files:**
- Create: `src/api/app.py`
- Create: `tests/test_api.py`

- [ ] **Implement `src/api/app.py`**
```python
from __future__ import annotations
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Header, Depends
from pydantic import BaseModel
from src.config import get_config, AppConfig

log = logging.getLogger(__name__)

_dispatcher = None
_runner = None
_db = None


@asynccontextmanager
async def _lifespan(app: FastAPI):
    global _dispatcher, _runner, _db
    cfg = get_config()

    from src.storage.db import build_db
    from src.llm.factory import build_llm, build_embedder
    from src.vector.store import VectorStore
    from src.vault.tools import VaultTools
    from src.pipeline.runner import PipelineRunner
    from src.dispatcher.dispatcher import Dispatcher
    from src.dispatcher.watcher import VaultWatcher
    from src.vault_config.loader import VaultConfigLoader

    # Load vault config first
    VaultConfigLoader(cfg).apply()

    _db = build_db(cfg)
    await _db.initialize()

    llm = build_llm(cfg)
    embedder = build_embedder(cfg)
    vector_store = VectorStore(cfg.vault_path, embedder)
    tools = VaultTools(cfg.vault_path)

    _runner = PipelineRunner(cfg, _db, tools, llm, vector_store)
    _dispatcher = Dispatcher(cfg, _db, tools, _runner)

    watcher = VaultWatcher(
        cfg.vault_path,
        excluded=set(cfg.vault_excluded_folders),
        callback=_dispatcher.on_file_event,
    )
    watcher.start()
    app.state.watcher = watcher

    await _dispatcher.reconcile()
    log.info("vault-librarian ready — watching %s", cfg.vault_path)

    yield

    watcher.stop()
    await _db.close()
    log.info("vault-librarian stopped")


def create_app(settings: AppConfig | None = None) -> FastAPI:
    app = FastAPI(title="vault-librarian", lifespan=_lifespan)

    def _check_secret(x_librarian_secret: str = Header(default="")):
        cfg = get_config()
        if x_librarian_secret != cfg.secret:
            raise HTTPException(status_code=401, detail="Invalid secret")

    @app.get("/status")
    async def status():
        cfg = get_config()
        return {
            "vault": cfg.vault_path,
            "provider": cfg.llm_provider,
            "enrolled_agents": cfg.enrolled_agents,
            "autonomy_default": cfg.autonomy_default,
        }

    @app.post("/webhook/git", dependencies=[Depends(_check_secret)])
    async def webhook_git():
        if _dispatcher:
            import asyncio
            asyncio.create_task(_dispatcher.reconcile())
        return {"ok": True}

    @app.post("/webhook/jira", dependencies=[Depends(_check_secret)])
    async def webhook_jira(body: dict):
        ticket_id = body.get("ticket_id", "")
        if ticket_id and _runner:
            rel = f"Jira/{ticket_id}.md"
            import asyncio
            asyncio.create_task(_runner.run(rel))
        return {"ok": True}

    class ScaffoldRequest(BaseModel):
        title: str
        note_type: str
        context: str = ""

    @app.post("/trigger/scaffold", dependencies=[Depends(_check_secret)])
    async def trigger_scaffold(req: ScaffoldRequest):
        cfg = get_config()
        from src.llm.factory import build_llm
        from src.vault.tools import VaultTools
        from src.agents.scaffolder import run_scaffolder
        llm = build_llm(cfg)
        tools = VaultTools(cfg.vault_path)
        rel = run_scaffolder(req.title, req.note_type, req.context, llm, tools, cfg)
        return {"created": rel}

    @app.post("/trigger/{agent}", dependencies=[Depends(_check_secret)])
    async def trigger_agent(agent: str, body: dict = {}):
        note_path = body.get("note_path", "")
        if note_path and _runner:
            import asyncio
            asyncio.create_task(_runner.run(note_path))
        return {"ok": True, "agent": agent, "note_path": note_path}

    @app.get("/runs")
    async def runs(path: str = "", limit: int = 20):
        if not _db:
            return {"runs": []}
        from src.storage.repository import AgentRunRepo, AuditLogRepo
        audit_repo = AuditLogRepo(_db)
        entries = await audit_repo.query(since="30d", limit=limit)
        return {"runs": [
            {"agent": e.agent, "action": e.action, "note": e.note_path, "ts": str(e.timestamp)}
            for e in entries
        ]}

    return app
```

- [ ] **Write smoke test**
```python
# tests/test_api.py
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_status_endpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("LIBRARIAN_VAULT_PATH", str(tmp_path))
    monkeypatch.setenv("LIBRARIAN_LLM_API_KEY", "test")
    monkeypatch.setenv("LIBRARIAN_SECRET", "secret")

    # Patch out all heavy initialization
    with patch("src.api.app.build_db") as mock_db, \
         patch("src.api.app.build_llm", return_value=MagicMock()), \
         patch("src.api.app.build_embedder", return_value=MagicMock()), \
         patch("src.api.app.VectorStore", return_value=MagicMock()), \
         patch("src.api.app.VaultTools", return_value=MagicMock()), \
         patch("src.api.app.PipelineRunner", return_value=MagicMock()), \
         patch("src.api.app.Dispatcher", return_value=MagicMock(reconcile=AsyncMock())), \
         patch("src.api.app.VaultWatcher", return_value=MagicMock(start=MagicMock(), stop=MagicMock())), \
         patch("src.api.app.VaultConfigLoader", return_value=MagicMock(apply=MagicMock())):

        db_mock = AsyncMock()
        db_mock.initialize = AsyncMock()
        db_mock.close = AsyncMock()
        mock_db.return_value = db_mock

        from src.api.app import create_app
        from src.config import AppConfig, get_config
        import src.api.app as app_module
        app_module._instance = None  # reset singleton

        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/status")
            assert resp.status_code == 200
            data = resp.json()
            assert "vault" in data
```

- [ ] **Run tests**
```bash
uv run pytest tests/test_api.py -v
```
Expected: 1 passed.

- [ ] **Run full test suite**
```bash
uv run pytest tests/ -v
```
Expected: all tests pass.

- [ ] **Commit**
```bash
git add src/api/ tests/test_api.py
git commit -m "feat: add FastAPI app with lifecycle, webhooks, and trigger endpoints"
```

---

## Final Verification

- [ ] **Lint**
```bash
uv run ruff check src/ tests/
```
Expected: no errors.

- [ ] **Type check**
```bash
uv run mypy src/ --ignore-missing-imports
```
Expected: no errors (or only minor stubs warnings).

- [ ] **Full test suite**
```bash
uv run pytest tests/ -v --tb=short
```
Expected: all tests pass.

- [ ] **CLI smoke test**
```bash
uv run vault-librarian --help
uv run vault-librarian status
```
Expected: help text shown, status prints config (vault path may be empty if no .env).

- [ ] **Tag milestone**
```bash
git tag v0.1.0-core
```

---

## What's next (Plan 2)

The following features are deferred to the Plan 2 implementation:
- **Scheduled agents** — Auditor (quick + full), Daily Brief, Weekly Review, APScheduler jobs
- **Audit trail** — `.librarian/Activity.md` callout log, Rich terminal live feed, Daily Brief agent activity summary
- **MCP server** — Claude Code / Copilot CLI tool use
- **Git commit hook** — `vault-librarian install-hooks`
- **Full `vault-librarian log` implementation** — currently stubs to empty
