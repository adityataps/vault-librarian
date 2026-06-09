from __future__ import annotations

import logging

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from src.agents.state import VaultState
from src.autonomy.inbox import LibrarianInbox
from src.config import AppConfig
from src.vault.tools import VaultTools

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are the Meeting Enricher agent. Extract action items from this meeting note and identify the linked project.

Return action items as plain strings (no markdown). Each is a concrete task.
If no project is clearly referenced, return empty linked_project.
If no action items, return empty list.
"""


class MeetingAnalysis(BaseModel):
    action_items: list[str]
    linked_project: str
    missing_fields: dict


def meeting_enricher_node(state: VaultState, llm, tools: VaultTools, cfg: AppConfig, **_) -> dict:
    if state.get("note_type") != "meeting":
        return {"changes": []}

    instructions = cfg.get_agent_instructions("meeting_enricher")
    system = _SYSTEM_PROMPT + (f"\n\n{instructions}" if instructions else "")

    structured = llm.with_structured_output(MeetingAnalysis)
    try:
        analysis: MeetingAnalysis = structured.invoke(
            [
                SystemMessage(content=system),
                HumanMessage(content=state["note_content"][:2000]),
            ]
        )
    except Exception as exc:
        log.warning("MeetingEnricher failed: %s", exc)
        return {"changes": [f"MeetingEnricher skipped: {exc}"]}

    changes = []
    autonomy = cfg.get_autonomy("meeting_enricher")

    if analysis.missing_fields and autonomy == "full":
        tools.update_frontmatter(state["note_path"], analysis.missing_fields)
        changes.append(f"Meeting: added {list(analysis.missing_fields.keys())}")

    if analysis.action_items and analysis.linked_project:
        items_md = "\n".join(
            f"- [ ] {item} ([[{state['note_path']}]])" for item in analysis.action_items
        )
        project_rel = f"Projects/{analysis.linked_project}.md"
        try:
            existing = tools.read_note(project_rel)
            if "## Action Items" not in existing:
                updated = existing.rstrip() + f"\n\n## Action Items\n{items_md}\n"
            else:
                updated = existing.rstrip() + f"\n{items_md}\n"
            if autonomy == "full":
                tools.write_note(project_rel, updated)
                changes.append(
                    f"Meeting: added {len(analysis.action_items)} action items to {project_rel}"
                )
            else:
                LibrarianInbox(cfg, tools).propose(
                    f"Add action items to `{project_rel}` from `{state['note_path']}`"
                )
                changes.append(f"Meeting: proposed action items for {project_rel}")
        except FileNotFoundError:
            log.debug("Linked project note not found: %s", project_rel)

    return {"action_items": analysis.action_items, "changes": changes}
