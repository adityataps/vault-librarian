"""LLM router: selects the best provider for a given task type."""
from __future__ import annotations

import logging
from enum import Enum
from typing import AsyncIterator

from .base import EmbeddingResponse, LLMMessage, LLMProvider, LLMResponse

logger = logging.getLogger(__name__)


class TaskType(str, Enum):
    """Task types for routing decisions."""
    WRITING = "writing"        # Note summaries, descriptions
    ANALYSIS = "analysis"      # Vault audits, link analysis
    CODING = "coding"          # Code in notes, Jira tech notes
    EMBEDDING = "embedding"    # Vector embedding generation
    CHAT = "chat"              # Conversational interface
    CLASSIFICATION = "classification"  # Folder/tag classification


# Default routing table: task → preferred providers in priority order
DEFAULT_ROUTING: dict[TaskType, list[str]] = {
    TaskType.WRITING: ["anthropic", "copilot", "ollama"],
    TaskType.ANALYSIS: ["anthropic", "copilot", "ollama"],
    TaskType.CODING: ["copilot", "anthropic", "ollama"],
    TaskType.EMBEDDING: ["copilot", "ollama"],
    TaskType.CHAT: ["copilot", "anthropic", "ollama"],
    TaskType.CLASSIFICATION: ["copilot", "anthropic", "ollama"],
}


class LLMRouter:
    """Routes LLM calls to the best available provider with fallback."""

    def __init__(
        self,
        providers: dict[str, LLMProvider],
        routing: dict[TaskType, list[str]] | None = None,
        default_provider: str = "copilot",
    ) -> None:
        self._providers = providers
        self._routing = routing or DEFAULT_ROUTING
        self._default_provider = default_provider

    def _get_chain(self, task: TaskType) -> list[LLMProvider]:
        """Return providers in priority order, filtering to only available ones."""
        preferred = self._routing.get(task, [self._default_provider])
        chain = [self._providers[name] for name in preferred if name in self._providers]
        # Append any remaining providers not already in chain as last-resort fallbacks
        for name, prov in self._providers.items():
            if prov not in chain:
                chain.append(prov)
        return chain

    async def generate(
        self,
        messages: list[LLMMessage],
        task: TaskType = TaskType.CHAT,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Generate with automatic provider fallback."""
        errors: list[str] = []
        for provider in self._get_chain(task):
            try:
                return await provider.generate(messages, model=model, temperature=temperature, max_tokens=max_tokens)
            except Exception as e:
                logger.warning("Provider %s failed: %s", provider.name, e)
                errors.append(f"{provider.name}: {e}")
        raise RuntimeError(f"All providers failed for task {task}: {'; '.join(errors)}")

    async def stream(
        self,
        messages: list[LLMMessage],
        task: TaskType = TaskType.CHAT,
        model: str | None = None,
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        """Stream from the first available provider for this task."""
        for provider in self._get_chain(task):
            try:
                async for token in provider.stream(messages, model=model, temperature=temperature):
                    yield token
                return
            except Exception as e:
                logger.warning("Provider %s stream failed: %s", provider.name, e)
        raise RuntimeError(f"All providers failed streaming for task {task}")

    async def embed(self, text: str, model: str | None = None) -> EmbeddingResponse:
        """Embed using the first embedding-capable provider."""
        for provider in self._get_chain(TaskType.EMBEDDING):
            try:
                return await provider.embed(text, model=model)
            except NotImplementedError:
                continue
            except Exception as e:
                logger.warning("Provider %s embed failed: %s", provider.name, e)
        raise RuntimeError("No embedding-capable provider available")

    def get_provider(self, name: str) -> LLMProvider | None:
        return self._providers.get(name)

    @property
    def available_providers(self) -> list[str]:
        return list(self._providers.keys())
