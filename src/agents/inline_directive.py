from __future__ import annotations

import logging
import re

from langchain_core.messages import HumanMessage, SystemMessage

from src.agents.state import Directive, VaultState
from src.config import AppConfig
from src.vault.tools import VaultTools

log = logging.getLogger(__name__)

_TAG_RE = re.compile(
    r"<agent-(scaffold|context)>(.*?)</agent-\1>|<agent-fill\s*/>",
    re.DOTALL,
)

_SYSTEM_PROMPT = "You are an inline content generator for an Obsidian vault note. Generate concise, well-formatted markdown content based on the user's prompt and surrounding note context. Do not include the prompt itself in your output."


def _find_directives(content: str) -> list[Directive]:
    directives = []
    for m in _TAG_RE.finditer(content):
        tag = m.group(1) or "fill"
        prompt = (m.group(2) or "").strip()
        directives.append(Directive(tag=tag, prompt=prompt, start=m.start(), end=m.end()))
    return directives


def inline_directive_node(
    state: VaultState, llm, tools: VaultTools, vector_store, cfg: AppConfig, **_
) -> dict:
    directives = _find_directives(state["note_content"])
    if not directives:
        return {"directives": [], "changes": []}

    content = state["note_content"]
    changes = []
    offset = 0

    for d in directives:
        context_notes = ""
        if d.tag == "context":
            try:
                similar = vector_store.search_similar(d.prompt, k=3)
                context_notes = "\n\n".join(
                    f"From {p}:\n{tools.read_note(p)[:500]}" for p in similar
                )
            except Exception:
                pass

        surrounding = content[max(0, d.start + offset - 300) : d.start + offset]
        user_prompt = f"Note: {state['note_path']}\nContext:\n{surrounding}\n\nDirective ({d.tag}): {d.prompt}"
        if context_notes:
            user_prompt += f"\n\nRelated vault content:\n{context_notes}"

        try:
            response = llm.invoke(
                [SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=user_prompt)]
            )
            generated = response.content.strip()
        except Exception as exc:
            log.warning("Inline directive LLM failed: %s", exc)
            continue

        replacement = generated
        start = d.start + offset
        end = d.end + offset
        content = content[:start] + replacement + content[end:]
        offset += len(replacement) - (d.end - d.start)
        changes.append(f"Inline directive ({d.tag}) resolved")

    if changes:
        # Always write back — the directive tags must be consumed so they
        # don't re-trigger on the next file save.
        tools.write_note(
            state["note_path"], content, dispatch_hash=state.get("dispatch_hash") or None
        )

    return {"directives": directives, "changes": changes}
