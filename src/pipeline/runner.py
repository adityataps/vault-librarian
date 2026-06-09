from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from src.agents.state import make_state
from src.audit.activity import ActivityLog
from src.audit.terminal import get_feed
from src.config import AppConfig
from src.storage.db import Database
from src.storage.models import AgentRunRecord, NoteRecord
from src.storage.repository import AgentRunRepo, AuditLogRepo, NoteRepo
from src.vault.parser import parse_note
from src.vault.tools import ConflictError, VaultTools

log = logging.getLogger(__name__)


class PipelineRunner:
    def __init__(
        self,
        cfg: AppConfig,
        db: Database,
        tools: VaultTools,
        llm,
        vector_store,
    ) -> None:
        self._cfg = cfg
        self._db = db
        self._tools = tools
        self._llm = llm
        self._vector_store = vector_store
        self._activity = ActivityLog(cfg, tools)

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
        note_repo = NoteRepo(self._db)
        run_repo = AgentRunRepo(self._db)
        audit_repo = AuditLogRepo(self._db)

        await note_repo.save(
            NoteRecord(
                path=meta.path,
                title=meta.title,
                note_type=meta.note_type,
                tags=str(meta.tags),
                content_hash=meta.content_hash,
                word_count=meta.word_count,
            )
        )

        enrolled = self._cfg.enrolled_agents
        completed = await run_repo.completed_agents(rel, dispatch_hash)
        needed = [a for a in enrolled if a not in completed and a in self._pipeline_agents()]

        if not needed:
            log.debug("All agents complete for %s@%s", rel, dispatch_hash[:8])
            return

        context = {
            "llm": self._llm,
            "tools": self._tools,
            "vector_store": self._vector_store,
            "cfg": self._cfg,
            "db": self._db,
        }

        from src.pipeline.builder import build_pipeline

        pipeline, ran_agents = build_pipeline(meta.note_type, needed, context)
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
            log.warning("Conflict on %s — re-queue on next file event: %s", rel, exc)
            return
        except Exception as exc:
            log.exception("Pipeline error for %s: %s", rel, exc)
            return

        # Only record agents that the pipeline actually included (build_pipeline may
        # exclude e.g. meeting_enricher for non-meeting notes).
        for agent in ran_agents:
            await run_repo.save(
                AgentRunRecord(
                    note_path=rel,
                    content_hash=dispatch_hash,
                    agent=agent,
                )
            )

        changes = result.get("changes", [])
        for change in changes:
            await audit_repo.write("pipeline", "change", change, rel)

        if changes:
            await asyncio.to_thread(
                self._tools.git_commit,
                f"[librarian] {rel}: {'; '.join(changes[:3])}",
            )
            outcome = (
                "proposed" if any("Proposed" in c or "proposed" in c for c in changes)
                else "error" if any("failed" in c.lower() or "skipped" in c.lower() for c in changes)
                else "enriched" if any("backlink" in c.lower() or "action item" in c.lower() for c in changes)
                else "executed"
            )
            self._activity.append(f"pipeline({rel})", changes, outcome)
            get_feed().feed(f"pipeline({rel})", changes, outcome)

    def _pipeline_agents(self) -> list[str]:
        from src.pipeline.builder import PIPELINE_ORDER

        return PIPELINE_ORDER


async def reconcile_all(cfg: AppConfig, force: bool = False) -> None:
    from src.llm.factory import build_embedder, build_llm
    from src.storage.db import build_db
    from src.vector.store import VectorStore

    db = build_db(cfg)
    await db.initialize()
    llm = build_llm(cfg)
    embedder = build_embedder(cfg)
    vector_store = VectorStore(cfg.vault_path, embedder)
    tools = VaultTools(cfg.vault_path)
    runner = PipelineRunner(cfg, db, tools, llm, vector_store)
    from src.vault.scanner import VaultScanner

    for meta in VaultScanner(cfg).iter_notes():
        await runner.run(meta.path)
    await db.close()
