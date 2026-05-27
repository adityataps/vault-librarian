"""Agent run and audit report API routes."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, status as http_status
from src.storage import AgentRun, AuditReport
from src.storage.models import ReportType

router = APIRouter()


async def _get_run_by_id(request: Request, run_id: UUID) -> AgentRun | None:
    storage = request.app.state.storage
    primary = getattr(storage, "_primary", storage)
    storage_name = primary.__class__.__name__

    if storage_name == "PostgresStorage":
        from sqlalchemy import select

        from src.storage.orm import AgentRunRow
        from src.storage.postgres import _run_from_row

        async with primary._session_factory() as session:
            result = await session.execute(
                select(AgentRunRow).where(AgentRunRow.id == run_id)
            )
            row = result.scalars().first()
            return _run_from_row(row) if row else None

    if storage_name == "SQLiteStorage":
        from sqlalchemy import text

        from src.storage.sqlite import _parse_dt

        async with primary._session_factory() as session:
            result = await session.execute(
                text("SELECT * FROM agent_runs WHERE id = :id"),
                {"id": str(run_id)},
            )
            row = result.mappings().first()
            if row is None:
                return None

            return AgentRun(
                id=UUID(row["id"]),
                crew_name=row["crew_name"],
                agent_name=row["agent_name"],
                trigger_type=row["trigger_type"],  # type: ignore[arg-type]
                status=row["status"],  # type: ignore[arg-type]
                started_at=_parse_dt(row["started_at"]) or datetime.now(timezone.utc),
                completed_at=_parse_dt(row["completed_at"]),
                duration_ms=row["duration_ms"],
                notes_processed=row["notes_processed"] or 0,
                notes_created=row["notes_created"] or 0,
                notes_updated=row["notes_updated"] or 0,
                notes_moved=row["notes_moved"] or 0,
                tokens_used=row["tokens_used"] or 0,
                error_message=row["error_message"],
                metadata=json.loads(row["metadata"]) if row["metadata"] else {},
            )

    for run in await storage.get_recent_runs(limit=1000):
        if run.id == run_id:
            return run
    return None


@router.get("", response_model=list[AgentRun])
async def list_runs(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
) -> list[AgentRun]:
    return await request.app.state.storage.get_recent_runs(limit=limit)


@router.get("/reports", response_model=list[AuditReport])
async def list_reports(
    request: Request,
    report_type: ReportType | None = Query(default=None, alias="type"),
    limit: int = Query(default=10, ge=1, le=100),
) -> list[AuditReport]:
    return await request.app.state.storage.get_recent_reports(
        report_type=report_type,
        limit=limit,
    )


@router.get("/{run_id}", response_model=AgentRun)
async def get_run(run_id: UUID, request: Request) -> AgentRun:
    run = await _get_run_by_id(request, run_id)
    if run is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Run not found",
        )
    return run
