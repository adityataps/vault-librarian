"""CrewAI linker agent factory."""
from __future__ import annotations

from typing import TYPE_CHECKING

from crewai import Agent

from src.llm.router import LLMRouter, TaskType

from .base import _make_llm

if TYPE_CHECKING:
    from src.storage.base import StorageBackend
    from src.tools.graph_traversal import GraphTraversalTool
    from src.tools.vector_search import VectorSearchTool


def create_linker(
    router: LLMRouter,
    storage: StorageBackend,
    vector_search: VectorSearchTool | None = None,
    graph_traversal: GraphTraversalTool | None = None,
) -> Agent:
    tools = [tool for tool in [vector_search, graph_traversal] if tool is not None]
    return Agent(
        role="Note Linker",
        goal=(
            "Discover semantic relationships between vault notes and create [[wikilinks]] "
            "to connect related content. Find orphaned notes and integrate them into the "
            "knowledge graph. Resolve and fix broken wikilinks."
        ),
        backstory=(
            "You are a knowledge graph specialist who understands how ideas connect. "
            "You use semantic search to find conceptually related notes and suggest "
            "meaningful links. You only create links that genuinely add value — "
            "not superficial keyword matches."
        ),
        llm=_make_llm(router, TaskType.ANALYSIS),
        tools=tools,
        verbose=False,
        allow_delegation=False,
        max_iter=8,
    )
