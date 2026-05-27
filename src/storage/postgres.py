"""PostgreSQL storage backend using SQLAlchemy async + pgvector."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
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
from .orm import (
    AgentRunRow,
    AuditReportRow,
    EmbeddingRow,
    JiraTicketRow,
    NoteRow,
    TagRow,
    WikilinkRow,
)


def _note_from_row(row: NoteRow) -> Note:
    return Note(
        id=row.id,
        path=row.path,
        title=row.title,
        folder=row.folder,
        tags=row.tags or [],
        type=row.type,
        status=row.status,
        content_hash=row.content_hash,
        word_count=row.word_count or 0,
        created_at=row.created_at,
        updated_at=row.updated_at,
        last_modified=row.last_modified,
    )


def _run_from_row(row: AgentRunRow) -> AgentRun:
    return AgentRun(
        id=row.id,
        crew_name=row.crew_name,
        agent_name=row.agent_name,
        trigger_type=row.trigger_type,  # type: ignore[arg-type]
        status=row.status,  # type: ignore[arg-type]
        started_at=row.started_at,
        completed_at=row.completed_at,
        duration_ms=row.duration_ms,
        notes_processed=row.notes_processed or 0,
        notes_created=row.notes_created or 0,
        notes_updated=row.notes_updated or 0,
        notes_moved=row.notes_moved or 0,
        tokens_used=row.tokens_used or 0,
        error_message=row.error_message,
        metadata=row.run_metadata or {},
    )


class PostgresStorage(StorageBackend):
    """PostgreSQL + pgvector storage backend."""

    def __init__(self, database_url: str, pool_size: int = 10) -> None:
        self._url = database_url
        self._engine = create_async_engine(
            database_url,
            pool_size=pool_size,
            max_overflow=20,
            pool_pre_ping=True,
            echo=False,
        )
        self._session_factory = async_sessionmaker(
            self._engine, expire_on_commit=False, class_=AsyncSession
        )

    async def initialize(self) -> None:
        """Verify connectivity. Schema is managed by Alembic."""
        async with self._engine.connect() as conn:
            await conn.execute(select(1))

    async def close(self) -> None:
        await self._engine.dispose()

    # ── Notes ──────────────────────────────────────────────────────────────

    async def save_note(self, note: NoteCreate) -> Note:
        async with self._session_factory() as session:
            stmt = (
                pg_insert(NoteRow)
                .values(
                    path=note.path,
                    title=note.title,
                    folder=note.folder,
                    tags=note.tags,
                    type=note.type,
                    status=note.status,
                    content_hash=note.content_hash,
                    word_count=note.word_count,
                    last_modified=note.last_modified,
                )
                .on_conflict_do_update(
                    index_elements=["path"],
                    set_={
                        "title": note.title,
                        "folder": note.folder,
                        "tags": note.tags,
                        "type": note.type,
                        "status": note.status,
                        "content_hash": note.content_hash,
                        "word_count": note.word_count,
                        "last_modified": note.last_modified,
                        "updated_at": datetime.now(timezone.utc),
                    },
                )
                .returning(NoteRow)
            )
            result = await session.execute(stmt)
            await session.commit()
            row = result.scalars().one()
            return _note_from_row(row)

    async def get_note(self, note_id: uuid.UUID) -> Note | None:
        async with self._session_factory() as session:
            row = await session.get(NoteRow, note_id)
            return _note_from_row(row) if row else None

    async def get_note_by_path(self, path: str) -> Note | None:
        async with self._session_factory() as session:
            result = await session.execute(select(NoteRow).where(NoteRow.path == path))
            row = result.scalars().first()
            return _note_from_row(row) if row else None

    async def query_notes(self, filters: NoteFilter) -> list[Note]:
        async with self._session_factory() as session:
            stmt = select(NoteRow)
            if filters.folder:
                stmt = stmt.where(NoteRow.folder == filters.folder)
            if filters.type:
                stmt = stmt.where(NoteRow.type == filters.type)
            if filters.status:
                stmt = stmt.where(NoteRow.status == filters.status)
            if filters.updated_after:
                stmt = stmt.where(NoteRow.updated_at >= filters.updated_after)
            if filters.tags:
                # Note has ALL of the requested tags (array containment)
                stmt = stmt.where(NoteRow.tags.contains(filters.tags))
            stmt = stmt.offset(filters.offset).limit(filters.limit)
            result = await session.execute(stmt)
            return [_note_from_row(r) for r in result.scalars().all()]

    async def delete_note(self, note_id: uuid.UUID) -> bool:
        async with self._session_factory() as session:
            result = await session.execute(
                delete(NoteRow).where(NoteRow.id == note_id)
            )
            await session.commit()
            return result.rowcount > 0

    # ── Wikilinks ──────────────────────────────────────────────────────────

    async def save_wikilinks(
        self, note_id: uuid.UUID, links: list[WikilinkCreate]
    ) -> list[Wikilink]:
        async with self._session_factory() as session:
            await session.execute(
                delete(WikilinkRow).where(WikilinkRow.source_note_id == note_id)
            )
            rows = [
                WikilinkRow(
                    source_note_id=note_id,
                    target_path=link.target_path,
                    target_note_id=link.target_note_id,
                    link_text=link.link_text,
                    is_broken=link.is_broken,
                )
                for link in links
            ]
            session.add_all(rows)
            await session.commit()
            return [
                Wikilink(
                    id=r.id,
                    source_note_id=r.source_note_id,
                    target_path=r.target_path,
                    target_note_id=r.target_note_id,
                    link_text=r.link_text,
                    is_broken=r.is_broken,
                    created_at=r.created_at,
                    updated_at=r.updated_at,
                )
                for r in rows
            ]

    async def get_wikilinks(self, note_id: uuid.UUID) -> list[Wikilink]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(WikilinkRow).where(WikilinkRow.source_note_id == note_id)
            )
            return [
                Wikilink(
                    id=r.id,
                    source_note_id=r.source_note_id,
                    target_path=r.target_path,
                    target_note_id=r.target_note_id,
                    link_text=r.link_text,
                    is_broken=r.is_broken,
                    created_at=r.created_at,
                    updated_at=r.updated_at,
                )
                for r in result.scalars().all()
            ]

    async def get_broken_links(self) -> list[Wikilink]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(WikilinkRow).where(WikilinkRow.is_broken.is_(True))
            )
            return [
                Wikilink(
                    id=r.id,
                    source_note_id=r.source_note_id,
                    target_path=r.target_path,
                    target_note_id=r.target_note_id,
                    link_text=r.link_text,
                    is_broken=r.is_broken,
                    created_at=r.created_at,
                    updated_at=r.updated_at,
                )
                for r in result.scalars().all()
            ]

    # ── Embeddings ─────────────────────────────────────────────────────────

    async def save_embedding(
        self, note_id: uuid.UUID, vector: list[float], model: str
    ) -> Embedding:
        async with self._session_factory() as session:
            stmt = (
                pg_insert(EmbeddingRow)
                .values(note_id=note_id, vector=vector, model=model)
                .on_conflict_do_update(
                    constraint="embeddings_note_id_model_key",
                    set_={
                        "vector": vector,
                        "generated_at": datetime.now(timezone.utc),
                    },
                )
                .returning(EmbeddingRow)
            )
            result = await session.execute(stmt)
            await session.commit()
            row = result.scalars().one()
            return Embedding(
                id=row.id,
                note_id=row.note_id,
                vector=list(row.vector),
                model=row.model,
                generated_at=row.generated_at,
            )

    async def search_similar(
        self,
        vector: list[float],
        limit: int = 10,
        threshold: float = 0.7,
        model: str = "text-embedding-3-small",
    ) -> list[tuple[Note, float]]:
        """Use pgvector cosine similarity search."""
        async with self._session_factory() as session:
            # cosine_distance returns 0=identical, 2=opposite; similarity = 1 - distance
            from pgvector.sqlalchemy import Vector as VectorType
            from sqlalchemy import func, cast

            distance_col = EmbeddingRow.vector.cosine_distance(vector).label("distance")
            stmt = (
                select(NoteRow, distance_col)
                .join(EmbeddingRow, EmbeddingRow.note_id == NoteRow.id)
                .where(EmbeddingRow.model == model)
                .where(EmbeddingRow.vector.cosine_distance(vector) <= (1.0 - threshold))
                .order_by(distance_col)
                .limit(limit)
            )
            result = await session.execute(stmt)
            pairs = result.all()
            return [(_note_from_row(row), 1.0 - float(dist)) for row, dist in pairs]

    # ── Agent runs ─────────────────────────────────────────────────────────

    async def create_agent_run(self, run: AgentRunCreate) -> AgentRun:
        async with self._session_factory() as session:
            row = AgentRunRow(
                crew_name=run.crew_name,
                agent_name=run.agent_name,
                trigger_type=run.trigger_type,
                status="running",
                metadata=run.metadata,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return _run_from_row(row)

    async def update_agent_run(
        self, run_id: uuid.UUID, update: AgentRunUpdate
    ) -> AgentRun:
        async with self._session_factory() as session:
            stmt = (
                update(AgentRunRow)
                .where(AgentRunRow.id == run_id)
                .values(
                    status=update.status,
                    completed_at=update.completed_at,
                    duration_ms=update.duration_ms,
                    notes_processed=update.notes_processed,
                    notes_created=update.notes_created,
                    notes_updated=update.notes_updated,
                    notes_moved=update.notes_moved,
                    tokens_used=update.tokens_used,
                    error_message=update.error_message,
                    metadata=update.metadata,
                )
                .returning(AgentRunRow)
            )
            result = await session.execute(stmt)
            await session.commit()
            row = result.scalars().one()
            return _run_from_row(row)

    async def get_recent_runs(self, limit: int = 20) -> list[AgentRun]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(AgentRunRow).order_by(AgentRunRow.started_at.desc()).limit(limit)
            )
            return [_run_from_row(r) for r in result.scalars().all()]

    # ── Jira ───────────────────────────────────────────────────────────────

    async def get_jira_ticket(self, key: str) -> JiraTicket | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(JiraTicketRow).where(JiraTicketRow.key == key)
            )
            row = result.scalars().first()
            return self._ticket_from_row(row) if row else None

    async def save_jira_ticket(self, ticket: JiraTicketCreate) -> JiraTicket:
        async with self._session_factory() as session:
            stmt = (
                pg_insert(JiraTicketRow)
                .values(
                    key=ticket.key,
                    note_id=ticket.note_id,
                    summary=ticket.summary,
                    description=ticket.description,
                    status=ticket.status,
                    issue_type=ticket.issue_type,
                    priority=ticket.priority,
                    assignee=ticket.assignee,
                    parent_key=ticket.parent_key,
                    repos=ticket.repos,
                    labels=ticket.labels,
                    jira_created_at=ticket.jira_created_at,
                    jira_updated_at=ticket.jira_updated_at,
                    last_synced_at=datetime.now(timezone.utc),
                )
                .on_conflict_do_update(
                    index_elements=["key"],
                    set_={
                        "note_id": ticket.note_id,
                        "summary": ticket.summary,
                        "description": ticket.description,
                        "status": ticket.status,
                        "issue_type": ticket.issue_type,
                        "priority": ticket.priority,
                        "assignee": ticket.assignee,
                        "parent_key": ticket.parent_key,
                        "repos": ticket.repos,
                        "labels": ticket.labels,
                        "jira_updated_at": ticket.jira_updated_at,
                        "last_synced_at": datetime.now(timezone.utc),
                    },
                )
                .returning(JiraTicketRow)
            )
            result = await session.execute(stmt)
            await session.commit()
            row = result.scalars().one()
            return self._ticket_from_row(row)

    async def list_jira_tickets(self, status: str | None = None) -> list[JiraTicket]:
        async with self._session_factory() as session:
            stmt = select(JiraTicketRow)
            if status:
                stmt = stmt.where(JiraTicketRow.status == status)
            result = await session.execute(stmt)
            return [self._ticket_from_row(r) for r in result.scalars().all()]

    @staticmethod
    def _ticket_from_row(row: JiraTicketRow) -> JiraTicket:
        return JiraTicket(
            id=row.id,
            key=row.key,
            note_id=row.note_id,
            summary=row.summary,
            description=row.description,
            status=row.status,
            issue_type=row.issue_type,
            priority=row.priority,
            assignee=row.assignee,
            parent_key=row.parent_key,
            repos=row.repos or [],
            labels=row.labels or [],
            jira_created_at=row.jira_created_at,
            jira_updated_at=row.jira_updated_at,
            last_synced_at=row.last_synced_at,
            created_at=row.created_at,
        )

    # ── Tags ───────────────────────────────────────────────────────────────

    async def list_tags(self, limit: int = 100) -> list[Tag]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(TagRow).order_by(TagRow.usage_count.desc()).limit(limit)
            )
            return [
                Tag(
                    id=r.id,
                    name=r.name,
                    normalized_name=r.normalized_name,
                    usage_count=r.usage_count,
                    created_at=r.created_at,
                    updated_at=r.updated_at,
                )
                for r in result.scalars().all()
            ]

    # ── Audit reports ──────────────────────────────────────────────────────

    async def save_audit_report(self, report: AuditReportCreate) -> AuditReport:
        async with self._session_factory() as session:
            row = AuditReportRow(
                agent_run_id=report.agent_run_id,
                report_type=report.report_type,
                summary=report.summary,
                findings_count=len(report.findings),
                findings=report.findings,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return AuditReport(
                id=row.id,
                agent_run_id=row.agent_run_id,
                report_type=row.report_type,  # type: ignore[arg-type]
                summary=row.summary,
                findings_count=row.findings_count,
                findings=row.findings or [],
                created_at=row.created_at,
            )

    async def get_recent_reports(
        self, report_type: str | None = None, limit: int = 10
    ) -> list[AuditReport]:
        async with self._session_factory() as session:
            stmt = select(AuditReportRow).order_by(AuditReportRow.created_at.desc())
            if report_type:
                stmt = stmt.where(AuditReportRow.report_type == report_type)
            stmt = stmt.limit(limit)
            result = await session.execute(stmt)
            return [
                AuditReport(
                    id=r.id,
                    agent_run_id=r.agent_run_id,
                    report_type=r.report_type,  # type: ignore[arg-type]
                    summary=r.summary,
                    findings_count=r.findings_count,
                    findings=r.findings or [],
                    created_at=r.created_at,
                )
                for r in result.scalars().all()
            ]
