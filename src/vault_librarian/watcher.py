"""Filesystem watcher (architecture.md §4.1).

Watches for *.md create/modify/delete, filters by the ignore-list, and forwards raw events
into the dispatcher's asyncio event loop via a thread-safe queue (watchdog's observer runs
in its own OS thread).
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver

logger = logging.getLogger("vault_librarian.watcher")


class _Handler(FileSystemEventHandler):
    def __init__(
        self,
        vault_path: Path,
        ignore_paths: list[str],
        loop: asyncio.AbstractEventLoop,
        queue: "asyncio.Queue[tuple[str, Path]]",
    ):
        self._vault_path = vault_path
        self._ignore_paths = ignore_paths
        self._loop = loop
        self._queue = queue

    def _relevant(self, raw_path: str) -> Path | None:
        path = Path(raw_path)
        if path.suffix.lower() != ".md":
            return None
        try:
            rel = path.relative_to(self._vault_path)
        except ValueError:
            return None
        rel_str = str(rel)
        if any(rel_str.startswith(ip.rstrip("/")) for ip in self._ignore_paths):
            return None
        return path

    def _forward(self, event_type: str, raw_path: str) -> None:
        path = self._relevant(raw_path)
        if path is None:
            return
        self._loop.call_soon_threadsafe(self._queue.put_nowait, (event_type, path))

    def on_created(self, event) -> None:
        if not event.is_directory:
            self._forward("created", event.src_path)

    def on_modified(self, event) -> None:
        if not event.is_directory:
            self._forward("modified", event.src_path)

    def on_deleted(self, event) -> None:
        if not event.is_directory:
            self._forward("deleted", event.src_path)

    def on_moved(self, event) -> None:
        if not event.is_directory:
            self._forward("deleted", event.src_path)
            self._forward("created", event.dest_path)


class Watcher:
    """Owns the watchdog observer thread. Raw (event_type, path) tuples land on `events`, an
    asyncio.Queue consumed by the dispatcher's debounce layer. Must be constructed from
    within a running event loop."""

    def __init__(self, vault_path: Path, ignore_paths: list[str], use_polling: bool = False):
        self.vault_path = vault_path
        self.events: "asyncio.Queue[tuple[str, Path]]" = asyncio.Queue()
        self._observer = PollingObserver() if use_polling else Observer()
        self._handler = _Handler(
            vault_path, ignore_paths, asyncio.get_running_loop(), self.events
        )

    def start(self) -> None:
        self._observer.schedule(self._handler, str(self.vault_path), recursive=True)
        self._observer.start()
        logger.info(
            "watching %s (polling=%s)",
            self.vault_path,
            isinstance(self._observer, PollingObserver),
        )

    def stop(self) -> None:
        self._observer.stop()
        self._observer.join(timeout=5)
