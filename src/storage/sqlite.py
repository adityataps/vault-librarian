"""SQLite storage backend — dev/offline fallback (no pgvector, in-memory similarity)."""

from __future__ import annotations

import json
import math
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .base import StorageBackend
from .models import (
    AgentRun,
    AgentRunCreate,
    AgentRunUpdate,
    AuditReport,
    AuditReportCreate,
    Embedding,
    JiraTicket,
    JiraTicketCreate,
    Note,
    NoteCreate,
    NoteFilter,
    Tag,
    Wikilink,
    WikilinkCreate,
)

# SQLite schema (minimal, no pgvector — embeddings stored as JSON text)
SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS notes (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    path TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    folder TEXT NOT NULL,
    tags TEXT NOT NULL DEFAULT '[]',
    type TEXT,
    status TEXT,
    content_hash TEXT NOT NULL,
    word_count INTEGER DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_modified TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS embeddings (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    note_id TEXT NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    vector TEXT NOT NULL,
    model TEXT NOT NULL,
    generated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(note_id, model)
);
CREATE TABLE IF NOT EXISTS wikilinks (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    source_note_id TEXT NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    target_path TEXT NOT NULL,
    target_note_id TEXT REFERENCES notes(id) ON DELETE SET NULL,
    link_text TEXT NOT NULL,
    is_broken INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS jira_tickets (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    key TEXT NOT NULL UNIQUE,
    note_id TEXT REFERENCES notes(id) ON DELETE SET NULL,
    summary TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL,
    issue_type TEXT NOT NULL,
    priority TEXT,
    assignee TEXT,
    parent_key TEXT,
    repos TEXT NOT NULL DEFAULT '[]',
    labels TEXT NOT NULL DEFAULT '[]',
    jira_created_at TEXT,
    jira_updated_at TEXT NOT NULL,
    last_synced_at TEXT NOT NULL DEFAULT (datetime('now')),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS agent_runs (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    crew_name TEXT NOT NULL,
    agent_name TEXT,
    trigger_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at TEXT,
    duration_ms INTEGER,
    notes_processed INTEGER DEFAULT 0,
    notes_created INTEGER DEFAULT 0,
    notes_updated INTEGER DEFAULT 0,
    notes_moved INTEGER DEFAULT 0,
    tokens_used INTEGER DEFAULT 0,
    error_message TEXT,
    metadata TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS tags (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    name TEXT NOT NULL UNIQUE,
    normalized_name TEXT NOT NULL,
    usage_count INTEGER DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS audit_reports (
    id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    agent_run_id TEXT REFERENCES agent_runs(id) ON DELETE CASCADE,
    report_type TEXT NOT NULL,
    summary TEXT NOT NULL,
    findings_count INTEGER DEFAULT 0,
    findings TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


def _parse_dt(val: str | None) -> datetime | None:
    if not val:
        return None
    return datetime.fromisoformat(val)


def _row_to_note(row: Any) -> Note:
    return Note(
        id=uuid.UUID(row["id"]) if len(row["id"]) == 36 else uuid.UUID(
            f"{row['id'][:8]}-{row['id'][8:12]}-{row['id'][12:16]}-{row['id'][16:20]}-{row['id'][20:]}"
        ),
        path=row["path"],
        title=row["title"],
        folder=row["folder"],
        tags=json.loads(row["tags"]) if isinstance(row["tags"], str) else (row["tags"] or []),
        type=row["type"],
        status=row["status"],
        content_hash=row["content_hash"],
        word_count=row["word_count"] or 0,
        created_at=_parse_dt(row["created_at"]) or datetime.now(timezone.utc),
        updated_at=_parse_dt(row["updated_at"]) or datetime.now(timezone.utc),
        last_modified=_parse_dt(row["last_modified"]) or datetime.now(timezone.utc),
    )


class SQLiteStorage(StorageBackend):
    """SQLite storage backend for development and offline use.

    Vector similarity search falls back to in-memory cosine computation —
    not suitable for large vaults (>10k notes) but fine for dev.
    """

    def __init__(self, db_path: str = "vault_crawler.db") -> None:
        url = f"sqlite+aiosqlite:///{db_path}"
        self._engine = create_async_engine(url, echo=False)
        self._session_factory = async_sessionmaker(
            self._engine, expire_on_commit=False, class_=AsyncSession
        )

    async def initialize(self) -> None:
        async with self._engine.begin() as conn:
            for stmt in SQLITE_SCHEMA.strip().split(";"):
                stmt = stmt.strip()
                if stmt:
                    await conn.execute(text(stmt))

    async def close(self) -> None:
        await self._engine.dispose()

    # ── Notes ──────────────────────────────────────────────────────────────

    async def save_note(self, note: NoteCreate) -> Note:
        async with self._session_factory() as session:
            now = datetime.now(timezone.utc).isoformat()
            row_id = str(uuid.uuid4())
            await session.execute(
                text("""
                    INSERT INTO notes (id, path, title, folder, tags, type, status,
                        content_hash, word_count, last_modified, created_at, updated_at)
                    VALUES (:id, :path, :title, :folder, :tags, :type, :status,
                        :content_hash, :word_count, :last_modified, :now, :now)
                    ON CONFLICT(path) DO UPDATE SET
                        title=excluded.title, folder=excluded.folder, tags=excluded.tags,
                        type=excluded.type, status=excluded.status,
                        content_hash=excluded.content_hash, word_count=excluded.word_count,
                        last_modified=excluded.last_modified, updated_at=:now
                """),
                {
                    "id": row_id,
                    "path": note.path,
                    "title": note.title,
                    "folder": note.folder,
                    "tags": json.dumps(note.tags),
                    "type": note.type,
                    "status": note.status,
                    "content_hash": note.content_hash,
                    "word_count": note.word_count,
                    "last_modified": note.last_modified.isoformat(),
                    "now": now,
                },
            )
            await session.commit()
            saved = await session.execute(
                text("SELECT * FROM notes WHERE path = :path"), {"path": note.path}
            )
            return _row_to_note(dict(saved.mappings().one()))

    async def get_note(self, note_id: uuid.UUID) -> Note | None:
        async with self._session_factory() as session:
            result = await session.execute(
                text("SELECT * FROM notes WHERE id = :id"), {"id": str(note_id)}
            )
            row = result.mappings().first()
            return _row_to_note(dict(row)) if row else None

    async def get_note_by_path(self, path: str) -> Note | None:
        async with self._session_factory() as session:
            result = await session.execute(
                text("SELECT * FROM notes WHERE path = :path"), {"path": path}
            )
            row = result.mappings().first()
            return _row_to_note(dict(row)) if row else None

    async def query_notes(self, filters: NoteFilter) -> list[Note]:
        async with self._session_factory() as session:
            where, params = ["1=1"], {}
            if filters.folder:
                where.append("folder = :folder")
                params["folder"] = filters.folder
            if filters.type:
                where.append("type = :type")
                params["type"] = filters.type
            if filters.status:
                where.append("status = :status")
                params["status"] = filters.status
            if filters.updated_after:
                where.append("updated_at >= :updated_after")
                params["updated_after"] = filters.updated_after.isoformat()
            query = f"SELECT * FROM notes WHERE {' AND '.join(where)} LIMIT :limit OFFSET :offset"
            params["limit"] = filters.limit
            params["offset"] = filters.offset
            result = await session.execute(text(query), params)
            notes = [_row_to_note(dict(r)) for r in result.mappings().all()]
            # Filter by tags in Python (SQLite lacks array operators)
            if filters.tags:
                tag_set = set(filters.tags)
                notes = [n for n in notes if tag_set.issubset(set(n.tags))]
            return notes

    async def delete_note(self, note_id: uuid.UUID) -> bool:
        async with self._session_factory() as session:
            result = await session.execute(
                text("DELETE FROM notes WHERE id = :id"), {"id": str(note_id)}
            )
            await session.commit()
            return result.rowcount > 0

    # ── Wikilinks ──────────────────────────────────────────────────────────

    async def save_wikilinks(
        self, note_id: uuid.UUID, links: list[WikilinkCreate]
    ) -> list[Wikilink]:
        async with self._session_factory() as session:
            await session.execute(
                text("DELETE FROM wikilinks WHERE source_note_id = :nid"),
                {"nid": str(note_id)},
            )
            created: list[Wikilink] = []
            now = datetime.now(timezone.utc).isoformat()
            for link in links:
                lid = str(uuid.uuid4())
                await session.execute(
                    text("""
                        INSERT INTO wikilinks (id, source_note_id, target_path,
                            target_note_id, link_text, is_broken, created_at, updated_at)
                        VALUES (:id, :src, :tpath, :tnid, :ltext, :broken, :now, :now)
                    """),
                    {
                        "id": lid, "src": str(note_id), "tpath": link.target_path,
                        "tnid": str(link.target_note_id) if link.target_note_id else None,
                        "ltext": link.link_text, "broken": int(link.is_broken), "now": now,
                    },
                )
                created.append(Wikilink(
                    id=uuid.UUID(lid), source_note_id=note_id,
                    target_path=link.target_path, target_note_id=link.target_note_id,
                    link_text=link.link_text, is_broken=link.is_broken,
                ))
            await session.commit()
            return created

    async def get_wikilinks(self, note_id: uuid.UUID) -> list[Wikilink]:
        async with self._session_factory() as session:
            result = await session.execute(
                text("SELECT * FROM wikilinks WHERE source_note_id = :nid"),
                {"nid": str(note_id)},
            )
            return [
                Wikilink(
                    id=uuid.UUID(r["id"]), source_note_id=uuid.UUID(r["source_note_id"]),
                    target_path=r["target_path"],
                    target_note_id=uuid.UUID(r["target_note_id"]) if r["target_note_id"] else None,
                    link_text=r["link_text"], is_broken=bool(r["is_broken"]),
                )
                for r in result.mappings().all()
            ]

    async def get_broken_links(self) -> list[Wikilink]:
        async with self._session_factory() as session:
            result = await session.execute(
                text("SELECT * FROM wikilinks WHERE is_broken = 1")
            )
            return [
                Wikilink(
                    id=uuid.UUID(r["id"]), source_note_id=uuid.UUID(r["source_note_id"]),
                    target_path=r["target_path"],
                    target_note_id=uuid.UUID(r["target_note_id"]) if r["target_note_id"] else None,
                    link_text=r["link_text"], is_broken=True,
                )
                for r in result.mappings().all()
            ]

    # ── Embeddings ─────────────────────────────────────────────────────────

    async def save_embedding(
        self, note_id: uuid.UUID, vector: list[float], model: str
    ) -> Embedding:
        async with self._session_factory() as session:
            eid = str(uuid.uuid4())
            now = datetime.now(timezone.utc).isoformat()
            await session.execute(
                text("""
                    INSERT INTO embeddings (id, note_id, vector, model, generated_at)
                    VALUES (:id, :nid, :vec, :model, :now)
                    ON CONFLICT(note_id, model) DO UPDATE SET vector=excluded.vector, generated_at=:now
                """),
                {"id": eid, "nid": str(note_id), "vec": json.dumps(vector), "model": model, "now": now},
            )
            await session.commit()
            return Embedding(id=uuid.UUID(eid), note_id=note_id, vector=vector, model=model)

    async def search_similar(
        self,
        vector: list[float],
        limit: int = 10,
        threshold: float = 0.7,
        model: str = "text-embedding-3-small",
    ) -> list[tuple[Note, float]]:
        """In-memory cosine similarity (SQLite has no vector index)."""
        async with self._session_factory() as session:
            result = await session.execute(
                text("SELECT * FROM embeddings WHERE model = :model"), {"model": model}
            )
            rows = result.mappings().all()

        scored: list[tuple[uuid.UUID, float]] = []
        for row in rows:
            stored = json.loads(row["vector"])
            sim = _cosine_similarity(vector, stored)
            if sim >= threshold:
                scored.append((uuid.UUID(row["note_id"]), sim))

        scored.sort(key=lambda x: x[1], reverse=True)
        scored = scored[:limit]

        results: list[tuple[Note, float]] = []
        for note_id, sim in scored:
            note = await self.get_note(note_id)
            if note:
                results.append((note, sim))
        return results

    # ── Agent runs ─────────────────────────────────────────────────────────

    async def create_agent_run(self, run: AgentRunCreate) -> AgentRun:
        async with self._session_factory() as session:
            rid = str(uuid.uuid4())
            now = datetime.now(timezone.utc).isoformat()
            await session.execute(
                text("""
                    INSERT INTO agent_runs (id, crew_name, agent_name, trigger_type,
                        status, started_at, metadata)
                    VALUES (:id, :crew, :agent, :trigger, 'running', :now, :meta)
                """),
                {"id": rid, "crew": run.crew_name, "agent": run.agent_name,
                 "trigger": run.trigger_type, "now": now, "meta": json.dumps(run.metadata)},
            )
            await session.commit()
        return AgentRun(
            id=uuid.UUID(rid), crew_name=run.crew_name, agent_name=run.agent_name,
            trigger_type=run.trigger_type, status="running",  # type: ignore[arg-type]
            metadata=run.metadata,
        )

    async def update_agent_run(self, run_id: uuid.UUID, update: AgentRunUpdate) -> AgentRun:
        async with self._session_factory() as session:
            await session.execute(
                text("""
                    UPDATE agent_runs SET status=:status, completed_at=:completed,
                        duration_ms=:dur, notes_processed=:np, notes_created=:nc,
                        notes_updated=:nu, notes_moved=:nm, tokens_used=:tu,
                        error_message=:err, metadata=:meta
                    WHERE id=:id
                """),
                {
                    "id": str(run_id), "status": update.status,
                    "completed": update.completed_at.isoformat(),
                    "dur": update.duration_ms, "np": update.notes_processed,
                    "nc": update.notes_created, "nu": update.notes_updated,
                    "nm": update.notes_moved, "tu": update.tokens_used,
                    "err": update.error_message, "meta": json.dumps(update.metadata),
                },
            )
            await session.commit()
        run = await self.get_recent_runs(limit=1)
        # Return a reconstructed model (SQLite lacks RETURNING)
        return AgentRun(
            id=run_id, crew_name="", agent_name=None,
            trigger_type="manual", status=update.status,  # type: ignore[arg-type]
            completed_at=update.completed_at, duration_ms=update.duration_ms,
        )

    async def get_recent_runs(self, limit: int = 20) -> list[AgentRun]:
        async with self._session_factory() as session:
            result = await session.execute(
                text("SELECT * FROM agent_runs ORDER BY started_at DESC LIMIT :limit"),
                {"limit": limit},
            )
            runs = []
            for r in result.mappings().all():
                runs.append(AgentRun(
                    id=uuid.UUID(r["id"]), crew_name=r["crew_name"],
                    agent_name=r["agent_name"], trigger_type=r["trigger_type"],  # type: ignore[arg-type]
                    status=r["status"],  # type: ignore[arg-type]
                    started_at=_parse_dt(r["started_at"]) or datetime.now(timezone.utc),
                    completed_at=_parse_dt(r["completed_at"]),
                    duration_ms=r["duration_ms"],
                    notes_processed=r["notes_processed"] or 0,
                    notes_created=r["notes_created"] or 0,
                    notes_updated=r["notes_updated"] or 0,
                    notes_moved=r["notes_moved"] or 0,
                    tokens_used=r["tokens_used"] or 0,
                    error_message=r["error_message"],
                    metadata=json.loads(r["metadata"]) if r["metadata"] else {},
                ))
            return runs

    # ── Jira ───────────────────────────────────────────────────────────────

    async def get_jira_ticket(self, key: str) -> JiraTicket | None:
        async with self._session_factory() as session:
            result = await session.execute(
                text("SELECT * FROM jira_tickets WHERE key = :key"), {"key": key}
            )
            row = result.mappings().first()
            return self._ticket_from_row(dict(row)) if row else None

    async def save_jira_ticket(self, ticket: JiraTicketCreate) -> JiraTicket:
        async with self._session_factory() as session:
            tid = str(uuid.uuid4())
            now = datetime.now(timezone.utc).isoformat()
            await session.execute(
                text("""
                    INSERT INTO jira_tickets (id, key, note_id, summary, description,
                        status, issue_type, priority, assignee, parent_key, repos, labels,
                        jira_created_at, jira_updated_at, last_synced_at, created_at)
                    VALUES (:id, :key, :nid, :summary, :desc, :status, :itype, :priority,
                        :assignee, :parent, :repos, :labels, :jc, :ju, :now, :now)
                    ON CONFLICT(key) DO UPDATE SET
                        note_id=excluded.note_id, summary=excluded.summary,
                        description=excluded.description, status=excluded.status,
                        issue_type=excluded.issue_type, priority=excluded.priority,
                        assignee=excluded.assignee, parent_key=excluded.parent_key,
                        repos=excluded.repos, labels=excluded.labels,
                        jira_updated_at=excluded.jira_updated_at, last_synced_at=:now
                """),
                {
                    "id": tid, "key": ticket.key,
                    "nid": str(ticket.note_id) if ticket.note_id else None,
                    "summary": ticket.summary, "desc": ticket.description,
                    "status": ticket.status, "itype": ticket.issue_type,
                    "priority": ticket.priority, "assignee": ticket.assignee,
                    "parent": ticket.parent_key,
                    "repos": json.dumps(ticket.repos), "labels": json.dumps(ticket.labels),
                    "jc": ticket.jira_created_at.isoformat() if ticket.jira_created_at else None,
                    "ju": ticket.jira_updated_at.isoformat(), "now": now,
                },
            )
            await session.commit()
            return await self.get_jira_ticket(ticket.key)  # type: ignore[return-value]

    async def list_jira_tickets(self, status: str | None = None) -> list[JiraTicket]:
        async with self._session_factory() as session:
            if status:
                result = await session.execute(
                    text("SELECT * FROM jira_tickets WHERE status = :s"), {"s": status}
                )
            else:
                result = await session.execute(text("SELECT * FROM jira_tickets"))
            return [self._ticket_from_row(dict(r)) for r in result.mappings().all()]

    @staticmethod
    def _ticket_from_row(row: dict) -> JiraTicket:
        return JiraTicket(
            id=uuid.UUID(row["id"]) if len(row["id"]) == 36 else uuid.uuid4(),
            key=row["key"],
            note_id=uuid.UUID(row["note_id"]) if row.get("note_id") else None,
            summary=row["summary"], description=row.get("description"),
            status=row["status"], issue_type=row["issue_type"],
            priority=row.get("priority"), assignee=row.get("assignee"),
            parent_key=row.get("parent_key"),
            repos=json.loads(row["repos"]) if isinstance(row["repos"], str) else (row["repos"] or []),
            labels=json.loads(row["labels"]) if isinstance(row["labels"], str) else (row["labels"] or []),
            jira_created_at=_parse_dt(row.get("jira_created_at")),
            jira_updated_at=_parse_dt(row["jira_updated_at"]) or datetime.now(timezone.utc),
            last_synced_at=_parse_dt(row.get("last_synced_at")) or datetime.now(timezone.utc),
            created_at=_parse_dt(row.get("created_at")) or datetime.now(timezone.utc),
        )

    # ── Tags ───────────────────────────────────────────────────────────────

    async def list_tags(self, limit: int = 100) -> list[Tag]:
        async with self._session_factory() as session:
            result = await session.execute(
                text("SELECT * FROM tags ORDER BY usage_count DESC LIMIT :limit"), {"limit": limit}
            )
            return [
                Tag(
                    id=uuid.UUID(r["id"]), name=r["name"],
                    normalized_name=r["normalized_name"], usage_count=r["usage_count"] or 0,
                    created_at=_parse_dt(r["created_at"]) or datetime.now(timezone.utc),
                    updated_at=_parse_dt(r["updated_at"]) or datetime.now(timezone.utc),
                )
                for r in result.mappings().all()
            ]

    # ── Audit reports ──────────────────────────────────────────────────────

    async def save_audit_report(self, report: AuditReportCreate) -> AuditReport:
        async with self._session_factory() as session:
            rid = str(uuid.uuid4())
            now = datetime.now(timezone.utc).isoformat()
            await session.execute(
                text("""
                    INSERT INTO audit_reports (id, agent_run_id, report_type, summary,
                        findings_count, findings, created_at)
                    VALUES (:id, :arid, :rtype, :summary, :fc, :findings, :now)
                """),
                {
                    "id": rid,
                    "arid": str(report.agent_run_id) if report.agent_run_id else None,
                    "rtype": report.report_type, "summary": report.summary,
                    "fc": len(report.findings), "findings": json.dumps(report.findings),
                    "now": now,
                },
            )
            await session.commit()
            return AuditReport(
                id=uuid.UUID(rid), agent_run_id=report.agent_run_id,
                report_type=report.report_type,  # type: ignore[arg-type]
                summary=report.summary, findings_count=len(report.findings),
                findings=report.findings,
            )

    async def get_recent_reports(
        self, report_type: str | None = None, limit: int = 10
    ) -> list[AuditReport]:
        async with self._session_factory() as session:
            if report_type:
                result = await session.execute(
                    text("""
                        SELECT * FROM audit_reports WHERE report_type = :rt
                        ORDER BY created_at DESC LIMIT :limit
                    """),
                    {"rt": report_type, "limit": limit},
                )
            else:
                result = await session.execute(
                    text("SELECT * FROM audit_reports ORDER BY created_at DESC LIMIT :limit"),
                    {"limit": limit},
                )
            return [
                AuditReport(
                    id=uuid.UUID(r["id"]),
                    agent_run_id=uuid.UUID(r["agent_run_id"]) if r["agent_run_id"] else None,
                    report_type=r["report_type"],  # type: ignore[arg-type]
                    summary=r["summary"],
                    findings_count=r["findings_count"] or 0,
                    findings=json.loads(r["findings"]) if isinstance(r["findings"], str) else [],
                    created_at=_parse_dt(r["created_at"]) or datetime.now(timezone.utc),
                )
                for r in result.mappings().all()
            ]
