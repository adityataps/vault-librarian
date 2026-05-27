"""APScheduler jobs with real crew implementations."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from src.llm import LLMRouter
from src.storage import StorageBackend, NoteFilter
from src.storage.models import AgentRunCreate, AgentRunUpdate, AuditReportCreate

if TYPE_CHECKING:
    from src.config import Settings

logger = logging.getLogger(__name__)


async def daily_audit_job(
    storage: StorageBackend,
    llm_router: LLMRouter,
    vault_root: Path,
    excluded_folders: list[str],
) -> None:
    """Run a full vault health audit and save the report to storage."""
    from src.crews.daily_audit import DailyAuditCrew
    from src.tools.graph_traversal import GraphTraversalTool
    from src.watcher.scanner import VaultScanner

    run = await storage.create_agent_run(
        AgentRunCreate(crew_name="DailyAuditCrew", trigger_type="scheduled")
    )
    started = datetime.now(timezone.utc)
    logger.info("Daily audit started (run_id=%s)", run.id)

    try:
        scanner = VaultScanner(vault_root=vault_root, excluded_folders=excluded_folders)
        scan = scanner.scan()
        now = datetime.now(timezone.utc)
        stale_cutoff = now - timedelta(days=90)

        stale = [n.path for n in scan.parsed if n.last_modified < stale_cutoff]  # type: ignore[attr-defined]
        missing_type = [n.path for n in scan.parsed if not n.frontmatter.get("type")]

        # Broken links from storage
        broken = await storage.get_broken_links()

        graph_tool = GraphTraversalTool(storage=storage)
        crew = DailyAuditCrew(
            llm_router=llm_router,
            storage=storage,
            graph_traversal=graph_tool,
        )
        summary = crew.run(
            vault_stats={
                "total_notes": scan.success_count,
                "stale_notes": stale,
                "broken_links": [{"source": l.source_note_id, "target": l.target_path} for l in broken],
                "orphan_notes": [],  # computed by graph tool during crew run
                "notes_missing_type": missing_type,
            }
        )

        elapsed_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
        await storage.update_agent_run(
            run.id,
            AgentRunUpdate(
                status="success",
                duration_ms=elapsed_ms,
                notes_processed=scan.success_count,
            ),
        )
        await storage.save_audit_report(
            AuditReportCreate(
                agent_run_id=run.id,
                report_type="daily_audit",
                summary=summary[:500],
                findings=[{"full_report": summary}],
            )
        )
        logger.info("Daily audit complete (%dms)", elapsed_ms)

    except Exception as exc:
        elapsed_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
        logger.error("Daily audit failed: %s", exc)
        await storage.update_agent_run(
            run.id,
            AgentRunUpdate(status="failed", duration_ms=elapsed_ms, error_message=str(exc)),
        )


async def jira_sync_job(
    storage: StorageBackend,
    llm_router: LLMRouter,
    vault_root: Path,
    jira_base_url: str,
    jira_username: str,
    jira_api_token: str,
    jql_filter: str,
    jira_folder: str = "Work/Jira",
) -> None:
    """Fetch Jira tickets and sync them as vault notes."""
    from src.crews.jira_sync import JiraSyncCrew
    from src.tools.jira_client import JiraClient

    run = await storage.create_agent_run(
        AgentRunCreate(crew_name="JiraSyncCrew", trigger_type="scheduled")
    )
    started = datetime.now(timezone.utc)
    logger.info("Jira sync started (run_id=%s)", run.id)

    try:
        async with JiraClient(jira_base_url, jira_username, jira_api_token) as jira:
            crew = JiraSyncCrew(
                llm_router=llm_router,
                storage=storage,
                jira_client=jira,
                vault_root=vault_root,
                jira_folder=jira_folder,
                jql_filter=jql_filter,
            )
            result = await crew.run()

        elapsed_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
        status = "failed" if result.errors and result.tickets_fetched == 0 else "success"
        await storage.update_agent_run(
            run.id,
            AgentRunUpdate(
                status=status,
                duration_ms=elapsed_ms,
                notes_created=result.notes_created,
                notes_updated=result.notes_updated,
                error_message="; ".join(result.errors) if result.errors else None,
            ),
        )
        logger.info(
            "Jira sync complete: %d created, %d updated (%dms)",
            result.notes_created, result.notes_updated, elapsed_ms,
        )

    except Exception as exc:
        elapsed_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
        logger.error("Jira sync failed: %s", exc)
        await storage.update_agent_run(
            run.id,
            AgentRunUpdate(status="failed", duration_ms=elapsed_ms, error_message=str(exc)),
        )


async def weekly_digest_job(storage: StorageBackend, llm_router: LLMRouter) -> None:
    """Generate a weekly digest report summarising vault activity."""
    logger.info("Weekly digest triggered — pulling recent audit reports")
    reports = await storage.get_recent_reports(limit=7)
    logger.info("Weekly digest: %d recent reports found", len(reports))
    # Full implementation wired in when digest crew is added


def build_scheduler(
    settings: "Settings",
    storage: StorageBackend,
    llm_router: LLMRouter,
) -> AsyncIOScheduler:
    """Build and configure the application scheduler."""
    scheduler = AsyncIOScheduler()

    if not settings.scheduler.enabled:
        logger.info("Scheduler disabled in configuration")
        return scheduler

    vault_root = settings.vault.path
    excluded_folders = list(settings.vault.excluded_folders)

    scheduler.add_job(
        daily_audit_job,
        trigger=CronTrigger(
            hour=settings.scheduler.daily_audit_hour,
            minute=settings.scheduler.daily_audit_minute,
        ),
        id="daily_audit",
        replace_existing=True,
        kwargs={
            "storage": storage,
            "llm_router": llm_router,
            "vault_root": vault_root,
            "excluded_folders": excluded_folders,
        },
    )

    if settings.jira.enabled and settings.jira.base_url and settings.jira.api_token:
        scheduler.add_job(
            jira_sync_job,
            trigger=IntervalTrigger(minutes=settings.scheduler.jira_sync_interval_minutes),
            id="jira_sync",
            replace_existing=True,
            kwargs={
                "storage": storage,
                "llm_router": llm_router,
                "vault_root": vault_root,
                "jira_base_url": settings.jira.base_url,
                "jira_username": settings.jira.username or "",
                "jira_api_token": settings.jira.api_token,
                "jql_filter": settings.jira.jql_filter,
            },
        )
        logger.info("Jira sync job registered (every %dm)", settings.scheduler.jira_sync_interval_minutes)
    else:
        logger.info("Jira sync skipped — Jira not enabled or missing credentials")

    scheduler.add_job(
        weekly_digest_job,
        trigger=CronTrigger(
            day_of_week=settings.scheduler.weekly_digest_day,
            hour=settings.scheduler.weekly_digest_hour,
            minute=0,
        ),
        id="weekly_digest",
        replace_existing=True,
        kwargs={"storage": storage, "llm_router": llm_router},
    )

    logger.info("Scheduler configured with %d jobs", len(scheduler.get_jobs()))
    return scheduler

