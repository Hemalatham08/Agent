import tempfile
import unittest
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from backend.agent.models import TaskStatus
from backend.agent.persistence.database import (
    create_agent_engine,
    create_session_factory,
)
from backend.agent.persistence.repository import TaskRepository
from backend.agent.services import TaskManager

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class MigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._temp_dir.name) / "migrated.db"
        self.database_url = f"sqlite:///{self.db_path.as_posix()}"
        self.config = Config(str(PROJECT_ROOT / "alembic.ini"))
        self.config.set_main_option(
            "script_location",
            str(PROJECT_ROOT / "backend" / "migrations"),
        )
        self.config.set_main_option("sqlalchemy.url", self.database_url)
        self._engines = []

    def tearDown(self) -> None:
        for engine in reversed(self._engines):
            engine.dispose()
        self._temp_dir.cleanup()

    def test_upgrade_creates_expected_schema_and_supports_repository(self) -> None:
        command.upgrade(self.config, "head")

        engine = create_agent_engine(self.database_url)
        self._engines.append(engine)
        inspector = inspect(engine)

        tables = set(inspector.get_table_names())
        self.assertIn("agent_tasks", tables)
        self.assertIn("agent_task_events", tables)
        self.assertIn("alembic_version", tables)

        task_columns = {
            column["name"]
            for column in inspector.get_columns("agent_tasks")
        }
        self.assertEqual(
            task_columns,
            {
                "task_id",
                "session_id",
                "goal",
                "status",
                "created_at",
                "updated_at",
                "started_at",
                "completed_at",
                "paused_from",
                "iteration_count",
                "tool_call_count",
                "error",
                "version",
                "metadata",
            },
        )

        event_columns = {
            column["name"]
            for column in inspector.get_columns("agent_task_events")
        }
        self.assertEqual(
            event_columns,
            {
                "event_seq",
                "event_id",
                "task_id",
                "task_version",
                "event_type",
                "from_status",
                "to_status",
                "occurred_at",
                "payload",
            },
        )

        task_indexes = {
            index["name"]
            for index in inspector.get_indexes("agent_tasks")
        }
        self.assertEqual(
            task_indexes,
            {
                "ix_agent_tasks_status",
                "ix_agent_tasks_session_created",
                "ix_agent_tasks_created_at",
            },
        )

        event_indexes = {
            index["name"]
            for index in inspector.get_indexes("agent_task_events")
        }
        self.assertEqual(
            event_indexes,
            {"ix_agent_task_events_task_seq"},
        )

        task_checks = {
            constraint["name"]
            for constraint in inspector.get_check_constraints("agent_tasks")
        }
        self.assertEqual(
            task_checks,
            {
                "ck_agent_tasks_status",
                "ck_agent_tasks_paused_from",
                "ck_agent_tasks_iteration_count",
                "ck_agent_tasks_tool_call_count",
                "ck_agent_tasks_version",
            },
        )

        event_checks = {
            constraint["name"]
            for constraint in inspector.get_check_constraints(
                "agent_task_events"
            )
        }
        self.assertEqual(
            event_checks,
            {
                "ck_agent_task_events_event_type",
                "ck_agent_task_events_from_status",
                "ck_agent_task_events_to_status",
                "ck_agent_task_events_task_version",
            },
        )

        unique_constraints = {
            constraint["name"]
            for constraint in inspector.get_unique_constraints(
                "agent_task_events"
            )
        }
        self.assertIn(
            "uq_agent_task_events_event_id",
            unique_constraints,
        )

        foreign_keys = inspector.get_foreign_keys("agent_task_events")
        self.assertEqual(len(foreign_keys), 1)
        self.assertEqual(
            foreign_keys[0]["referred_table"],
            "agent_tasks",
        )
        self.assertEqual(
            foreign_keys[0]["options"].get("ondelete"),
            "CASCADE",
        )

        manager = TaskManager(
            TaskRepository(create_session_factory(engine))
        )
        task = manager.create_task("migrated task")
        manager.transition_task(task.task_id, TaskStatus.PLANNING)
        manager.transition_task(task.task_id, TaskStatus.PLANNED)

        restored = manager.get_task(task.task_id)
        self.assertEqual(restored.status, TaskStatus.PLANNED)
        self.assertEqual(restored.version, 2)
        self.assertEqual(
            [
                event.event_type.value
                for event in manager.list_events(task.task_id)
            ],
            [
                "task_created",
                "task_transitioned",
                "task_transitioned",
            ],
        )

        command.check(self.config)

    def test_downgrade_removes_agent_tables(self) -> None:
        command.upgrade(self.config, "head")
        command.downgrade(self.config, "base")

        engine = create_agent_engine(self.database_url)
        self._engines.append(engine)
        tables = set(inspect(engine).get_table_names())

        self.assertNotIn("agent_tasks", tables)
        self.assertNotIn("agent_task_events", tables)


if __name__ == "__main__":
    unittest.main()
