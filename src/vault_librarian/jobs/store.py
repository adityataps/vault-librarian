"""Async SQLite-backed job/run state store (architecture.md §4.13, §4.19).

Single-writer by construction (the PID lockfile guarantees exactly one process per vault);
runs with WAL mode for future concurrent reads (e.g. a status endpoint polled while the
worker writes).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from vault_librarian.jobs.models import Base, FileState, WorkflowRun


class JobStore:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self._engine = create_async_engine(f"sqlite+aiosqlite:///{self.db_path}")
        self._sessionmaker = async_sessionmaker(self._engine, expire_on_commit=False)

    async def init(self) -> None:
        async with self._engine.begin() as conn:
            await conn.exec_driver_sql("PRAGMA journal_mode=WAL")
            await conn.run_sync(Base.metadata.create_all)

    async def close(self) -> None:
        await self._engine.dispose()

    async def get_file_state(self, path: str, workflow: str) -> FileState | None:
        async with self._sessionmaker() as session:
            return await session.get(FileState, (path, workflow))

    async def record_file_state(self, path: str, workflow: str, input_hash: str, output_hash: str) -> None:
        async with self._sessionmaker() as session:
            state = await session.get(FileState, (path, workflow))
            now = datetime.now(timezone.utc)
            if state is None:
                session.add(
                    FileState(
                        path=path,
                        workflow=workflow,
                        input_hash=input_hash,
                        output_hash=output_hash,
                        processed_at=now,
                    )
                )
            else:
                state.input_hash = input_hash
                state.output_hash = output_hash
                state.processed_at = now
            await session.commit()

    async def record_run(
        self,
        path: str,
        workflows: list[str],
        status: str,
        detail: str | None,
        commit_sha: str | None,
        started_at: datetime,
        finished_at: datetime,
    ) -> None:
        async with self._sessionmaker() as session:
            session.add(
                WorkflowRun(
                    path=path,
                    workflows=",".join(workflows),
                    status=status,
                    detail=detail,
                    commit_sha=commit_sha,
                    started_at=started_at,
                    finished_at=finished_at,
                )
            )
            await session.commit()

    async def recent_runs(self, limit: int = 20) -> list[WorkflowRun]:
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(WorkflowRun).order_by(WorkflowRun.id.desc()).limit(limit)
            )
            return list(result.scalars())

    async def file_states_for(self, path: str) -> list[FileState]:
        async with self._sessionmaker() as session:
            result = await session.execute(select(FileState).where(FileState.path == path))
            return list(result.scalars())
