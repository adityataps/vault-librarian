"""Redis cache layer — wraps a primary StorageBackend with read-through caching."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

import redis.asyncio as aioredis

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

logger = logging.getLogger(__name__)

# Cache TTLs (seconds)
NOTE_TTL = 300        # 5 min — notes change frequently
TICKET_TTL = 600      # 10 min
TAG_TTL = 1800        # 30 min — tags change infrequently
REPORT_TTL = 3600     # 1 hour


class RedisCache(StorageBackend):
    """Read-through Redis cache over any primary StorageBackend.

    Writes always go to primary; reads check Redis first.
    On cache miss the result is stored in Redis with a TTL.
    """

    def __init__(
        self,
        primary: StorageBackend,
        redis_url: str = "redis://localhost:6379/0",
        key_prefix: str = "vc",
    ) -> None:
        self._primary = primary
        self._redis_url = redis_url
        self._prefix = key_prefix
        self._redis: aioredis.Redis | None = None

    def _k(self, *parts: str) -> str:
        return f"{self._prefix}:{':'.join(parts)}"

    async def initialize(self) -> None:
        self._redis = aioredis.from_url(self._redis_url, decode_responses=True)
        await self._primary.initialize()

    async def close(self) -> None:
        if self._redis:
            await self._redis.aclose()
        await self._primary.close()

    # ── Cache helpers ──────────────────────────────────────────────────────

    async def _get_json(self, key: str) -> Any | None:
        if not self._redis:
            return None
        try:
            raw = await self._redis.get(key)
            return json.loads(raw) if raw else None
        except Exception:
            return None

    async def _set_json(self, key: str, value: Any, ttl: int) -> None:
        if not self._redis:
            return
        try:
            await self._redis.setex(key, ttl, json.dumps(value, default=str))
        except Exception:
            pass

    async def _del(self, *keys: str) -> None:
        if not self._redis:
            return
        try:
            await self._redis.delete(*keys)
        except Exception:
            pass

    # ── Notes ──────────────────────────────────────────────────────────────

    async def save_note(self, note: NoteCreate) -> Note:
        saved = await self._primary.save_note(note)
        await self._del(
            self._k("note", "path", note.path),
            self._k("note", "id", str(saved.id)),
        )
        await self._set_json(
            self._k("note", "path", note.path), saved.model_dump(mode="json"), NOTE_TTL
        )
        return saved

    async def get_note(self, note_id: uuid.UUID) -> Note | None:
        key = self._k("note", "id", str(note_id))
        cached = await self._get_json(key)
        if cached:
            return Note.model_validate(cached)
        note = await self._primary.get_note(note_id)
        if note:
            await self._set_json(key, note.model_dump(mode="json"), NOTE_TTL)
        return note

    async def get_note_by_path(self, path: str) -> Note | None:
        key = self._k("note", "path", path)
        cached = await self._get_json(key)
        if cached:
            return Note.model_validate(cached)
        note = await self._primary.get_note_by_path(path)
        if note:
            await self._set_json(key, note.model_dump(mode="json"), NOTE_TTL)
        return note

    async def query_notes(self, filters: NoteFilter) -> list[Note]:
        # Queries are not cached (too many permutations); pass through
        return await self._primary.query_notes(filters)

    async def delete_note(self, note_id: uuid.UUID) -> bool:
        deleted = await self._primary.delete_note(note_id)
        await self._del(self._k("note", "id", str(note_id)))
        return deleted

    # ── Wikilinks ──────────────────────────────────────────────────────────

    async def save_wikilinks(
        self, note_id: uuid.UUID, links: list[WikilinkCreate]
    ) -> list[Wikilink]:
        saved = await self._primary.save_wikilinks(note_id, links)
        await self._del(self._k("wikilinks", str(note_id)))
        return saved

    async def get_wikilinks(self, note_id: uuid.UUID) -> list[Wikilink]:
        return await self._primary.get_wikilinks(note_id)

    async def get_broken_links(self) -> list[Wikilink]:
        return await self._primary.get_broken_links()

    # ── Embeddings ─────────────────────────────────────────────────────────

    async def save_embedding(
        self, note_id: uuid.UUID, vector: list[float], model: str
    ) -> Embedding:
        return await self._primary.save_embedding(note_id, vector, model)

    async def search_similar(
        self,
        vector: list[float],
        limit: int = 10,
        threshold: float = 0.7,
        model: str = "text-embedding-3-small",
    ) -> list[tuple[Note, float]]:
        return await self._primary.search_similar(vector, limit, threshold, model)

    # ── Agent runs ─────────────────────────────────────────────────────────

    async def create_agent_run(self, run: AgentRunCreate) -> AgentRun:
        return await self._primary.create_agent_run(run)

    async def update_agent_run(
        self, run_id: uuid.UUID, update: AgentRunUpdate
    ) -> AgentRun:
        return await self._primary.update_agent_run(run_id, update)

    async def get_recent_runs(self, limit: int = 20) -> list[AgentRun]:
        return await self._primary.get_recent_runs(limit)

    # ── Jira ───────────────────────────────────────────────────────────────

    async def get_jira_ticket(self, key: str) -> JiraTicket | None:
        cache_key = self._k("jira", key)
        cached = await self._get_json(cache_key)
        if cached:
            return JiraTicket.model_validate(cached)
        ticket = await self._primary.get_jira_ticket(key)
        if ticket:
            await self._set_json(cache_key, ticket.model_dump(mode="json"), TICKET_TTL)
        return ticket

    async def save_jira_ticket(self, ticket: JiraTicketCreate) -> JiraTicket:
        saved = await self._primary.save_jira_ticket(ticket)
        await self._del(self._k("jira", ticket.key))
        return saved

    async def list_jira_tickets(self, status: str | None = None) -> list[JiraTicket]:
        return await self._primary.list_jira_tickets(status)

    # ── Tags ───────────────────────────────────────────────────────────────

    async def list_tags(self, limit: int = 100) -> list[Tag]:
        key = self._k("tags", str(limit))
        cached = await self._get_json(key)
        if cached:
            return [Tag.model_validate(t) for t in cached]
        tags = await self._primary.list_tags(limit)
        await self._set_json(key, [t.model_dump(mode="json") for t in tags], TAG_TTL)
        return tags

    # ── Audit reports ──────────────────────────────────────────────────────

    async def save_audit_report(self, report: AuditReportCreate) -> AuditReport:
        return await self._primary.save_audit_report(report)

    async def get_recent_reports(
        self, report_type: str | None = None, limit: int = 10
    ) -> list[AuditReport]:
        return await self._primary.get_recent_reports(report_type, limit)
