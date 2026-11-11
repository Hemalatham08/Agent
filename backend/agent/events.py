from __future__ import annotations

from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from backend.agent.models import NonBlankStr, TaskStatus, utc_now


class TaskEventType(str, Enum):
    TASK_CREATED = "task_created"
    TASK_TRANSITIONED = "task_transitioned"
    TASK_PAUSED = "task_paused"
    TASK_RESUMED = "task_resumed"
    TASK_FAILED = "task_failed"
    TASK_COMPLETED = "task_completed"
    TASK_CANCELLED = "task_cancelled"


_EVENT_TARGETS: dict[TaskEventType, TaskStatus] = {
    TaskEventType.TASK_PAUSED: TaskStatus.PAUSED,
    TaskEventType.TASK_FAILED: TaskStatus.FAILED,
    TaskEventType.TASK_COMPLETED: TaskStatus.COMPLETED,
    TaskEventType.TASK_CANCELLED: TaskStatus.CANCELLED,
}


class TaskEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: NonBlankStr = Field(default_factory=lambda: str(uuid4()))
    task_id: NonBlankStr
    task_version: int = Field(ge=0)
    event_type: TaskEventType
    from_status: TaskStatus | None = None
    to_status: TaskStatus
    occurred_at: AwareDatetime = Field(default_factory=utc_now)
    payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_event(self) -> TaskEvent:
        if self.event_type is TaskEventType.TASK_CREATED:
            if self.from_status is not None:
                raise ValueError("created event must not have from_status")
            if self.to_status is not TaskStatus.CREATED:
                raise ValueError("created event must target CREATED")
            return self

        if self.from_status is None:
            raise ValueError("non-created event requires from_status")
        if self.from_status is self.to_status:
            raise ValueError("event must change task status")

        if self.event_type is TaskEventType.TASK_RESUMED:
            if self.from_status is not TaskStatus.PAUSED:
                raise ValueError("resumed event must start from PAUSED")
            if self.to_status is TaskStatus.PAUSED:
                raise ValueError("resumed event must leave PAUSED")
            return self

        if self.event_type is TaskEventType.TASK_TRANSITIONED:
            if self.to_status in {
                TaskStatus.PAUSED,
                TaskStatus.COMPLETED,
                TaskStatus.FAILED,
                TaskStatus.CANCELLED,
            }:
                raise ValueError(
                    "transitioned event target has a dedicated event type"
                )
            return self

        expected_target = _EVENT_TARGETS[self.event_type]
        if self.to_status is not expected_target:
            raise ValueError(
                f"{self.event_type.value} event must target "
                f"{expected_target.value}"
            )
        return self
