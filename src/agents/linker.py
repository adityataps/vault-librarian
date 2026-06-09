from __future__ import annotations

import logging
import re

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from src.agents.state import VaultState
from src.autonomy.inbox import LibrarianInbox
from src.config import AppConfig
from src.vault.tools import VaultTools

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are the Linker agent. Given a note and candidate related notes, decide which are genuinely related and should appear in a Related section.

Return only paths that are meaningfully related (not superficially). Max 5. Exclude the note itself.
"""


class LinkDecision(BaseModel):
    related_paths: list[str]
    reasoning: str


def linker_node(
    state: VaultState, llm, tools: VaultTools, vector_store, cfg: AppConfig, **_
) -> dict:
    instructions = cfg.get_agent_instructions("linker")
    try:
        candidates = [
            c
            for c in vector_store.search_similar(state["note_content"], k=8)
            if c != state["note_path"]
        ]
    except Exception as exc:
        log.warning("Vector search failed: %s", exc)
        return {"changes": []}

    if not candidates:
        return {"changes": []}

    structured = llm.with_structured_output(LinkDecision)
    try:
        decision: LinkDecision = structured.invoke(
            [
                SystemMessage(
                    content=_SYSTEM_PROMPT + (f"\n\n{instructions}" if instructions else "")
                ),
                HumanMessage(
                    content=f"Note: {state['note_path']}\n\nCandidates:\n" + "\n".join(candidates)
                ),
            ]
        )
    except Exception as exc:
        log.warning("Linker LLM failed: %s", exc)
        return {"changes": []}

    if not decision.related_paths:
        return {"related_notes": [], "changes": []}

    links = " · ".join(f"[[{p.removesuffix('.md')}]]" for p in decision.related_paths)
    related_section = f"\n\n## Related\n{links}\n"
    content = state["note_content"]
    if "## Related" in content:
        content = re.sub(r"\n## Related\n.*?(?=\n##|\Z)", related_section, content, flags=re.DOTALL)
    else:
        content = content.rstrip() + related_section

    if cfg.get_autonomy("linker") == "full":
        tools.write_note(
            state["note_path"], content, dispatch_hash=state.get("dispatch_hash") or None
        )
        changes = [f"Linker: added {len(decision.related_paths)} backlinks"]
    else:
        LibrarianInbox(cfg, tools).propose(f"Add Related section to `{state['note_path']}`")
        changes = [f"Linker: proposed {len(decision.related_paths)} backlinks"]

    try:
        vector_store.upsert(state["note_path"], content)
    except Exception as exc:
        log.debug("Vector upsert failed: %s", exc)

    return {"related_notes": decision.related_paths, "changes": changes}
