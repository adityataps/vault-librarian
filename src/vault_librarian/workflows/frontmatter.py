"""Frontmatter automation-control normalization (architecture.md §4.4).

Ensures the `vault-librarian` frontmatter block exists with opt-out-by-default semantics
(automation enabled unless explicitly disabled/skipped) and that `skip` only lists known
workflow names. Fully deterministic — no LLM.

Deliberately does NOT use `frontmatter.dumps()` to re-render the whole file: that round-trips
the body through the library's content parser, which silently eats trailing whitespace/newlines
at the end of the document (defeating format.py's hard-break preservation). Instead we only
reconstruct the frontmatter block itself and splice it back onto the original body text
byte-for-byte.
"""

from __future__ import annotations

import re

import yaml

KNOWN_WORKFLOWS = {"format", "backlink", "frontmatter", "spellcheck", "mermaid"}

_FRONTMATTER_RE = re.compile(r"\A---[ \t]*\n(.*?\n)---[ \t]*\n?", re.DOTALL)


def run(text: str) -> tuple[str, bool]:
    """Returns (new_text, changed)."""
    match = _FRONTMATTER_RE.match(text)
    if match:
        try:
            metadata = yaml.safe_load(match.group(1))
        except yaml.YAMLError:
            # Unparseable frontmatter is left alone; don't risk corrupting the file further.
            return text, False
        if metadata is None:
            metadata = {}
        if not isinstance(metadata, dict):
            return text, False
        body = text[match.end() :]
    else:
        metadata = {}
        body = text
        # New block being prepended to a file that had no frontmatter at all: keep the
        # conventional blank-line separator before the original content.
        if body and not body.startswith("\n"):
            body = "\n" + body

    vl_raw = metadata.get("vault-librarian")
    changed = match is None or not isinstance(vl_raw, dict) or "enabled" not in vl_raw

    if isinstance(vl_raw, dict):
        vl: dict = vl_raw
    else:
        vl = {"enabled": True}
        metadata["vault-librarian"] = vl

    if "enabled" not in vl:
        vl["enabled"] = True

    skip = vl.get("skip")
    if skip is not None:
        cleaned = [w for w in skip if w in KNOWN_WORKFLOWS]
        if cleaned != skip:
            vl["skip"] = cleaned
            changed = True

    if not changed:
        return text, False

    fm_yaml = yaml.safe_dump(metadata, sort_keys=False, default_flow_style=False).rstrip("\n")
    new_text = f"---\n{fm_yaml}\n---\n{body}"
    if not new_text.endswith("\n"):
        new_text += "\n"
    return new_text, True
