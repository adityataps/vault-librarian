"""Vault scanner — walks the Obsidian vault and indexes all notes."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from src.tools.note_parser import ParsedNote, parse_note

logger = logging.getLogger(__name__)


@dataclass
class ScanResult:
    """Summary of a vault scan run."""

    total_files: int = 0
    parsed: list[ParsedNote] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)  # (path, error msg)

    @property
    def success_count(self) -> int:
        return len(self.parsed)

    @property
    def error_count(self) -> int:
        return len(self.errors)


class VaultScanner:
    """Recursively scans an Obsidian vault directory and parses all markdown notes.

    Respects exclusion lists from config so .obsidian/, _agent/, Attachments/, etc.
    are never indexed.
    """

    DEFAULT_EXCLUDED_FOLDERS = {".obsidian", ".trash", "_agent", "Attachments"}
    DEFAULT_EXCLUDED_FILES = {"CLAUDE.md", "Work MOC.md"}

    def __init__(
        self,
        vault_root: Path,
        excluded_folders: list[str] | None = None,
        excluded_files: list[str] | None = None,
    ) -> None:
        self.vault_root = vault_root.resolve()
        self.excluded_folders: set[str] = set(
            excluded_folders or self.DEFAULT_EXCLUDED_FOLDERS
        )
        self.excluded_files: set[str] = set(
            excluded_files or self.DEFAULT_EXCLUDED_FILES
        )

    # ── Public API ─────────────────────────────────────────────────────────

    def scan(self) -> ScanResult:
        """Synchronous full-vault scan. Returns ScanResult with all parsed notes."""
        result = ScanResult()
        md_files = list(self._iter_markdown_files())
        result.total_files = len(md_files)

        for file_path in md_files:
            try:
                parsed = parse_note(file_path, self.vault_root)
                result.parsed.append(parsed)
            except Exception as exc:
                rel = str(file_path.relative_to(self.vault_root))
                logger.warning("Failed to parse %s: %s", rel, exc)
                result.errors.append((rel, str(exc)))

        logger.info(
            "Vault scan complete: %d parsed, %d errors out of %d files",
            result.success_count,
            result.error_count,
            result.total_files,
        )
        return result

    def scan_file(self, file_path: Path) -> ParsedNote | None:
        """Parse a single file. Returns None if the file should be skipped."""
        if not self._should_index(file_path):
            return None
        return parse_note(file_path, self.vault_root)

    def iter_notes(self):
        """Generator: yield ParsedNote for each valid vault file (skips errors)."""
        for file_path in self._iter_markdown_files():
            try:
                yield parse_note(file_path, self.vault_root)
            except Exception as exc:
                logger.warning("Skipping %s: %s", file_path.name, exc)

    def get_all_paths(self) -> list[str]:
        """Return relative paths of all indexable .md files (no parsing)."""
        return [
            str(f.relative_to(self.vault_root))
            for f in self._iter_markdown_files()
        ]

    def resolve_wikilink(self, link_text: str) -> Path | None:
        """Find the vault file that best matches a [[wikilink]] target.

        Tries exact filename match first, then case-insensitive search.
        Returns the absolute path if found, None if the link is broken.
        """
        # Strip any path separators — Obsidian resolves by filename only by default
        stem = Path(link_text).stem
        candidates: list[Path] = []

        for md_file in self._iter_markdown_files():
            if md_file.stem == stem:
                candidates.append(md_file)
            elif md_file.stem.lower() == stem.lower():
                candidates.append(md_file)

        if not candidates:
            return None
        # Prefer exact case match
        exact = [c for c in candidates if c.stem == stem]
        return (exact or candidates)[0]

    # ── Private helpers ────────────────────────────────────────────────────

    def _iter_markdown_files(self):
        """Yield all .md files not under excluded folders."""
        for md_file in sorted(self.vault_root.rglob("*.md")):
            if self._should_index(md_file):
                yield md_file

    def _should_index(self, file_path: Path) -> bool:
        """Return True if this file should be indexed."""
        try:
            rel = file_path.relative_to(self.vault_root)
        except ValueError:
            return False

        # Check every path component against excluded folders
        for part in rel.parts[:-1]:  # All parts except the filename
            if part in self.excluded_folders:
                return False

        # Check filename against excluded files
        if file_path.name in self.excluded_files:
            return False

        return True
