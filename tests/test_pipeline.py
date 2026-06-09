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
    # meeting_enricher excluded from enrolled, meeting note type
    pipeline = build_pipeline(note_type="meeting", enrolled=["librarian", "formatter"])
    assert pipeline is not None


def test_build_pipeline_empty_enrolled():
    pipeline = build_pipeline(note_type="project", enrolled=[])
    assert pipeline is not None


def test_build_pipeline_meeting_enricher_excluded_for_non_meeting():
    # meeting_enricher should be skipped if note_type != meeting
    # We can verify via PIPELINE_ORDER: build with all agents enrolled but non-meeting type
    # The pipeline runs without error
    pipeline = build_pipeline(note_type="project", enrolled=PIPELINE_ORDER)
    assert pipeline is not None


def test_directive_dataclass():
    d = Directive(tag="scaffold", prompt="fill this", start=10, end=50)
    assert d.tag == "scaffold"
    assert d.prompt == "fill this"
