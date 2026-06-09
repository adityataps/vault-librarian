from __future__ import annotations

import logging
import re
from pathlib import Path

from src.agents.state import VaultState
from src.autonomy.inbox import LibrarianInbox
from src.config import AppConfig
from src.vault.tools import VaultTools

log = logging.getLogger(__name__)

_FOLDER_MOC: dict[str, str] = {
    "Projects": "Work MOC.md",
    "Jira": "Work MOC.md",
    "Meetings": "Work MOC.md",
    "Tech Notes": "Work MOC.md",
}

_SECTION_MAP: dict[str, str] = {
    "Projects": "## 🏗 Active Projects",
    "Jira": "## 🎫 Jira Tickets",
    "Meetings": "## 📋 Meetings",
    "Tech Notes": "## 📚 Tech Notes",
}

_STATUS_ICONS: dict[str, str] = {
    "In Progress": "🟡",
    "Planning": "🔵",
    "Backlog": "⚪",
    "Blocked": "🔴",
    "Done": "✅",
}


def moc_maintainer_node(state: VaultState, tools: VaultTools, cfg: AppConfig, **_) -> dict:
    folder = str(Path(state["note_path"]).parent)
    if folder == ".":
        folder = ""
    moc_rel = _FOLDER_MOC.get(folder)
    if not moc_rel:
        return {"changes": []}

    title = Path(state["note_path"]).stem
    link = f"[[{title}]]"

    try:
        moc_content = tools.read_note(moc_rel)
    except FileNotFoundError:
        return {"changes": [f"MOC not found: {moc_rel}"]}

    if link in moc_content:
        if folder == "Jira" and state["frontmatter"].get("status"):
            status = state["frontmatter"]["status"]
            updated = _update_jira_status(moc_content, title, status)
            if updated != moc_content:
                if cfg.get_autonomy("moc_maintainer") == "full":
                    tools.write_note(moc_rel, updated)
                    return {"changes": [f"MOC: updated {title} status → {status}"]}
                else:
                    LibrarianInbox(cfg, tools).propose(
                        f"Update `{title}` status to {status} in {moc_rel}"
                    )
                    return {"changes": [f"MOC: proposed status update for {title}"]}
        return {"changes": []}

    section = _SECTION_MAP.get(folder, "## Notes")
    entry = f"| {link} | |\n" if folder in ("Projects", "Jira") else f"- {link}\n"
    updated = _insert_into_section(moc_content, section, entry)

    if cfg.get_autonomy("moc_maintainer") == "full":
        tools.write_note(moc_rel, updated)
        return {"changes": [f"MOC: added {title} to {section}"]}
    else:
        LibrarianInbox(cfg, tools).propose(f"Add `{title}` to {moc_rel} under {section}")
        return {"changes": [f"MOC: proposed adding {title}"]}


def _insert_into_section(content: str, section: str, entry: str) -> str:
    if section not in content:
        return content.rstrip() + f"\n\n{section}\n\n{entry}"
    parts = content.split(section, 1)
    lines = parts[1].split("\n")
    lines.insert(2, entry.rstrip())
    return parts[0] + section + "\n".join(lines)


def _update_jira_status(content: str, title: str, status: str) -> str:
    icon = _STATUS_ICONS.get(status, "⬜")
    return re.sub(
        rf"(\| \[\[{re.escape(title)}\]\][^|]*\|[^|]*\|)[^\n]*",
        rf"\1 {icon} {status} |",
        content,
    )
