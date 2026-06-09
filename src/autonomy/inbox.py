from __future__ import annotations

import logging
import re
from datetime import date

from src.config import AppConfig
from src.vault.tools import VaultTools

log = logging.getLogger(__name__)

_INBOX_REL = "Librarian/Inbox.md"
_CHECKED_RE = re.compile(r"^- \[x\] (.+)$", re.MULTILINE)
_MOVE_RE = re.compile(r"Move `(.+?)` → `(.+?)`")

_PENDING_START = "%% Pending proposals (processed by consolidate) %%"
_PENDING_END = "%% End pending %%"

_CONSOLIDATE_PROMPT = """\
You are an Obsidian vault librarian. Below is a user's action inbox with two sections:

**Curated (visible to user):**
{curated}

**Pending (new raw proposals from agents):**
{pending}

Merge the pending items into the curated list. Rules:
- Remove exact and semantic duplicates (e.g. "Create stub for [[GCP]]" and "Create stub for [[Google Cloud Platform]]" are the same concept — keep the more descriptive one).
- Remove items that reference template placeholders like [[Note Title]], [[wikilink]], [[filename]].
- Remove items already completed (marked ✅).
- Keep the same markdown format: `- [ ] action text`
- Preserve any checked `- [x]` or completed `- ✅` items from the curated section as-is.
- Sort by type of action (stubs, moves, links, etc.) for readability.
- Do NOT invent new items. Only include items from the input.
- Output ONLY the final merged task list (lines starting with `- `). No headings, no explanation.
"""


class LibrarianInbox:
    def __init__(self, cfg: AppConfig, tools: VaultTools) -> None:
        self._cfg = cfg
        self._tools = tools

    def _read(self) -> str:
        try:
            return self._tools.read_note(_INBOX_REL)
        except FileNotFoundError:
            return (
                "# Librarian Inbox\n\n"
                "<!-- Check items to execute, then save -->\n\n"
                f"{_PENDING_START}\n{_PENDING_END}\n"
            )

    def _write(self, content: str) -> None:
        self._tools.create_note(_INBOX_REL, content)

    def _split_pending(self, content: str) -> tuple[str, list[str]]:
        """Split content into (body_without_pending, pending_items_list)."""
        start = content.find(_PENDING_START)
        end = content.find(_PENDING_END)
        if start == -1 or end == -1:
            return content, []
        pending_block = content[start + len(_PENDING_START) : end]
        items = [
            line.strip()
            for line in pending_block.strip().splitlines()
            if line.strip().startswith("- [ ]")
        ]
        body = content[:start].rstrip() + "\n"
        after = content[end + len(_PENDING_END) :].strip()
        if after:
            body += after + "\n"
        return body, items

    def _append_pending(self, content: str, action: str) -> str:
        """Append an action to the pending comment block, adding it if missing."""
        line = f"- [ ] {action}"
        start = content.find(_PENDING_START)
        end = content.find(_PENDING_END)
        if start == -1 or end == -1:
            return content.rstrip() + f"\n\n{_PENDING_START}\n{line}\n{_PENDING_END}\n"
        return content[:end] + f"{line}\n" + content[end:]

    def propose(self, action: str) -> None:
        content = self._read()
        # Dedup: check both the visible curated section and pending block
        if f"- [ ] {action}" in content:
            log.debug("Inbox: skipping duplicate proposal: %s", action)
            return
        content = self._append_pending(content, action)
        self._write(content)
        log.debug("Inbox: proposed → pending: %s", action)

    async def consolidate(self) -> int:
        """Use the LLM to deduplicate and merge pending items into the curated list.

        Returns the number of items promoted.
        """
        from src.llm.factory import build_llm

        content = self._read()
        body, pending = self._split_pending(content)
        if not pending:
            log.info("Inbox consolidate: nothing pending")
            return 0

        curated_lines = [
            line.strip()
            for line in body.splitlines()
            if line.strip().startswith(("- [ ]", "- [x]", "- ✅"))
        ]

        llm = build_llm(self._cfg)
        prompt = _CONSOLIDATE_PROMPT.format(
            curated="\n".join(curated_lines) if curated_lines else "(empty)",
            pending="\n".join(pending),
        )
        result = await llm.ainvoke(prompt)
        merged_text = result.content if hasattr(result, "content") else str(result)
        merged_lines = [
            line.strip()
            for line in merged_text.strip().splitlines()
            if line.strip().startswith("- ")
        ]

        if not merged_lines:
            log.warning("Inbox consolidate: LLM returned no items, keeping existing")
            return 0

        # Rebuild: header + merged list + empty pending block
        header_lines = [
            line
            for line in body.splitlines()
            if not line.strip().startswith(("- [ ]", "- [x]", "- ✅"))
        ]
        header = "\n".join(header_lines).rstrip()
        new_content = (
            f"{header}\n\n"
            + "\n".join(merged_lines)
            + f"\n\n{_PENDING_START}\n{_PENDING_END}\n"
        )
        self._write(new_content)

        promoted = len(merged_lines)
        log.info(
            "Inbox consolidate: %d pending → %d curated items",
            len(pending),
            promoted,
        )
        return promoted

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
