"""Factory to build LLMRouter from application config."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .anthropic import AnthropicProvider
from .copilot import CopilotProvider
from .embeddings import EmbeddingService
from .ollama import OllamaProvider
from .router import LLMRouter

if TYPE_CHECKING:
    from src.config import Settings

logger = logging.getLogger(__name__)


def build_llm_router(settings: "Settings") -> LLMRouter:
    """Instantiate enabled providers and return a configured LLMRouter."""
    providers: dict = {}

    if settings.llm.copilot_enabled and settings.llm.copilot_api_key:
        providers["copilot"] = CopilotProvider(api_key=settings.llm.copilot_api_key)
        logger.info("LLM: Copilot provider enabled")

    if settings.llm.anthropic_enabled and settings.llm.anthropic_api_key:
        providers["anthropic"] = AnthropicProvider(api_key=settings.llm.anthropic_api_key)
        logger.info("LLM: Anthropic provider enabled")

    if settings.llm.ollama_enabled:
        providers["ollama"] = OllamaProvider(base_url=settings.llm.ollama_base_url)
        logger.info("LLM: Ollama provider enabled (%s)", settings.llm.ollama_base_url)

    if not providers:
        logger.warning("No LLM providers configured — agent functionality will be limited")

    return LLMRouter(
        providers=providers,
        default_provider=settings.llm.default_provider,
    )


def build_embedding_service(
    router: LLMRouter,
    redis_client=None,
    model: str = "text-embedding-3-small",
) -> EmbeddingService:
    return EmbeddingService(router=router, redis_client=redis_client, default_model=model)
