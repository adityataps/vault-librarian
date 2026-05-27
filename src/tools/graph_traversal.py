"""CrewAI tool for traversing note wikilinks."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any

from crewai.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

from src.storage.models import Note, NoteFilter, Wikilink


def _run_coroutine_sync(coro: Any) -> Any:
    try:
        loop = asyncio.get_event_loop()
        if not loop.is_running():
            return loop.run_until_complete(coro)
    except RuntimeError:
        pass

    try:
        new_loop = asyncio.new_event_loop()
        try:
            return new_loop.run_until_complete(coro)
        finally:
            new_loop.close()
    except RuntimeError as exc:
        if "another loop is running" not in str(exc).casefold():
            raise

        result: dict[str, Any] = {}
        error: dict[str, BaseException] = {}

        def _runner() -> None:
            thread_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(thread_loop)
            try:
                result["value"] = thread_loop.run_until_complete(coro)
            except BaseException as runner_exc:
                error["value"] = runner_exc
            finally:
                asyncio.set_event_loop(None)
                thread_loop.close()

        thread = threading.Thread(target=_runner, daemon=True)
        thread.start()
        thread.join()
        if "value" in error:
            raise error["value"]
        return result.get("value")


def _normalize_path(value: str) -> str:
    normalized = Path(value).as_posix().strip()
    return normalized[:-3].casefold() if normalized.endswith(".md") else normalized.casefold()


class GraphTraversalInput(BaseModel):
    note_path: str = Field(
        description="Path to the starting note (relative to vault root)"
    )
    depth: int = Field(default=2, ge=1, le=3, description="How many link hops to traverse (1-3)")
    direction: str = Field(
        default="outgoing",
        description="'outgoing', 'incoming', or 'both'",
    )


class GraphTraversalTool(BaseTool):
    name: str = "graph_traversal"
    description: str = (
        "Traverse the wikilink graph starting from a note. "
        "Returns connected notes up to N hops away. "
        "Use this to understand note relationships, find orphans, or map topic clusters."
    )
    args_schema: type[BaseModel] = GraphTraversalInput
    storage: Any = None

    model_config = ConfigDict(arbitrary_types_allowed=True)

    async def _load_notes(self) -> list[Note]:
        notes: list[Note] = []
        offset = 0
        batch_size = 500

        while True:
            batch = await self.storage.query_notes(
                NoteFilter(limit=batch_size, offset=offset)
            )
            if not batch:
                break
            notes.extend(batch)
            if len(batch) < batch_size:
                break
            offset += batch_size

        return notes

    def _build_note_lookup(self, notes: list[Note]) -> tuple[dict[str, Note], dict[str, Note], dict[str, Note]]:
        by_path = {note.path: note for note in notes}
        by_id = {str(note.id): note for note in notes}
        aliases: dict[str, Note] = {}

        for note in notes:
            for key in {
                note.path,
                _normalize_path(note.path),
                note.title,
                note.title.casefold(),
                Path(note.path).stem,
                Path(note.path).stem.casefold(),
            }:
                aliases.setdefault(str(key), note)

        return by_path, by_id, aliases

    def _resolve_note(
        self,
        link: Wikilink,
        by_path: dict[str, Note],
        by_id: dict[str, Note],
        aliases: dict[str, Note],
    ) -> Note | None:
        if link.target_note_id is not None:
            resolved = by_id.get(str(link.target_note_id))
            if resolved is not None:
                return resolved

        if link.target_path in by_path:
            return by_path[link.target_path]

        return aliases.get(_normalize_path(link.target_path)) or aliases.get(link.target_path) or aliases.get(
            link.target_path.casefold()
        )

    async def _load_graph(
        self,
    ) -> tuple[dict[str, Note], dict[str, list[tuple[str, Note]]], dict[str, list[tuple[str, Note]]], dict[str, bool]]:
        notes = await self._load_notes()
        by_path, by_id, aliases = self._build_note_lookup(notes)
        wikilink_lists = await asyncio.gather(
            *(self.storage.get_wikilinks(note.id) for note in notes)
        )

        outgoing: dict[str, list[tuple[str, Note]]] = {note.path: [] for note in notes}
        incoming: dict[str, list[tuple[str, Note]]] = {note.path: [] for note in notes}
        has_any_outgoing: dict[str, bool] = {note.path: False for note in notes}

        for note, links in zip(notes, wikilink_lists, strict=False):
            if links:
                has_any_outgoing[note.path] = True
            for link in links:
                target = self._resolve_note(link, by_path, by_id, aliases)
                if target is None:
                    continue
                outgoing[note.path].append(("outgoing", target))
                incoming[target.path].append(("incoming", note))

        for edges in outgoing.values():
            edges.sort(key=lambda item: (item[1].title.casefold(), item[1].path.casefold()))
        for edges in incoming.values():
            edges.sort(key=lambda item: (item[1].title.casefold(), item[1].path.casefold()))

        return by_path, outgoing, incoming, has_any_outgoing

    async def _find_orphans(self) -> str:
        by_path, _outgoing, incoming, has_any_outgoing = await self._load_graph()
        orphans = [
            note
            for path, note in sorted(by_path.items(), key=lambda item: item[1].title.casefold())
            if not has_any_outgoing.get(path, False) and not incoming.get(path)
        ]

        if not orphans:
            return "No orphan notes found."

        lines = [f"Found {len(orphans)} orphan notes:"]
        for index, note in enumerate(orphans, start=1):
            lines.append(f"{index}. [{note.title}] (path: {note.path})")
        return "\n".join(lines)

    def _neighbors(
        self,
        path: str,
        direction: str,
        outgoing: dict[str, list[tuple[str, Note]]],
        incoming: dict[str, list[tuple[str, Note]]],
    ) -> list[tuple[str, Note]]:
        if direction == "outgoing":
            return outgoing.get(path, [])
        if direction == "incoming":
            return incoming.get(path, [])

        combined = outgoing.get(path, []) + incoming.get(path, [])
        combined.sort(key=lambda item: (item[1].title.casefold(), item[1].path.casefold(), item[0]))
        return combined

    async def _traverse(self, note_path: str, depth: int = 2, direction: str = "outgoing") -> str:
        if self.storage is None:
            return "Graph traversal unavailable: storage backend not configured"

        normalized_direction = direction.casefold()
        if normalized_direction not in {"outgoing", "incoming", "both"}:
            return "Invalid direction. Use 'outgoing', 'incoming', or 'both'."

        if note_path == "__orphans__":
            return await self._find_orphans()

        start_note = await self.storage.get_note_by_path(note_path)
        if start_note is None:
            return f"Starting note not found: {note_path}"

        by_path, outgoing, incoming, _ = await self._load_graph()
        if start_note.path not in by_path:
            by_path[start_note.path] = start_note
            outgoing.setdefault(start_note.path, [])
            incoming.setdefault(start_note.path, [])

        lines = [f"Graph from [{start_note.title}] (path: {start_note.path}):"]
        visited = {start_note.path}

        def walk(current_path: str, hops_remaining: int, hop: int) -> None:
            if hops_remaining == 0:
                return

            neighbors = self._neighbors(current_path, normalized_direction, outgoing, incoming)
            for relation, neighbor in neighbors:
                if neighbor.path in visited:
                    continue
                visited.add(neighbor.path)
                arrow = "→" if relation == "outgoing" else "←"
                relation_suffix = "" if normalized_direction != "both" else f", {relation}"
                indent = "  " * hop
                lines.append(
                    f"{indent}{arrow} [{neighbor.title}] (path: {neighbor.path}, {hop} hop{'s' if hop != 1 else ''}{relation_suffix})"
                )
                walk(neighbor.path, hops_remaining - 1, hop + 1)

        walk(start_note.path, depth, 1)

        if len(lines) == 1:
            lines.append("  No connected notes found.")
        return "\n".join(lines)

    def _run(self, note_path: str, depth: int = 2, direction: str = "outgoing") -> str:
        return _run_coroutine_sync(
            self._traverse(note_path=note_path, depth=depth, direction=direction)
        )

    async def _arun(self, note_path: str, depth: int = 2, direction: str = "outgoing") -> str:
        return await self._traverse(note_path=note_path, depth=depth, direction=direction)
