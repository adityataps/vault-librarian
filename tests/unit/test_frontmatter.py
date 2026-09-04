from __future__ import annotations

from vault_librarian.workflows import frontmatter as frontmatter_wf


def test_adds_default_block_when_missing():
    text = "# Note\n\nBody text.\n"
    new_text, changed = frontmatter_wf.run(text)
    assert changed
    assert "vault-librarian:" in new_text
    assert "enabled: true" in new_text
    assert new_text == "---\nvault-librarian:\n  enabled: true\n---\n\n# Note\n\nBody text.\n"


def test_leaves_well_formed_block_unchanged():
    text = "---\nvault-librarian:\n  enabled: true\n---\n\n# Note\n"
    new_text, changed = frontmatter_wf.run(text)
    assert not changed
    assert new_text == text


def test_fills_missing_enabled_default():
    text = "---\nvault-librarian:\n  skip: [spellcheck]\n---\n\n# Note\n"
    new_text, changed = frontmatter_wf.run(text)
    assert changed
    assert "enabled: true" in new_text
    assert "spellcheck" in new_text


def test_strips_unknown_workflow_names_from_skip():
    text = "---\nvault-librarian:\n  enabled: true\n  skip: [spellcheck, not-a-real-workflow]\n---\n\n# Note\n"
    new_text, changed = frontmatter_wf.run(text)
    assert changed
    assert "not-a-real-workflow" not in new_text
    assert "spellcheck" in new_text


def test_does_not_corrupt_body_hard_break_when_adding_block():
    # Regression: adding the default frontmatter block must not round-trip the body through
    # a lossy parser that eats trailing whitespace/newlines (see module docstring).
    text = "# Note\n\nLine with a hard break.  \nNext line.\n"
    new_text, changed = frontmatter_wf.run(text)
    assert changed
    assert new_text.endswith("Line with a hard break.  \nNext line.\n")


def test_preserves_final_newline_and_trailing_whitespace_on_last_line():
    text = "---\nvault-librarian:\n  skip: [not-a-real-workflow]\n---\n\n# Note\n\nLast line.  \n"
    new_text, changed = frontmatter_wf.run(text)
    assert changed
    assert new_text.endswith("Last line.  \n")
