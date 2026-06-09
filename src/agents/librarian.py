from __future__ import annotations

import logging
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from src.agents.state import VaultState
from src.autonomy.inbox import LibrarianInbox
from src.config import AppConfig
from src.vault.tools import VaultTools

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are the Librarian agent for an Obsidian vault. Your job is to:
1. Classify the note type (meeting, project, jira, tech_note, career, reference, personal)
2. Decide which folder the note belongs in

Vault folder taxonomy (use these exact folder names):
- Projects/ — active work with deliverables
- Career/ — interview prep, retrospectives, STAR stories
- Meetings/ — any meeting, desk check, sprint demo
- Jira/ — ticket notes matching AICOE-* or similar patterns
- Tech Notes/ — reference material, how-tos, technical docs
- Reference/ — glossary, definitions
- Personal/ — anything non-work related

Rules:
- If the note is already in the correct folder, set target_folder to the current folder name
- Notes at vault root: always assign a folder
- Prefer Projects/ over Career/ for AI platform work
"""


class FilingDecision(BaseModel):
    note_type: str
    target_folder: str
    reasoning: str


def librarian_node(state: VaultState, llm, tools: VaultTools, cfg: AppConfig, **_) -> dict:
    instructions = cfg.get_agent_instructions("librarian")
    system = _SYSTEM_PROMPT
    if instructions:
        system += f"\n\nAdditional instructions:\n{instructions}"

    structured = llm.with_structured_output(FilingDecision)
    try:
        decision: FilingDecision = structured.invoke(
            [
                SystemMessage(content=system),
                HumanMessage(
                    content=f"Note path: {state['note_path']}\n\n{state['note_content'][:2000]}"
                ),
            ]
        )
    except Exception as exc:
        log.warning("Librarian LLM call failed for %s: %s", state["note_path"], exc)
        return {"note_type": None, "changes": [f"Librarian skipped: {exc}"]}

    current_folder = str(Path(state["note_path"]).parent)
    if current_folder == ".":
        current_folder = ""
    target = decision.target_folder.rstrip("/")

    changes = [f"Classified as {decision.note_type}"]

    if Path(current_folder) != Path(target):
        filename = Path(state["note_path"]).name
        dst_rel = f"{target}/{filename}"
        if cfg.get_autonomy("librarian") == "full":
            try:
                tools.move_note(state["note_path"], dst_rel)
                changes.append(f"Moved to {target}/")
            except Exception as exc:
                log.warning("Librarian move failed: %s", exc)
                changes.append(f"Move to {target}/ failed: {exc}")
        else:
            _propose(tools, cfg, f"Move `{state['note_path']}` → `{dst_rel}`")
            changes.append(f"Proposed: move to {target}/")

    return {"note_type": decision.note_type, "changes": changes}


def _propose(tools: VaultTools, cfg: AppConfig, action: str) -> None:
    LibrarianInbox(cfg, tools).propose(action)
