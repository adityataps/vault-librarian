from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from src.storage.db import Database
from src.storage.models import ActionItemRecord, AgentRunRecord, AuditLogRecord, NoteRecord


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
            except IntegrityError:
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

    async def write(
        self,
        agent: str,
        action: str,
        detail: str = "",
        note_path: str | None = None,
    ) -> None:
        async with self._db.session() as s:
            s.add(AuditLogRecord(agent=agent, action=action, detail=detail, note_path=note_path))
            await s.commit()

    async def query(
        self,
        agent: str | None = None,
        since: str = "7d",
        limit: int = 50,
    ) -> list[AuditLogRecord]:
        days = int(since.rstrip("d")) if since.endswith("d") else 7
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        async with self._db.session() as s:
            q = select(AuditLogRecord).where(AuditLogRecord.timestamp >= cutoff)
            if agent:
                q = q.where(AuditLogRecord.agent == agent)
            q = q.order_by(AuditLogRecord.timestamp.desc()).limit(limit)
            return list((await s.execute(q)).scalars())
