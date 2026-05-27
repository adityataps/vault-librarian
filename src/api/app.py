"""FastAPI application factory for vault-crawler."""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from time import perf_counter
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes import api_router
from src.llm import EmbeddingService, LLMRouter, build_embedding_service, build_llm_router
from src.storage import NoteFilter, StorageBackend, build_storage

if TYPE_CHECKING:
    from src.config import Settings

logger = logging.getLogger(__name__)
VERSION = "0.1.0"


def _get_cors_origins(settings: "Settings") -> list[str]:
    if settings.is_development:
        return ["*"]

    allowed_origins = os.getenv("ALLOWED_ORIGINS", "")
    return [origin.strip() for origin in allowed_origins.split(",") if origin.strip()]


def create_app(settings: "Settings") -> FastAPI:
    """Create and configure the FastAPI application."""
    storage: StorageBackend = build_storage(settings)
    llm_router: LLMRouter = build_llm_router(settings)
    embedding_service: EmbeddingService = build_embedding_service(llm_router)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        from src.crews.conversational import ConversationalCrew
        from src.tools.vector_search import VectorSearchTool
        from src.tools.graph_traversal import GraphTraversalTool
        from src.scheduler.jobs import build_scheduler

        app.state.settings = settings
        app.state.storage = storage
        app.state.llm_router = llm_router
        app.state.embedding_service = embedding_service

        logger.info("Initializing storage backend")
        await storage.initialize()

        # Wire up CrewAI tools and conversational crew
        vector_search = VectorSearchTool(storage=storage, embedding_service=embedding_service)
        graph_traversal = GraphTraversalTool(storage=storage)
        app.state.conversational_crew = ConversationalCrew(
            llm_router=llm_router,
            storage=storage,
            vector_search=vector_search,
            graph_traversal=graph_traversal,
        )

        # Start scheduler
        scheduler = build_scheduler(settings, storage, llm_router)
        scheduler.start()
        app.state.scheduler = scheduler
        logger.info("Scheduler started")

        try:
            yield
        finally:
            scheduler.shutdown(wait=False)
            logger.info("Closing storage backend")
            await storage.close()

    cors_origins = _get_cors_origins(settings)

    app = FastAPI(
        title="vault-crawler",
        version=VERSION,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=bool(cors_origins and cors_origins != ["*"]),
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def log_requests(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        start = perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (perf_counter() - start) * 1000
            logger.exception(
                "Request failed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": 500,
                    "duration_ms": round(duration_ms, 2),
                },
            )
            raise

        duration_ms = (perf_counter() - start) * 1000
        logger.info(
            "%s %s -> %s in %.2fms",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {
            "status": "ok",
            "version": VERSION,
            "environment": settings.environment,
        }

    @app.get("/health/detailed")
    async def detailed_health() -> dict[str, object]:
        components: dict[str, dict[str, object]] = {}
        overall_status = "ok"

        try:
            await app.state.storage.query_notes(NoteFilter(limit=1, offset=0))
            components["database"] = {"status": "ok"}
        except Exception as exc:
            overall_status = "degraded"
            components["database"] = {"status": "error", "detail": str(exc)}

        providers = app.state.llm_router.available_providers
        llm_status = "ok" if providers else "degraded"
        if llm_status != "ok":
            overall_status = "degraded"
        components["llm"] = {
            "status": llm_status,
            "providers": providers,
        }
        components["embedding_service"] = {
            "status": "ok",
            "default_model": getattr(app.state.embedding_service, "_model", None),
        }
        components["scheduler"] = {
            "status": "enabled" if settings.scheduler.enabled else "disabled"
        }

        return {
            "status": overall_status,
            "version": VERSION,
            "environment": settings.environment,
            "components": components,
        }

    app.include_router(api_router, prefix="/api/v1")

    return app
