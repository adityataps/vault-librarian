"""GitHub Copilot / GitHub Models LLM provider."""
from __future__ import annotations

import logging
from typing import AsyncIterator

from openai import AsyncOpenAI

from .base import EmbeddingResponse, LLMMessage, LLMProvider, LLMResponse

logger = logging.getLogger(__name__)

DEFAULT_CHAT_MODEL = "gpt-4o-mini"
DEFAULT_EMBED_MODEL = "text-embedding-3-small"
GITHUB_MODELS_BASE_URL = "https://models.inference.ai.azure.com"


class CopilotProvider(LLMProvider):
    """Provider for GitHub Models API (Copilot backend)."""

    name = "copilot"

    def __init__(self, api_key: str, base_url: str = GITHUB_MODELS_BASE_URL) -> None:
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._default_chat_model = DEFAULT_CHAT_MODEL
        self._default_embed_model = DEFAULT_EMBED_MODEL

    async def generate(
        self,
        messages: list[LLMMessage],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        m = model or self._default_chat_model
        oai_msgs = [{"role": msg.role, "content": msg.content} for msg in messages]
        kwargs: dict = {"model": m, "messages": oai_msgs, "temperature": temperature}
        if max_tokens:
            kwargs["max_tokens"] = max_tokens

        resp = await self._client.chat.completions.create(**kwargs)
        choice = resp.choices[0]
        usage = resp.usage or type("u", (), {"prompt_tokens": 0, "completion_tokens": 0})()
        return LLMResponse(
            content=choice.message.content or "",
            model=m,
            provider=self.name,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
        )

    async def stream(
        self,
        messages: list[LLMMessage],
        model: str | None = None,
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        m = model or self._default_chat_model
        oai_msgs = [{"role": msg.role, "content": msg.content} for msg in messages]
        async with self._client.chat.completions.stream(
            model=m, messages=oai_msgs, temperature=temperature
        ) as stream:
            async for text in stream.text_stream:
                yield text

    async def embed(self, text: str, model: str | None = None) -> EmbeddingResponse:
        m = model or self._default_embed_model
        resp = await self._client.embeddings.create(input=text, model=m)
        usage = resp.usage or type("u", (), {"total_tokens": 0})()
        return EmbeddingResponse(
            vector=resp.data[0].embedding,
            model=m,
            provider=self.name,
            tokens=usage.total_tokens,
        )

    async def health_check(self) -> bool:
        try:
            await self._client.models.list()
            return True
        except Exception:
            logger.warning("Copilot provider health check failed")
            return False
