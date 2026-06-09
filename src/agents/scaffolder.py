from __future__ import annotations

import logging
from datetime import date

from langchain_core.messages import HumanMessage, SystemMessage

from src.config import AppConfig
from src.vault.tools import VaultTools

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are the Scaffolder agent. Generate a well-structured Obsidian note stub.

Rules:
- Include YAML frontmatter with tags, type, created, modified
- Follow the template structure if provided
- Pre-fill any fields you can infer from the title and context
- Leave genuinely unknown fields empty (not placeholder text)
"""

_FOLDER_MAP: dict[str, str] = {
    "meeting": "Meetings",
    "project": "Projects",
    "jira": "Jira",
    "tech_note": "Tech Notes",
    "career": "Career",
    "reference": "Reference",
}


def run_scaffolder(
    title: str, note_type: str, context: str, llm, tools: VaultTools, cfg: AppConfig
) -> str:
    today = date.today().isoformat()
    template_content = ""
    try:
        template_rel = f"Templates/{note_type.replace('_', ' ').title()} Template.md"
        template_content = tools.read_note(template_rel)
    except FileNotFoundError:
        pass

    prompt = f"Title: {title}\nType: {note_type}\nDate: {today}"
    if context:
        prompt += f"\nContext: {context}"
    if template_content:
        prompt += f"\n\nTemplate to follow:\n{template_content[:1500]}"

    try:
        response = llm.invoke([SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=prompt)])
        content = response.content.strip()
    except Exception as exc:
        log.warning("Scaffolder LLM failed: %s", exc)
        content = f"---\ntitle: {title}\ntype: {note_type}\ncreated: {today}\n---\n# {title}\n"

    safe_title = title.replace("/", "-").replace(":", "-")
    folder = _FOLDER_MAP.get(note_type, "")
    rel = f"{folder}/{safe_title}.md" if folder else f"{safe_title}.md"
    tools.create_note(rel, content)
    log.info("Scaffolded %s", rel)
    return rel
