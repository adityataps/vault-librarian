"""CrewAI archivist agent factory."""
from __future__ import annotations

from typing import TYPE_CHECKING

from crewai import Agent

from src.llm.router import LLMRouter, TaskType

from .base import _make_llm

if TYPE_CHECKING:
    from src.storage.base import StorageBackend
    from src.tools.vector_search import VectorSearchTool


def create_archivist(
    router: LLMRouter,
    storage: StorageBackend,
    vector_search: VectorSearchTool | None = None,
) -> Agent:
    return Agent(
        role="Vault Archivist",
        goal=(
            "Maintain and improve Obsidian note metadata. Update frontmatter fields "
            "(type, status, tags), ensure notes are in correct folders, and flag "
            "notes that are stale or need attention."
        ),
        backstory=(
            "You are a meticulous archivist who keeps the vault organized and metadata "
            "accurate. You update frontmatter fields conservatively — only changing what "
            "is clearly wrong or missing. You never delete content, only reorganize it."
        ),
        llm=_make_llm(router, TaskType.CLASSIFICATION),
        tools=[vector_search] if vector_search else [],
        verbose=False,
        allow_delegation=False,
        max_iter=5,
    )
