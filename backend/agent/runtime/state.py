from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.agent.models import (
    PAUSABLE_STATUSES,
    TERMINAL_STATUSES,
    AgentTask,
    TaskError,
    TaskStatus,
    utc_now,
)

ALLOWED_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.CREATED: frozenset(
        {
            TaskStatus.PLANNING,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.PLANNING: frozenset(
        {
            TaskStatus.PLANNED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.PLANNED: frozenset(
        {
            TaskStatus.EXECUTING,
            TaskStatus.PAUSED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.EXECUTING: frozenset(
        {
            TaskStatus.WAITING_APPROVAL,
            TaskStatus.VERIFYING,
            TaskStatus.PAUSED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.WAITING_APPROVAL: frozenset(
        {
            TaskStatus.EXECUTING,
            TaskStatus.PAUSED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.PAUSED: frozenset(
        {
            TaskStatus.PLANNED,
            TaskStatus.EXECUTING,
            TaskStatus.WAITING_APPROVAL,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.VERIFYING: frozenset(
        {
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.COMPLETED: frozenset(),
    TaskStatus.FAILED: frozenset(),
    TaskStatus.CANCELLED: frozenset(),
}


class TransitionError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        from_status: TaskStatus | None = None,
        to_status: TaskStatus | None = None,
    ) -> None:
        super().__init__(message)
        self.from_status = from_status
        self.to_status = to_status


def validate_transition(from_status: TaskStatus, to_status: TaskStatus) -> None:
    if not isinstance(from_status, TaskStatus) or not isinstance(to_status, TaskStatus):
        raise TransitionError("task statuses must be TaskStatus values")

    if from_status == to_status:
        raise TransitionError(
            f"self-transition is not allowed: {from_status.value} -> {to_status.value}",
            from_status=from_status,
            to_status=to_status,
        )

    if from_status in TERMINAL_STATUSES:
        raise TransitionError(
            f"terminal state {from_status.value} cannot transition to {to_status.value}",
            from_status=from_status,
            to_status=to_status,
        )

    allowed = ALLOWED_TRANSITIONS.get(from_status, frozenset())
    if to_status not in allowed:
        raise TransitionError(
            f"invalid transition: {from_status.value} -> {to_status.value}",
            from_status=from_status,
            to_status=to_status,
        )


def _validate_timestamp(timestamp: datetime, task: AgentTask) -> None:
    if not isinstance(timestamp, datetime):
        raise TransitionError(
            "transition timestamp must be a datetime",
            from_status=task.status,
        )
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise TransitionError(
            "transition timestamp must be timezone-aware",
            from_status=task.status,
        )
    if timestamp < task.created_at:
        raise TransitionError(
            "transition timestamp cannot precede task creation",
            from_status=task.status,
        )
    if timestamp < task.updated_at:
        raise TransitionError(
            "transition timestamp cannot move backwards",
            from_status=task.status,
        )


def _replace(task: AgentTask, **updates: Any) -> AgentTask:
    payload = task.model_dump()
    payload.update(updates)
    return AgentTask.model_validate(payload)


def transition_to(
    task: AgentTask,
    new_status: TaskStatus,
    *,
    at: datetime | None = None,
    error: TaskError | None = None,
) -> AgentTask:
    if not isinstance(task, AgentTask):
        raise TransitionError("task must be an AgentTask")

    timestamp = at if at is not None else utc_now()
    _validate_timestamp(timestamp, task)
    validate_transition(task.status, new_status)

    if task.status is TaskStatus.PAUSED and new_status in PAUSABLE_STATUSES:
        if task.paused_from is None:
            raise TransitionError(
                "paused task is missing paused_from",
                from_status=task.status,
                to_status=new_status,
            )
        if task.paused_from is not new_status:
            raise TransitionError(
                f"resume must restore {task.paused_from.value}, not {new_status.value}",
                from_status=task.status,
                to_status=new_status,
            )

    if new_status is TaskStatus.PAUSED and task.status not in PAUSABLE_STATUSES:
        raise TransitionError(
            f"task cannot be paused from {task.status.value}",
            from_status=task.status,
            to_status=new_status,
        )

    if new_status is TaskStatus.FAILED:
        if not isinstance(error, TaskError):
            raise TransitionError(
                "FAILED transition requires a TaskError",
                from_status=task.status,
                to_status=new_status,
            )
    elif error is not None:
        raise TransitionError(
            "TaskError is only allowed when transitioning to FAILED",
            from_status=task.status,
            to_status=new_status,
        )

    updates: dict[str, Any] = {
        "status": new_status,
        "updated_at": timestamp,
        "version": task.version + 1,
        "completed_at": timestamp if new_status in TERMINAL_STATUSES else None,
        "error": error if new_status is TaskStatus.FAILED else None,
    }

    if new_status is TaskStatus.EXECUTING and task.started_at is None:
        updates["started_at"] = timestamp

    if new_status is TaskStatus.PAUSED:
        updates["paused_from"] = task.status
    elif new_status in TERMINAL_STATUSES or task.status is TaskStatus.PAUSED:
        updates["paused_from"] = None

    return _replace(task, **updates)


def pause(task: AgentTask, *, at: datetime | None = None) -> AgentTask:
    if task.status not in PAUSABLE_STATUSES:
        raise TransitionError(
            f"task cannot be paused from {task.status.value}",
            from_status=task.status,
            to_status=TaskStatus.PAUSED,
        )
    return transition_to(task, TaskStatus.PAUSED, at=at)


def resume(task: AgentTask, *, at: datetime | None = None) -> AgentTask:
    if task.status is not TaskStatus.PAUSED:
        raise TransitionError(
            "only PAUSED tasks can be resumed",
            from_status=task.status,
        )
    if task.paused_from is None:
        raise TransitionError(
            "paused task is missing paused_from",
            from_status=task.status,
        )
    if task.paused_from not in PAUSABLE_STATUSES:
        raise TransitionError(
            f"cannot resume to invalid state {task.paused_from.value}",
            from_status=task.status,
            to_status=task.paused_from,
        )
    return transition_to(task, task.paused_from, at=at)


def cancel(task: AgentTask, *, at: datetime | None = None) -> AgentTask:
    return transition_to(task, TaskStatus.CANCELLED, at=at)


def fail(
    task: AgentTask,
    error: TaskError,
    *,
    at: datetime | None = None,
) -> AgentTask:
    if not isinstance(error, TaskError):
        raise TransitionError(
            "fail requires a TaskError",
            from_status=task.status,
            to_status=TaskStatus.FAILED,
        )
    return transition_to(task, TaskStatus.FAILED, at=at, error=error)


def complete(task: AgentTask, *, at: datetime | None = None) -> AgentTask:
    if task.status is not TaskStatus.VERIFYING:
        raise TransitionError(
            "completion is only allowed from VERIFYING",
            from_status=task.status,
            to_status=TaskStatus.COMPLETED,
        )
    return transition_to(task, TaskStatus.COMPLETED, at=at)
