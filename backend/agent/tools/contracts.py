"""Typed contracts for defining and recording tool executions.

Frozen Pydantic models prevent reassignment of model fields. They do not
deep-freeze mutable values stored inside fields, such as dictionaries in
``metadata``, ``arguments``, ``output``, or ``details``. Treat nested values
on these models as read-only by convention after construction.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated
from uuid import uuid4

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    model_validator,
)

from backend.agent.models import ErrorCategory, NonBlankStr, TaskError

ToolName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9]*(?:[._][a-z0-9]+)*$",
    ),
]
ToolDescription = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=1024),
]
ToolVersion = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=32,
        pattern=r"^[0-9A-Za-z][0-9A-Za-z._-]*$",
    ),
]


class ToolDefinition(BaseModel):
    """Describe a tool and its JSON-compatible argument schema.

    The model is frozen at the attribute level. Nested values in
    ``input_schema`` and ``metadata`` remain mutable Python objects.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: ToolName
    description: ToolDescription
    input_schema: dict[str, JsonValue]
    version: ToolVersion | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_input_schema(self) -> ToolDefinition:
        schema = self.input_schema
        if schema.get("type") != "object":
            raise ValueError("input_schema must declare type='object'")

        properties = schema.get("properties")
        if properties is not None:
            if not isinstance(properties, dict):
                raise ValueError("input_schema.properties must be an object")
            for property_schema in properties.values():
                if not isinstance(property_schema, dict):
                    raise ValueError(
                        "input_schema.properties values must be objects"
                    )

        required = schema.get("required")
        if required is not None:
            if not isinstance(required, list):
                raise ValueError("input_schema.required must be a list")
            if any(
                not isinstance(item, str) or not item.strip()
                for item in required
            ):
                raise ValueError(
                    "input_schema.required entries must be nonblank strings"
                )
            if len(set(required)) != len(required):
                raise ValueError(
                    "input_schema.required entries must be unique"
                )
            if required and properties is None:
                raise ValueError(
                    "input_schema.required requires input_schema.properties"
                )
            if properties is not None and not set(required).issubset(
                properties.keys()
            ):
                raise ValueError(
                    "input_schema.required entries must exist in properties"
                )

        additional_properties = schema.get("additionalProperties")
        if additional_properties is not None and not isinstance(
            additional_properties, (bool, dict)
        ):
            raise ValueError(
                "input_schema.additionalProperties must be a boolean or object"
            )

        return self


class ToolExecutionRequest(BaseModel):
    """Immutable request to execute one tool.

    Nested values in ``arguments`` and ``metadata`` remain mutable Python
    objects even though the model's attributes are frozen.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    execution_id: NonBlankStr = Field(default_factory=lambda: str(uuid4()))
    tool_name: ToolName
    arguments: dict[str, JsonValue] = Field(default_factory=dict)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class ToolExecutionContext(BaseModel):
    """Immutable context supplied to a tool handler.

    Nested values in ``metadata`` remain mutable Python objects even though the
    model's attributes are frozen.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    execution_id: NonBlankStr
    tool_name: ToolName
    started_at: AwareDatetime
    timeout_seconds: float | None = Field(default=None, gt=0)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @property
    def timeout(self) -> float | None:
        return self.timeout_seconds


class ToolExecutionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in TERMINAL_TOOL_EXECUTION_STATUSES


TERMINAL_TOOL_EXECUTION_STATUSES = frozenset(
    {
        ToolExecutionStatus.SUCCEEDED,
        ToolExecutionStatus.FAILED,
        ToolExecutionStatus.CANCELLED,
    }
)


class ToolExecutionError(TaskError):
    """Structured tool error with JSON-compatible details."""

    category: ErrorCategory = ErrorCategory.TOOL
    details: dict[str, JsonValue] = Field(default_factory=dict)


class ToolExecutionResult(BaseModel):
    """Immutable record of one tool execution attempt.

    Nested values in ``output`` and ``error.details`` remain mutable Python
    objects even though the model's attributes are frozen.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    execution_id: NonBlankStr
    tool_name: ToolName
    status: ToolExecutionStatus
    output: JsonValue | None = None
    error: ToolExecutionError | None = None
    started_at: AwareDatetime | None = None
    finished_at: AwareDatetime | None = None
    duration_ms: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_execution_state(self) -> ToolExecutionResult:
        if (
            self.started_at is not None
            and self.finished_at is not None
            and self.finished_at < self.started_at
        ):
            raise ValueError("finished_at must not precede started_at")

        if self.status is ToolExecutionStatus.PENDING:
            if any(
                value is not None
                for value in (
                    self.output,
                    self.error,
                    self.started_at,
                    self.finished_at,
                    self.duration_ms,
                )
            ):
                raise ValueError(
                    "PENDING result cannot contain output, error, "
                    "timestamps, or duration"
                )
        elif self.status is ToolExecutionStatus.RUNNING:
            if self.started_at is None:
                raise ValueError("RUNNING result requires started_at")
            if any(
                value is not None
                for value in (
                    self.output,
                    self.error,
                    self.finished_at,
                    self.duration_ms,
                )
            ):
                raise ValueError(
                    "RUNNING result cannot contain output, error, "
                    "finished_at, or duration"
                )
        elif self.status is ToolExecutionStatus.SUCCEEDED:
            if self.started_at is None or self.finished_at is None:
                raise ValueError(
                    "SUCCEEDED result requires started_at and finished_at"
                )
            if self.error is not None:
                raise ValueError(
                    "SUCCEEDED result cannot contain an error"
                )
        elif self.status is ToolExecutionStatus.FAILED:
            if self.finished_at is None:
                raise ValueError("FAILED result requires finished_at")
            if self.error is None:
                raise ValueError("FAILED result requires an error")
            if self.output is not None:
                raise ValueError("FAILED result cannot contain output")
        elif self.status is ToolExecutionStatus.CANCELLED:
            if self.finished_at is None:
                raise ValueError("CANCELLED result requires finished_at")
            if self.output is not None:
                raise ValueError("CANCELLED result cannot contain output")
            if self.error is not None:
                raise ValueError("CANCELLED result cannot contain an error")

        return self


__all__ = [
    "TERMINAL_TOOL_EXECUTION_STATUSES",
    "ToolDefinition",
    "ToolDescription",
    "ToolExecutionError",
    "ToolExecutionContext",
    "ToolExecutionRequest",
    "ToolExecutionResult",
    "ToolExecutionStatus",
    "ToolName",
    "ToolVersion",
]
