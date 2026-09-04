"""LiteLLM call layer + shared tenacity retry policy (architecture.md §4.12).

Resolves a workflow's configured model tier (from Config.md `models:`) to a concrete
provider/model and wraps every call in exponential-backoff retry — generic, not just for
the mermaid fix cascade.
"""

from __future__ import annotations

import logging

import litellm
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from vault_librarian.config import ModelConfig

logger = logging.getLogger("vault_librarian.llm")

RETRYABLE_EXCEPTIONS = (
    litellm.exceptions.Timeout,
    litellm.exceptions.RateLimitError,
    litellm.exceptions.APIConnectionError,
    litellm.exceptions.ServiceUnavailableError,
)


class LLMFactory:
    def __init__(self, models: dict[str, ModelConfig]):
        self._models = models

    def caller_for(self, tier: str):
        """Returns an async `(prompt: str) -> str` callable for the given model tier, or None
        if the tier isn't configured — callers must treat that as "no LLM available"."""
        model_cfg = self._models.get(tier)
        if model_cfg is None:
            return None

        async def _call(prompt: str) -> str:
            return await self._call(model_cfg, prompt)

        return _call

    async def _call(self, model_cfg: ModelConfig, prompt: str) -> str:
        @retry(
            retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
            stop=stop_after_attempt(max(model_cfg.max_retries, 1)),
            wait=wait_exponential(multiplier=1, min=1, max=20),
            reraise=True,
        )
        async def _attempt() -> str:
            response = await litellm.acompletion(
                model=f"{model_cfg.provider}/{model_cfg.model}",
                messages=[{"role": "user", "content": prompt}],
                timeout=model_cfg.timeout_seconds,
            )
            return response.choices[0].message.content or ""

        return await _attempt()
