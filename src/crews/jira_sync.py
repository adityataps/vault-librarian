"""JiraSyncCrew — syncs Jira tickets to vault notes on a schedule.

Fetches tickets via JiraClient, upserts to storage, and creates/updates markdown files.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from crewai import Crew, Task

if TYPE_CHECKING:
    from src.llm.router import LLMRouter
    from src.storage.base import StorageBackend
    from src.tools.jira_client import JiraClient

logger = logging.getLogger(__name__)


@dataclass
class JiraSyncResult:
    tickets_fetched: int = 0
    notes_created: int = 0
    notes_updated: int = 0
    errors: list[str] = field(default_factory=list)


NOTE_TEMPLATE = """\
---
title: "{summary}"
type: Story
jira_key: {key}
jira_status: "{status}"
jira_type: "{issue_type}"
priority: "{priority}"
assignee: "{assignee}"
parent: "{parent_key}"
tags: {tags}
labels: {labels}
last_synced: "{last_synced}"
---

# {key}: {summary}

**Status:** {status}  
**Type:** {issue_type}  
**Priority:** {priority}  
**Assignee:** {assignee}  
{parent_line}

## Description

{description}

## Notes

<!-- Add your personal notes here — this section is preserved on re-sync -->
"""


class JiraSyncCrew:
    """Fetches Jira tickets and syncs them as vault notes."""

    def __init__(
        self,
        llm_router: "LLMRouter",
        storage: "StorageBackend",
        jira_client: "JiraClient",
        vault_root: Path,
        jira_folder: str = "Work/Jira",
        jql_filter: str = "project = AICOE AND updated >= -7d",
    ) -> None:
        self._router = llm_router
        self._storage = storage
        self._jira = jira_client
        self._vault_root = vault_root
        self._jira_folder = jira_folder
        self._jql = jql_filter

    async def run(self) -> JiraSyncResult:
        """Async run — fetches tickets and syncs notes. Returns sync result."""
        from src.agents.jira_sync import create_jira_sync_agent
        from src.storage.models import JiraTicketCreate
        from datetime import datetime, timezone

        result = JiraSyncResult()

        # 1. Fetch tickets from Jira
        try:
            raw_issues = await self._jira.search_issues(
                jql=self._jql, max_results=100
            )
            result.tickets_fetched = len(raw_issues)
            logger.info("Fetched %d Jira tickets", result.tickets_fetched)
        except Exception as exc:
            result.errors.append(f"Jira fetch failed: {exc}")
            logger.error("Jira fetch failed: %s", exc)
            return result

        # 2. Process each ticket
        for raw in raw_issues:
            try:
                ticket_data = self._jira.extract_ticket_data(raw)
                await self._upsert_ticket(ticket_data, result)
            except Exception as exc:
                result.errors.append(f"{raw.get('key', '?')}: {exc}")
                logger.warning("Failed to sync %s: %s", raw.get("key"), exc)

        logger.info(
            "Jira sync complete: %d created, %d updated, %d errors",
            result.notes_created,
            result.notes_updated,
            len(result.errors),
        )
        return result

    async def _upsert_ticket(self, ticket_data: dict, result: JiraSyncResult) -> None:
        """Create or update a vault note for this ticket."""
        from src.storage.models import JiraTicketCreate
        from datetime import datetime, timezone

        key = ticket_data["key"]
        note_filename = f"{key}.md"
        note_path = Path(self._jira_folder) / note_filename
        abs_path = self._vault_root / note_path

        # Save to storage
        ticket_create = JiraTicketCreate(
            key=key,
            summary=ticket_data["summary"],
            description=ticket_data.get("description"),
            status=ticket_data["status"],
            issue_type=ticket_data["issue_type"],
            priority=ticket_data.get("priority") or "Medium",
            assignee=ticket_data.get("assignee"),
            parent_key=ticket_data.get("parent_key"),
            labels=ticket_data.get("labels", []),
            repos=ticket_data.get("repos", []),
            jira_created_at=ticket_data.get("jira_created_at"),
            jira_updated_at=ticket_data["jira_updated_at"],
        )
        await self._storage.save_jira_ticket(ticket_create)

        # Build note content
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        parent_line = (
            f"**Parent:** [[{ticket_data['parent_key']}]]"
            if ticket_data.get("parent_key")
            else ""
        )

        # Preserve existing personal notes section if file exists
        existing_notes_section = "<!-- Add your personal notes here — this section is preserved on re-sync -->"
        if abs_path.exists():
            existing = abs_path.read_text(encoding="utf-8")
            marker = "## Notes\n\n"
            if marker in existing:
                existing_notes_section = existing.split(marker, 1)[1].strip()
            result.notes_updated += 1
        else:
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            result.notes_created += 1

        content = NOTE_TEMPLATE.format(
            key=key,
            summary=ticket_data["summary"].replace('"', '\\"'),
            status=ticket_data["status"],
            issue_type=ticket_data["issue_type"],
            priority=ticket_data.get("priority") or "Medium",
            assignee=ticket_data.get("assignee") or "Unassigned",
            parent_key=ticket_data.get("parent_key") or "",
            tags=str(ticket_data.get("labels", [])),
            labels=str(ticket_data.get("labels", [])),
            last_synced=now,
            description=ticket_data.get("description") or "_No description provided._",
            parent_line=parent_line,
        ).rstrip()

        # Re-attach preserved notes section
        content = content + f"\n\n## Notes\n\n{existing_notes_section}\n"
        abs_path.write_text(content, encoding="utf-8")
