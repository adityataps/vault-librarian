"""Abstract LLM provider interface."""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator


@dataclass
class LLMMessage:
    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass
class LLMResponse:
    content: str
    model: str
    provider: str
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass
class EmbeddingResponse:
    vector: list[float]
    model: str
    provider: str
    tokens: int = 0


class LLMProvider(ABC):
    """Abstract base for all LLM providers."""

    name: str = "base"

    @abstractmethod
    async def generate(
        self,
        messages: list[LLMMessage],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Generate a completion from a list of messages."""
        ...

    @abstractmethod
    async def stream(
        self,
        messages: list[LLMMessage],
        model: str | None = None,
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        """Stream completion tokens."""
        ...

    @abstractmethod
    async def embed(self, text: str, model: str | None = None) -> EmbeddingResponse:
        """Generate an embedding vector for text."""
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Return True if provider is reachable."""
        ...

    def make_messages(self, prompt: str, system: str | None = None) -> list[LLMMessage]:
        """Convenience: build message list from prompt + optional system."""
        msgs: list[LLMMessage] = []
        if system:
            msgs.append(LLMMessage(role="system", content=system))
        msgs.append(LLMMessage(role="user", content=prompt))
        return msgs
