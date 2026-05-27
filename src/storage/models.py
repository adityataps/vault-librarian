"""Domain models for vault-crawler storage layer."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

NoteType = Literal["Story", "Meeting", "TechNote", "Project", "Template", "Reference", "Career", "Other"]
NoteStatus = Literal["Backlog", "Planning", "In Progress", "Blocked", "Done"]
TriggerType = Literal["file_event", "scheduled", "manual", "api"]
RunStatus = Literal["running", "success", "failed", "cancelled"]
ReportType = Literal["daily_audit", "stale_notes", "broken_links", "orphans", "weekly_digest"]


class Note(BaseModel):
    """A vault note with its metadata."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    path: str
    title: str
    folder: str
    tags: list[str] = Field(default_factory=list)
    type: NoteType | None = None
    status: NoteStatus | None = None
    content_hash: str
    word_count: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    last_modified: datetime = Field(default_factory=datetime.utcnow)

    # Frontmatter extras: populated from file, not persisted as DB columns
    frontmatter: dict[str, Any] = Field(default_factory=dict, exclude=True)


class NoteCreate(BaseModel):
    """Input for creating or upserting a note."""

    path: str
    title: str
    folder: str
    tags: list[str] = Field(default_factory=list)
    type: NoteType | None = None
    status: NoteStatus | None = None
    content_hash: str
    word_count: int = 0
    last_modified: datetime = Field(default_factory=datetime.utcnow)
    frontmatter: dict[str, Any] = Field(default_factory=dict)


class NoteFilter(BaseModel):
    """Filters for querying notes."""

    folder: str | None = None
    tags: list[str] | None = None
    type: NoteType | None = None
    status: NoteStatus | None = None
    updated_after: datetime | None = None
    limit: int = 100
    offset: int = 0


class Tag(BaseModel):
    """A tag with usage statistics."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    name: str
    normalized_name: str
    usage_count: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Embedding(BaseModel):
    """A vector embedding for a note."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    note_id: uuid.UUID
    vector: list[float]
    model: str
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class Wikilink(BaseModel):
    """A [[wikilink]] between two notes."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    source_note_id: uuid.UUID
    target_path: str
    target_note_id: uuid.UUID | None = None
    link_text: str
    is_broken: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class WikilinkCreate(BaseModel):
    """Input for creating a wikilink."""

    target_path: str
    link_text: str
    target_note_id: uuid.UUID | None = None
    is_broken: bool = False


class AgentRun(BaseModel):
    """A record of an agent/crew execution."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    crew_name: str
    agent_name: str | None = None
    trigger_type: TriggerType
    status: RunStatus
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None
    duration_ms: int | None = None
    notes_processed: int = 0
    notes_created: int = 0
    notes_updated: int = 0
    notes_moved: int = 0
    tokens_used: int = 0
    error_message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentRunCreate(BaseModel):
    """Input for starting an agent run."""

    crew_name: str
    agent_name: str | None = None
    trigger_type: TriggerType
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentRunUpdate(BaseModel):
    """Input for completing an agent run."""

    status: RunStatus
    completed_at: datetime = Field(default_factory=datetime.utcnow)
    duration_ms: int | None = None
    notes_processed: int = 0
    notes_created: int = 0
    notes_updated: int = 0
    notes_moved: int = 0
    tokens_used: int = 0
    error_message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class JiraTicket(BaseModel):
    """A synced Jira ticket."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    key: str
    note_id: uuid.UUID | None = None
    summary: str
    description: str | None = None
    status: str
    issue_type: str
    priority: str | None = None
    assignee: str | None = None
    parent_key: str | None = None
    repos: list[str] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)
    jira_created_at: datetime | None = None
    jira_updated_at: datetime
    last_synced_at: datetime = Field(default_factory=datetime.utcnow)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class JiraTicketCreate(BaseModel):
    """Input for upserting a Jira ticket."""

    key: str
    note_id: uuid.UUID | None = None
    summary: str
    description: str | None = None
    status: str
    issue_type: str
    priority: str | None = None
    assignee: str | None = None
    parent_key: str | None = None
    repos: list[str] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)
    jira_created_at: datetime | None = None
    jira_updated_at: datetime


class AuditReport(BaseModel):
    """An audit report from the daily or weekly audit crew."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    agent_run_id: uuid.UUID | None = None
    report_type: ReportType
    summary: str
    findings_count: int = 0
    findings: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AuditReportCreate(BaseModel):
    """Input for creating an audit report."""

    agent_run_id: uuid.UUID | None = None
    report_type: ReportType
    summary: str
    findings: list[dict[str, Any]] = Field(default_factory=list)
