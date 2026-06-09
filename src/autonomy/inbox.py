from __future__ import annotations

import logging
import re
from datetime import date

from src.config import AppConfig
from src.vault.tools import VaultTools

log = logging.getLogger(__name__)

_INBOX_REL = ".librarian/Inbox.md"
_CHECKED_RE = re.compile(r"^- \[x\] (.+)$", re.MULTILINE)
_MOVE_RE = re.compile(r"Move `(.+?)` → `(.+?)`")


class LibrarianInbox:
    def __init__(self, cfg: AppConfig, tools: VaultTools) -> None:
        self._cfg = cfg
        self._tools = tools

    def _read(self) -> str:
        try:
            return self._tools.read_note(_INBOX_REL)
        except FileNotFoundError:
            return "# Librarian Inbox\n\n<!-- Check items to execute, then save -->\n\n"

    def _write(self, content: str) -> None:
        self._tools.create_note(_INBOX_REL, content)

    def propose(self, action: str) -> None:
        content = self._read()
        content = content.rstrip() + f"\n- [ ] {action}\n"
        self._write(content)

    def execute_checked(self) -> list[str]:
        content = self._read()
        if not _CHECKED_RE.search(content):
            return []

        executed: list[str] = []
        today = date.today().isoformat()

        def _execute_and_mark(m: re.Match) -> str:
            item = m.group(1)
            success = self._try_execute(item)
            if success:
                executed.append(item)
                return f"- ✅ Executed {today} — {item}"
            return m.group(0)

        updated = _CHECKED_RE.sub(_execute_and_mark, content)
        self._write(updated)
        return executed

    def _try_execute(self, item: str) -> bool:
        if m := _MOVE_RE.search(item):
            src, dst = m.group(1), m.group(2)
            try:
                self._tools.move_note(src, dst)
                log.info("Inbox executed: move %s → %s", src, dst)
                return True
            except Exception as exc:
                log.warning("Inbox move failed: %s", exc)
                return False
        log.info("Inbox item not auto-executable (manual review): %s", item)
        return False
