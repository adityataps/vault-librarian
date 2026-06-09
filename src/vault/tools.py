from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from pathlib import Path

import frontmatter
import git


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
        return self.root / rel

    def read_note(self, rel: str) -> str:
        return self.abs(rel).read_text(encoding="utf-8")

    def current_hash(self, rel: str) -> str:
        return hashlib.sha256(self.read_note(rel).encode()).hexdigest()

    def write_note(self, rel: str, content: str, dispatch_hash: str | None = None) -> None:
        target = self.abs(rel)
        if dispatch_hash is not None and target.exists():
            if self.current_hash(rel) != dispatch_hash:
                raise ConflictError(f"{rel} was modified during agent processing")
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
            os.replace(tmp, target)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def move_note(self, src_rel: str, dst_rel: str) -> None:
        dst = self.abs(dst_rel)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(self.abs(src_rel)), str(dst))

    def update_frontmatter(self, rel: str, fields: dict) -> None:
        text = self.read_note(rel)
        post = frontmatter.loads(text)
        post.metadata.update(fields)
        self.write_note(rel, frontmatter.dumps(post))

    def create_note(self, rel: str, content: str) -> None:
        self.write_note(rel, content)

    def list_notes(self, folder: str = "") -> list[str]:
        base = self.root / folder if folder else self.root
        return [
            str(p.relative_to(self.root))
            for p in base.rglob("*.md")
            if not any(part.startswith(".") for part in p.relative_to(self.root).parts)
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
