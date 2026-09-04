"""Deterministic backlink suggestion (architecture.md §4.3).

Wraps the first mention of another note's exact title with a [[wikilink]] where it appears
as plain prose. Deliberately mechanical/exact-match only for MVP — anything fuzzier
(synonyms, partial matches) is out of scope and would need an LLM (design principle 1).
"""

from __future__ import annotations

import re
from pathlib import Path

from vault_librarian.workflows._text import inline_code_spans, protected_line_mask

_WIKILINK_RE = re.compile(r"\[\[([^\]|]+)")


def _candidate_titles(vault_path: Path, ignore_paths: list[str], self_path: Path) -> list[str]:
    titles = []
    for md in vault_path.rglob("*.md"):
        if md.resolve() == self_path.resolve():
            continue
        try:
            rel = md.relative_to(vault_path)
        except ValueError:
            continue
        rel_str = str(rel)
        if any(rel_str.startswith(ip.rstrip("/")) for ip in ignore_paths):
            continue
        titles.append(md.stem)
    # Longest-first so multi-word titles win over single-word substrings of themselves.
    return sorted(set(titles), key=len, reverse=True)


def _link_first_mention(line: str, title: str, linked_already: set[str]) -> str:
    if title in linked_already:
        return line
    code_spans = inline_code_spans(line)

    def in_code(pos: int) -> bool:
        return any(start <= pos < end for start, end in code_spans)

    pattern = re.compile(r"(?<!\[\[)\b" + re.escape(title) + r"\b(?!\]\])")
    match = pattern.search(line)
    if match and not in_code(match.start()):
        linked_already.add(title)
        return line[: match.start()] + f"[[{title}]]" + line[match.end() :]
    return line


def run(text: str, vault_path: Path, self_path: Path, ignore_paths: list[str]) -> tuple[str, bool]:
    titles = _candidate_titles(vault_path, ignore_paths, self_path)
    if not titles:
        return text, False

    already_linked = {m.group(1).strip() for m in _WIKILINK_RE.finditer(text)}
    lines = text.split("\n")
    mask = protected_line_mask(text)
    changed = False

    for i, (line, protected) in enumerate(zip(lines, mask)):
        if protected or not line.strip() or line.lstrip().startswith("#"):
            continue
        new_line = line
        for title in titles:
            new_line = _link_first_mention(new_line, title, already_linked)
        if new_line != line:
            lines[i] = new_line
            changed = True

    if not changed:
        return text, False
    return "\n".join(lines), True
