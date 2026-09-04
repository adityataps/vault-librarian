"""Config.md schema, loading, and validate-then-swap hot-reload (architecture.md §4.18, §4.19).

Config lives in the vault as a human-editable Markdown file with a fenced ```yaml block
(design principle 6); operational state does not. The service's own config manager owns
loading/validating/swapping so a bad edit never crashes the running service.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError

CONFIG_REL_PATH = Path("Librarian") / "Config.md"

_YAML_BLOCK_RE = re.compile(r"```ya?ml\n(.*?)```", re.DOTALL)

DEFAULT_CONFIG_MD = """\
# Vault Librarian Config

Edit the values below and save — the service hot-reloads this file.

```yaml
debounce_seconds: 20
workflows:
  format: {enabled: true, model: fast}
  backlink: {enabled: true, model: fast}
  frontmatter: {enabled: true, model: fast}
  spellcheck: {enabled: true, model: fast}
  mermaid: {enabled: true, model: fast}
  research_directive: {enabled: true, model: strong}
  org_agent: {enabled: false, model: strong, schedule: "0 6 * * *"}
models:
  fast: {provider: github_copilot, model: gpt-4.1-mini, timeout_seconds: 30, max_retries: 3}
  strong: {provider: anthropic, model: claude-sonnet, timeout_seconds: 60, max_retries: 3}
ignore_paths:
  - Attachments/
  - .obsidian/
  - Templates/
backup:
  enabled: false
  remote: null
  schedule: "0 3 * * *"
mcp:
  enabled: false
  bind: 127.0.0.1
  token: null
```
"""


class ConfigError(Exception):
    """Raised when Config.md is missing its fenced yaml block or fails validation."""


class ModelConfig(BaseModel):
    provider: str
    model: str
    timeout_seconds: int = 30
    max_retries: int = 3


class WorkflowConfig(BaseModel):
    enabled: bool = True
    model: str = "fast"
    schedule: str | None = None


class BackupConfig(BaseModel):
    enabled: bool = False
    remote: str | None = None
    schedule: str = "0 3 * * *"


class MCPConfig(BaseModel):
    enabled: bool = False
    bind: str = "127.0.0.1"
    token: str | None = None


class VaultLibrarianConfig(BaseModel):
    debounce_seconds: float = 20
    workflows: dict[str, WorkflowConfig] = Field(default_factory=dict)
    models: dict[str, ModelConfig] = Field(default_factory=dict)
    ignore_paths: list[str] = Field(
        default_factory=lambda: ["Attachments/", ".obsidian/", "Templates/"]
    )
    backup: BackupConfig = Field(default_factory=BackupConfig)
    mcp: MCPConfig = Field(default_factory=MCPConfig)

    def workflow(self, name: str) -> WorkflowConfig:
        return self.workflows.get(name, WorkflowConfig(enabled=False))

    def model_for(self, tier: str) -> ModelConfig | None:
        return self.models.get(tier)


def ensure_default_config(vault_path: Path) -> Path:
    """Create Librarian/Config.md with documented defaults if it doesn't exist yet."""
    config_path = vault_path / CONFIG_REL_PATH
    if not config_path.exists():
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(DEFAULT_CONFIG_MD, encoding="utf-8")
    return config_path


def extract_yaml_block(md_text: str) -> str:
    match = _YAML_BLOCK_RE.search(md_text)
    if not match:
        raise ConfigError("No ```yaml fenced block found in Config.md")
    return match.group(1)


def load_config(vault_path: Path) -> VaultLibrarianConfig:
    config_path = ensure_default_config(vault_path)
    text = config_path.read_text(encoding="utf-8")
    yaml_text = extract_yaml_block(text)
    try:
        data = yaml.safe_load(yaml_text) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"Config.md yaml block is invalid: {exc}") from exc
    try:
        return VaultLibrarianConfig.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"Config.md failed validation: {exc}") from exc


class ConfigManager:
    """Holds the current validated config; `reload()` is validate-then-swap (§4.19) — a bad
    edit is logged and the previous config stays active rather than crashing the service."""

    def __init__(self, vault_path: Path):
        self.vault_path = vault_path
        self._config = load_config(vault_path)

    @property
    def config(self) -> VaultLibrarianConfig:
        return self._config

    def reload(self) -> tuple[bool, str | None]:
        try:
            new_config = load_config(self.vault_path)
        except ConfigError as exc:
            return False, str(exc)
        self._config = new_config
        return True, None
