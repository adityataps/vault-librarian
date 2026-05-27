"""Configuration management using Pydantic Settings."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Sub-config data classes (plain BaseModel — env vars read by root Settings)
# ---------------------------------------------------------------------------

class DatabaseSettings(BaseModel):
    """Database configuration."""

    host: str = "localhost"
    port: int = 5432
    user: str = "vault_crawler"
    password: str = "vault_crawler_dev"
    database: str = "vault_crawler"

    @property
    def url(self) -> str:
        return f"postgresql+asyncpg://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"

    @property
    def sync_url(self) -> str:
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"


class RedisSettings(BaseModel):
    """Redis configuration."""

    enabled: bool = False
    host: str = "localhost"
    port: int = 6379
    password: str | None = None
    db: int = 0

    @property
    def url(self) -> str:
        auth = f":{self.password}@" if self.password else ""
        return f"redis://{auth}{self.host}:{self.port}/{self.db}"


class LLMSettings(BaseModel):
    """LLM configuration."""

    default_provider: Literal["copilot", "anthropic", "ollama"] = "copilot"
    default_model: str = "gpt-4o-mini"

    copilot_enabled: bool = True
    copilot_api_key: str | None = None
    copilot_rate_limit: int = 60

    anthropic_enabled: bool = False
    anthropic_api_key: str | None = None
    anthropic_rate_limit: int = 50

    ollama_enabled: bool = False
    ollama_base_url: str = "http://localhost:11434"


class VaultSettings(BaseModel):
    """Obsidian vault configuration."""

    path: Path
    excluded_folders: list[str] = Field(
        default_factory=lambda: [".obsidian", ".trash", "_agent", "Attachments"]
    )
    excluded_files: list[str] = Field(
        default_factory=lambda: ["CLAUDE.md.md", "Work MOC.md"]
    )

    @field_validator("path")
    @classmethod
    def validate_vault_path(cls, v: Path) -> Path:
        if not v.exists():
            raise ValueError(f"Vault path does not exist: {v}")
        if not v.is_dir():
            raise ValueError(f"Vault path is not a directory: {v}")
        return v.resolve()


class SchedulerSettings(BaseModel):
    """Scheduler configuration."""

    enabled: bool = True
    daily_audit_hour: int = 2
    daily_audit_minute: int = 0
    jira_sync_interval_minutes: int = 60
    weekly_digest_day: int = 6
    weekly_digest_hour: int = 21


class JiraSettings(BaseModel):
    """Jira integration configuration."""

    enabled: bool = False
    base_url: str | None = None
    username: str | None = None
    api_token: str | None = None
    jql_filter: str = "project = AICOE AND updated >= -7d"


# ---------------------------------------------------------------------------
# Root settings — all env vars read here, sub-configs built in validator
# ---------------------------------------------------------------------------

class Settings(BaseSettings):
    """Application settings — reads from environment / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    # ── Application ────────────────────────────────────────────────────────
    environment: Literal["development", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    storage_backend: Literal["postgres", "sqlite"] = "postgres"
    sqlite_path: Path = Path("vault_crawler.db")

    # ── Vault (required) ───────────────────────────────────────────────────
    obsidian_vault_path: Path = Field(alias="OBSIDIAN_VAULT_PATH")
    vault_excluded_folders: list[str] = Field(
        default_factory=lambda: [".obsidian", ".trash", "_agent", "Attachments"]
    )
    vault_excluded_files: list[str] = Field(
        default_factory=lambda: ["CLAUDE.md.md", "Work MOC.md"]
    )

    # ── Database ───────────────────────────────────────────────────────────
    postgres_host: str = Field(default="localhost", alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, alias="POSTGRES_PORT")
    postgres_user: str = Field(default="vault_crawler", alias="POSTGRES_USER")
    postgres_password: str = Field(default="vault_crawler_dev", alias="POSTGRES_PASSWORD")
    postgres_db: str = Field(default="vault_crawler", alias="POSTGRES_DB")

    # ── Redis ──────────────────────────────────────────────────────────────
    enable_redis: bool = Field(default=False, alias="ENABLE_REDIS")
    redis_host: str = Field(default="localhost", alias="REDIS_HOST")
    redis_port: int = Field(default=6379, alias="REDIS_PORT")
    redis_password: str | None = Field(default=None, alias="REDIS_PASSWORD")

    # ── LLM ────────────────────────────────────────────────────────────────
    default_llm_provider: Literal["copilot", "anthropic", "ollama"] = Field(
        default="copilot", alias="DEFAULT_LLM_PROVIDER"
    )
    github_token: str | None = Field(default=None, alias="GITHUB_TOKEN")
    anthropic_api_key: str | None = Field(default=None, alias="ANTHROPIC_API_KEY")
    ollama_base_url: str = Field(default="http://localhost:11434", alias="OLLAMA_BASE_URL")
    enable_ollama: bool = Field(default=False, alias="ENABLE_OLLAMA")

    # ── Scheduler ──────────────────────────────────────────────────────────
    scheduler_enabled: bool = Field(default=True, alias="SCHEDULER_ENABLED")
    daily_audit_hour: int = Field(default=2, alias="DAILY_AUDIT_HOUR")
    jira_sync_interval_minutes: int = Field(default=60, alias="JIRA_SYNC_INTERVAL_MINUTES")

    # ── Jira ───────────────────────────────────────────────────────────────
    jira_enabled: bool = Field(default=False, alias="JIRA_ENABLED")
    jira_base_url: str | None = Field(default=None, alias="JIRA_BASE_URL")
    jira_username: str | None = Field(default=None, alias="JIRA_USERNAME")
    jira_api_token: str | None = Field(default=None, alias="JIRA_API_TOKEN")
    jira_jql_filter: str = Field(
        default="project = AICOE AND updated >= -7d", alias="JIRA_JQL_FILTER"
    )

    # ── Computed sub-configs (built in validator, never serialised) ────────
    _database: DatabaseSettings | None = None
    _redis: RedisSettings | None = None
    _llm: LLMSettings | None = None
    _vault: VaultSettings | None = None
    _scheduler: SchedulerSettings | None = None
    _jira: JiraSettings | None = None

    @model_validator(mode="after")
    def _build_sub_configs(self) -> "Settings":
        """Build structured sub-configs from flat env vars."""
        if not self.github_token and self.default_llm_provider == "copilot":
            logger.warning(
                "GITHUB_TOKEN is not set — Copilot provider will be unavailable. "
                "Set GITHUB_TOKEN or change DEFAULT_LLM_PROVIDER in your .env."
            )

        self._database = DatabaseSettings(
            host=self.postgres_host,
            port=self.postgres_port,
            user=self.postgres_user,
            password=self.postgres_password,
            database=self.postgres_db,
        )
        self._redis = RedisSettings(
            enabled=self.enable_redis,
            host=self.redis_host,
            port=self.redis_port,
            password=self.redis_password,
        )
        self._llm = LLMSettings(
            default_provider=self.default_llm_provider,
            copilot_api_key=self.github_token,
            copilot_enabled=bool(self.github_token),
            anthropic_api_key=self.anthropic_api_key,
            anthropic_enabled=bool(self.anthropic_api_key),
            ollama_enabled=self.enable_ollama,
            ollama_base_url=self.ollama_base_url,
        )
        self._vault = VaultSettings(
            path=self.obsidian_vault_path,
            excluded_folders=self.vault_excluded_folders,
            excluded_files=self.vault_excluded_files,
        )
        self._scheduler = SchedulerSettings(
            enabled=self.scheduler_enabled,
            daily_audit_hour=self.daily_audit_hour,
            jira_sync_interval_minutes=self.jira_sync_interval_minutes,
        )
        self._jira = JiraSettings(
            enabled=self.jira_enabled,
            base_url=self.jira_base_url,
            username=self.jira_username,
            api_token=self.jira_api_token,
            jql_filter=self.jira_jql_filter,
        )
        return self

    # ── Convenience accessors (same interface as before) ───────────────────

    @property
    def database(self) -> DatabaseSettings:
        assert self._database is not None
        return self._database

    @property
    def redis(self) -> RedisSettings:
        assert self._redis is not None
        return self._redis

    @property
    def llm(self) -> LLMSettings:
        assert self._llm is not None
        return self._llm

    @property
    def vault(self) -> VaultSettings:
        assert self._vault is not None
        return self._vault

    @property
    def scheduler(self) -> SchedulerSettings:
        assert self._scheduler is not None
        return self._scheduler

    @property
    def jira(self) -> JiraSettings:
        assert self._jira is not None
        return self._jira

    @property
    def is_development(self) -> bool:
        return self.environment == "development"

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reload_settings() -> Settings:
    global _settings
    _settings = Settings()
    return _settings

