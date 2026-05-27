"""Configuration management using Pydantic Settings."""

from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    """Database configuration."""

    host: str = Field(default="localhost", alias="POSTGRES_HOST")
    port: int = Field(default=5432, alias="POSTGRES_PORT")
    user: str = Field(default="vault_crawler", alias="POSTGRES_USER")
    password: str = Field(default="vault_crawler_dev", alias="POSTGRES_PASSWORD")
    database: str = Field(default="vault_crawler", alias="POSTGRES_DB")

    @property
    def url(self) -> str:
        """Build async PostgreSQL connection URL."""
        return f"postgresql+asyncpg://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"

    @property
    def sync_url(self) -> str:
        """Build sync PostgreSQL connection URL (for Alembic)."""
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"


class RedisSettings(BaseSettings):
    """Redis configuration."""

    enabled: bool = Field(default=False)
    host: str = Field(default="localhost", alias="REDIS_HOST")
    port: int = Field(default=6379, alias="REDIS_PORT")
    password: str | None = Field(default=None, alias="REDIS_PASSWORD")
    db: int = Field(default=0)

    @property
    def url(self) -> str:
        """Build Redis connection URL."""
        auth = f":{self.password}@" if self.password else ""
        return f"redis://{auth}{self.host}:{self.port}/{self.db}"


class LLMProviderSettings(BaseSettings):
    """LLM provider configuration."""

    enabled: bool = True
    api_key: str | None = None
    base_url: str | None = None
    models: list[str] = Field(default_factory=list)
    rate_limit: int | None = None  # Requests per minute


class LLMSettings(BaseSettings):
    """LLM configuration."""

    default_provider: Literal["copilot", "anthropic", "ollama"] = "copilot"
    default_model: str = "gpt-4o-mini"

    # Provider configs
    copilot_enabled: bool = True
    copilot_api_key: str | None = Field(default=None, alias="GITHUB_TOKEN")
    copilot_rate_limit: int = 60

    anthropic_enabled: bool = False
    anthropic_api_key: str | None = Field(default=None, alias="ANTHROPIC_API_KEY")
    anthropic_rate_limit: int = 50

    ollama_enabled: bool = False
    ollama_base_url: str = Field(
        default="http://localhost:11434", alias="OLLAMA_BASE_URL"
    )

    @field_validator("copilot_api_key")
    @classmethod
    def validate_copilot_key(cls, v: str | None, info) -> str | None:
        """Warn (never hard-fail) when GITHUB_TOKEN is missing at config load time.

        The provider itself will raise a clear error at first use if the key
        is still missing then.  Hard-failing here prevents commands like
        ``vault-crawler status`` or ``vault-crawler migrate`` from running even
        when the user just hasn't set the token yet.
        """
        if not v and info.data.get("default_provider") == "copilot":
            import logging
            logging.getLogger(__name__).warning(
                "GITHUB_TOKEN is not set — Copilot provider will be unavailable. "
                "Set GITHUB_TOKEN or change DEFAULT_LLM_PROVIDER in your .env."
            )
        return v


class VaultSettings(BaseSettings):
    """Obsidian vault configuration."""

    path: Path = Field(alias="OBSIDIAN_VAULT_PATH")
    excluded_folders: list[str] = Field(
        default_factory=lambda: [".obsidian", ".trash", "_agent", "Attachments"]
    )
    excluded_files: list[str] = Field(
        default_factory=lambda: ["CLAUDE.md.md", "Work MOC.md"]
    )

    @field_validator("path")
    @classmethod
    def validate_vault_path(cls, v: Path) -> Path:
        """Ensure vault path exists and is a directory."""
        if not v.exists():
            raise ValueError(f"Vault path does not exist: {v}")
        if not v.is_dir():
            raise ValueError(f"Vault path is not a directory: {v}")
        return v.resolve()


class SchedulerSettings(BaseSettings):
    """Scheduler configuration."""

    enabled: bool = True
    daily_audit_hour: int = 2  # 2 AM
    daily_audit_minute: int = 0
    jira_sync_interval_minutes: int = 60
    weekly_digest_day: int = 6  # Sunday
    weekly_digest_hour: int = 21  # 9 PM


class JiraSettings(BaseSettings):
    """Jira integration configuration."""

    enabled: bool = False
    base_url: str | None = Field(default=None, alias="JIRA_BASE_URL")
    username: str | None = Field(default=None, alias="JIRA_USERNAME")
    api_token: str | None = Field(default=None, alias="JIRA_API_TOKEN")
    jql_filter: str = 'project = AICOE AND updated >= -7d'


class Settings(BaseSettings):
    """Application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    environment: Literal["development", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    
    # Storage backend
    storage_backend: Literal["postgres", "sqlite"] = "postgres"
    sqlite_path: Path = Field(default=Path("vault_crawler.db"))

    # Sub-configs
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    vault: VaultSettings = Field(default_factory=VaultSettings)
    scheduler: SchedulerSettings = Field(default_factory=SchedulerSettings)
    jira: JiraSettings = Field(default_factory=JiraSettings)

    @property
    def is_development(self) -> bool:
        """Check if running in development mode."""
        return self.environment == "development"

    @property
    def is_production(self) -> bool:
        """Check if running in production mode."""
        return self.environment == "production"


# Global settings instance
_settings: Settings | None = None


def get_settings() -> Settings:
    """Get or create settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reload_settings() -> Settings:
    """Reload settings from environment."""
    global _settings
    _settings = Settings()
    return _settings
