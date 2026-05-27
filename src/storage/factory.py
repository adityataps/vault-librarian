"""Storage factory — builds the right backend from app config."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .base import StorageBackend

if TYPE_CHECKING:
    from src.config import Settings

logger = logging.getLogger(__name__)


def build_storage(settings: "Settings") -> StorageBackend:
    """Create and return the configured storage backend.

    Selection logic:
    - ``storage_backend = "postgres"`` → PostgresStorage (optionally wrapped in RedisCache)
    - ``storage_backend = "sqlite"``   → SQLiteStorage (dev/offline; no Redis cache)
    """
    if settings.storage_backend == "sqlite":
        from .sqlite import SQLiteStorage

        logger.info("Storage: SQLite backend at %s", settings.sqlite_path)
        return SQLiteStorage(db_path=str(settings.sqlite_path))

    # Default: PostgreSQL
    from .postgres import PostgresStorage

    primary: StorageBackend = PostgresStorage(database_url=settings.database.url)
    logger.info("Storage: PostgreSQL backend at %s:%d", settings.database.host, settings.database.port)

    if settings.redis.enabled:
        from .redis_cache import RedisCache

        logger.info("Storage: Redis cache layer enabled at %s:%d", settings.redis.host, settings.redis.port)
        return RedisCache(primary=primary, redis_url=settings.redis.url)

    return primary
