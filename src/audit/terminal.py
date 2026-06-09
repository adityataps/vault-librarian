from __future__ import annotations

import logging
from collections import deque
from datetime import datetime

from rich.console import Console

log = logging.getLogger(__name__)

_console = Console(highlight=False)

_STYLE: dict[str, str] = {
    "executed": "bold green",
    "enriched": "bold cyan",
    "proposed": "bold yellow",
    "error": "bold red",
    "info": "dim",
}

_MAX_ENTRIES = 50


class RichActivityFeed:
    def __init__(self) -> None:
        self._entries: deque[str] = deque(maxlen=_MAX_ENTRIES)

    def feed(self, agent: str, changes: list[str], outcome: str = "info") -> None:
        if not changes:
            return
        style = _STYLE.get(outcome, "dim")
        ts = datetime.now().strftime("%H:%M:%S")
        summary = changes[0] if len(changes) == 1 else f"{changes[0]} (+{len(changes) - 1} more)"
        line = f"[dim]{ts}[/dim] [{style}]{agent}[/{style}] {summary}"
        self._entries.append(line)
        _console.print(line)

    def recent(self, n: int = 10) -> list[str]:
        return list(self._entries)[-n:]


_feed: RichActivityFeed | None = None


def get_feed() -> RichActivityFeed:
    global _feed
    if _feed is None:
        _feed = RichActivityFeed()
    return _feed
