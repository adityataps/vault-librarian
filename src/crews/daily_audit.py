"""DailyAuditCrew — scheduled once-daily vault health check.

Runs: Auditor (scan for issues) → Archivist (fix metadata) → Linker (repair broken links)
Produces an AuditReport saved to storage.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from crewai import Crew, Task

if TYPE_CHECKING:
    from src.llm.router import LLMRouter
    from src.storage.base import StorageBackend
    from src.tools.graph_traversal import GraphTraversalTool
    from src.tools.vector_search import VectorSearchTool

logger = logging.getLogger(__name__)


class DailyAuditCrew:
    """Runs a full vault health audit and persists findings as an AuditReport."""

    def __init__(
        self,
        llm_router: "LLMRouter",
        storage: "StorageBackend",
        graph_traversal: "GraphTraversalTool | None" = None,
        vector_search: "VectorSearchTool | None" = None,
    ) -> None:
        self._router = llm_router
        self._storage = storage
        self._graph_traversal = graph_traversal
        self._vector_search = vector_search

    def run(self, vault_stats: dict) -> str:
        """Run the daily audit. Returns the audit summary string.

        Args:
            vault_stats: Pre-computed stats dict with keys:
                total_notes, notes_by_folder, stale_notes (list of paths),
                broken_links (list of dicts), orphan_notes (list of paths),
                notes_missing_type (list of paths)
        """
        from src.agents.auditor import create_auditor
        from src.agents.archivist import create_archivist
        from src.agents.linker import create_linker

        auditor = create_auditor(self._router, self._storage, self._graph_traversal)
        archivist = create_archivist(self._router, self._storage, self._vector_search)
        linker = create_linker(self._router, self._storage, self._vector_search, self._graph_traversal)

        stats_summary = (
            f"Vault statistics as of {datetime.now(timezone.utc).strftime('%Y-%m-%d')}:\n"
            f"- Total notes: {vault_stats.get('total_notes', 0)}\n"
            f"- Stale notes (90+ days): {len(vault_stats.get('stale_notes', []))}\n"
            f"- Broken wikilinks: {len(vault_stats.get('broken_links', []))}\n"
            f"- Orphan notes: {len(vault_stats.get('orphan_notes', []))}\n"
            f"- Notes missing 'type' field: {len(vault_stats.get('notes_missing_type', []))}\n"
        )

        audit_task = Task(
            description=(
                f"{stats_summary}\n"
                "Perform a comprehensive audit of this vault. Categorize findings by severity "
                "(critical/warning/info). For each issue, provide: the note path, the problem, "
                "and a specific recommended action. Format as a structured report."
            ),
            expected_output=(
                "Structured audit report with sections: CRITICAL, WARNINGS, INFO. "
                "Each finding includes: path, issue, recommendation."
            ),
            agent=auditor,
        )

        metadata_task = Task(
            description=(
                "Based on the audit findings, identify the top 10 notes with missing or "
                "incorrect metadata (type, status, tags). For each, suggest the correct "
                "frontmatter values as a JSON object."
            ),
            expected_output="List of {path, suggested_frontmatter} objects for metadata corrections",
            agent=archivist,
            context=[audit_task],
        )

        link_repair_task = Task(
            description=(
                "Based on the audit, identify broken wikilinks and suggest corrections. "
                "For each broken link, find the most likely intended target note using "
                "fuzzy matching on note titles. Return as {broken_link, suggested_fix} pairs."
            ),
            expected_output="List of broken link repairs: {source_note, broken_link, suggested_target}",
            agent=linker,
            context=[audit_task],
        )

        crew = Crew(
            agents=[auditor, archivist, linker],
            tasks=[audit_task, metadata_task, link_repair_task],
            verbose=False,
        )

        try:
            result = crew.kickoff()
            return str(result)
        except Exception as exc:
            logger.error("DailyAuditCrew failed: %s", exc)
            return f"Audit failed: {exc}"
