"""CrewAI librarian agent factory."""
from __future__ import annotations

from typing import TYPE_CHECKING

from crewai import Agent

from src.llm.router import LLMRouter, TaskType

from .base import _make_llm

if TYPE_CHECKING:
    from src.storage.base import StorageBackend
    from src.tools.vector_search import VectorSearchTool


def create_librarian(
    router: LLMRouter,
    storage: StorageBackend,
    vector_search: VectorSearchTool | None = None,
) -> Agent:
    return Agent(
        role="Vault Librarian",
        goal=(
            "Classify Obsidian vault notes and determine the correct folder for each note "
            "based on its content, tags, frontmatter type, and similarity to existing notes."
        ),
        backstory=(
            "You are an expert knowledge manager with deep familiarity with Obsidian vaults. "
            "You understand the vault's folder taxonomy and can accurately place any note "
            "into the right location. You prefer precision over assumptions — if unsure, "
            "you ask for clarification rather than guessing."
        ),
        llm=_make_llm(router, TaskType.CLASSIFICATION),
        tools=[vector_search] if vector_search else [],
        verbose=False,
        allow_delegation=False,
        max_iter=5,
    )
