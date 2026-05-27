"""CrewAI summarizer agent factory."""
from __future__ import annotations

from typing import TYPE_CHECKING

from crewai import Agent

from src.llm.router import LLMRouter, TaskType

from .base import _make_llm

if TYPE_CHECKING:
    from src.storage.base import StorageBackend


def create_summarizer(router: LLMRouter, storage: StorageBackend) -> Agent:
    return Agent(
        role="Note Summarizer",
        goal=(
            "Generate concise, accurate summaries for Obsidian vault notes. "
            "Add or update the 'summary' field in frontmatter. Preserve the original "
            "content completely — only add or update the summary field."
        ),
        backstory=(
            "You are a skilled technical writer who reads notes carefully and produces "
            "clear, informative summaries in 1-3 sentences. You focus on the key insights "
            "and actionable information in each note."
        ),
        llm=_make_llm(router, TaskType.WRITING),
        tools=[],
        verbose=False,
        allow_delegation=False,
        max_iter=3,
    )
