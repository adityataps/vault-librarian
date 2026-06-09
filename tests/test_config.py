import os
import pytest
from src.config import AppConfig


def test_config_loads_from_env(monkeypatch):
    monkeypatch.setenv("LIBRARIAN_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("LIBRARIAN_LLM_MODEL", "claude-sonnet-4-6")
    monkeypatch.setenv("LIBRARIAN_LLM_API_KEY", "sk-test")
    monkeypatch.setenv("LIBRARIAN_VAULT_PATH", "/tmp/vault")
    monkeypatch.setenv("LIBRARIAN_SECRET", "secret")
    cfg = AppConfig(_env_file=None)
    assert cfg.llm_provider == "anthropic"
    assert cfg.llm_model == "claude-sonnet-4-6"
    assert cfg.vault_path == "/tmp/vault"


def test_config_default_autonomy():
    cfg = AppConfig(
        llm_provider="copilot", llm_model="gpt-4o",
        llm_api_key="x", vault_path="/tmp", secret="s",
        _env_file=None,
    )
    assert cfg.autonomy_default == "supervised"
    assert cfg.autonomy_overrides.get("formatter") == "full"


def test_config_enrolled_agents_default():
    cfg = AppConfig(
        llm_provider="copilot", llm_model="gpt-4o",
        llm_api_key="x", vault_path="/tmp", secret="s",
        _env_file=None,
    )
    assert "librarian" in cfg.enrolled_agents
    assert "formatter" in cfg.enrolled_agents


def test_config_agents_env_var(monkeypatch):
    monkeypatch.setenv("LIBRARIAN_ENROLLED_AGENTS", "librarian,formatter")
    monkeypatch.setenv("LIBRARIAN_LLM_API_KEY", "x")
    monkeypatch.setenv("LIBRARIAN_VAULT_PATH", "/tmp")
    monkeypatch.setenv("LIBRARIAN_SECRET", "s")
    cfg = AppConfig(_env_file=None)
    assert cfg.enrolled_agents == ["librarian", "formatter"]


def test_get_autonomy_override():
    cfg = AppConfig(
        llm_provider="copilot", llm_model="gpt-4o",
        llm_api_key="x", vault_path="/tmp", secret="s",
        autonomy_default="supervised",
        autonomy_overrides={"formatter": "full"},
        _env_file=None,
    )
    assert cfg.get_autonomy("formatter") == "full"
    assert cfg.get_autonomy("librarian") == "supervised"


def test_agent_instructions_roundtrip():
    cfg = AppConfig(
        llm_provider="copilot", llm_model="gpt-4o",
        llm_api_key="x", vault_path="/tmp", secret="s",
        _env_file=None,
    )
    assert cfg.get_agent_instructions("librarian") == ""
    cfg.update_agent_instructions({"librarian": "Prefer Tech Notes/ for homelab."})
    assert "homelab" in cfg.get_agent_instructions("librarian")
