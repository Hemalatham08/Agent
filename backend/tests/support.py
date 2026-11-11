from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.agent.events import TaskEvent, TaskEventType
from backend.agent.models import AgentTask, TaskError
from backend.agent.persistence.database import (
    create_agent_engine,
    create_session_factory,
)
from backend.agent.persistence.orm import Base
from backend.agent.persistence.repository import TaskRepository
from backend.agent.services import TaskManager


class PersistenceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._temp_dir.name) / "agent-test.db"
        self.database_url = f"sqlite:///{self.db_path.as_posix()}"
        self.engine = create_agent_engine(self.database_url)
        Base.metadata.create_all(self.engine)
        self.session_factory = create_session_factory(self.engine)
        self.repository = TaskRepository(self.session_factory)
        self.manager = TaskManager(self.repository)

    def tearDown(self) -> None:
        self.engine.dispose()
        self._temp_dir.cleanup()


def make_task(goal: str = "manual task", task_id: str | None = None) -> AgentTask:
    values = {"goal": goal}
    if task_id is not None:
        values["task_id"] = task_id
    return AgentTask(**values)


def make_created_event(task: AgentTask) -> TaskEvent:
    return TaskEvent(
        task_id=task.task_id,
        task_version=task.version,
        event_type=TaskEventType.TASK_CREATED,
        from_status=None,
        to_status=task.status,
        occurred_at=task.created_at,
    )


def make_error() -> TaskError:
    return TaskError(code="test_failure", message="task failed")
