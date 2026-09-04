"""Mermaid diagram validation + fix cascade (architecture.md §4.3): parse -> deterministic
auto-fix -> LLM fix (last resort) -> re-validate; give up after MAX_ATTEMPTS per block and
let the dispatcher route the file to Failed Processing.md rather than looping forever.
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Optional

logger = logging.getLogger("vault_librarian.workflows.mermaid")

MAX_ATTEMPTS = 3
_MERMAID_BLOCK_RE = re.compile(r"```mermaid\n(.*?)```", re.DOTALL)

_KNOWN_HEADERS = (
    "flowchart",
    "graph",
    "sequenceDiagram",
    "classDiagram",
    "stateDiagram",
    "erDiagram",
    "gantt",
    "pie",
    "journey",
    "mindmap",
    "timeline",
)


@dataclass
class MermaidResult:
    text: str
    changed: bool
    quarantined_blocks: list[str] = field(default_factory=list)


def _mmdc_command() -> Optional[list[str]]:
    mmdc = shutil.which("mmdc")
    if mmdc:
        return [mmdc]
    npx = shutil.which("npx")
    if npx:
        return [npx, "-y", "@mermaid-js/mermaid-cli"]
    return None


async def _validate(source: str) -> Optional[str]:
    """Return None if the diagram source is valid, else the parser's error text."""
    cmd = _mmdc_command()
    if cmd is None:
        logger.warning("mermaid validation skipped: neither `mmdc` nor `npx` found on PATH")
        return None
    with tempfile.TemporaryDirectory() as tmp:
        in_path = Path(tmp) / "diagram.mmd"
        out_path = Path(tmp) / "diagram.svg"
        in_path.write_text(source, encoding="utf-8")
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            "-i",
            str(in_path),
            "-o",
            str(out_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode == 0:
            return None
        return stderr.decode("utf-8", errors="replace").strip()


def _deterministic_fix(source: str) -> Optional[str]:
    """Mechanical fixes for common mistakes: missing diagram-type header, unbalanced
    brackets/quotes. Returns a candidate fix, or None if no known pattern applies."""
    fixed = source
    applied = False

    first_line = next((line for line in fixed.splitlines() if line.strip()), "")
    if not first_line.strip().startswith(_KNOWN_HEADERS):
        fixed = "flowchart TD\n" + fixed
        applied = True

    for opener, closer in (("[", "]"), ("(", ")"), ("{", "}")):
        diff = fixed.count(opener) - fixed.count(closer)
        if diff > 0:
            fixed = fixed.rstrip("\n") + closer * diff + "\n"
            applied = True
        elif diff < 0:
            return None  # more closers than openers isn't safely auto-fixable

    if fixed.count('"') % 2 == 1:
        fixed = fixed.rstrip("\n") + '"\n'
        applied = True

    return fixed if applied else None


async def _llm_fix(source: str, error: str, llm_call: Callable[[str], Awaitable[str]]) -> Optional[str]:
    prompt = (
        "The following Mermaid diagram fails to parse. Fix ONLY the syntax error described, "
        "preserving all diagram content/labels/structure. Return ONLY the corrected mermaid "
        f"source, no commentary, no code fences.\n\nParser error:\n{error}\n\nSource:\n{source}"
    )
    try:
        result = await llm_call(prompt)
    except Exception:
        logger.exception("mermaid LLM-fix call failed")
        return None
    if not result:
        return None
    cleaned = result.strip().strip("`")
    if cleaned.startswith("mermaid\n"):
        cleaned = cleaned[len("mermaid\n") :]
    return cleaned if cleaned.endswith("\n") else cleaned + "\n"


async def _fix_block(source: str, llm_call: Optional[Callable[[str], Awaitable[str]]]) -> tuple[str, bool, bool]:
    """Returns (final_source, changed, quarantined)."""
    current = source
    for attempt in range(MAX_ATTEMPTS):
        error = await _validate(current)
        if error is None:
            return current, current != source, False
        if attempt == 0:
            fixed = _deterministic_fix(current)
            if fixed is not None:
                current = fixed
                continue
        if llm_call is None:
            break
        fixed = await _llm_fix(current, error, llm_call)
        if fixed is None:
            break
        current = fixed
    return source, False, True  # still broken after MAX_ATTEMPTS — leave original untouched


async def run(text: str, llm_call: Optional[Callable[[str], Awaitable[str]]] = None) -> MermaidResult:
    changed = False
    quarantined: list[str] = []
    result_parts: list[str] = []
    last_end = 0

    for match in _MERMAID_BLOCK_RE.finditer(text):
        result_parts.append(text[last_end : match.start()])
        block_source = match.group(1)
        final_source, block_changed, was_quarantined = await _fix_block(block_source, llm_call)
        if block_changed:
            changed = True
        if was_quarantined:
            quarantined.append(block_source)
        result_parts.append(f"```mermaid\n{final_source}```")
        last_end = match.end()

    result_parts.append(text[last_end:])
    return MermaidResult(text="".join(result_parts), changed=changed, quarantined_blocks=quarantined)
