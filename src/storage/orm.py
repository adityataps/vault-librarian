"""SQLAlchemy ORM models matching the Alembic schema."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from pgvector.sqlalchemy import Vector


class Base(DeclarativeBase):
    pass


class NoteRow(Base):
    __tablename__ = "notes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    path: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    folder: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    type: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    word_count: Mapped[int] = mapped_column(Integer, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("NOW()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("NOW()")
    )
    last_modified: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "type IN ('Story','Meeting','TechNote','Project','Template','Reference','Career','Other')",
            name="notes_type_check",
        ),
        CheckConstraint(
            "status IN ('Backlog','Planning','In Progress','Blocked','Done')",
            name="notes_status_check",
        ),
        Index("idx_notes_folder", "folder"),
        Index("idx_notes_type", "type"),
        Index("idx_notes_status", "status"),
        Index("idx_notes_updated_at", "updated_at"),
    )

    embeddings: Mapped[list["EmbeddingRow"]] = relationship(
        "EmbeddingRow", back_populates="note", cascade="all, delete-orphan"
    )
    outgoing_links: Mapped[list["WikilinkRow"]] = relationship(
        "WikilinkRow",
        foreign_keys="WikilinkRow.source_note_id",
        cascade="all, delete-orphan",
    )


class EmbeddingRow(Base):
    __tablename__ = "embeddings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    note_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("notes.id", ondelete="CASCADE"), nullable=False
    )
    vector: Mapped[list[float]] = mapped_column(Vector(1536), nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("NOW()")
    )

    __table_args__ = (
        UniqueConstraint("note_id", "model", name="embeddings_note_id_model_key"),
    )

    note: Mapped["NoteRow"] = relationship("NoteRow", back_populates="embeddings")


class WikilinkRow(Base):
    __tablename__ = "wikilinks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    source_note_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("notes.id", ondelete="CASCADE"), nullable=False
    )
    target_path: Mapped[str] = mapped_column(Text, nullable=False)
    target_note_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("notes.id", ondelete="SET NULL"), nullable=True
    )
    link_text: Mapped[str] = mapped_column(Text, nullable=False)
    is_broken: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("NOW()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("NOW()")
    )

    __table_args__ = (
        Index("idx_wikilinks_source", "source_note_id"),
        Index("idx_wikilinks_target_path", "target_path"),
    )


class JiraTicketRow(Base):
    __tablename__ = "jira_tickets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    note_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("notes.id", ondelete="SET NULL"), nullable=True
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    issue_type: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[str | None] = mapped_column(Text, nullable=True)
    assignee: Mapped[str | None] = mapped_column(Text, nullable=True)
    parent_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    repos: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    labels: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    jira_created_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    jira_updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    last_synced_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("NOW()")
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("NOW()")
    )

    __table_args__ = (
        Index("idx_jira_tickets_status", "status"),
        Index("idx_jira_tickets_note_id", "note_id"),
    )


class AgentRunRow(Base):
    __tablename__ = "agent_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    crew_name: Mapped[str] = mapped_column(Text, nullable=False)
    agent_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    trigger_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("NOW()")
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes_processed: Mapped[int] = mapped_column(Integer, server_default="0")
    notes_created: Mapped[int] = mapped_column(Integer, server_default="0")
    notes_updated: Mapped[int] = mapped_column(Integer, server_default="0")
    notes_moved: Mapped[int] = mapped_column(Integer, server_default="0")
    tokens_used: Mapped[int] = mapped_column(Integer, server_default="0")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # "metadata" is reserved by SQLAlchemy DeclarativeBase; use run_metadata with explicit column name
    run_metadata: Mapped[dict] = mapped_column("metadata", JSONB, server_default="{}")

    audit_reports: Mapped[list["AuditReportRow"]] = relationship(
        "AuditReportRow", back_populates="agent_run", cascade="all, delete-orphan"
    )


class TagRow(Base):
    __tablename__ = "tags"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    normalized_name: Mapped[str] = mapped_column(Text, nullable=False)
    usage_count: Mapped[int] = mapped_column(Integer, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("NOW()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("NOW()")
    )


class AuditReportRow(Base):
    __tablename__ = "audit_reports"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=True,
    )
    report_type: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    findings_count: Mapped[int] = mapped_column(Integer, server_default="0")
    findings: Mapped[list] = mapped_column(JSONB, server_default="[]")
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("NOW()")
    )

    agent_run: Mapped["AgentRunRow | None"] = relationship(
        "AgentRunRow", back_populates="audit_reports"
    )
