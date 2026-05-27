"""ConversationalCrew — powers the chat interface.

Routes user messages to the right agent based on intent detection.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import AsyncIterator, TYPE_CHECKING

from crewai import Crew, Task

if TYPE_CHECKING:
    from src.llm.router import LLMRouter
    from src.storage.base import StorageBackend
    from src.tools.vector_search import VectorSearchTool
    from src.tools.graph_traversal import GraphTraversalTool

logger = logging.getLogger(__name__)


@dataclass
class ChatMessage:
    role: str  # "user" | "assistant"
    content: str


@dataclass
class ChatResponse:
    content: str
    agent_used: str = "assistant"
    sources: list[str] = field(default_factory=list)  # Note paths referenced


class ConversationalCrew:
    """Handles conversational queries about the vault.

    Detects intent and routes to the appropriate specialist agent:
    - Vault queries → Librarian (find notes, classify)
    - Link queries → Linker (what's related to X?)
    - Audit queries → Auditor (what's stale? what's broken?)
    - Jira queries → Jira Sync (what's the status of X?)
    - General → uses the best available LLM directly
    """

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

    def chat(
        self,
        message: str,
        history: list[ChatMessage] | None = None,
    ) -> ChatResponse:
        """Process a user message and return a response."""
        from src.agents.librarian import create_librarian
        from src.agents.auditor import create_auditor
        from src.agents.linker import create_linker

        # Simple intent routing based on keywords
        msg_lower = message.lower()
        if any(k in msg_lower for k in ["find", "search", "where", "which folder", "classify"]):
            agent = create_librarian(self._router, self._storage, self._vector_search)
            agent_name = "Librarian"
        elif any(k in msg_lower for k in ["link", "related", "connected", "graph", "orphan"]):
            agent = create_linker(self._router, self._storage, self._vector_search, self._graph_traversal)
            agent_name = "Linker"
        elif any(k in msg_lower for k in ["stale", "broken", "audit", "health", "missing", "issue"]):
            agent = create_auditor(self._router, self._storage, self._graph_traversal)
            agent_name = "Auditor"
        else:
            # Default to librarian for general vault queries
            agent = create_librarian(self._router, self._storage, self._vector_search)
            agent_name = "Librarian"

        # Build context from history
        history_text = ""
        if history:
            for msg in history[-6:]:  # Last 3 exchanges
                prefix = "User" if msg.role == "user" else "Assistant"
                history_text += f"{prefix}: {msg.content}\n"

        task = Task(
            description=(
                f"{history_text}"
                f"User: {message}\n\n"
                "Answer the user's question about their Obsidian vault. "
                "Be concise and specific. If referencing notes, include their paths."
            ),
            expected_output="A helpful, conversational response to the user's vault query",
            agent=agent,
        )

        crew = Crew(agents=[agent], tasks=[task], verbose=False)

        try:
            result = crew.kickoff()
            return ChatResponse(content=str(result), agent_used=agent_name)
        except Exception as exc:
            logger.error("ConversationalCrew failed: %s", exc)
            return ChatResponse(
                content=f"I encountered an error processing your request: {exc}",
                agent_used=agent_name,
            )

    async def stream_chat(
        self,
        message: str,
        history: list[ChatMessage] | None = None,
    ) -> AsyncIterator[str]:
        """Stream a response token-by-token using the LLM router directly."""
        from src.llm.router import TaskType
        from src.llm.base import LLMMessage

        # Build context
        msgs: list[LLMMessage] = [
            LLMMessage(
                role="system",
                content=(
                    "You are a helpful assistant for an Obsidian vault. "
                    "Answer questions about note organization, content, and relationships. "
                    "Be concise and reference specific note paths when relevant."
                ),
            )
        ]
        if history:
            for h in history[-6:]:
                msgs.append(LLMMessage(role=h.role, content=h.content))
        msgs.append(LLMMessage(role="user", content=message))

        async for token in self._router.stream(msgs, task=TaskType.CHAT):
            yield token
