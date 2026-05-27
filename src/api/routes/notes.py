"""Note API routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, status as http_status
from pydantic import BaseModel

from src.storage import Note, NoteFilter, Wikilink
from src.storage.models import NoteStatus, NoteType

router = APIRouter()


class SimilarNoteResult(BaseModel):
    """A semantic similarity match for a note."""

    note: Note
    score: float


def _parse_tags(tags: str | None) -> list[str] | None:
    if not tags:
        return None
    parsed = [tag.strip() for tag in tags.split(",") if tag.strip()]
    return parsed or None


def _embedding_text(note: Note) -> str:
    parts = [
        note.title,
        note.path,
        note.folder,
        " ".join(note.tags),
        f"type:{note.type}" if note.type else "",
        f"status:{note.status}" if note.status else "",
    ]
    return "\n".join(part for part in parts if part)


@router.get("", response_model=list[Note])
async def list_notes(
    request: Request,
    folder: str | None = None,
    note_type: NoteType | None = Query(default=None, alias="type"),
    note_status: NoteStatus | None = Query(default=None, alias="status"),
    tags: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[Note]:
    filters = NoteFilter(
        folder=folder,
        type=note_type,
        status=note_status,
        tags=_parse_tags(tags),
        limit=limit,
        offset=offset,
    )
    return await request.app.state.storage.query_notes(filters)


@router.get("/by-path", response_model=Note)
async def get_note_by_path(request: Request, path: str = Query(...)) -> Note:
    note = await request.app.state.storage.get_note_by_path(path)
    if note is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Note not found",
        )
    return note


@router.get("/{note_id}", response_model=Note)
async def get_note(note_id: UUID, request: Request) -> Note:
    note = await request.app.state.storage.get_note(note_id)
    if note is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Note not found",
        )
    return note


@router.get("/{note_id}/similar", response_model=list[SimilarNoteResult])
async def get_similar_notes(
    note_id: UUID,
    request: Request,
    limit: int = Query(default=10, ge=1, le=100),
    threshold: float = Query(default=0.7, ge=0.0, le=1.0),
) -> list[SimilarNoteResult]:
    note = await request.app.state.storage.get_note(note_id)
    if note is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Note not found",
        )

    try:
        vector = await request.app.state.embedding_service.embed(_embedding_text(note))
        matches = await request.app.state.storage.search_similar(
            vector=vector,
            limit=limit + 1,
            threshold=threshold,
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    results: list[SimilarNoteResult] = []
    for matched_note, score in matches:
        if matched_note.id == note.id:
            continue
        results.append(SimilarNoteResult(note=matched_note, score=score))
        if len(results) >= limit:
            break

    return results


@router.get("/{note_id}/links", response_model=list[Wikilink])
async def get_note_links(note_id: UUID, request: Request) -> list[Wikilink]:
    note = await request.app.state.storage.get_note(note_id)
    if note is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Note not found",
        )
    return await request.app.state.storage.get_wikilinks(note_id)
