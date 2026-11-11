from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict


class ChatRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    role: ChatRole
    content: str
    name: str | None = None


class LLMResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    content: str
    model: str
    duration_ms: float | None = None
    prompt_eval_count: int | None = None
    eval_count: int | None = None


class ModelInfo(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    modified_at: str | None = None
    size: int | None = None


class ToolSelectionDecision(BaseModel):
    """Structured decision output from the reasoning model."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    thought: str = ""
    action: str  # "call_tool" or "final_answer"
    tool_name: str | None = None
    arguments: dict[str, Any] | None = None
    final_answer: str | None = None

