from __future__ import annotations

import logging
from datetime import date, datetime, timezone, timedelta

from langchain_core.messages import HumanMessage, SystemMessage

from src.config import AppConfig
from src.storage.repository import ActionItemRepo, AuditLogRepo, NoteRepo
from src.vault.tools import VaultTools

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are the Daily Brief agent for an Obsidian vault. Given raw data about
the user's work, write a concise daily brief note in Obsidian markdown. Include:
- A short 2-3 sentence summary paragraph
- Sections for open tickets, recent meetings, unresolved action items (if any)
- A vault health score (0-100, estimate based on note counts and activity)

Keep it scannable. Use Obsidian markdown (## headings, bullet points). Max 400 words.
"""


async def run_daily_brief(
    cfg: AppConfig,
    db,
    tools: VaultTools,
    llm,
) -> None:
    today = date.today().isoformat()

    note_repo = NoteRepo(db)
    action_repo = ActionItemRepo(db)
    audit_repo = AuditLogRepo(db)

    all_hashes = await note_repo.all_hashes()
    action_items = await action_repo.unresolved()
    recent_audit = await audit_repo.query(since="1d", limit=50)

    jira_notes = [p for p in all_hashes if p.startswith("Jira/")]
    meeting_notes = [p for p in all_hashes if p.startswith("Meetings/")]

    agent_summary: dict[str, int] = {}
    for entry in recent_audit:
        agent_summary[entry.agent] = agent_summary.get(entry.agent, 0) + 1

    context = (
        f"Date: {today}\n"
        f"Jira notes in vault: {len(jira_notes)}\n"
        f"Recent meeting notes: {', '.join(meeting_notes[-3:]) or 'none'}\n"
        f"Unresolved action items: {len(action_items)}\n"
        f"Yesterday's agent operations: {dict(list(agent_summary.items())[:5])}\n"
        f"Total vault notes: {len(all_hashes)}\n"
    )

    try:
        response = llm.invoke([
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=context),
        ])
        content = response.content.strip()
    except Exception as exc:
        log.warning("Daily Brief LLM failed: %s", exc)
        content = f"_LLM unavailable — raw data:_\n\n{context}"

    note = f"---\ndate: {today}\ntype: daily_brief\n---\n# Daily Brief — {today}\n\n{content}\n"
    tools.create_note(f".librarian/Daily Brief — {today}.md", note)
    log.info("Daily Brief written for %s", today)
