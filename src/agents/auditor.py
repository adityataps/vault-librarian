from __future__ import annotations

import asyncio
import logging
import re
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

from src.agents.state import VaultState
from src.autonomy.inbox import LibrarianInbox
from src.config import AppConfig
from src.vault.tools import VaultTools

log = logging.getLogger(__name__)

_WIKI_LINK_RE = re.compile(r"\[\[([^\]|#\n]+?)(?:[|#][^\]]+)?\]\]")
_VAULT_FOLDERS = [
    "", "Projects", "Jira", "Tech Notes", "Meetings",
    "Career", "Reference", "Personal", "Templates",
]


def _find_file(link: str, tools: VaultTools) -> bool:
    """Return True if a note matching [[link]] exists anywhere in the vault."""
    for folder in _VAULT_FOLDERS:
        candidate = f"{folder}/{link}.md" if folder else f"{link}.md"
        try:
            if tools.abs(candidate).exists():
                return True
        except ValueError:
            continue
    return False


def auditor_quick_node(state: VaultState, tools: VaultTools, cfg: AppConfig, **_) -> dict:
    """Lightweight pipeline pass: detect broken wiki-links in the settled note."""
    links = _WIKI_LINK_RE.findall(state["note_content"])
    broken = [lnk for lnk in dict.fromkeys(links) if not _find_file(lnk, tools)]

    if not broken:
        return {"changes": []}

    changes = []
    autonomy = cfg.get_autonomy("auditor")
    inbox = LibrarianInbox(cfg, tools) if autonomy != "full" else None
    for link in broken:
        stub_rel = f"Reference/{link}.md"
        if autonomy == "full":
            if not tools.abs(stub_rel).exists():
                tools.create_note(stub_rel, f"# {link}\n\n_stub — created by librarian_\n")
                changes.append(f"Auditor: created stub for [[{link}]]")
        else:
            inbox.propose(f"Create stub for [[{link}]] in `Reference/`")
            changes.append(f"Auditor: proposed stub for [[{link}]]")

    return {"changes": changes}


async def run_auditor_full(
    cfg: AppConfig,
    db,
    tools: VaultTools,
    llm,
) -> None:
    """Full-vault scheduled sweep — writes Vault Audit YYYY-MM-DD.md."""
    import os

    from src.vault.scanner import VaultScanner

    today = date.today().isoformat()
    stale_cutoff = datetime.now(timezone.utc) - timedelta(days=cfg.stale_days)

    def _scan_blocking():
        _broken: dict[str, list[str]] = {}
        _orphans: list[str] = []
        _stale: list[str] = []
        _unprocessed: list[str] = []
        _conflict: list[str] = []

        for meta in VaultScanner(cfg).iter_notes():
            links = _WIKI_LINK_RE.findall(meta.raw_content)
            for lnk in links:
                if not _find_file(lnk, tools):
                    _broken.setdefault(lnk, []).append(meta.path)
            if not links and meta.folder not in ("Templates", ".librarian", "Reference"):
                _orphans.append(meta.path)
            mtime = datetime.fromtimestamp(Path(meta.abs_path).stat().st_mtime, tz=timezone.utc)
            if mtime < stale_cutoff:
                _stale.append(meta.path)
            if "<agent-" in meta.raw_content:
                _unprocessed.append(meta.path)

        for root, dirs, _ in os.walk(cfg.vault_path):
            for d in dirs:
                if re.search(r"\s+\d+$", d):
                    rel = str(Path(root).relative_to(cfg.vault_path) / d)
                    _conflict.append(rel)

        return _broken, _orphans, _stale, _unprocessed, _conflict

    broken_links, orphans, stale, unprocessed, conflict_folders = await asyncio.to_thread(_scan_blocking)

    report_lines = [
        f"# Vault Audit — {today}\n",
        f"_vault-librarian · stale threshold: {cfg.stale_days} days_\n",
    ]
    action_items: list[str] = []

    if broken_links:
        report_lines.append("\n## 🔗 Broken Wiki-links\n")
        for lnk, sources in broken_links.items():
            report_lines.append(
                f"- `[[{lnk}]]` in: {', '.join(f'`{s}`' for s in sources[:3])}"
            )
            action_items.append(f"Create stub for [[{lnk}]] in `Reference/`")

    if orphans:
        report_lines.append("\n## 👻 Orphaned Notes\n")
        for p in orphans[:20]:
            report_lines.append(f"- `{p}`")

    if stale:
        report_lines.append(f"\n## 🕰 Stale Notes (>{cfg.stale_days} days)\n")
        for p in stale[:20]:
            report_lines.append(f"- `{p}`")

    if conflict_folders:
        report_lines.append("\n## 📁 Duplicate Folders\n")
        for f in conflict_folders:
            report_lines.append(f"- `{f}`")
            action_items.append(f"Review duplicate folder `{f}`")

    if unprocessed:
        report_lines.append("\n## ⚡ Unprocessed Directives\n")
        for p in unprocessed[:10]:
            report_lines.append(f"- `{p}`")

    if action_items:
        report_lines.append("\n## 🔧 Actionable Items\n")
        report_lines.append("<!-- Check items to execute, then save -->\n")
        for item in action_items:
            report_lines.append(f"- [ ] {item}")

    report = "\n".join(report_lines) + "\n"
    report_rel = f".librarian/Vault Audit — {today}.md"
    tools.create_note(report_rel, report)
    log.info("Auditor full sweep complete → %s", report_rel)
