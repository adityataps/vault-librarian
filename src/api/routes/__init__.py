from fastapi import APIRouter

from .agent_runs import router as runs_router
from .chat import router as chat_router
from .notes import router as notes_router

api_router = APIRouter()
api_router.include_router(notes_router, prefix="/notes", tags=["notes"])
api_router.include_router(runs_router, prefix="/runs", tags=["agent-runs"])
api_router.include_router(chat_router, prefix="/chat", tags=["chat"])
