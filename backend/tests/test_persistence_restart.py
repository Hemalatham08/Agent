import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.agent.models import TaskStatus
from backend.agent.persistence.config import (
    DEFAULT_AGENT_DB_PATH,
    default_agent_database_url,
    get_agent_database_url,
)
from backend.agent.persistence.database import (
    create_agent_engine,
    create_session_factory,
)
from backend.agent.persistence.orm import Base
from backend.agent.persistence.repository import TaskRepository
from backend.agent.services import TaskManager
from backend.tests.support import make_error


class PersistenceRestartTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._temp_dir.name) / "restart.db"
        self.database_url = f"sqlite:///{self.db_path.as_posix()}"
        self.engine = create_agent_engine(self.database_url)
        Base.metadata.create_all(self.engine)
        self._engines = [self.engine]
        self.manager = TaskManager(
            TaskRepository(create_session_factory(self.engine))
        )

    def tearDown(self) -> None:
        for engine in reversed(self._engines):
            engine.dispose()
        self._temp_dir.cleanup()

    def _reopen_manager(self) -> TaskManager:
        engine = create_agent_engine(self.database_url)
        self._engines.append(engine)
        return TaskManager(
            TaskRepository(create_session_factory(engine))
        )

    def test_restart_preserves_task_metadata_and_events(self) -> None:
        task = self.manager.create_task(
            "restart goal",
            session_id="restart-session",
            metadata={"source": "restart", "nested": {"enabled": True}},
        )
        self.manager.transition_task(task.task_id, TaskStatus.PLANNING)
        before_task = self.manager.get_task(task.task_id)
        before_events = self.manager.list_events(task.task_id)

        self.engine.dispose()
        reopened = self._reopen_manager()

        after_task = reopened.get_task(task.task_id)
        after_events = reopened.list_events(task.task_id)

        self.assertEqual(after_task.model_dump(), before_task.model_dump())
        self.assertEqual(
            [event.model_dump() for event in after_events],
            [event.model_dump() for event in before_events],
        )
        self.assertEqual(
            after_task.metadata,
            {"source": "restart", "nested": {"enabled": True}},
        )

        next_task = reopened.transition_task(
            task.task_id,
            TaskStatus.PLANNED,
        )
        self.assertEqual(next_task.version, 2)
        self.assertEqual(len(reopened.list_events(task.task_id)), 3)

    def test_restart_preserves_failure_error(self) -> None:
        error = make_error()
        task = self.manager.create_task("restart failure")
        self.manager.fail_task(task.task_id, error)

        self.engine.dispose()
        reopened = self._reopen_manager()

        restored = reopened.get_task(task.task_id)
        self.assertEqual(restored.status, TaskStatus.FAILED)
        self.assertEqual(restored.error, error)
        self.assertEqual(
            reopened.list_events(task.task_id)[-1].payload["error"]["code"],
            error.code,
        )


class AgentDatabaseConfigTests(unittest.TestCase):
    def test_default_location_is_agent_data_directory(self) -> None:
        self.assertEqual(DEFAULT_AGENT_DB_PATH.name, "agent.db")
        self.assertEqual(DEFAULT_AGENT_DB_PATH.parent.name, "agent_data")
        self.assertTrue(
            default_agent_database_url().startswith("sqlite:///")
        )

    def test_environment_override_and_blank_fallback(self) -> None:
        with patch.dict(
            os.environ,
            {"AGENT_DATABASE_URL": "sqlite:///custom-agent.db"},
        ):
            self.assertEqual(
                get_agent_database_url(),
                "sqlite:///custom-agent.db",
            )

        with patch.dict(os.environ, {"AGENT_DATABASE_URL": "   "}):
            self.assertEqual(
                get_agent_database_url(),
                default_agent_database_url(),
            )


if __name__ == "__main__":
    unittest.main()

