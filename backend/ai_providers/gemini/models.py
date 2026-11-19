"""Data models for the Gemini AI provider.

These models mirror the shared message/response concepts used by the Ollama
client (roles, messages, normalized response) so that the Gemini output can be
mapped into a common contract in a later phase. No Ollama modules are imported.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class GeminiChatRole(str, Enum):
    """Role of a message participant in a Gemini conversation."""

    SYSTEM = "system"
    USER = "user"
    MODEL = "model"
    FUNCTION = "function"
    TOOL = "tool"


class GeminiChatMessage(BaseModel):
    """A single message in a Gemini conversation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    role: GeminiChatRole
    content: str
    call_id: str | None = None
    tool_name: str | None = None
    function_calls: list[dict[str, Any]] | None = None
    thought_signature: bytes | None = None


class GeminiModelInfo(BaseModel):
    """Describe one model reported by the Gemini service."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    version: str | None = None


class GeminiResponse(BaseModel):
    """Normalized response from a non-streaming Gemini generation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    content: str
    model: str
    duration_ms: float | None = None
    request_duration_ms: float | None = None
    finish_reason: str | None = None
    safety_ratings: list[dict[str, Any]] = []
    truncated: bool = False
    function_calls: list[dict[str, Any]] = Field(default_factory=list)


__all__ = [
    "GeminiChatMessage",
    "GeminiChatRole",
    "GeminiModelInfo",
    "GeminiResponse",
]
