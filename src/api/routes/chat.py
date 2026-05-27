"""Chat endpoint — conversational interface to the vault."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.crews.conversational import ChatMessage, ChatResponse

router = APIRouter()


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = []
    stream: bool = False


@router.post("", response_model=ChatResponse)
async def chat(req: ChatRequest, request: Request) -> ChatResponse | StreamingResponse:
    """Send a message to the vault assistant."""
    crew = request.app.state.conversational_crew
    if not crew:
        return ChatResponse(content="Conversational crew not available — check LLM configuration.")

    if req.stream:
        async def token_stream():
            async for token in crew.stream_chat(req.message, req.history):
                yield token

        return StreamingResponse(token_stream(), media_type="text/plain")

    return crew.chat(req.message, req.history)
