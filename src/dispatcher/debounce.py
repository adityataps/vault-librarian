from __future__ import annotations

import asyncio
from typing import Callable


class DebounceMap:
    def __init__(
        self,
        default_delay: float = 3.0,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        self.default_delay = default_delay
        self._handles: dict[str, asyncio.TimerHandle] = {}
        # Captured at construction so schedule() is safe from any thread.
        self._loop: asyncio.AbstractEventLoop | None = loop

    def _get_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is not None:
            return self._loop
        return asyncio.get_event_loop()

    def schedule(self, path: str, callback: Callable[[], None], delay: float | None = None) -> None:
        d = delay if delay is not None else self.default_delay
        loop = self._get_loop()

        def _do_schedule() -> None:
            if path in self._handles:
                self._handles[path].cancel()
            self._handles[path] = loop.call_later(d, lambda: self._fire(path, callback))

        # call_soon_threadsafe is safe to call from any thread (e.g. watchdog).
        loop.call_soon_threadsafe(_do_schedule)

    def _fire(self, path: str, callback: Callable[[], None]) -> None:
        self._handles.pop(path, None)
        callback()

    def cancel(self, path: str) -> None:
        def _do_cancel() -> None:
            if handle := self._handles.pop(path, None):
                handle.cancel()

        loop = self._get_loop()
        loop.call_soon_threadsafe(_do_cancel)
