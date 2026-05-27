"""Ollama local LLM provider."""
from __future__ import annotations

import json
import logging
from typing import AsyncIterator

import httpx

from .base import EmbeddingResponse, LLMMessage, LLMProvider, LLMResponse

logger = logging.getLogger(__name__)

DEFAULT_CHAT_MODEL = "llama3.2"
DEFAULT_EMBED_MODEL = "nomic-embed-text"


class OllamaProvider(LLMProvider):
    """Provider for locally-running Ollama models."""

    name = "ollama"

    def __init__(self, base_url: str = "http://localhost:11434") -> None:
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(base_url=self._base_url, timeout=120.0)
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
        payload: dict = {
            "model": m,
            "messages": [{"role": msg.role, "content": msg.content} for msg in messages],
            "stream": False,
            "options": {"temperature": temperature},
        }
        if max_tokens:
            payload["options"]["num_predict"] = max_tokens

        resp = await self._client.post("/api/chat", json=payload)
        resp.raise_for_status()
        data = resp.json()
        return LLMResponse(
            content=data["message"]["content"],
            model=m,
            provider=self.name,
            prompt_tokens=data.get("prompt_eval_count", 0),
            completion_tokens=data.get("eval_count", 0),
        )

    async def stream(
        self,
        messages: list[LLMMessage],
        model: str | None = None,
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        m = model or self._default_chat_model
        payload = {
            "model": m,
            "messages": [{"role": msg.role, "content": msg.content} for msg in messages],
            "stream": True,
            "options": {"temperature": temperature},
        }
        async with self._client.stream("POST", "/api/chat", json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line:
                    continue
                data = json.loads(line)
                if token := data.get("message", {}).get("content"):
                    yield token
                if data.get("done"):
                    break

    async def embed(self, text: str, model: str | None = None) -> EmbeddingResponse:
        m = model or self._default_embed_model
        resp = await self._client.post("/api/embeddings", json={"model": m, "prompt": text})
        resp.raise_for_status()
        data = resp.json()
        return EmbeddingResponse(
            vector=data["embedding"],
            model=m,
            provider=self.name,
        )

    async def health_check(self) -> bool:
        try:
            resp = await self._client.get("/api/tags", timeout=5.0)
            return resp.status_code == 200
        except Exception:
            logger.warning("Ollama provider health check failed")
            return False

    async def aclose(self) -> None:
        await self._client.aclose()
