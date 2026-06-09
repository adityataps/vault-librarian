import pytest
from src.vault_config.loader import VaultConfigLoader

import src.config as _cfg_module
from src.config import AppConfig


@pytest.fixture(autouse=True)
def reset_singleton():
    _cfg_module._instance = None
    yield
    _cfg_module._instance = None


@pytest.fixture
def cfg_with_vault(tmp_path):
    (tmp_path / ".librarian").mkdir()
    return AppConfig(
        llm_provider="copilot",
        llm_model="gpt-4o",
        llm_api_key="x",
        vault_path=str(tmp_path),
        secret="s",
        _env_file=None,
    ), tmp_path


def test_loader_reads_frontmatter_settings(cfg_with_vault):
    cfg, vault = cfg_with_vault
    config_file = vault / ".librarian" / "config.md"
    config_file.write_text(
        "---\nautonomy_default: full\nstale_days: 45\n---\n\n## Formatter\n\nAlways add company tag.\n"
    )
    loader = VaultConfigLoader(cfg)
    loader.apply()
    assert cfg.autonomy_default == "full"
    assert cfg.stale_days == 45


def test_loader_reads_agent_instructions(cfg_with_vault):
    cfg, vault = cfg_with_vault
    config_file = vault / ".librarian" / "config.md"
    config_file.write_text(
        "---\n---\n\n## Librarian\n\nPrefer Tech Notes/ for homelab content.\n\n"
        "## Formatter\n\nNormalize all dates to ISO 8601.\n"
    )
    loader = VaultConfigLoader(cfg)
    loader.apply()
    assert "homelab" in cfg.get_agent_instructions("librarian")
    assert "ISO 8601" in cfg.get_agent_instructions("formatter")


def test_loader_handles_missing_file_gracefully(cfg_with_vault):
    cfg, vault = cfg_with_vault
    loader = VaultConfigLoader(cfg)
    loader.apply()  # no config.md — should not raise


def test_loader_applies_agents_block(cfg_with_vault):
    cfg, vault = cfg_with_vault
    config_file = vault / ".librarian" / "config.md"
    config_file.write_text(
        "---\nagents:\n  autonomy: full\n  overrides:\n    linker: supervised\n---\n\n"
    )
    loader = VaultConfigLoader(cfg)
    loader.apply()
    assert cfg.autonomy_default == "full"
    assert cfg.autonomy_overrides.get("linker") == "supervised"


def test_loader_section_names_lowercased(cfg_with_vault):
    cfg, vault = cfg_with_vault
    config_file = vault / ".librarian" / "config.md"
    config_file.write_text("---\n---\n\n## MOC Maintainer\n\nAlways update the Work MOC.\n")
    loader = VaultConfigLoader(cfg)
    loader.apply()
    # Section "MOC Maintainer" → "moc_maintainer"
    assert "Work MOC" in cfg.get_agent_instructions("moc_maintainer")
