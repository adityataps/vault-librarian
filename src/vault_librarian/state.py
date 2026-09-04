"""Vault identification and external state directory layout (architecture.md §4.17).

Librarian's own operational state (job DB, vector KB, logs, PID lockfile) always lives
outside the vault, keyed by a hash of the vault's resolved real path, so vault git
history only ever contains actual content changes (design principle 5).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

STATE_ROOT = Path.home() / ".vault-librarian"


def vault_id(vault_path: Path) -> str:
    """Stable short id for a vault, derived from its resolved real path."""
    real = str(Path(vault_path).resolve())
    return hashlib.sha256(real.encode("utf-8")).hexdigest()[:12]


def state_dir(vault_path: Path) -> Path:
    """External, vault-keyed state directory (job DB, vector KB, logs, lockfile)."""
    d = STATE_ROOT / vault_id(vault_path)
    d.mkdir(parents=True, exist_ok=True)
    return d


def register_vault(vault_path: Path) -> None:
    """Record vault path -> id in ~/.vault-librarian/vaults.json for `vault-librarian list`."""
    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    registry_path = STATE_ROOT / "vaults.json"
    registry: dict[str, str] = {}
    if registry_path.exists():
        try:
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            registry = {}
    registry[vault_id(vault_path)] = str(Path(vault_path).resolve())
    registry_path.write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def list_vaults() -> dict[str, str]:
    """Known vault id -> resolved path pairs, for `vault-librarian list`."""
    registry_path = STATE_ROOT / "vaults.json"
    if not registry_path.exists():
        return {}
    try:
        return json.loads(registry_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
