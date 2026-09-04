"""Deterministic markdown formatting (architecture.md §4.3) — mechanical fixes only, no LLM.

Normalizes trailing whitespace (preserving the two-trailing-space markdown hard-break
convention), collapses runs of 3+ blank lines down to one, and ensures a single trailing
newline at EOF. Never touches lines inside fenced code blocks.
"""

from __future__ import annotations

from vault_librarian.workflows._text import protected_line_mask


def _normalize_trailing_whitespace(line: str) -> str:
    core = line.rstrip(" \t")
    if core == "":
        return ""
    trailing_spaces = len(line) - len(line.rstrip(" "))
    return core + "  " if trailing_spaces >= 2 else core


def run(text: str) -> tuple[str, bool]:
    lines = text.split("\n")
    mask = protected_line_mask(text)
    changed = False
    out_lines: list[str] = []
    blank_run = 0

    for line, protected in zip(lines, mask):
        if protected:
            out_lines.append(line)
            blank_run = 0
            continue
        new_line = _normalize_trailing_whitespace(line)
        if new_line != line:
            changed = True
        if new_line.strip() == "":
            blank_run += 1
            if blank_run > 1:
                changed = True
                continue  # collapse extra blank lines
        else:
            blank_run = 0
        out_lines.append(new_line)

    new_text = "\n".join(out_lines)
    if not new_text.endswith("\n"):
        new_text += "\n"
        changed = True
    while new_text.endswith("\n\n\n"):
        new_text = new_text[:-1]
        changed = True

    if not changed:
        return text, False
    return new_text, True
