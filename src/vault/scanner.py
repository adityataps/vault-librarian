from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from src.config import AppConfig
from src.vault.parser import NoteMetadata, parse_note

log = logging.getLogger(__name__)


@dataclass
class ScanResult:
    notes: list[NoteMetadata]
    total: int
    errors: int


class VaultScanner:
    def __init__(self, cfg: AppConfig) -> None:
        self.root = Path(cfg.vault_path)
        self._excluded = set(cfg.vault_excluded_folders)
        self._excluded_files = set(cfg.vault_excluded_files)

    def _is_excluded(self, path: Path) -> bool:
        return any(part in self._excluded for part in path.relative_to(self.root).parts)

    def iter_notes(self):
        for md in self.root.rglob("*.md"):
            if self._is_excluded(md) or md.name in self._excluded_files:
                continue
            try:
                yield parse_note(str(md), str(self.root))
            except Exception as exc:
                log.warning("Could not parse %s: %s", md, exc)

    def scan(self) -> ScanResult:
        notes, errors = [], 0
        for md in self.root.rglob("*.md"):
            if self._is_excluded(md) or md.name in self._excluded_files:
                continue
            try:
                notes.append(parse_note(str(md), str(self.root)))
            except Exception:
                errors += 1
        return ScanResult(notes=notes, total=len(notes) + errors, errors=errors)
