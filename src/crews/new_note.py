"""NewNoteCrew — triggered when a new or unclassified note is detected.

Runs: Librarian (classify) → Archivist (update metadata) → Linker (find connections)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from crewai import Crew, Task

if TYPE_CHECKING:
    from src.llm.router import LLMRouter
    from src.storage.base import StorageBackend
    from src.tools.vector_search import VectorSearchTool
    from src.tools.graph_traversal import GraphTraversalTool

logger = logging.getLogger(__name__)


@dataclass
class NewNoteResult:
    note_path: str
    assigned_folder: str | None = None
    frontmatter_updates: dict = None  # type: ignore[assignment]
    suggested_links: list[str] = None  # type: ignore[assignment]
    raw_output: str = ""

    def __post_init__(self):
        if self.frontmatter_updates is None:
            self.frontmatter_updates = {}
        if self.suggested_links is None:
            self.suggested_links = []


class NewNoteCrew:
    """Processes a newly created or unclassified note through the full pipeline."""

    def __init__(
        self,
        llm_router: "LLMRouter",
        storage: "StorageBackend",
        vector_search: "VectorSearchTool | None" = None,
        graph_traversal: "GraphTraversalTool | None" = None,
    ) -> None:
        self._router = llm_router
        self._storage = storage
        self._vector_search = vector_search
        self._graph_traversal = graph_traversal

    def run(self, note_path: str, note_content: str) -> NewNoteResult:
        """Synchronously process a note. Returns structured result."""
        from src.agents.librarian import create_librarian
        from src.agents.archivist import create_archivist
        from src.agents.linker import create_linker

        librarian = create_librarian(self._router, self._storage, self._vector_search)
        archivist = create_archivist(self._router, self._storage, self._vector_search)
        linker = create_linker(self._router, self._storage, self._vector_search, self._graph_traversal)

        classify_task = Task(
            description=(
                f"A new note has been added to the vault at path: {note_path}\n\n"
                f"Content:\n{note_content[:2000]}\n\n"
                "Determine the correct folder for this note based on its content and type. "
                "Respond with ONLY the folder name (e.g. 'Work', 'Personal', 'Projects/AICOE')."
            ),
            expected_output="The correct folder path for this note (e.g. 'Work' or 'Projects/AICOE')",
            agent=librarian,
        )

        metadata_task = Task(
            description=(
                f"Review the note at {note_path} and update its frontmatter metadata.\n\n"
                f"Content:\n{note_content[:2000]}\n\n"
                "Suggest frontmatter updates as a JSON object with keys like 'type', 'status', 'tags'. "
                "Only include fields that should be added or changed. Do not remove existing fields."
            ),
            expected_output="JSON object of frontmatter fields to set, e.g. {\"type\": \"TechNote\", \"tags\": [\"python\"]}",
            agent=archivist,
            context=[classify_task],
        )

        link_task = Task(
            description=(
                f"Find notes in the vault that are conceptually related to: {note_path}\n\n"
                f"Content preview:\n{note_content[:1000]}\n\n"
                "Use vector search to find the top 5 most semantically similar notes. "
                "Return a list of note paths that would make good [[wikilinks]] from this note."
            ),
            expected_output="List of related note paths to link to, one per line",
            agent=linker,
            context=[classify_task],
        )

        crew = Crew(
            agents=[librarian, archivist, linker],
            tasks=[classify_task, metadata_task, link_task],
            verbose=False,
        )

        try:
            result = crew.kickoff()
            return NewNoteResult(
                note_path=note_path,
                raw_output=str(result),
            )
        except Exception as exc:
            logger.error("NewNoteCrew failed for %s: %s", note_path, exc)
            return NewNoteResult(note_path=note_path, raw_output=f"Error: {exc}")
