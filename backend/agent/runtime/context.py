from __future__ import annotations

from typing import Any

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from backend.agent.models import (
    Action,
    NonBlankStr,
    TaskStatus,
    ToolResult,
    VerificationResult,
    utc_now,
)


class AgentState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: NonBlankStr
    status: TaskStatus = TaskStatus.CREATED
    current_action: Action | None = None
    observations: list[ToolResult] = Field(default_factory=list)
    pending_actions: list[Action] = Field(default_factory=list)
    last_verification: VerificationResult | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExecutionContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: NonBlankStr
    session_id: NonBlankStr | None = None
    attempt: int = Field(default=1, ge=1)
    max_iterations: int = Field(ge=1)
    max_tool_calls: int = Field(ge=1)
    started_at: AwareDatetime = Field(default_factory=utc_now)
    deadline: AwareDatetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_deadline(self) -> ExecutionContext:
        if self.deadline is not None and self.deadline < self.started_at:
            raise ValueError("deadline must not precede started_at")
        return self
