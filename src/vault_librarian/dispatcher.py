"""Dispatcher (architecture.md §4.2, §4.19): quiescence debounce -> ordered-set queue ->
single sequential worker running the batched reactive-workflow pipeline against each
settled file. This is where the concurrency=1 guarantee, the clobber guard, the
conflict-marker guard, and revert-detection all live.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import frontmatter

from vault_librarian.config import ConfigManager, VaultLibrarianConfig
from vault_librarian.git_safety import GitSafetyNet
from vault_librarian.jobs.store import JobStore
from vault_librarian.llm.factory import LLMFactory
from vault_librarian.workflows import backlink as backlink_wf
from vault_librarian.workflows import format as format_wf
from vault_librarian.workflows import frontmatter as frontmatter_wf
from vault_librarian.workflows import mermaid as mermaid_wf
from vault_librarian.workflows import spellcheck as spellcheck_wf

logger = logging.getLogger("vault_librarian.dispatcher")

CONFLICT_MARKERS = ("<<<<<<<", "=======", ">>>>>>>")
MAX_CONSECUTIVE_FAILURES = 3
# Batched pipeline order: frontmatter normalize -> format -> backlink -> spellcheck -> mermaid.
PIPELINE_ORDER = ["frontmatter", "format", "backlink", "spellcheck", "mermaid"]
ACTIVITY_LOG_REL = Path("Librarian") / "Activity Log.md"
FAILED_PROCESSING_REL = Path("Librarian") / "Failed Processing.md"


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _has_conflict_markers(text: str) -> bool:
    return any(line.startswith(marker) for line in text.splitlines() for marker in CONFLICT_MARKERS)


def _frontmatter_settings(text: str) -> tuple[bool, list[str]]:
    try:
        post = frontmatter.loads(text)
    except Exception:
        return True, []
    vl = post.metadata.get("vault-librarian")
    if not isinstance(vl, dict):
        return True, []
    return bool(vl.get("enabled", True)), list(vl.get("skip", []) or [])


@dataclass
class _PendingFile:
    path: Path
    task: asyncio.Task


class Dispatcher:
    """Owns the debounce timers, the ordered-set queue, and the single sequential worker."""

    def __init__(
        self,
        vault_path: Path,
        config_manager: ConfigManager,
        git_safety: GitSafetyNet,
        job_store: JobStore,
        llm_factory: LLMFactory,
        dry_run: bool = False,
    ):
        self.vault_path = vault_path
        self.config_manager = config_manager
        self.git_safety = git_safety
        self.job_store = job_store
        self.llm_factory = llm_factory
        self.dry_run = dry_run

        self._pending: dict[Path, _PendingFile] = {}
        self._queue: "asyncio.Queue[Path]" = asyncio.Queue()
        self._queued: set[Path] = set()
        self._own_writes: dict[Path, str] = {}  # feedback-loop guard (§4.1)
        # Currently only mermaid has a retry-exhaustion/quarantine concept in Phase 1.
        self._mermaid_failures: dict[Path, int] = {}
        self._worker_task: asyncio.Task | None = None

        self.current_path: Path | None = None
        self.queue_depth = 0

    def start(self) -> None:
        self._worker_task = asyncio.create_task(self._worker_loop())

    async def stop(self) -> None:
        for pending in self._pending.values():
            pending.task.cancel()
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except (asyncio.CancelledError, Exception):
                pass

    def notify(self, event_type: str, path: Path) -> None:
        """Called for every raw watcher event. Resets/starts the per-path quiescence timer."""
        if event_type == "deleted":
            self._own_writes.pop(path, None)
            return
        existing = self._pending.pop(path, None)
        if existing is not None:
            existing.task.cancel()
        debounce_seconds = self.config_manager.config.debounce_seconds
        self._pending[path] = _PendingFile(
            path=path, task=asyncio.create_task(self._settle(path, debounce_seconds))
        )

    async def _settle(self, path: Path, debounce_seconds: float) -> None:
        try:
            await asyncio.sleep(debounce_seconds)
        except asyncio.CancelledError:
            return
        self._pending.pop(path, None)
        if path not in self._queued:
            self._queued.add(path)
            await self._queue.put(path)

    async def _worker_loop(self) -> None:
        while True:
            path = await self._queue.get()
            self._queued.discard(path)
            self.current_path = path
            self.queue_depth = self._queue.qsize()
            try:
                await self._process(path)
            except Exception:
                logger.exception("unhandled error processing %s", path)
            finally:
                self.current_path = None

    async def _process(self, path: Path) -> None:
        if not path.exists():
            return
        try:
            original_text = path.read_text(encoding="utf-8")
        except OSError:
            logger.warning("could not read %s, re-enqueuing", path)
            await self._queue.put(path)
            return

        if self._own_writes.get(path) == _content_hash(original_text):
            # This is the watcher event our own last write generated — suppress the loop.
            self._own_writes.pop(path, None)
            return

        if _has_conflict_markers(original_text):
            logger.warning("skipping %s: unresolved merge-conflict markers present", path)
            return

        enabled, skip = _frontmatter_settings(original_text)
        if not enabled:
            logger.info("skipping %s: automation disabled via frontmatter", path)
            return

        rel_path = str(path.relative_to(self.vault_path))
        config = self.config_manager.config
        mtime_before = path.stat().st_mtime
        text = original_text
        changed_any = False
        ran_workflows: list[str] = []
        started_at = datetime.now(timezone.utc)
        failed_processing_touched = False

        for workflow_name in PIPELINE_ORDER:
            if workflow_name in skip:
                continue
            wf_config = config.workflow(workflow_name)
            if not wf_config.enabled:
                continue

            input_hash = _content_hash(text)
            # Revert detection (§4.2): exempt "frontmatter" so the opt-out schema is always
            # kept normalized rather than permanently skippable via a revert.
            if workflow_name != "frontmatter":
                prior_state = await self.job_store.get_file_state(rel_path, workflow_name)
                if prior_state is not None and prior_state.input_hash == input_hash:
                    logger.info(
                        "%s: reverted to a prior pre-%s state; not reapplying "
                        "(add `skip: [%s]` to frontmatter to suppress permanently)",
                        rel_path,
                        workflow_name,
                        workflow_name,
                    )
                    continue

            new_text, wf_changed, failed_touched = await self._run_workflow(
                workflow_name, text, path, config
            )
            failed_processing_touched = failed_processing_touched or failed_touched
            if wf_changed:
                text = new_text
                changed_any = True
                ran_workflows.append(workflow_name)
                await self.job_store.record_file_state(
                    rel_path, workflow_name, input_hash, _content_hash(text)
                )

        finished_at = datetime.now(timezone.utc)

        if not changed_any:
            return

        if self.dry_run:
            logger.info("[dry-run] %s: would apply %s", rel_path, ", ".join(ran_workflows))
            await self.job_store.record_run(
                rel_path, ran_workflows, "dry-run", None, None, started_at, finished_at
            )
            return

        # Live-edit clobber guard (§4.2): bail if the file changed on disk since we started.
        try:
            mtime_now = path.stat().st_mtime
        except OSError:
            return
        if mtime_now != mtime_before:
            logger.info("%s changed while processing; re-enqueuing instead of overwriting", rel_path)
            await self._queue.put(path)
            return

        self._own_writes[path] = _content_hash(text)
        path.write_text(text, encoding="utf-8")

        self._append_activity_log(rel_path, ran_workflows)
        touched_paths = [path, self.vault_path / ACTIVITY_LOG_REL]
        if failed_processing_touched:
            touched_paths.append(self.vault_path / FAILED_PROCESSING_REL)

        commit_message = f"vault-librarian: {', '.join(ran_workflows)} — {rel_path}"
        commit_sha = None
        try:
            commit_sha = await self.git_safety.commit_paths(touched_paths, commit_message)
        except Exception:
            logger.exception("git commit failed for %s", rel_path)

        await self.job_store.record_run(
            rel_path, ran_workflows, "ok", None, commit_sha, started_at, finished_at
        )

    async def _run_workflow(
        self, name: str, text: str, path: Path, config: VaultLibrarianConfig
    ) -> tuple[str, bool, bool]:
        """Returns (new_text, changed, failed_processing_touched)."""
        if name == "frontmatter":
            new_text, changed = frontmatter_wf.run(text)
            return new_text, changed, False
        if name == "format":
            new_text, changed = format_wf.run(text)
            return new_text, changed, False
        if name == "backlink":
            new_text, changed = backlink_wf.run(text, self.vault_path, path, config.ignore_paths)
            return new_text, changed, False
        if name == "spellcheck":
            tier = config.workflow("spellcheck").model
            caller = self.llm_factory.caller_for(tier)
            new_text, changed = await spellcheck_wf.run(text, caller)
            return new_text, changed, False
        if name == "mermaid":
            tier = config.workflow("mermaid").model
            caller = self.llm_factory.caller_for(tier)
            result = await mermaid_wf.run(text, caller)
            failed_touched = False
            if result.quarantined_blocks:
                failed_touched = self._note_mermaid_failure(
                    path, f"{len(result.quarantined_blocks)} block(s) still invalid after retries"
                )
            else:
                self._mermaid_failures.pop(path, None)
            return result.text, result.changed, failed_touched
        raise ValueError(f"unknown workflow {name}")

    def _append_activity_log(self, rel_path: str, workflows: list[str]) -> None:
        log_path = self.vault_path / ACTIVITY_LOG_REL
        log_path.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        line = f"- {ts} — `{rel_path}`: {', '.join(workflows)}\n"
        with log_path.open("a", encoding="utf-8") as f:
            f.write(line)

    def _note_mermaid_failure(self, path: Path, detail: str) -> bool:
        """Failure quarantine (§4.14): stop retrying silently after N consecutive failures and
        log to Failed Processing.md. Returns True iff Failed Processing.md was written."""
        count = self._mermaid_failures.get(path, 0) + 1
        self._mermaid_failures[path] = count
        if count < MAX_CONSECUTIVE_FAILURES:
            return False
        rel_path = str(path.relative_to(self.vault_path))
        log_path = self.vault_path / FAILED_PROCESSING_REL
        log_path.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        line = f"- {ts} — `{rel_path}` [mermaid]: {detail} (after {count} attempts)\n"
        with log_path.open("a", encoding="utf-8") as f:
            f.write(line)
        return True
