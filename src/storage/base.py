"""Abstract storage backend interface."""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod

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


class StorageBackend(ABC):
    """Abstract storage backend. All implementations must be async-safe."""

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize connections and run any pending setup (migrations, schema)."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Close connections cleanly."""
        ...

    # ── Notes ──────────────────────────────────────────────────────────────

    @abstractmethod
    async def save_note(self, note: NoteCreate) -> Note:
        """Create or update a note. Upsert by path."""
        ...

    @abstractmethod
    async def get_note(self, note_id: uuid.UUID) -> Note | None:
        ...

    @abstractmethod
    async def get_note_by_path(self, path: str) -> Note | None:
        ...

    @abstractmethod
    async def query_notes(self, filters: NoteFilter) -> list[Note]:
        ...

    @abstractmethod
    async def delete_note(self, note_id: uuid.UUID) -> bool:
        """Return True if the note was found and deleted."""
        ...

    # ── Wikilinks ──────────────────────────────────────────────────────────

    @abstractmethod
    async def save_wikilinks(
        self, note_id: uuid.UUID, links: list[WikilinkCreate]
    ) -> list[Wikilink]:
        """Replace all wikilinks for a note (delete-then-insert)."""
        ...

    @abstractmethod
    async def get_wikilinks(self, note_id: uuid.UUID) -> list[Wikilink]:
        ...

    @abstractmethod
    async def get_broken_links(self) -> list[Wikilink]:
        ...

    # ── Embeddings ─────────────────────────────────────────────────────────

    @abstractmethod
    async def save_embedding(
        self, note_id: uuid.UUID, vector: list[float], model: str
    ) -> Embedding:
        """Upsert embedding for (note_id, model) pair."""
        ...

    @abstractmethod
    async def search_similar(
        self,
        vector: list[float],
        limit: int = 10,
        threshold: float = 0.7,
        model: str = "text-embedding-3-small",
    ) -> list[tuple[Note, float]]:
        """Return (note, similarity_score) pairs ordered by similarity descending."""
        ...

    # ── Agent runs ─────────────────────────────────────────────────────────

    @abstractmethod
    async def create_agent_run(self, run: AgentRunCreate) -> AgentRun:
        ...

    @abstractmethod
    async def update_agent_run(
        self, run_id: uuid.UUID, update: AgentRunUpdate
    ) -> AgentRun:
        ...

    @abstractmethod
    async def get_recent_runs(self, limit: int = 20) -> list[AgentRun]:
        ...

    # ── Jira ───────────────────────────────────────────────────────────────

    @abstractmethod
    async def get_jira_ticket(self, key: str) -> JiraTicket | None:
        ...

    @abstractmethod
    async def save_jira_ticket(self, ticket: JiraTicketCreate) -> JiraTicket:
        """Upsert by ticket key."""
        ...

    @abstractmethod
    async def list_jira_tickets(self, status: str | None = None) -> list[JiraTicket]:
        ...

    # ── Tags ───────────────────────────────────────────────────────────────

    @abstractmethod
    async def list_tags(self, limit: int = 100) -> list[Tag]:
        ...

    # ── Audit reports ──────────────────────────────────────────────────────

    @abstractmethod
    async def save_audit_report(self, report: AuditReportCreate) -> AuditReport:
        ...

    @abstractmethod
    async def get_recent_reports(
        self, report_type: str | None = None, limit: int = 10
    ) -> list[AuditReport]:
        ...
