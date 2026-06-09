from __future__ import annotations

import logging
import re
from datetime import date

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from src.agents.state import VaultState
from src.autonomy.inbox import LibrarianInbox
from src.config import AppConfig
from src.vault.tools import VaultTools

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are the Formatter agent for an Obsidian vault. Audit the note's frontmatter and suggest missing or incorrect fields.

Rules:
- NEVER suggest changes to content inside ```dataview ... ``` blocks
- Always suggest `created` and `modified` dates if missing (use today: {today})
- Normalize tag casing to lowercase-hyphenated
- For meeting notes: ensure `date` field exists
- Only suggest fields that are genuinely missing or wrong
- Return empty fields_to_add dict if nothing needs fixing
"""

_DATAVIEW_RE = re.compile(r"```dataview.*?```", re.DOTALL)


class FrontmatterFix(BaseModel):
    fields_to_add: dict
    reasoning: str


def _strip_dataview(content: str) -> str:
    return _DATAVIEW_RE.sub("```dataview[preserved]```", content)


def formatter_node(state: VaultState, llm, tools: VaultTools, cfg: AppConfig, **_) -> dict:
    instructions = cfg.get_agent_instructions("formatter")
    today = date.today().isoformat()
    system = _SYSTEM_PROMPT.replace("{today}", today)
    if instructions:
        system += f"\n\nAdditional instructions:\n{instructions}"

    safe_content = _strip_dataview(state["note_content"])
    structured = llm.with_structured_output(FrontmatterFix)
    try:
        fix: FrontmatterFix = structured.invoke(
            [
                SystemMessage(content=system),
                HumanMessage(
                    content=f"Path: {state['note_path']}\nFrontmatter: {state['frontmatter']}\n\n{safe_content[:1500]}"
                ),
            ]
        )
    except Exception as exc:
        log.warning("Formatter LLM failed for %s: %s", state["note_path"], exc)
        return {"changes": [f"Formatter skipped: {exc}"]}

    if not fix.fields_to_add:
        return {"changes": []}

    if cfg.get_autonomy("formatter") == "full":
        try:
            tools.update_frontmatter(state["note_path"], fix.fields_to_add)
            return {"changes": [f"Formatter: added {list(fix.fields_to_add.keys())}"]}
        except Exception as exc:
            log.warning("Formatter write failed: %s", exc)
            return {"changes": [f"Formatter write failed: {exc}"]}
    else:
        LibrarianInbox(cfg, tools).propose(
            f"Update frontmatter on `{state['note_path']}`: add {fix.fields_to_add}"
        )
        return {"changes": [f"Formatter: proposed frontmatter update for {state['note_path']}"]}
