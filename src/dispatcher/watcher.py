from __future__ import annotations

from pathlib import Path
from typing import Callable

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer


class _Handler(FileSystemEventHandler):
    def __init__(self, callback: Callable[[str, str], None], excluded: set[str]) -> None:
        self._cb = callback
        self._excluded = excluded

    def _is_excluded(self, path: str) -> bool:
        return any(part in self._excluded for part in Path(path).parts)

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory and str(event.src_path).endswith(".md"):
            if not self._is_excluded(event.src_path):
                self._cb(str(event.src_path), "created")

    def on_modified(self, event: FileSystemEvent) -> None:
        if not event.is_directory and str(event.src_path).endswith(".md"):
            if not self._is_excluded(event.src_path):
                self._cb(str(event.src_path), "modified")


class VaultWatcher:
    def __init__(
        self, vault_root: str, excluded: set[str], callback: Callable[[str, str], None]
    ) -> None:
        self._observer = Observer()
        handler = _Handler(callback, excluded)
        self._observer.schedule(handler, vault_root, recursive=True)

    def start(self) -> None:
        self._observer.start()

    def stop(self) -> None:
        self._observer.stop()
        self._observer.join()
