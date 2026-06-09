from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager


class FileLockMap:
    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}

    def _get(self, path: str) -> asyncio.Lock:
        if path not in self._locks:
            self._locks[path] = asyncio.Lock()
        return self._locks[path]

    @asynccontextmanager
    async def acquire(self, path: str):
        async with self._get(path):
            yield
