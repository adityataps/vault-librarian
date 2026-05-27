"""CrewAI tool for semantic note search."""

from __future__ import annotations

import asyncio
import threading
from typing import Any

from crewai.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field


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


class VectorSearchInput(BaseModel):
    query: str = Field(description="Natural language search query")
    limit: int = Field(default=10, ge=1, description="Max results to return")
    threshold: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Minimum similarity score 0-1",
    )
    folder: str | None = Field(default=None, description="Filter by folder name")


class VectorSearchTool(BaseTool):
    name: str = "vector_search"
    description: str = (
        "Search the Obsidian vault using semantic similarity. "
        "Returns notes whose content is conceptually similar to the query. "
        "Use this to find related notes, detect duplicates, or discover connections."
    )
    args_schema: type[BaseModel] = VectorSearchInput
    storage: Any = None
    embedding_service: Any = None

    model_config = ConfigDict(arbitrary_types_allowed=True)

    async def _search(
        self,
        query: str,
        limit: int = 10,
        threshold: float = 0.7,
        folder: str | None = None,
    ) -> str:
        if self.storage is None:
            return "Vector search unavailable: storage backend not configured"
        if self.embedding_service is None:
            return "Vector search unavailable: embedding service not configured"

        model = getattr(self.embedding_service, "_model", "text-embedding-3-small")

        try:
            vector = await self.embedding_service.embed(query, model=model)
        except Exception as exc:
            return f"Vector search unavailable: {exc}"

        try:
            search_limit = limit if folder is None else max(limit * 5, limit)
            results = await self.storage.search_similar(
                vector,
                limit=search_limit,
                threshold=threshold,
                model=model,
            )
        except Exception as exc:
            return f"Vector search unavailable: {exc}"

        if folder is not None:
            results = [
                (note, score) for note, score in results if note.folder.casefold() == folder.casefold()
            ]

        results = results[:limit]
        if not results:
            suffix = f" in folder '{folder}'" if folder else ""
            return f"No similar notes found for query '{query}'{suffix}."

        lines = [f"Found {len(results)} similar notes:"]
        for index, (note, score) in enumerate(results, start=1):
            lines.append(
                f"{index}. [{note.title}] (path: {note.path}, score: {score:.2f})"
            )
        return "\n".join(lines)

    def _run(
        self,
        query: str,
        limit: int = 10,
        threshold: float = 0.7,
        folder: str | None = None,
    ) -> str:
        return _run_coroutine_sync(
            self._search(query=query, limit=limit, threshold=threshold, folder=folder)
        )

    async def _arun(
        self,
        query: str,
        limit: int = 10,
        threshold: float = 0.7,
        folder: str | None = None,
    ) -> str:
        return await self._search(
            query=query,
            limit=limit,
            threshold=threshold,
            folder=folder,
        )
