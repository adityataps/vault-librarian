"""Anthropic Claude LLM provider."""
from __future__ import annotations

import logging
from typing import AsyncIterator

from anthropic import AsyncAnthropic

from .base import EmbeddingResponse, LLMMessage, LLMProvider, LLMResponse

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-3-5-haiku-latest"


class AnthropicProvider(LLMProvider):
    """Provider for Anthropic Claude models."""

    name = "anthropic"

    def __init__(self, api_key: str) -> None:
        self._client = AsyncAnthropic(api_key=api_key)
        self._default_model = DEFAULT_MODEL

    async def generate(
        self,
        messages: list[LLMMessage],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        m = model or self._default_model
        system_msg = next((msg.content for msg in messages if msg.role == "system"), None)
        user_msgs = [
            {"role": msg.role, "content": msg.content}
            for msg in messages if msg.role != "system"
        ]
        kwargs: dict = {
            "model": m,
            "messages": user_msgs,
            "max_tokens": max_tokens or 4096,
            "temperature": temperature,
        }
        if system_msg:
            kwargs["system"] = system_msg

        resp = await self._client.messages.create(**kwargs)
        content = resp.content[0].text if resp.content else ""
        return LLMResponse(
            content=content,
            model=m,
            provider=self.name,
            prompt_tokens=resp.usage.input_tokens,
            completion_tokens=resp.usage.output_tokens,
        )

    async def stream(
        self,
        messages: list[LLMMessage],
        model: str | None = None,
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        m = model or self._default_model
        system_msg = next((msg.content for msg in messages if msg.role == "system"), None)
        user_msgs = [
            {"role": msg.role, "content": msg.content}
            for msg in messages if msg.role != "system"
        ]
        kwargs: dict = {
            "model": m,
            "messages": user_msgs,
            "max_tokens": 4096,
            "temperature": temperature,
        }
        if system_msg:
            kwargs["system"] = system_msg

        async with self._client.messages.stream(**kwargs) as stream:
            async for text in stream.text_stream:
                yield text

    async def embed(self, text: str, model: str | None = None) -> EmbeddingResponse:
        # Anthropic does not currently expose an embedding API. Raise to trigger fallback.
        raise NotImplementedError("Anthropic does not provide an embedding API")

    async def health_check(self) -> bool:
        try:
            # Minimal API call to verify credentials
            await self._client.models.list()
            return True
        except Exception:
            logger.warning("Anthropic provider health check failed")
            return False
