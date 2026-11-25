"""Isolated FastAPI router for conversation history.

Mount this router in any FastAPI application after setting
``app.state.conversation_service``.  It does not import or modify the ERP
backend.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from .errors import (
    AssistantPayloadError,
    HistoryError,
    HistoryValidationError,
    SessionNotFoundError,
)
from .models import (
    ChatRequest,
    ChatResponse,
    ClearResponse,
    DeleteResponse,
    SessionDetail,
    SessionSummary,
)
from .service import ConversationService

router = APIRouter(prefix="/chat", tags=["conversation-history"])


def get_conversation_service(request: Request) -> ConversationService:
    service = getattr(request.app.state, "conversation_service", None)
    if not isinstance(service, ConversationService):
        raise HTTPException(
            status_code=503,
            detail="Conversation history service is not configured.",
        )
    return service


def _raise_http(exc: HistoryError) -> None:
    if isinstance(exc, SessionNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, AssistantPayloadError):
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if isinstance(exc, HistoryValidationError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    raise HTTPException(
        status_code=500,
        detail="Internal conversation history error.",
    ) from exc


@router.post("", response_model=ChatResponse)
def chat(
    payload: ChatRequest,
    service: ConversationService = Depends(get_conversation_service),
) -> ChatResponse:
    """Create a new conversation or continue an existing one."""
    try:
        result = service.chat(
            message=payload.message,
            session_id=payload.session_id,
            user_id=payload.user_id,
        )
    except HistoryError as exc:
        _raise_http(exc)
    return ChatResponse(**result)


@router.get("/sessions", response_model=list[SessionSummary])
def list_sessions(
    user_id: str | None = Query(default=None, max_length=128),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    service: ConversationService = Depends(get_conversation_service),
) -> list[SessionSummary]:
    """List conversations, newest first."""
    try:
        sessions = service.list_sessions(
            user_id=user_id, limit=limit, offset=offset
        )
    except HistoryError as exc:
        _raise_http(exc)
    return [SessionSummary(**session) for session in sessions]


@router.get("/search", response_model=list[SessionSummary])
def search_sessions(
    q: str = Query(min_length=1, max_length=200),
    user_id: str | None = Query(default=None, max_length=128),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    service: ConversationService = Depends(get_conversation_service),
) -> list[SessionSummary]:
    """Search conversation titles and stored message payloads."""
    try:
        sessions = service.search(
            query=q, user_id=user_id, limit=limit, offset=offset
        )
    except HistoryError as exc:
        _raise_http(exc)
    return [SessionSummary(**session) for session in sessions]


@router.get("/sessions/{session_id}", response_model=SessionDetail)
def get_session(
    session_id: UUID,
    user_id: str | None = Query(default=None, max_length=128),
    service: ConversationService = Depends(get_conversation_service),
) -> SessionDetail:
    """Retrieve a conversation and all of its messages."""
    try:
        session = service.get_session_detail(
            session_id=session_id, user_id=user_id
        )
    except HistoryError as exc:
        _raise_http(exc)
    return SessionDetail(**session)


@router.delete("/sessions/{session_id}", response_model=DeleteResponse)
def delete_session(
    session_id: UUID,
    user_id: str | None = Query(default=None, max_length=128),
    service: ConversationService = Depends(get_conversation_service),
) -> DeleteResponse:
    """Delete a conversation and cascade to its messages."""
    try:
        service.delete_session(session_id=session_id, user_id=user_id)
    except HistoryError as exc:
        _raise_http(exc)
    return DeleteResponse(deleted=True, session_id=str(session_id))


@router.delete("/sessions", response_model=ClearResponse)
def clear_user_sessions(
    user_id: str = Query(min_length=1, max_length=128),
    service: ConversationService = Depends(get_conversation_service),
) -> ClearResponse:
    """Clear every conversation owned by one user."""
    try:
        deleted_count = service.clear_user_history(user_id)
    except HistoryError as exc:
        _raise_http(exc)
    return ClearResponse(deleted_count=deleted_count, user_id=user_id)
