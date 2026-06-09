from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from src.config import AppConfig
from src.dispatcher.debounce import DebounceMap
from src.dispatcher.locks import FileLockMap
from src.vault.tools import VaultTools

log = logging.getLogger(__name__)

_CONFIG_REL = "Librarian/config.md"
_INBOX_REL = "Librarian/Inbox.md"


class Dispatcher:
    def __init__(
        self,
        cfg: AppConfig,
        db,  # Database — stored directly so reconcile() doesn't reach into runner internals
        tools: VaultTools,
        pipeline_runner,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        self._cfg = cfg
        self._db = db
        self._tools = tools
        self._runner = pipeline_runner
        self._loop = loop or asyncio.get_event_loop()
        self._debounce = DebounceMap(default_delay=cfg.debounce_standard, loop=self._loop)
        self._locks = FileLockMap()

    def on_file_event(self, abs_path: str, event_type: str) -> None:
        try:
            rel = str(Path(abs_path).relative_to(self._cfg.vault_path))
        except ValueError:
            log.warning("Event path outside vault root: %s", abs_path)
            return
        if rel == _CONFIG_REL:
            self._debounce.schedule(rel, self._reload_config, delay=0.5)
            return
        if rel == _INBOX_REL:
            self._debounce.schedule(
                rel, self._process_inbox, delay=self._cfg.debounce_inbox
            )
            return
        try:
            has_directive = self._tools.has_directive_tags(rel)
        except Exception:
            has_directive = False
        delay = self._cfg.debounce_directive if has_directive else self._cfg.debounce_standard
        self._debounce.schedule(rel, lambda r=rel: self._dispatch(r), delay=delay)

    def _reload_config(self) -> None:
        try:
            from src.vault_config.loader import VaultConfigLoader

            VaultConfigLoader(self._cfg).apply()
            log.info("Config reloaded from %s", _CONFIG_REL)
        except Exception as exc:
            log.warning("Config reload failed: %s", exc)

    def _process_inbox(self) -> None:
        self._loop.create_task(self._run_inbox())

    async def _run_inbox(self) -> None:
        async with self._locks.acquire(_INBOX_REL):
            try:
                from src.autonomy.inbox import LibrarianInbox

                inbox = LibrarianInbox(self._cfg, self._tools)
                log.info("Inbox: checking for user-checked items…")
                executed = inbox.execute_checked()
                if executed:
                    log.info("Inbox: executed %d item(s): %s", len(executed), executed)
                else:
                    log.debug("Inbox: no checked items to execute")
            except Exception:
                log.exception("Inbox processing failed")

    def _dispatch(self, rel: str) -> None:
        # Called from the event loop (via call_later), so create_task is always safe here.
        self._loop.create_task(self._run_pipeline(rel))

    async def _run_pipeline(self, rel: str) -> None:
        async with self._locks.acquire(rel):
            try:
                await self._runner.run(rel)
            except Exception:
                log.exception("Pipeline failed for %s", rel)

    async def reconcile(self) -> None:
        from src.storage.repository import AgentRunRepo, NoteRepo
        from src.vault.scanner import VaultScanner

        note_repo = NoteRepo(self._db)
        run_repo = AgentRunRepo(self._db)
        stored_hashes = await note_repo.all_hashes()
        pipeline_agents = set(self._cfg.enrolled_agents) - {
            "scaffolder",
            "daily_brief",
            "weekly_review",
        }
        for meta in VaultScanner(self._cfg).iter_notes():
            stored_hash = stored_hashes.get(meta.path)
            completed = await run_repo.completed_agents(meta.path, meta.content_hash)
            if meta.content_hash != stored_hash or not pipeline_agents.issubset(completed):
                self._debounce.schedule(meta.path, lambda r=meta.path: self._dispatch(r), delay=0.1)
