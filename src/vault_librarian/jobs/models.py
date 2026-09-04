"""SQLAlchemy models for job/run state (architecture.md §4.13, §4.19).

`FileState` is the crash-recovery/idempotency/revert-detection table: one row per
(path, workflow), recording both the pre-transform (`input_hash`) and post-transform
(`output_hash`) content hash. `WorkflowRun` is a human-inspectable run history.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class FileState(Base):
    __tablename__ = "file_state"

    path: Mapped[str] = mapped_column(String, primary_key=True)
    workflow: Mapped[str] = mapped_column(String, primary_key=True)
    input_hash: Mapped[str] = mapped_column(String)
    output_hash: Mapped[str] = mapped_column(String)
    processed_at: Mapped[datetime] = mapped_column(DateTime)


class WorkflowRun(Base):
    __tablename__ = "workflow_run"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    path: Mapped[str] = mapped_column(String)
    workflows: Mapped[str] = mapped_column(String)  # comma-joined list run this cycle
    status: Mapped[str] = mapped_column(String)  # ok, dry-run, error, skipped
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    commit_sha: Mapped[str | None] = mapped_column(String, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime)
    finished_at: Mapped[datetime] = mapped_column(DateTime)
