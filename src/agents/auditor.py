"""CrewAI auditor agent factory."""
from __future__ import annotations

from typing import TYPE_CHECKING

from crewai import Agent

from src.llm.router import LLMRouter, TaskType

from .base import _make_llm

if TYPE_CHECKING:
    from src.storage.base import StorageBackend
    from src.tools.graph_traversal import GraphTraversalTool


def create_auditor(
    router: LLMRouter,
    storage: StorageBackend,
    graph_traversal: GraphTraversalTool | None = None,
) -> Agent:
    return Agent(
        role="Vault Auditor",
        goal=(
            "Audit the Obsidian vault for health issues: stale notes (not updated in 90+ days), "
            "broken [[wikilinks]], orphaned notes with no connections, notes in wrong folders, "
            "and missing required frontmatter. Produce a structured audit report."
        ),
        backstory=(
            "You are a thorough systems auditor who examines the vault objectively. "
            "You identify problems, categorize their severity, and suggest specific "
            "remediation steps. You produce clear, actionable reports."
        ),
        llm=_make_llm(router, TaskType.ANALYSIS),
        tools=[graph_traversal] if graph_traversal else [],
        verbose=False,
        allow_delegation=False,
        max_iter=10,
    )
