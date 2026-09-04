from __future__ import annotations

from vault_librarian.workflows import spellcheck as spellcheck_wf


async def test_skips_gracefully_with_no_llm_call():
    text = "Some note text.\n"
    new_text, changed = await spellcheck_wf.run(text, None)
    assert not changed
    assert new_text == text


async def test_applies_llm_correction():
    async def fake_llm(prompt: str) -> str:
        return "Corrected text.\n"

    new_text, changed = await spellcheck_wf.run("Correctd text.\n", fake_llm)
    assert changed
    assert new_text == "Corrected text.\n"


async def test_noop_when_llm_returns_identical_text():
    text = "Already correct.\n"

    async def fake_llm(prompt: str) -> str:
        return text

    new_text, changed = await spellcheck_wf.run(text, fake_llm)
    assert not changed
    assert new_text == text


async def test_llm_failure_leaves_file_unchanged():
    async def failing_llm(prompt: str) -> str:
        raise RuntimeError("provider unavailable")

    text = "Some note text.\n"
    new_text, changed = await spellcheck_wf.run(text, failing_llm)
    assert not changed
    assert new_text == text
