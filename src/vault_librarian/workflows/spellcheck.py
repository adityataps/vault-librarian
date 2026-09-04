"""Spellcheck workflow (architecture.md §4.3).

Spelling semantics are fuzzy, so this is LLM-backed rather than deterministic (design
principle 1). Skips gracefully — logs and no-ops — if no usable provider/credentials are
configured, rather than failing the whole file's pipeline.
"""

from __future__ import annotations

import logging
from typing import Awaitable, Callable, Optional

logger = logging.getLogger("vault_librarian.workflows.spellcheck")

PROMPT_TEMPLATE = (
    "You are a careful copy-editor. Fix ONLY spelling mistakes in the following Markdown "
    "note. Do not change wording, tone, formatting, links, code blocks, or frontmatter. If "
    "there are no spelling mistakes, return the text completely unchanged. Return ONLY the "
    "corrected Markdown, no commentary.\n\n{text}"
)


async def run(text: str, llm_call: Optional[Callable[[str], Awaitable[str]]]) -> tuple[str, bool]:
    if llm_call is None:
        logger.info("spellcheck skipped: no LLM provider configured/available")
        return text, False
    try:
        result = await llm_call(PROMPT_TEMPLATE.format(text=text))
    except Exception:
        logger.exception("spellcheck LLM call failed; leaving file unchanged")
        return text, False
    if not result or not result.strip():
        return text, False
    new_text = result if result.endswith("\n") else result + "\n"
    if new_text == text:
        return text, False
    return new_text, True
