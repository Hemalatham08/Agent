from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from backend.agent.errors import (
    AgentStorageError,
    ConcurrencyError,
    DuplicateTaskError,
    TaskNotFoundError,
)
from backend.agent.events import TaskEvent
from backend.agent.models import AgentTask, TaskStatus
from backend.agent.persistence.mappers import (
    event_to_domain,
    event_to_values,
    task_to_domain,
    task_to_values,
)
from backend.agent.persistence.orm import (
    AgentTaskEventRecord,
    AgentTaskRecord,
)


class TaskRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def create(self, task: AgentTask, event: TaskEvent) -> None:
        self._validate_event(task, event)

        with self._session_factory() as session:
            try:
                session.add(AgentTaskRecord(**task_to_values(task)))
                session.flush()
                session.add(AgentTaskEventRecord(**event_to_values(event)))
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                if session.get(AgentTaskRecord, task.task_id) is not None:
                    raise DuplicateTaskError(task.task_id) from exc
                raise AgentStorageError(
                    f"failed to create task {task.task_id}"
                ) from exc

    def get(self, task_id: str) -> AgentTask | None:
        with self._session_factory() as session:
            record = session.get(AgentTaskRecord, task_id)
            if record is None:
                return None
            return task_to_domain(record)

    def list(
        self,
        *,
        status: TaskStatus | None = None,
        session_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AgentTask]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        if offset < 0:
            raise ValueError("offset must not be negative")

        statement = select(AgentTaskRecord)
        if status is not None:
            statement = statement.where(AgentTaskRecord.status == status)
        if session_id is not None:
            statement = statement.where(
                AgentTaskRecord.session_id == session_id
            )
        statement = statement.order_by(
            AgentTaskRecord.created_at.desc(),
            AgentTaskRecord.task_id.asc(),
        ).limit(limit).offset(offset)

        with self._session_factory() as session:
            records = session.scalars(statement).all()
            return [task_to_domain(record) for record in records]

    def update_with_event(
        self,
        task: AgentTask,
        event: TaskEvent,
        *,
        expected_version: int,
    ) -> None:
        self._validate_event(task, event)
        values = task_to_values(task)
        values.pop("task_id")

        with self._session_factory() as session:
            try:
                result = session.execute(
                    update(AgentTaskRecord)
                    .where(
                        AgentTaskRecord.task_id == task.task_id,
                        AgentTaskRecord.version == expected_version,
                    )
                    .values(**values)
                    .execution_options(synchronize_session=False)
                )
                if result.rowcount != 1:
                    current = session.get(AgentTaskRecord, task.task_id)
                    actual_version = (
                        current.version if current is not None else None
                    )
                    session.rollback()
                    if actual_version is None:
                        raise TaskNotFoundError(task.task_id)
                    raise ConcurrencyError(
                        task.task_id,
                        expected_version,
                        actual_version,
                    )

                session.add(AgentTaskEventRecord(**event_to_values(event)))
                session.commit()
            except (TaskNotFoundError, ConcurrencyError):
                raise
            except IntegrityError as exc:
                session.rollback()
                raise AgentStorageError(
                    f"failed to persist task {task.task_id} transition"
                ) from exc

    def list_events(self, task_id: str) -> list[TaskEvent]:
        statement = (
            select(AgentTaskEventRecord)
            .where(AgentTaskEventRecord.task_id == task_id)
            .order_by(AgentTaskEventRecord.event_seq.asc())
        )
        with self._session_factory() as session:
            records = session.scalars(statement).all()
            return [event_to_domain(record) for record in records]

    @staticmethod
    def _validate_event(task: AgentTask, event: TaskEvent) -> None:
        if event.task_id != task.task_id:
            raise ValueError("event task_id must match task task_id")
        if event.task_version != task.version:
            raise ValueError("event task_version must match task version")
