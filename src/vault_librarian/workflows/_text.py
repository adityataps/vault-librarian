"""Shared text-segmentation helpers so workflows never mutate inside fenced/inline code.

Workflows must already treat existing markdown fenced/inline code spans as implicitly
protected — never spellchecked, reformatted, or re-linked inside them (requirements.md
NFR-16). This is a small internal utility, not the `<agent-ignore>` directive itself
(that's a Phase 2 feature, architecture.md §4.5).
"""

from __future__ import annotations

import re

_INLINE_CODE_RE = re.compile(r"`[^`\n]*`")


def protected_line_mask(text: str) -> list[bool]:
    """Return one bool per line: True if that line is inside a fenced (``` or ~~~) code block."""
    lines = text.split("\n")
    mask = [False] * len(lines)
    in_fence = False
    fence_marker = ""
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not in_fence and (stripped.startswith("```") or stripped.startswith("~~~")):
            in_fence = True
            fence_marker = stripped[:3]
            mask[i] = True
            continue
        if in_fence:
            mask[i] = True
            if stripped.startswith(fence_marker):
                in_fence = False
            continue
    return mask


def inline_code_spans(line: str) -> list[tuple[int, int]]:
    """Character ranges of `inline code` spans within a single line."""
    return [(m.start(), m.end()) for m in _INLINE_CODE_RE.finditer(line)]
