from __future__ import annotations

import operator
from dataclasses import dataclass
from typing import Annotated, TypedDict


@dataclass
class Directive:
    tag: str  # scaffold | fill | context
    prompt: str
    start: int  # char offset in content
    end: int


class VaultState(TypedDict):
    note_path: str
    note_content: str
    frontmatter: dict
    note_type: str | None
    directives: list[Directive]
    action_items: list[str]
    related_notes: list[str]
    dispatch_hash: str
    changes: Annotated[list[str], operator.add]


def make_state(
    note_path: str,
    note_content: str,
    frontmatter: dict,
    note_type: str | None = None,
    dispatch_hash: str = "",
) -> VaultState:
    return VaultState(
        note_path=note_path,
        note_content=note_content,
        frontmatter=frontmatter,
        note_type=note_type,
        directives=[],
        action_items=[],
        related_notes=[],
        dispatch_hash=dispatch_hash,
        changes=[],
    )
