from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

from src.api.mcp import build_mcp_server_lazy
from src.config import get_config
from src.dispatcher.dispatcher import Dispatcher
from src.dispatcher.watcher import VaultWatcher
from src.llm.factory import build_embedder, build_llm
from src.pipeline.runner import PipelineRunner
from src.storage.db import build_db
from src.vault.tools import VaultTools
from src.scheduler.jobs import build_scheduler
from src.vault_config.loader import VaultConfigLoader
from src.vector.store import VectorStore

log = logging.getLogger(__name__)

# Module-level refs set during lifespan
_dispatcher = None
_runner = None
_db = None
_scheduler = None


@asynccontextmanager
async def _lifespan(app: FastAPI):
    global _dispatcher, _runner, _db, _scheduler

    cfg = get_config()
    VaultConfigLoader(cfg).apply()

    _db = build_db(cfg)
    await _db.initialize()

    llm = build_llm(cfg)
    embedder = build_embedder(cfg)
    vector_store = VectorStore(cfg.vault_path, embedder)
    tools = VaultTools(cfg.vault_path)

    _runner = PipelineRunner(cfg, _db, tools, llm, vector_store)
    _dispatcher = Dispatcher(cfg, _db, tools, _runner)

    _scheduler = build_scheduler(cfg, _db, tools, llm)
    _scheduler.start()
    log.info("Scheduler started with %d jobs", len(_scheduler.get_jobs()))

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

    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
    watcher.stop()
    await _db.close()
    log.info("vault-librarian stopped")


def _check_secret(x_librarian_secret: str = Header(default="")) -> None:
    cfg = get_config()
    if x_librarian_secret != cfg.secret:
        raise HTTPException(status_code=401, detail="Invalid secret")


def create_app() -> FastAPI:
    app = FastAPI(title="vault-librarian", lifespan=_lifespan)

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
            import asyncio

            asyncio.create_task(_runner.run(f"Jira/{ticket_id}.md"))
        return {"ok": True}

    class ScaffoldRequest(BaseModel):
        title: str
        note_type: str
        context: str = ""

    @app.post("/trigger/scaffold", dependencies=[Depends(_check_secret)])
    async def trigger_scaffold(req: ScaffoldRequest):
        cfg = get_config()
        from src.agents.scaffolder import run_scaffolder
        from src.llm.factory import build_llm
        from src.vault.tools import VaultTools

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
    async def runs(limit: int = 20):
        if not _db:
            return {"runs": []}
        from src.storage.repository import AuditLogRepo

        repo = AuditLogRepo(_db)
        entries = await repo.query(since="30d", limit=limit)
        return {
            "runs": [
                {"agent": e.agent, "action": e.action, "note": e.note_path, "ts": str(e.timestamp)}
                for e in entries
            ]
        }

    mcp_server = build_mcp_server_lazy()
    app.mount("/mcp", mcp_server.streamable_http_app())
    return app
