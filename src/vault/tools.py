from __future__ import annotations

import hashlib
import logging
import os
import shutil
import tempfile
from pathlib import Path

import frontmatter
import git

log = logging.getLogger(__name__)


class ConflictError(Exception):
    """Raised when a note was modified by a human during agent processing."""


class VaultTools:
    def __init__(self, vault_root: str) -> None:
        self.root = Path(vault_root)
        try:
            self._repo = git.Repo(vault_root)
        except git.InvalidGitRepositoryError:
            self._repo = None

    def abs(self, rel: str) -> Path:
        """Resolve rel against vault root, rejecting path traversal and absolute paths."""
        if Path(rel).is_absolute():
            raise ValueError(f"absolute path not allowed: {rel!r}")
        candidate = (self.root / rel).resolve(strict=False)
        root = self.root.resolve(strict=False)
        try:
            candidate.relative_to(root)
        except ValueError:
            raise ValueError(f"path escapes vault root: {rel!r}")
        return candidate

    def read_note(self, rel: str) -> str:
        path = self.abs(rel)
        if path.is_symlink():
            raise ValueError(f"refusing to read symlink: {rel!r}")
        return path.read_text(encoding="utf-8")

    def current_hash(self, rel: str) -> str:
        return hashlib.sha256(self.read_note(rel).encode()).hexdigest()

    def write_note(self, rel: str, content: str, dispatch_hash: str | None = None) -> None:
        target = self.abs(rel)
        if target.is_symlink():
            raise ValueError(f"refusing to write through symlink: {rel!r}")
        if dispatch_hash is not None and target.exists():
            if self.current_hash(rel) != dispatch_hash:
                raise ConflictError(f"{rel} was modified during agent processing")
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
            os.replace(tmp, target)
            log.info("Wrote %s (%d bytes)", rel, len(content))
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def move_note(self, src_rel: str, dst_rel: str) -> None:
        src = self.abs(src_rel)
        dst = self.abs(dst_rel)
        if src.is_symlink() or dst.is_symlink():
            raise ValueError(f"refusing to move symlink: {src_rel!r} → {dst_rel!r}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        log.info("Moved %s → %s", src_rel, dst_rel)

    def update_frontmatter(self, rel: str, fields: dict) -> None:
        text = self.read_note(rel)
        post = frontmatter.loads(text)
        post.metadata.update(fields)
        self.write_note(rel, frontmatter.dumps(post))
        log.info("Updated frontmatter on %s: %s", rel, list(fields.keys()))

    def create_note(self, rel: str, content: str) -> None:
        log.info("Creating note %s", rel)
        self.write_note(rel, content)

    def list_notes(self, folder: str = "") -> list[str]:
        base = self.abs(folder) if folder else self.root.resolve(strict=False)
        return [
            str(p.relative_to(self.root.resolve(strict=False)))
            for p in base.rglob("*.md")
            if not p.is_symlink()
            and not any(
                part.startswith(".")
                for part in p.relative_to(self.root.resolve(strict=False)).parts
            )
        ]

    def git_commit(self, message: str) -> None:
        if self._repo is None:
            return
        if not self._repo.is_dirty(untracked_files=True):
            return
        self._repo.git.add(A=True)
        self._repo.index.commit(
            message,
            author=git.Actor("vault-librarian[bot]", "librarian@local"),
        )

    def has_directive_tags(self, rel: str) -> bool:
        try:
            return "<agent-" in self.read_note(rel)
        except FileNotFoundError:
            return False
