from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any
from uuid import uuid4

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

NonBlankStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TaskStatus(str, Enum):
    CREATED = "created"
    PLANNING = "planning"
    PLANNED = "planned"
    EXECUTING = "executing"
    WAITING_APPROVAL = "waiting_approval"
    PAUSED = "paused"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in TERMINAL_STATUSES


TERMINAL_STATUSES = frozenset(
    {
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    }
)

PAUSABLE_STATUSES = frozenset(
    {
        TaskStatus.PLANNED,
        TaskStatus.EXECUTING,
        TaskStatus.WAITING_APPROVAL,
    }
)


class ErrorCategory(str, Enum):
    VALIDATION = "validation"
    NOT_FOUND = "not_found"
    PERMISSION = "permission"
    TIMEOUT = "timeout"
    TOOL = "tool"
    LLM = "llm"
    INTERNAL = "internal"


class ActionType(str, Enum):
    READ = "read"
    WRITE = "write"
    DECISION = "decision"


class VerificationStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    UNCERTAIN = "uncertain"


class TaskError(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: NonBlankStr
    message: NonBlankStr
    category: ErrorCategory = ErrorCategory.INTERNAL
    recoverable: bool = False
    retryable: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


class Action(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action_id: NonBlankStr = Field(default_factory=lambda: str(uuid4()))
    action_type: ActionType = ActionType.READ
    tool_name: NonBlankStr
    arguments: dict[str, Any] = Field(default_factory=dict)
    requires_approval: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_name: NonBlankStr
    success: bool
    output: Any | None = None
    error: TaskError | None = None
    started_at: AwareDatetime = Field(default_factory=utc_now)
    finished_at: AwareDatetime = Field(default_factory=utc_now)
    duration_ms: float | None = Field(default=None, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_result(self) -> ToolResult:
        if self.finished_at < self.started_at:
            raise ValueError("finished_at must not precede started_at")
        if self.success and self.error is not None:
            raise ValueError("a successful ToolResult cannot contain an error")
        if not self.success and self.error is None:
            raise ValueError("a failed ToolResult must contain a TaskError")
        return self


class VerificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: VerificationStatus
    passed: bool
    message: NonBlankStr
    checks: dict[str, bool] = Field(default_factory=dict)
    checked_at: AwareDatetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_status(self) -> VerificationResult:
        if self.status is VerificationStatus.PASSED and not self.passed:
            raise ValueError("PASSED verification must set passed=True")
        if self.status is not VerificationStatus.PASSED and self.passed:
            raise ValueError("only PASSED verification may set passed=True")
        return self


class AgentTask(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: NonBlankStr = Field(default_factory=lambda: str(uuid4()))
    session_id: NonBlankStr | None = None
    goal: NonBlankStr
    status: TaskStatus = TaskStatus.CREATED
    created_at: AwareDatetime = Field(default_factory=utc_now)
    updated_at: AwareDatetime = Field(default_factory=utc_now)
    started_at: AwareDatetime | None = None
    completed_at: AwareDatetime | None = None
    paused_from: TaskStatus | None = None
    iteration_count: int = Field(default=0, ge=0)
    tool_call_count: int = Field(default=0, ge=0)
    error: TaskError | None = None
    version: int = Field(default=0, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_lifecycle(self) -> AgentTask:
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not precede created_at")

        if self.status is TaskStatus.PAUSED:
            if self.paused_from is None:
                raise ValueError("PAUSED task must record paused_from")
            if self.paused_from not in PAUSABLE_STATUSES:
                raise ValueError("paused_from must be a pausable status")
        elif self.paused_from is not None:
            raise ValueError("paused_from is only allowed for PAUSED tasks")

        if self.status in TERMINAL_STATUSES:
            if self.paused_from is not None:
                raise ValueError("terminal task cannot retain paused_from")
        elif self.completed_at is not None:
            raise ValueError("non-terminal task cannot have completed_at")

        if self.status is TaskStatus.COMPLETED:
            if self.completed_at is None:
                raise ValueError("COMPLETED task requires completed_at")
            if self.error is not None:
                raise ValueError("COMPLETED task cannot contain an error")

        if self.status is TaskStatus.FAILED and self.error is None:
            raise ValueError("FAILED task requires a TaskError")

        if self.status is not TaskStatus.FAILED and self.error is not None:
            raise ValueError("error is only allowed for FAILED tasks")

        return self
