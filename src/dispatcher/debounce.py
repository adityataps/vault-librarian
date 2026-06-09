from __future__ import annotations

import asyncio
from typing import Callable


class DebounceMap:
    def __init__(self, default_delay: float = 3.0) -> None:
        self.default_delay = default_delay
        self._handles: dict[str, asyncio.TimerHandle] = {}

    def _loop(self) -> asyncio.AbstractEventLoop:
        return asyncio.get_event_loop()

    def schedule(self, path: str, callback: Callable[[], None], delay: float | None = None) -> None:
        d = delay if delay is not None else self.default_delay
        if path in self._handles:
            self._handles[path].cancel()
        self._handles[path] = self._loop().call_later(d, lambda: self._fire(path, callback))

    def _fire(self, path: str, callback: Callable[[], None]) -> None:
        self._handles.pop(path, None)
        callback()

    def cancel(self, path: str) -> None:
        if handle := self._handles.pop(path, None):
            handle.cancel()
