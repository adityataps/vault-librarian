from __future__ import annotations

import importlib

from langgraph.graph import END, StateGraph

from src.agents.state import VaultState

# Ordered pipeline — agents run in this sequence when enrolled
PIPELINE_ORDER = [
    "librarian",
    "formatter",
    "inline_directive",
    "meeting_enricher",
    "linker",
    "moc_maintainer",
]

# Maps agent name → "module:function" for lazy import
_AGENT_REGISTRY: dict[str, str] = {
    "librarian": "src.agents.librarian:librarian_node",
    "formatter": "src.agents.formatter:formatter_node",
    "meeting_enricher": "src.agents.meeting_enricher:meeting_enricher_node",
    "linker": "src.agents.linker:linker_node",
    "moc_maintainer": "src.agents.moc_maintainer:moc_maintainer_node",
    "inline_directive": "src.agents.inline_directive:inline_directive_node",
}


def _import_node(dotpath: str):
    module_path, name = dotpath.rsplit(":", 1)
    return getattr(importlib.import_module(module_path), name)


def build_pipeline(
    note_type: str | None,
    enrolled: list[str],
    context: dict | None = None,
):
    """Build and compile a LangGraph pipeline for a file event."""
    ctx = context or {}
    active = [a for a in PIPELINE_ORDER if a in enrolled]

    # meeting_enricher only activates for meeting notes
    if note_type != "meeting" and "meeting_enricher" in active:
        active.remove("meeting_enricher")

    graph = StateGraph(VaultState)

    if not active:
        graph.add_node("noop", lambda s: {})
        graph.set_entry_point("noop")
        graph.add_edge("noop", END)
        return graph.compile()

    for name in active:
        dotpath = _AGENT_REGISTRY[name]

        def make_node(dp=dotpath, c=ctx):
            def node(state: VaultState) -> dict:
                fn = _import_node(dp)
                return fn(state, **c)

            node.__name__ = dp.rsplit(":", 1)[-1]
            return node

        graph.add_node(name, make_node())

    graph.set_entry_point(active[0])
    for i in range(len(active) - 1):
        graph.add_edge(active[i], active[i + 1])
    graph.add_edge(active[-1], END)

    return graph.compile()
