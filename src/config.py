from __future__ import annotations

import threading
import typing
import warnings
from typing import Any

from pydantic import Field, PrivateAttr, field_validator
from pydantic_settings import BaseSettings, DotEnvSettingsSource, EnvSettingsSource, SettingsConfigDict


class _CommaSupportedEnvSource(EnvSettingsSource):
    """Env source that allows comma-separated values for list[str] fields."""

    def decode_complex_value(self, field_name: str, field: Any, value: Any) -> Any:
        origin = typing.get_origin(field.annotation)
        if origin is list and isinstance(value, str):
            stripped = value.strip()
            if not stripped.startswith("["):
                return stripped  # hand off to field_validator
        return super().decode_complex_value(field_name, field, value)


class _CommaSupportedDotEnvSource(DotEnvSettingsSource):
    """DotEnv source that allows comma-separated values for list[str] fields."""

    def decode_complex_value(self, field_name: str, field: Any, value: Any) -> Any:
        origin = typing.get_origin(field.annotation)
        if origin is list and isinstance(value, str):
            stripped = value.strip()
            if not stripped.startswith("["):
                return stripped
        return super().decode_complex_value(field_name, field, value)


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LIBRARIAN_", env_file=".env", extra="ignore")

    # LLM
    llm_provider: str = "copilot"
    llm_model: str = "gpt-4o"
    llm_api_key: str = ""

    # Vault
    vault_path: str = ""
    vault_excluded_folders: list[str] = Field(
        default_factory=lambda: [".obsidian", ".git", ".librarian", "Attachments"]
    )
    vault_excluded_files: list[str] = Field(default_factory=lambda: ["CLAUDE.md"])

    # Service
    secret: str = "change-me"
    log_level: str = "INFO"
    debounce_standard: float = 3.0
    debounce_directive: float = 0.5

    # Agent enrollment
    enrolled_agents: list[str] = Field(
        default_factory=lambda: [
            "librarian",
            "formatter",
            "meeting_enricher",
            "linker",
            "moc_maintainer",
            "inline_directive",
            "scaffolder",
            "auditor",
            "daily_brief",
            "weekly_review",
        ]
    )

    # Autonomy
    autonomy_default: str = "supervised"
    autonomy_overrides: dict[str, str] = Field(
        default_factory=lambda: {
            "formatter": "full",
            "inline_directive": "full",
            "meeting_enricher": "full",
        }
    )

    # Schedules
    auditor_schedule: str = "0 2 * * *"
    daily_brief_schedule: str = "0 7 * * *"
    weekly_review_schedule: str = "0 18 * * 0"

    # Stale threshold (days)
    stale_days: int = 60

    @field_validator("enrolled_agents", mode="before")
    @classmethod
    def parse_agents(cls, v: object) -> list[str]:
        if isinstance(v, str):
            return [a.strip() for a in v.split(",") if a.strip()]
        return v  # type: ignore[return-value]

    @field_validator("secret", mode="after")
    @classmethod
    def warn_insecure_secret(cls, v: str) -> str:
        if v == "change-me":
            warnings.warn(
                "LIBRARIAN_SECRET is using the insecure default. Set a strong secret before deploying.",
                stacklevel=2,
            )
        return v

    # Private: natural-language instructions from .librarian/config.md
    _agent_instructions: dict[str, str] = PrivateAttr(default_factory=dict)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        **kwargs: Any,
    ) -> tuple[Any, ...]:
        sources = super().settings_customise_sources(settings_cls, **kwargs)
        # Replace env and dotenv sources with comma-aware subclasses
        result = []
        for s in sources:
            if type(s) is DotEnvSettingsSource:
                result.append(_CommaSupportedDotEnvSource(
                    settings_cls, env_file=s.env_file, env_file_encoding=s.env_file_encoding,
                ))
            elif type(s) is EnvSettingsSource:
                result.append(_CommaSupportedEnvSource(settings_cls))
            else:
                result.append(s)
        return tuple(result)

    def get_autonomy(self, agent: str) -> str:
        return self.autonomy_overrides.get(agent, self.autonomy_default)

    def get_agent_instructions(self, agent: str) -> str:
        return self._agent_instructions.get(agent, "")

    def update_agent_instructions(self, instructions: dict[str, str]) -> None:
        self._agent_instructions.update(instructions)


_instance: AppConfig | None = None
_lock = threading.Lock()


def get_config() -> AppConfig:
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = AppConfig()
    return _instance
