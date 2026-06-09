from __future__ import annotations

from typing import Any

from pydantic import PrivateAttr, field_validator
from pydantic_settings import BaseSettings, EnvSettingsSource, SettingsConfigDict


class _CommaSupportedEnvSource(EnvSettingsSource):
    """Env source that allows comma-separated values for list[str] fields."""

    def decode_complex_value(self, field_name: str, field: Any, value: Any) -> Any:
        # If value is a plain comma-separated string (not JSON), return it as-is
        # so that the field_validator can split it.
        if isinstance(value, str):
            stripped = value.strip()
            if not (stripped.startswith("[") or stripped.startswith("{")):
                return stripped  # hand off to field_validator
        return super().decode_complex_value(field_name, field, value)


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LIBRARIAN_", extra="ignore")

    # LLM
    llm_provider: str = "copilot"
    llm_model: str = "gpt-4o"
    llm_api_key: str = ""

    # Vault
    vault_path: str = ""
    vault_excluded_folders: list[str] = [".obsidian", ".git", ".librarian", "Attachments"]
    vault_excluded_files: list[str] = ["CLAUDE.md"]

    # Service
    secret: str = "change-me"
    log_level: str = "INFO"
    debounce_standard: float = 3.0
    debounce_directive: float = 0.5

    # Agent enrollment
    enrolled_agents: list[str] = [
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

    # Autonomy
    autonomy_default: str = "supervised"
    autonomy_overrides: dict[str, str] = {
        "formatter": "full",
        "inline_directive": "full",
        "meeting_enricher": "full",
    }

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

    # Private: natural-language instructions from .librarian/config.md
    _agent_instructions: dict[str, str] = PrivateAttr(default_factory=dict)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        **kwargs: Any,
    ) -> tuple[Any, ...]:
        sources = super().settings_customise_sources(settings_cls, **kwargs)
        # Replace the default EnvSettingsSource with our comma-aware subclass
        return tuple(
            _CommaSupportedEnvSource(settings_cls) if isinstance(s, EnvSettingsSource) else s
            for s in sources
        )

    def get_autonomy(self, agent: str) -> str:
        return self.autonomy_overrides.get(agent, self.autonomy_default)

    def get_agent_instructions(self, agent: str) -> str:
        return self._agent_instructions.get(agent, "")

    def update_agent_instructions(self, instructions: dict[str, str]) -> None:
        self._agent_instructions = instructions


_instance: AppConfig | None = None


def get_config() -> AppConfig:
    global _instance
    if _instance is None:
        _instance = AppConfig()
    return _instance
