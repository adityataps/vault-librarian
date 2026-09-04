"""Local-only git safety net (architecture.md §4.9, §4.19).

Every automated edit is committed locally under a distinct author for revert/audit — this is
a rollback mechanism, never a backup mechanism, and it never touches a remote (design
principle 2). All repository-mutating call sites (workflow commits, startup recovery,
CLI/MCP rollback) serialize through one `asyncio.Lock` so they can never race each other.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import git
from git import GitCommandError, Repo

logger = logging.getLogger("vault_librarian.git_safety")

LIBRARIAN_AUTHOR_NAME = "Vault Librarian"
LIBRARIAN_AUTHOR_EMAIL = "vault-librarian@local"

# Seeded regardless of Config.md's ignore_paths — these are never useful to track.
DEFAULT_GITIGNORE_ENTRIES = [".obsidian/", ".trash/", ".librarian/"]


class GitSafetyNet:
    """Wraps a vault's local git repo with scoped commits and a distinct librarian author."""

    def __init__(self, vault_path: Path, ignore_paths: list[str] | None = None, dry_run: bool = False):
        self.vault_path = Path(vault_path)
        self._lock = asyncio.Lock()
        self.dry_run = dry_run
        self.repo = self._ensure_repo(ignore_paths or [])

    def _ensure_repo(self, ignore_paths: list[str]) -> Repo | None:
        if (self.vault_path / ".git").exists():
            return Repo(self.vault_path)
        if self.dry_run:
            logger.info(
                "dry-run: would initialize a local git repo at %s (skipping)", self.vault_path
            )
            return None
        logger.info("initializing local git repo for vault at %s", self.vault_path)
        repo = Repo.init(self.vault_path)
        self._write_gitignore(ignore_paths)
        # Commit the seeded .gitignore immediately so later startup recovery only ever
        # reports *actual* crash recovery, not routine first-run setup.
        repo.git.add("-A", "--", ".gitignore")
        author = git.Actor(LIBRARIAN_AUTHOR_NAME, LIBRARIAN_AUTHOR_EMAIL)
        repo.index.commit("vault-librarian: initial repo setup (.gitignore)", author=author, committer=author)
        return repo

    def _write_gitignore(self, ignore_paths: list[str]) -> None:
        gitignore = self.vault_path / ".gitignore"
        entries = list(dict.fromkeys(DEFAULT_GITIGNORE_ENTRIES + list(ignore_paths)))
        gitignore.write_text("\n".join(entries) + "\n", encoding="utf-8")

    def sync_gitignore(self, ignore_paths: list[str]) -> None:
        """Keep .gitignore matching the single ignore-list source of truth (design principle 3)."""
        if self.repo is None:
            return
        self._write_gitignore(ignore_paths)

    def _to_rel(self, path: Path) -> str:
        path = Path(path)
        if path.is_absolute():
            return str(path.relative_to(self.vault_path))
        return str(path)

    async def commit_paths(self, paths: list[Path], message: str) -> str | None:
        """Stage exactly `paths` (scoped add, handles create/modify/delete uniformly) and commit
        as the librarian author. Returns the new commit sha, or None if nothing changed."""
        async with self._lock:
            return await asyncio.to_thread(self._commit_paths_sync, paths, message)

    def _commit_paths_sync(self, paths: list[Path], message: str) -> str | None:
        if self.repo is None:
            logger.info("dry-run: would commit %s (skipping, no repo)", message)
            return None
        staged_any = False
        for path in paths:
            rel = self._to_rel(path)
            try:
                self.repo.git.add("-A", "--", rel)
                staged_any = True
            except GitCommandError:
                logger.warning("could not stage %s (untracked and already gone?)", rel)
        if not staged_any or not self.repo.is_dirty(index=True, working_tree=False, untracked_files=False):
            return None
        author = git.Actor(LIBRARIAN_AUTHOR_NAME, LIBRARIAN_AUTHOR_EMAIL)
        commit = self.repo.index.commit(message, author=author, committer=author)
        return commit.hexsha

    async def recover_dirty_tree(self) -> str | None:
        """Startup reconciliation (§4.19): auto-commit any dirty working tree left over from a
        crash before the watcher starts, so we always begin from a clean tree."""
        async with self._lock:
            return await asyncio.to_thread(self._recover_dirty_tree_sync)

    def _recover_dirty_tree_sync(self) -> str | None:
        if self.repo is None:
            return None
        if not self.repo.is_dirty(untracked_files=True):
            return None
        self.repo.git.add("-A")
        author = git.Actor(LIBRARIAN_AUTHOR_NAME, LIBRARIAN_AUTHOR_EMAIL)
        commit = self.repo.index.commit(
            "vault-librarian(recovery): reconcile dirty tree on startup",
            author=author,
            committer=author,
        )
        return commit.hexsha

    async def log_history(self, path: Path, max_count: int = 20) -> list[dict]:
        async with self._lock:
            return await asyncio.to_thread(self._log_history_sync, path, max_count)

    def _log_history_sync(self, path: Path, max_count: int) -> list[dict]:
        if self.repo is None:
            return []
        rel = self._to_rel(path)
        try:
            commits = list(self.repo.iter_commits(paths=rel, max_count=max_count))
        except GitCommandError:
            return []
        return [
            {
                "sha": c.hexsha[:10],
                "author": c.author.name,
                "date": c.committed_datetime.isoformat(),
                "message": c.message.strip(),
            }
            for c in commits
        ]

    async def rollback(self, path: Path, commit_sha: str | None = None) -> str:
        async with self._lock:
            return await asyncio.to_thread(self._rollback_sync, path, commit_sha)

    def _rollback_sync(self, path: Path, commit_sha: str | None) -> str:
        if self.repo is None:
            raise ValueError("No git history for this vault yet (never initialized).")
        rel = self._to_rel(path)
        if commit_sha is None:
            commits = list(self.repo.iter_commits(paths=rel, max_count=2))
            if len(commits) < 2:
                raise ValueError(f"No prior commit to roll back to for {rel}")
            commit_sha = commits[1].hexsha
        self.repo.git.checkout(commit_sha, "--", rel)
        if not self.repo.is_dirty(index=False, working_tree=True, untracked_files=False):
            return commit_sha
        author = git.Actor(LIBRARIAN_AUTHOR_NAME, LIBRARIAN_AUTHOR_EMAIL)
        self.repo.git.add("-A", "--", rel)
        message = f"vault-librarian(rollback): {rel} -> {commit_sha[:10]}"
        commit = self.repo.index.commit(message, author=author, committer=author)
        return commit.hexsha
