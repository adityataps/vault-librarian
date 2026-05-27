"""Vault file watcher — watchdog-based FSEvents listener that publishes to the event bus."""

from __future__ import annotations

import asyncio
import logging
import threading
from pathlib import Path
from typing import Any

from watchdog.events import (
    DirDeletedEvent,
    FileCreatedEvent,
    FileDeletedEvent,
    FileModifiedEvent,
    FileMovedEvent,
    FileSystemEvent,
    FileSystemEventHandler,
)
from watchdog.observers import Observer

from src.events.bus import Event, EventType, InMemoryEventBus, RedisEventBus

logger = logging.getLogger(__name__)

EventBus = InMemoryEventBus | RedisEventBus


class _VaultEventHandler(FileSystemEventHandler):
    """Watchdog handler that converts FS events to vault events and queues them."""

    def __init__(
        self,
        vault_root: Path,
        excluded_folders: set[str],
        excluded_files: set[str],
        queue: asyncio.Queue,
    ) -> None:
        self._vault_root = vault_root
        self._excluded_folders = excluded_folders
        self._excluded_files = excluded_files
        self._queue = queue

    def on_created(self, event: FileSystemEvent) -> None:
        if self._should_handle(event):
            self._enqueue(EventType.NOTE_CREATED, {"path": event.src_path})

    def on_modified(self, event: FileSystemEvent) -> None:
        if self._should_handle(event):
            self._enqueue(EventType.NOTE_MODIFIED, {"path": event.src_path})

    def on_deleted(self, event: FileSystemEvent) -> None:
        if isinstance(event, (FileDeletedEvent, DirDeletedEvent)):
            path = event.src_path
            if path.endswith(".md"):
                self._enqueue(EventType.NOTE_DELETED, {"path": path})

    def on_moved(self, event: FileSystemEvent) -> None:
        if isinstance(event, FileMovedEvent) and event.dest_path.endswith(".md"):
            self._enqueue(
                EventType.NOTE_MOVED,
                {"src_path": event.src_path, "dest_path": event.dest_path},
            )

    def _should_handle(self, event: FileSystemEvent) -> bool:
        if event.is_directory:
            return False
        if not event.src_path.endswith(".md"):
            return False
        try:
            rel = Path(event.src_path).relative_to(self._vault_root)
        except ValueError:
            return False
        for part in rel.parts[:-1]:
            if part in self._excluded_folders:
                return False
        if rel.name in self._excluded_files:
            return False
        return True

    def _enqueue(self, event_type: EventType, payload: dict[str, Any]) -> None:
        """Thread-safe enqueue to the asyncio queue."""
        # Make path relative to vault root
        raw_path = payload.get("path", "")
        if raw_path:
            try:
                payload["path"] = str(
                    Path(raw_path).relative_to(self._vault_root)
                )
            except ValueError:
                pass
        for key in ("src_path", "dest_path"):
            if key in payload:
                try:
                    payload[key] = str(
                        Path(payload[key]).relative_to(self._vault_root)
                    )
                except ValueError:
                    pass

        event = Event(type=event_type, payload=payload)
        # asyncio.Queue is not thread-safe from outside the loop; use call_soon_threadsafe
        try:
            loop = asyncio.get_event_loop()
            loop.call_soon_threadsafe(self._queue.put_nowait, event)
        except Exception as exc:
            logger.warning("Failed to enqueue event %s: %s", event_type, exc)


class VaultWatcher:
    """Runs watchdog in a thread and dispatches events to the async event bus.

    Usage::

        watcher = VaultWatcher(vault_root, event_bus, excluded_folders, excluded_files)
        await watcher.start()
        # ... runs in background until ...
        await watcher.stop()
    """

    def __init__(
        self,
        vault_root: Path,
        event_bus: EventBus,
        excluded_folders: list[str] | None = None,
        excluded_files: list[str] | None = None,
        debounce_seconds: float = 1.0,
    ) -> None:
        self._vault_root = vault_root.resolve()
        self._bus = event_bus
        self._excluded_folders: set[str] = set(
            excluded_folders or [".obsidian", ".trash", "_agent", "Attachments"]
        )
        self._excluded_files: set[str] = set(
            excluded_files or ["CLAUDE.md", "Work MOC.md"]
        )
        self._debounce = debounce_seconds
        self._queue: asyncio.Queue[Event] = asyncio.Queue()
        self._observer: Observer | None = None
        self._dispatch_task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start the watchdog observer and the async dispatch loop."""
        handler = _VaultEventHandler(
            self._vault_root,
            self._excluded_folders,
            self._excluded_files,
            self._queue,
        )
        self._observer = Observer()
        self._observer.schedule(handler, str(self._vault_root), recursive=True)
        self._observer.start()
        self._dispatch_task = asyncio.create_task(self._dispatch_loop())
        logger.info("Vault watcher started on %s", self._vault_root)

    async def stop(self) -> None:
        """Stop the observer and drain remaining events."""
        if self._observer:
            self._observer.stop()
            # Join in a thread executor so we don't block the event loop
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._observer.join)
        if self._dispatch_task:
            self._dispatch_task.cancel()
            try:
                await self._dispatch_task
            except asyncio.CancelledError:
                pass
        logger.info("Vault watcher stopped")

    async def _dispatch_loop(self) -> None:
        """Drain the event queue and publish to the bus, with debouncing per path."""
        pending: dict[str, Event] = {}  # path → latest event (debounce buffer)

        async def flush() -> None:
            for event in list(pending.values()):
                await self._bus.publish(event)
            pending.clear()

        try:
            while True:
                try:
                    event = await asyncio.wait_for(
                        self._queue.get(), timeout=self._debounce
                    )
                    key = event.payload.get("path") or event.id
                    pending[key] = event  # newer event for same path wins
                except asyncio.TimeoutError:
                    if pending:
                        await flush()
        except asyncio.CancelledError:
            await flush()  # Publish any buffered events before shutdown
