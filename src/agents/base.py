"""Shared helpers for CrewAI vault agents."""
from __future__ import annotations

from crewai.llm import LLM

from src.llm.router import DEFAULT_ROUTING, LLMRouter, TaskType

_COPILOT_MODEL = "openai/gpt-4o-mini"
_COPILOT_BASE_URL = "https://models.inference.ai.azure.com"
_ANTHROPIC_MODEL = "anthropic/claude-3-5-haiku-latest"
_OLLAMA_MODEL = "ollama/llama3.2"
_FALLBACK_MODEL = "gpt-4o-mini"


def _make_llm(router: LLMRouter, task: TaskType) -> LLM:
    """Wrap our router in a CrewAI-compatible LLM shim."""
    providers = router.available_providers
    preferred = [name for name in DEFAULT_ROUTING.get(task, []) if name in providers]
    provider_order = [*preferred, *[name for name in providers if name not in preferred]]

    for provider_name in provider_order:
        provider = router.get_provider(provider_name)
        if provider_name == "copilot" and provider is not None:
            return LLM(
                model=_COPILOT_MODEL,
                base_url=_COPILOT_BASE_URL,
                api_key=provider._client.api_key,
            )
        if provider_name == "anthropic" and provider is not None:
            return LLM(
                model=_ANTHROPIC_MODEL,
                api_key=provider._client.api_key,
            )
        if provider_name == "ollama" and provider is not None:
            return LLM(
                model=_OLLAMA_MODEL,
                base_url=provider._base_url,
            )

    return LLM(model=_FALLBACK_MODEL)
