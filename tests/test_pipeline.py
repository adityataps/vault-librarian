from src.agents.state import Directive, make_state
from src.pipeline.builder import PIPELINE_ORDER, build_pipeline


def test_make_state_defaults():
    state = make_state("Projects/Test.md", "# Test\n\nContent", {}, "project")
    assert state["note_path"] == "Projects/Test.md"
    assert state["note_type"] == "project"
    assert state["changes"] == []
    assert state["directives"] == []
    assert state["dispatch_hash"] == ""


def test_make_state_no_type():
    state = make_state("bare.md", "content", {})
    assert state["note_type"] is None


def test_build_pipeline_excludes_unenrolled():
    pipeline, active = build_pipeline(note_type="meeting", enrolled=["librarian", "formatter"])
    assert pipeline is not None
    assert "meeting_enricher" not in active


def test_build_pipeline_empty_enrolled():
    pipeline, active = build_pipeline(note_type="project", enrolled=[])
    assert pipeline is not None
    assert active == []


def test_build_pipeline_meeting_enricher_excluded_for_non_meeting():
    pipeline, active = build_pipeline(note_type="project", enrolled=PIPELINE_ORDER)
    assert pipeline is not None
    assert "meeting_enricher" not in active


def test_build_pipeline_meeting_enricher_included_for_meeting():
    pipeline, active = build_pipeline(note_type="meeting", enrolled=PIPELINE_ORDER)
    assert "meeting_enricher" in active


def test_directive_dataclass():
    d = Directive(tag="scaffold", prompt="fill this", start=10, end=50)
    assert d.tag == "scaffold"
    assert d.prompt == "fill this"
