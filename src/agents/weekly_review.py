from __future__ import annotations

import logging
from datetime import date, datetime, timezone, timedelta

from langchain_core.messages import HumanMessage, SystemMessage

from src.config import AppConfig
from src.storage.repository import ActionItemRepo, AuditLogRepo, NoteRepo
from src.vault.tools import VaultTools

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are the Weekly Review agent for an Obsidian vault. Given raw data,
write a concise weekly review note in Obsidian markdown. Include:
- A paragraph summarising the week
- What was shipped or closed
- What carries over to next week

Reflective and actionable. Obsidian markdown, max 500 words.
"""


async def run_weekly_review(
    cfg: AppConfig,
    db,
    tools: VaultTools,
    llm,
) -> None:
    today = date.today()
    iso_year, iso_week, _ = today.isocalendar()
    week_label = f"{iso_year}-W{iso_week:02d}"

    note_repo = NoteRepo(db)
    action_repo = ActionItemRepo(db)
    audit_repo = AuditLogRepo(db)

    all_hashes = await note_repo.all_hashes()
    unresolved = await action_repo.unresolved()
    weekly_audit = await audit_repo.query(since="7d", limit=200)

    agent_summary: dict[str, int] = {}
    for entry in weekly_audit:
        agent_summary[entry.agent] = agent_summary.get(entry.agent, 0) + 1

    meeting_notes = [p for p in all_hashes if p.startswith("Meetings/")]
    jira_notes = [p for p in all_hashes if p.startswith("Jira/")]

    context = (
        f"Week: {week_label}\n"
        f"Meeting notes: {', '.join(meeting_notes[-5:]) or 'none'}\n"
        f"Jira tickets in vault: {len(jira_notes)}\n"
        f"Unresolved action items: {len(unresolved)}\n"
        f"Agent operations this week: {dict(list(agent_summary.items())[:8])}\n"
        f"Total vault notes: {len(all_hashes)}\n"
    )

    try:
        response = llm.invoke([
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=context),
        ])
        content = response.content.strip()
    except Exception as exc:
        log.warning("Weekly Review LLM failed: %s", exc)
        content = f"_LLM unavailable_\n\n{context}"

    note = (
        f"---\nweek: {week_label}\ntype: weekly_review\n---\n"
        f"# Weekly Review — {week_label}\n\n{content}\n"
    )
    tools.create_note(f".librarian/Weekly Review — {week_label}.md", note)
    log.info("Weekly Review written for %s", week_label)
