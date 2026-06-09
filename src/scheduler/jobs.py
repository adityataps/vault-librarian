from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from src.config import AppConfig

log = logging.getLogger(__name__)


def _parse_cron(expr: str) -> dict:
    """Convert '0 2 * * *' to APScheduler trigger kwargs."""
    parts = expr.split()
    if len(parts) != 5:
        raise ValueError(f"Invalid cron expression: {expr!r}")
    minute, hour, day, month, day_of_week = parts
    return {"minute": minute, "hour": hour, "day": day, "month": month, "day_of_week": day_of_week}


def build_scheduler(cfg: AppConfig, db, tools, llm) -> AsyncIOScheduler:
    """Build a configured AsyncIOScheduler (not yet started)."""
    from src.agents.auditor import run_auditor_full
    from src.agents.daily_brief import run_daily_brief
    from src.agents.weekly_review import run_weekly_review

    scheduler = AsyncIOScheduler()

    if "auditor" in cfg.enrolled_agents:
        scheduler.add_job(
            run_auditor_full,
            trigger="cron",
            kwargs={"cfg": cfg, "db": db, "tools": tools, "llm": llm},
            id="auditor_full",
            replace_existing=True,
            misfire_grace_time=3600,
            **_parse_cron(cfg.auditor_schedule),
        )
        log.info("Auditor scheduled: %s", cfg.auditor_schedule)

    if "daily_brief" in cfg.enrolled_agents:
        scheduler.add_job(
            run_daily_brief,
            trigger="cron",
            kwargs={"cfg": cfg, "db": db, "tools": tools, "llm": llm},
            id="daily_brief",
            replace_existing=True,
            misfire_grace_time=3600,
            **_parse_cron(cfg.daily_brief_schedule),
        )
        log.info("Daily Brief scheduled: %s", cfg.daily_brief_schedule)

    if "weekly_review" in cfg.enrolled_agents:
        scheduler.add_job(
            run_weekly_review,
            trigger="cron",
            kwargs={"cfg": cfg, "db": db, "tools": tools, "llm": llm},
            id="weekly_review",
            replace_existing=True,
            misfire_grace_time=3600,
            **_parse_cron(cfg.weekly_review_schedule),
        )
        log.info("Weekly Review scheduled: %s", cfg.weekly_review_schedule)

    return scheduler
