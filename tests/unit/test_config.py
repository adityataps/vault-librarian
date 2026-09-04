from __future__ import annotations

from pathlib import Path

import pytest

from vault_librarian.config import ConfigError, ensure_default_config, load_config


def test_ensure_default_config_creates_file(tmp_path: Path):
    config_path = ensure_default_config(tmp_path)
    assert config_path.exists()
    assert config_path == tmp_path / "Librarian" / "Config.md"


def test_load_config_applies_defaults(tmp_path: Path):
    config = load_config(tmp_path)
    assert config.debounce_seconds == 20
    assert config.workflow("format").enabled is True
    assert "Attachments/" in config.ignore_paths
    assert config.models["fast"].provider == "github_copilot"


def test_load_config_rejects_missing_yaml_block(tmp_path: Path):
    config_path = tmp_path / "Librarian" / "Config.md"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("# Config\n\nNo yaml block here.\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(tmp_path)


def test_load_config_rejects_invalid_schema(tmp_path: Path):
    config_path = tmp_path / "Librarian" / "Config.md"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        "```yaml\ndebounce_seconds: \"not-a-number\"\n```\n", encoding="utf-8"
    )
    with pytest.raises(ConfigError):
        load_config(tmp_path)
