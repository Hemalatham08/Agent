from __future__ import annotations

from typing import Any

from backend.agent.events import TaskEvent
from backend.agent.models import AgentTask, TaskError
from backend.agent.persistence.orm import (
    AgentTaskEventRecord,
    AgentTaskRecord,
)


def task_to_values(task: AgentTask) -> dict[str, Any]:
    return {
        "task_id": task.task_id,
        "session_id": task.session_id,
        "goal": task.goal,
        "status": task.status,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "started_at": task.started_at,
        "completed_at": task.completed_at,
        "paused_from": task.paused_from,
        "iteration_count": task.iteration_count,
        "tool_call_count": task.tool_call_count,
        "error": (
            task.error.model_dump(mode="json")
            if task.error is not None
            else None
        ),
        "version": task.version,
        "task_metadata": dict(task.metadata),
    }


def task_to_domain(record: AgentTaskRecord) -> AgentTask:
    return AgentTask(
        task_id=record.task_id,
        session_id=record.session_id,
        goal=record.goal,
        status=record.status,
        created_at=record.created_at,
        updated_at=record.updated_at,
        started_at=record.started_at,
        completed_at=record.completed_at,
        paused_from=record.paused_from,
        iteration_count=record.iteration_count,
        tool_call_count=record.tool_call_count,
        error=(
            TaskError.model_validate(record.error)
            if record.error is not None
            else None
        ),
        version=record.version,
        metadata=dict(record.task_metadata or {}),
    )


def event_to_values(event: TaskEvent) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "task_id": event.task_id,
        "task_version": event.task_version,
        "event_type": event.event_type,
        "from_status": event.from_status,
        "to_status": event.to_status,
        "occurred_at": event.occurred_at,
        "payload": dict(event.payload),
    }


def event_to_domain(record: AgentTaskEventRecord) -> TaskEvent:
    return TaskEvent(
        event_id=record.event_id,
        task_id=record.task_id,
        task_version=record.task_version,
        event_type=record.event_type,
        from_status=record.from_status,
        to_status=record.to_status,
        occurred_at=record.occurred_at,
        payload=dict(record.payload or {}),
    )
