from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

from src.config import AppConfig
from src.vault.tools import VaultTools

log = logging.getLogger(__name__)

_INBOX_REL = "Librarian/Inbox.md"
_MOVE_RE = re.compile(r"Move `(.+?)` → `(.+?)`")

_PENDING_START = "%% Pending proposals (processed by consolidate) %%"
_PENDING_END = "%% End pending %%"

# Matches a top-level checked item: `- [x] **Category**` or `- [x] action`
_TOP_CHECKED_RE = re.compile(r"^- \[x\] (.+)$", re.MULTILINE)
# Matches an indented child item (4 spaces): `    - [ ] action`
_CHILD_RE = re.compile(r"^    - \[[ x]\] (.+)$")
# Matches an indented unchecked child: `    - [ ] action`
_CHILD_UNCHECKED_RE = re.compile(r"^    - \[ \] (.+)$")

# Matches executed timestamp: (✅ Executed 2026-06-09 16:04 ET)
_EXECUTED_TS_RE = re.compile(r"\(✅ Executed (\d{4}-\d{2}-\d{2} \d{2}:\d{2}) ET\)")

# US Eastern timezone (ET)
_ET = timezone(timedelta(hours=-4))

_CONSOLIDATE_PROMPT = """\
You are an Obsidian vault librarian. Below is a user's action inbox with two sections:

**Curated (visible to user):**
{curated}

**Pending (new raw proposals from agents):**
{pending}

Merge the pending items into the curated list. Rules:
- Group items into logical categories using this nested checkbox format:
  ```
  - [ ] **Category name**
      - [ ] Specific action item
      - [ ] Another action item
  ```
- Choose clear, descriptive category names (e.g. "Stub creation", "File reorganization", "Link suggestions").
- Each action item must be indented with exactly 4 spaces under its category.
- Remove exact and semantic duplicates (e.g. "Create stub for [[GCP]]" and \
"Create stub for [[Google Cloud Platform]]" are the same concept — keep the \
more descriptive one).
- Remove items that reference template placeholders like [[Note Title]], \
[[wikilink]], [[filename]].
- Remove items already executed (lines containing ~~strikethrough~~ with a ✅ timestamp).
- Preserve any checked `- [x]` items from the curated section as-is, \
keeping them under their original category if possible.
- Do NOT invent new action items. Only use items from the input.
- Output ONLY the final categorized task list. No extra commentary.
"""


class LibrarianInbox:
    def __init__(self, cfg: AppConfig, tools: VaultTools) -> None:
        self._cfg = cfg
        self._tools = tools

    @staticmethod
    def _executed_stamp() -> str:
        now = datetime.now(_ET)
        return f"(✅ Executed {now.strftime('%Y-%m-%d %H:%M')} ET)"

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

    # ── pending block helpers ──────────────────────────────────────────

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

    # ── propose ────────────────────────────────────────────────────────

    def propose(self, action: str) -> None:
        content = self._read()
        # Dedup: check both the visible curated section and pending block
        if f"- [ ] {action}" in content:
            log.debug("Inbox: skipping duplicate proposal: %s", action)
            return
        content = self._append_pending(content, action)
        self._write(content)
        log.debug("Inbox: proposed → pending: %s", action)

    # ── consolidate ───────────────────────────────────────────────────

    async def consolidate(self) -> int:
        """Deduplicate, recategorize, and merge pending items into the curated list.

        Always re-processes the full curated list through the LLM, even
        when there are no pending items, so categories stay tidy.
        Also cleans up expired executed items first.
        Returns the number of curated items after consolidation.
        """
        from src.llm.factory import build_llm

        # Clean up old executed items first
        self.cleanup_executed()

        content = self._read()
        body, pending = self._split_pending(content)

        # Collect all existing curated lines (categories + children + done)
        curated_lines = [
            line.rstrip()
            for line in body.splitlines()
            if re.match(r"^( {4})?- (\[[ x]\] |~~)", line)
        ]

        if not curated_lines and not pending:
            log.info("Inbox consolidate: nothing to process")
            return 0

        llm = build_llm(self._cfg, tier="heavy")
        prompt = _CONSOLIDATE_PROMPT.format(
            curated="\n".join(curated_lines) if curated_lines else "(empty)",
            pending="\n".join(pending) if pending else "(none)",
        )
        result = await llm.ainvoke(prompt)
        merged_text = result.content if hasattr(result, "content") else str(result)

        # Accept both top-level and indented list items from the LLM
        merged_lines = [
            line.rstrip()
            for line in merged_text.strip().splitlines()
            if re.match(r"^( {4})?- ", line.rstrip())
        ]

        if not merged_lines:
            log.warning("Inbox consolidate: LLM returned no items, keeping existing")
            return 0

        # Rebuild: header + merged list + empty pending block
        header_lines = [
            line
            for line in body.splitlines()
            if not re.match(r"^( {4})?- (\[[ x]\] |~~)", line)
        ]
        header = "\n".join(header_lines).rstrip()
        new_content = (
            f"{header}\n\n"
            + "\n".join(merged_lines)
            + f"\n\n{_PENDING_START}\n{_PENDING_END}\n"
        )
        self._write(new_content)

        item_count = sum(1 for ln in merged_lines if ln.startswith("    - "))
        categories = sum(1 for ln in merged_lines if re.match(r"^- \[ \] \*\*", ln))
        log.info(
            "Inbox consolidate: %d curated + %d pending → %d items in %d categories",
            len(curated_lines),
            len(pending),
            item_count,
            categories,
        )
        return item_count

    def cleanup_executed(self) -> int:
        """Remove executed items older than inbox_retention_hours. Returns count removed."""
        content = self._read()
        cutoff = datetime.now(_ET) - timedelta(hours=self._cfg.inbox_retention_hours)
        lines = content.splitlines()
        kept: list[str] = []
        removed = 0

        i = 0
        while i < len(lines):
            line = lines[i]
            if self._is_expired_line(line, cutoff):
                # Top-level expired — also skip expired children
                removed += 1
                i += 1
                while i < len(lines) and lines[i].startswith("    - "):
                    if self._is_expired_line(lines[i], cutoff):
                        removed += 1
                    # Drop all children of an expired category
                    i += 1
                continue
            # Indented expired line (parent not expired)
            if line.startswith("    - ") and self._is_expired_line(line, cutoff):
                removed += 1
                i += 1
                continue
            kept.append(line)
            i += 1

        if removed:
            self._write("\n".join(kept) + "\n")
            log.info("Inbox cleanup: removed %d expired item(s)", removed)
        return removed

    @staticmethod
    def _is_expired_line(line: str, cutoff: datetime) -> bool:
        m = _EXECUTED_TS_RE.search(line)
        if not m:
            return False
        try:
            ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M").replace(tzinfo=_ET)
            return ts < cutoff
        except ValueError:
            return False

    # ── execute checked ───────────────────────────────────────────────

    def execute_checked(self) -> list[str]:
        """Execute checked items. A checked category cascades to all its children."""
        content = self._read()
        lines = content.splitlines()
        executed: list[str] = []
        stamp = self._executed_stamp()
        result_lines: list[str] = []

        i = 0
        while i < len(lines):
            line = lines[i]

            # Check for a top-level checked item
            top_match = _TOP_CHECKED_RE.match(line)
            if not top_match:
                result_lines.append(line)
                i += 1
                continue

            top_text = top_match.group(1)

            # Collect any indented children following this top-level item
            children_start = i + 1
            children: list[tuple[int, str]] = []
            j = children_start
            while j < len(lines) and _CHILD_RE.match(lines[j]):
                children.append((j, lines[j]))
                j += 1

            if children:
                # Category header checked — cascade to all unchecked children
                category_executed: list[str] = []
                child_results: list[str] = []
                for _, child_line in children:
                    child_unchecked = _CHILD_UNCHECKED_RE.match(child_line)
                    if child_unchecked:
                        item = child_unchecked.group(1)
                        if self._try_execute(item):
                            category_executed.append(item)
                            child_results.append(
                                f"    - ~~{item}~~ {stamp}"
                            )
                        else:
                            child_results.append(child_line)
                    else:
                        # Already checked/done, keep as-is
                        child_results.append(child_line)

                if category_executed:
                    executed.extend(category_executed)
                    all_done = all("~~" in cl for cl in child_results)
                    if all_done:
                        result_lines.append(
                            f"- ~~{top_text}~~ {stamp}"
                        )
                    else:
                        result_lines.append(f"- [x] {top_text}")
                else:
                    result_lines.append(line)
                result_lines.extend(child_results)
                i = j
            else:
                # Leaf-level checked item (no children)
                if self._try_execute(top_text):
                    executed.append(top_text)
                    result_lines.append(
                        f"- ~~{top_text}~~ {stamp}"
                    )
                else:
                    result_lines.append(line)
                i += 1

        if executed:
            self._write("\n".join(result_lines) + "\n")
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
