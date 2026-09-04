from __future__ import annotations

from vault_librarian.workflows import format as format_wf


def test_strips_trailing_whitespace():
    text = "hello \nworld\n"
    new_text, changed = format_wf.run(text)
    assert changed
    assert new_text == "hello\nworld\n"


def test_canonicalizes_excess_trailing_spaces_to_hard_break():
    text = "hello     \nworld\n"
    new_text, changed = format_wf.run(text)
    assert changed
    assert new_text == "hello  \nworld\n"


def test_preserves_markdown_hard_break():
    text = "line one  \nline two\n"
    new_text, changed = format_wf.run(text)
    assert not changed
    assert new_text == text


def test_collapses_multiple_blank_lines():
    text = "a\n\n\n\n\nb\n"
    new_text, changed = format_wf.run(text)
    assert changed
    assert new_text == "a\n\nb\n"


def test_ensures_trailing_newline():
    text = "no newline at eof"
    new_text, changed = format_wf.run(text)
    assert changed
    assert new_text.endswith("\n")


def test_no_change_is_idempotent():
    text = "clean file\n\nwith one blank line\n"
    new_text, changed = format_wf.run(text)
    assert not changed
    assert new_text == text


def test_does_not_touch_fenced_code_block_whitespace():
    text = "```python\nx = 1   \n```\n"
    new_text, changed = format_wf.run(text)
    assert not changed
    assert new_text == text
