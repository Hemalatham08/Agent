from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.agent.errors import ConcurrencyError, TaskNotFoundError
from backend.agent.events import TaskEvent, TaskEventType
from backend.agent.models import (
    AgentTask,
    TaskError,
    TaskStatus,
    utc_now,
)
from backend.agent.persistence.repository import TaskRepository
from backend.agent.runtime.state import (
    cancel,
    complete,
    fail,
    pause,
    resume,
    transition_to,
)


class TaskManager:
    def __init__(self, repository: TaskRepository) -> None:
        self._repository = repository

    def create_task(
        self,
        goal: str,
        *,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        task_id: str | None = None,
        at: datetime | None = None,
    ) -> AgentTask:
        timestamp = at if at is not None else utc_now()
        values: dict[str, Any] = {
            "goal": goal,
            "session_id": session_id,
            "created_at": timestamp,
            "updated_at": timestamp,
            "metadata": metadata or {},
        }
        if task_id is not None:
            values["task_id"] = task_id

        task = AgentTask(**values)
        event = TaskEvent(
            task_id=task.task_id,
            task_version=task.version,
            event_type=TaskEventType.TASK_CREATED,
            from_status=None,
            to_status=task.status,
            occurred_at=task.created_at,
        )
        self._repository.create(task, event)
        return task

    def get_task(self, task_id: str) -> AgentTask:
        task = self._repository.get(task_id)
        if task is None:
            raise TaskNotFoundError(task_id)
        return task

    def list_tasks(
        self,
        *,
        status: TaskStatus | None = None,
        session_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AgentTask]:
        return self._repository.list(
            status=status,
            session_id=session_id,
            limit=limit,
            offset=offset,
        )

    def transition_task(
        self,
        task_id: str,
        new_status: TaskStatus,
        *,
        expected_version: int | None = None,
        at: datetime | None = None,
        error: TaskError | None = None,
    ) -> AgentTask:
        previous = self._load_task(task_id, expected_version)
        updated = transition_to(
            previous,
            new_status,
            at=at,
            error=error,
        )
        event_type = self._event_type_for(
            previous.status,
            new_status,
        )
        return self._persist_transition(
            previous,
            updated,
            event_type,
            error=error,
        )

    def pause_task(
        self,
        task_id: str,
        *,
        expected_version: int | None = None,
        at: datetime | None = None,
    ) -> AgentTask:
        previous = self._load_task(task_id, expected_version)
        updated = pause(previous, at=at)
        return self._persist_transition(
            previous,
            updated,
            TaskEventType.TASK_PAUSED,
        )

    def resume_task(
        self,
        task_id: str,
        *,
        expected_version: int | None = None,
        at: datetime | None = None,
    ) -> AgentTask:
        previous = self._load_task(task_id, expected_version)
        updated = resume(previous, at=at)
        return self._persist_transition(
            previous,
            updated,
            TaskEventType.TASK_RESUMED,
        )

    def fail_task(
        self,
        task_id: str,
        error: TaskError,
        *,
        expected_version: int | None = None,
        at: datetime | None = None,
    ) -> AgentTask:
        previous = self._load_task(task_id, expected_version)
        updated = fail(previous, error, at=at)
        return self._persist_transition(
            previous,
            updated,
            TaskEventType.TASK_FAILED,
            error=error,
        )

    def complete_task(
        self,
        task_id: str,
        *,
        expected_version: int | None = None,
        at: datetime | None = None,
    ) -> AgentTask:
        previous = self._load_task(task_id, expected_version)
        updated = complete(previous, at=at)
        return self._persist_transition(
            previous,
            updated,
            TaskEventType.TASK_COMPLETED,
        )

    def cancel_task(
        self,
        task_id: str,
        *,
        expected_version: int | None = None,
        at: datetime | None = None,
    ) -> AgentTask:
        previous = self._load_task(task_id, expected_version)
        updated = cancel(previous, at=at)
        return self._persist_transition(
            previous,
            updated,
            TaskEventType.TASK_CANCELLED,
        )

    def list_events(self, task_id: str) -> list[TaskEvent]:
        self.get_task(task_id)
        return self._repository.list_events(task_id)

    def _load_task(
        self,
        task_id: str,
        expected_version: int | None,
    ) -> AgentTask:
        task = self.get_task(task_id)
        if (
            expected_version is not None
            and task.version != expected_version
        ):
            raise ConcurrencyError(
                task_id,
                expected_version,
                task.version,
            )
        return task

    def _persist_transition(
        self,
        previous: AgentTask,
        updated: AgentTask,
        event_type: TaskEventType,
        *,
        error: TaskError | None = None,
    ) -> AgentTask:
        payload: dict[str, Any] = {}
        if error is not None:
            payload["error"] = error.model_dump(mode="json")

        event = TaskEvent(
            task_id=updated.task_id,
            task_version=updated.version,
            event_type=event_type,
            from_status=previous.status,
            to_status=updated.status,
            occurred_at=updated.updated_at,
            payload=payload,
        )
        self._repository.update_with_event(
            updated,
            event,
            expected_version=previous.version,
        )
        return updated

    @staticmethod
    def _event_type_for(
        from_status: TaskStatus,
        to_status: TaskStatus,
    ) -> TaskEventType:
        if to_status is TaskStatus.FAILED:
            return TaskEventType.TASK_FAILED
        if to_status is TaskStatus.COMPLETED:
            return TaskEventType.TASK_COMPLETED
        if to_status is TaskStatus.CANCELLED:
            return TaskEventType.TASK_CANCELLED
        if to_status is TaskStatus.PAUSED:
            return TaskEventType.TASK_PAUSED
        if from_status is TaskStatus.PAUSED:
            return TaskEventType.TASK_RESUMED
        return TaskEventType.TASK_TRANSITIONED
