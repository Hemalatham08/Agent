from __future__ import annotations

from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class ToolCallSummary(BaseModel):
    """Safe, high-level summary of an executed tool call."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    status: str  # "succeeded" | "failed" | "cancelled"
    duration_ms: float | None = None
    error: str | None = None


class AgentExecutionResult(BaseModel):
    """Overall outcome of the agent reasoning and tool orchestration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    answer: str
    tool_calls: list[ToolCallSummary] = Field(default_factory=list)
    status: str  # "completed" | "error" | "incomplete"
    error: str | None = None
    iterations: int = 0
    session_id: str | None = None
