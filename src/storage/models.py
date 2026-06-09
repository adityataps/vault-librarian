from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint
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
    tags: Mapped[str] = mapped_column(Text, default="[]")
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
