from __future__ import annotations

import logging
from datetime import datetime

from src.config import AppConfig
from src.vault.tools import VaultTools

log = logging.getLogger(__name__)

_ACTIVITY_REL = "Librarian/Activity.md"
_HEADER = "# Librarian Activity\n\n"

_CALLOUT: dict[str, str] = {
    "executed": "success",
    "enriched": "tip",
    "proposed": "warning",
    "error": "failure",
    "info": "info",
}


class ActivityLog:
    def __init__(self, cfg: AppConfig, tools: VaultTools) -> None:
        self._cfg = cfg
        self._tools = tools

    def append(self, agent: str, changes: list[str], outcome: str = "info") -> None:
        if not changes:
            return

        callout = _CALLOUT.get(outcome, "info")
        body = "\n".join(f"> {c}" for c in changes)
        block = f"\n> [!{callout}] {agent}\n{body}\n"

        try:
            existing = self._tools.read_note(_ACTIVITY_REL)
        except FileNotFoundError:
            existing = _HEADER

        date_heading = f"## {datetime.now().strftime('%Y-%m-%d')}"
        if date_heading in existing:
            # Advance past the heading line's trailing newline so new entries
            # are appended after existing ones (chronological order within the day).
            idx = existing.index(date_heading) + len(date_heading)
            if idx < len(existing) and existing[idx] == "\n":
                idx += 1
            # Find end of this day's section (next heading or EOF)
            next_heading = existing.find("\n##", idx)
            insert_at = next_heading if next_heading != -1 else len(existing)
            updated = existing[:insert_at] + block + existing[insert_at:]
        else:
            after_header = existing[len(_HEADER):] if existing.startswith(_HEADER) else existing
            updated = _HEADER + f"\n{date_heading}\n" + block + after_header

        self._tools.create_note(_ACTIVITY_REL, updated)
