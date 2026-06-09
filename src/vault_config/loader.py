from __future__ import annotations

import logging
import re
from pathlib import Path

import frontmatter

from src.config import AppConfig

log = logging.getLogger(__name__)

_CONFIG_REL = "Librarian/config.md"
_SECTION_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


class VaultConfigLoader:
    def __init__(self, cfg: AppConfig) -> None:
        self._cfg = cfg
        self._path = Path(cfg.vault_path) / _CONFIG_REL

    def apply(self) -> None:
        if not self._path.exists():
            return
        try:
            text = self._path.read_text(encoding="utf-8")
        except Exception as exc:
            log.warning("Could not read vault config: %s", exc)
            return

        post = frontmatter.loads(text)
        self._apply_frontmatter(dict(post.metadata))
        self._apply_instructions(post.content)

    def _apply_frontmatter(self, fm: dict) -> None:
        settable = {
            "autonomy_default",
            "stale_days",
            "debounce_standard",
            "debounce_directive",
            "auditor_schedule",
            "daily_brief_schedule",
            "weekly_review_schedule",
        }
        for key, value in fm.items():
            if key in settable:
                setattr(self._cfg, key, value)

        if "agents" in fm and isinstance(fm["agents"], dict):
            agents_cfg = fm["agents"]
            if "autonomy" in agents_cfg:
                self._cfg.autonomy_default = agents_cfg["autonomy"]
            if "overrides" in agents_cfg:
                self._cfg.autonomy_overrides.update(agents_cfg["overrides"])
            if "enabled" in agents_cfg:
                self._cfg.enrolled_agents = agents_cfg["enabled"]

    def _apply_instructions(self, body: str) -> None:
        sections = _SECTION_RE.split(body)
        instructions: dict[str, str] = {}
        # sections: [pre-heading, heading1, body1, heading2, body2, ...]
        i = 1
        while i < len(sections) - 1:
            heading = sections[i].strip().lower().replace(" ", "_")
            content = sections[i + 1].strip()
            if content:
                instructions[heading] = content
            i += 2
        self._cfg.update_agent_instructions(instructions)
