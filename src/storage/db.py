from __future__ import annotations

from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.config import AppConfig
from src.storage.models import Base


class Database:
    def __init__(self, url: str) -> None:
        self.url = url
        self.engine: AsyncEngine | None = None
        self._session_factory = None

    async def initialize(self) -> None:
        self.engine = create_async_engine(self.url, echo=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self._session_factory = sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )

    def session(self) -> AsyncSession:
        if self._session_factory is None:
            raise RuntimeError("Database not initialized. Call initialize() first.")
        return self._session_factory()

    async def close(self) -> None:
        if self.engine:
            await self.engine.dispose()
            self.engine = None


def build_db(cfg: AppConfig) -> Database:
    librarian_dir = Path(cfg.vault_path) / ".librarian"
    librarian_dir.mkdir(exist_ok=True)
    db_path = librarian_dir / "librarian.db"
    return Database(f"sqlite+aiosqlite:///{db_path}")
