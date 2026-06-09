from __future__ import annotations

from typing import Literal

from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel

from src.config import AppConfig

LLMTier = Literal["fast", "heavy"]


def build_llm(cfg: AppConfig, tier: LLMTier = "fast") -> BaseChatModel:
    model = cfg.llm_model if tier == "fast" else (cfg.llm_model_heavy or cfg.llm_model)
    match cfg.llm_provider:
        case "copilot":
            from langchain_openai import ChatOpenAI

            return ChatOpenAI(
                base_url="https://models.inference.ai.azure.com",
                api_key=cfg.llm_api_key,
                model=model,
                max_retries=2,
            )
        case "anthropic":
            from langchain_anthropic import ChatAnthropic

            return ChatAnthropic(
                model=model, api_key=cfg.llm_api_key, max_retries=2,
            )
        case "ollama":
            from langchain_community.chat_models import ChatOllama

            return ChatOllama(model=model)
        case _:
            raise ValueError(f"Unknown LLM provider: {cfg.llm_provider}")


def build_embedder(cfg: AppConfig) -> Embeddings:
    match cfg.embedding_provider:
        case "local":
            from langchain_huggingface import HuggingFaceEmbeddings

            return HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
        case "openai" | _:
            from langchain_openai import OpenAIEmbeddings

            return OpenAIEmbeddings(
                base_url="https://models.inference.ai.azure.com",
                api_key=cfg.llm_api_key,
                model="text-embedding-3-small",
            )
