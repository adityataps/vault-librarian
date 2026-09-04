from __future__ import annotations

import shutil

import pytest

from vault_librarian.workflows import mermaid as mermaid_wf

pytestmark = pytest.mark.skipif(
    shutil.which("mmdc") is None and shutil.which("npx") is None,
    reason="mermaid validation requires mmdc or npx on PATH",
)


async def test_valid_diagram_is_untouched():
    text = "```mermaid\nflowchart TD\n    A --> B\n```\n"
    result = await mermaid_wf.run(text)
    assert not result.changed
    assert not result.quarantined_blocks
    assert result.text == text


async def test_missing_header_is_deterministically_fixed():
    text = "```mermaid\nA --> B\n```\n"
    result = await mermaid_wf.run(text)
    assert result.changed
    assert not result.quarantined_blocks
    assert "flowchart TD" in result.text


async def test_unbalanced_bracket_is_deterministically_fixed():
    text = "```mermaid\nflowchart TD\n    A[Start] --> B[End\n```\n"
    result = await mermaid_wf.run(text)
    assert result.changed
    assert not result.quarantined_blocks
    assert "B[End]" in result.text


async def test_unfixable_diagram_is_quarantined_and_left_untouched():
    # More closing than opening brackets isn't safely auto-fixable, and with no llm_call
    # there's no escalation path — should be reported as quarantined, original preserved.
    text = "```mermaid\nflowchart TD\n    A] --> B\n```\n"
    result = await mermaid_wf.run(text)
    assert not result.changed
    assert result.quarantined_blocks
    assert "A] --> B" in result.text
