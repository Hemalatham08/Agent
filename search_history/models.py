"""Pydantic request/response models for the history API."""

from __future__ import annotations

from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .validation import USER_ID_MAX_LENGTH, validate_message


class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"


class ChatRequest(BaseModel):
    """A user question, optionally continuing an existing conversation.

    ``extra="forbid"`` prevents clients from injecting an assistant payload;
    assistant responses are always produced by the configured answer
    generator.
    """

    model_config = ConfigDict(extra="forbid")

    message: str
    session_id: UUID | None = None
    user_id: str | None = Field(default=None, max_length=USER_ID_MAX_LENGTH)

    @field_validator("message")
    @classmethod
    def _validate_message(cls, value: str) -> str:
        return validate_message(value)

    @field_validator("user_id")
    @classmethod
    def _normalize_user_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class AssistantPayload(BaseModel):
    """Documented shape of a stored assistant response.

    All fields are optional and unknown fields are preserved, because the ERP
    agent's response evolves over time.  The complete object is stored verbatim
    in ``chat_messages.payload_json``; it is never reduced to plain text.
    """

    model_config = ConfigDict(extra="allow")

    summary: Any | None = None
    answer: Any | None = None
    table: Any | None = None
    charts: Any | None = None
    chart: Any | None = None
    sql: Any | None = None
    tools: Any | None = None
    metadata: Any | None = None


class MessageOut(BaseModel):
    id: int
    role: MessageRole
    payload: dict[str, Any]
    created_at: str


class SessionSummary(BaseModel):
    id: str
    title: str
    user_id: str | None = None
    created_at: str
    updated_at: str
    message_count: int = 0


class SessionDetail(SessionSummary):
    messages: list[MessageOut] = Field(default_factory=list)


class ChatResponse(BaseModel):
    session: SessionSummary
    user_message: MessageOut
    assistant_message: MessageOut


class DeleteResponse(BaseModel):
    deleted: bool
    session_id: str


class ClearResponse(BaseModel):
    deleted_count: int
    user_id: str
