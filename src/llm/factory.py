from __future__ import annotations

from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel

from src.config import AppConfig


def build_llm(cfg: AppConfig) -> BaseChatModel:
    match cfg.llm_provider:
        case "copilot":
            from langchain_openai import ChatOpenAI

            return ChatOpenAI(
                base_url="https://models.inference.ai.azure.com",
                api_key=cfg.llm_api_key,
                model=cfg.llm_model,
            )
        case "anthropic":
            from langchain_anthropic import ChatAnthropic

            return ChatAnthropic(model=cfg.llm_model, api_key=cfg.llm_api_key)
        case "ollama":
            from langchain_community.chat_models import ChatOllama

            return ChatOllama(model=cfg.llm_model)
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
