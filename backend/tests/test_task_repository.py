import unittest
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, text

from backend.agent.errors import (
    AgentStorageError,
    ConcurrencyError,
    DuplicateTaskError,
    TaskNotFoundError,
)
from backend.agent.events import TaskEvent, TaskEventType
from backend.agent.models import ErrorCategory, TaskError, TaskStatus
from backend.agent.persistence.orm import AgentTaskRecord
from backend.agent.runtime.state import transition_to
from backend.tests.support import (
    PersistenceTestCase,
    make_created_event,
    make_error,
    make_task,
)


class TaskRepositoryTests(PersistenceTestCase):
    def test_create_and_get_round_trip(self) -> None:
        task = self.manager.create_task(
            "persisted goal",
            session_id="session-1",
            metadata={"source": "test", "count": 2},
            task_id="task-round-trip",
        )

        restored = self.repository.get(task.task_id)

        self.assertIsNotNone(restored)
        self.assertEqual(restored.model_dump(), task.model_dump())
        self.assertEqual(restored.metadata, {"source": "test", "count": 2})
        self.assertIsNotNone(restored.created_at.tzinfo)

    def test_get_missing_task_returns_none(self) -> None:
        self.assertIsNone(self.repository.get("missing-task"))

    def test_duplicate_task_is_rejected_without_extra_event(self) -> None:
        self.manager.create_task("first", task_id="duplicate-task")

        with self.assertRaises(DuplicateTaskError):
            self.manager.create_task("second", task_id="duplicate-task")

        restored = self.repository.get("duplicate-task")
        self.assertIsNotNone(restored)
        self.assertEqual(restored.goal, "first")
        self.assertEqual(len(self.repository.list_events("duplicate-task")), 1)

    def test_event_insert_failure_rolls_back_task_creation(self) -> None:
        first = self.manager.create_task("first")
        first_event = self.repository.list_events(first.task_id)[0]
        second = make_task("second", task_id="second-task")
        conflicting_event = TaskEvent(
            event_id=first_event.event_id,
            task_id=second.task_id,
            task_version=second.version,
            event_type=TaskEventType.TASK_CREATED,
            from_status=None,
            to_status=second.status,
            occurred_at=second.created_at,
        )

        with self.assertRaises(AgentStorageError):
            self.repository.create(second, conflicting_event)

        self.assertIsNone(self.repository.get(second.task_id))
        self.assertEqual(len(self.repository.list_events(first.task_id)), 1)

    def test_create_validates_event_reference(self) -> None:
        task = make_task("manual", task_id="manual-task")
        event = make_created_event(task)

        mismatched_task_event = TaskEvent(
            event_id=event.event_id,
            task_id="other-task",
            task_version=event.task_version,
            event_type=event.event_type,
            from_status=event.from_status,
            to_status=event.to_status,
            occurred_at=event.occurred_at,
        )
        with self.assertRaises(ValueError):
            self.repository.create(task, mismatched_task_event)

        mismatched_version_event = TaskEvent(
            event_id=event.event_id,
            task_id=task.task_id,
            task_version=event.task_version + 1,
            event_type=event.event_type,
            from_status=event.from_status,
            to_status=event.to_status,
            occurred_at=event.occurred_at,
        )
        with self.assertRaises(ValueError):
            self.repository.create(task, mismatched_version_event)

        self.assertIsNone(self.repository.get(task.task_id))

    def test_list_filters_orders_and_paginates(self) -> None:
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        first = self.manager.create_task(
            "first",
            session_id="session-1",
            at=base,
        )
        second = self.manager.create_task(
            "second",
            session_id="session-2",
            at=base + timedelta(seconds=1),
        )
        third = self.manager.create_task(
            "third",
            session_id="session-1",
            at=base + timedelta(seconds=2),
        )
        self.manager.transition_task(
            first.task_id,
            TaskStatus.PLANNING,
            at=base + timedelta(seconds=3),
        )

        all_tasks = self.repository.list()
        self.assertEqual(
            [task.task_id for task in all_tasks],
            [third.task_id, second.task_id, first.task_id],
        )

        planning = self.repository.list(status=TaskStatus.PLANNING)
        self.assertEqual([task.task_id for task in planning], [first.task_id])

        session_one = self.repository.list(session_id="session-1")
        self.assertEqual(
            [task.task_id for task in session_one],
            [third.task_id, first.task_id],
        )

        limited = self.repository.list(limit=1)
        self.assertEqual([task.task_id for task in limited], [third.task_id])

        offset = self.repository.list(limit=2, offset=1)
        self.assertEqual(
            [task.task_id for task in offset],
            [second.task_id, first.task_id],
        )

        with self.assertRaises(ValueError):
            self.repository.list(limit=0)
        with self.assertRaises(ValueError):
            self.repository.list(offset=-1)

    def test_metadata_and_error_round_trip(self) -> None:
        error = TaskError(
            code="tool_failure",
            message="tool failed",
            category=ErrorCategory.TOOL,
            recoverable=True,
            retryable=True,
            details={"tool": "read_data"},
        )
        task = self.manager.create_task(
            "will fail",
            metadata={"tenant": "demo", "nested": {"flag": True}},
        )
        self.manager.fail_task(task.task_id, error)

        restored = self.repository.get(task.task_id)

        self.assertIsNotNone(restored)
        self.assertEqual(restored.status, TaskStatus.FAILED)
        self.assertEqual(restored.error, error)
        self.assertEqual(
            restored.metadata,
            {"tenant": "demo", "nested": {"flag": True}},
        )
        self.assertIsNotNone(restored.completed_at)

        with self.session_factory() as session:
            raw = session.execute(
                text(
                    "SELECT status FROM agent_tasks "
                    "WHERE task_id = :task_id"
                ),
                {"task_id": task.task_id},
            ).scalar_one()
        self.assertEqual(raw, "failed")

    def test_stale_update_raises_and_does_not_add_event(self) -> None:
        task = self.manager.create_task("stale")
        first = self.manager.transition_task(
            task.task_id,
            TaskStatus.PLANNING,
        )
        stale = transition_to(
            first,
            TaskStatus.PLANNED,
            at=first.updated_at + timedelta(seconds=1),
        )
        event = TaskEvent(
            task_id=stale.task_id,
            task_version=stale.version,
            event_type=TaskEventType.TASK_TRANSITIONED,
            from_status=first.status,
            to_status=stale.status,
            occurred_at=stale.updated_at,
        )

        with self.assertRaises(ConcurrencyError) as context:
            self.repository.update_with_event(
                stale,
                event,
                expected_version=0,
            )

        self.assertEqual(context.exception.expected_version, 0)
        self.assertEqual(context.exception.actual_version, 1)
        current = self.repository.get(task.task_id)
        self.assertIsNotNone(current)
        self.assertEqual(current.status, TaskStatus.PLANNING)
        self.assertEqual(current.version, 1)
        self.assertEqual(len(self.repository.list_events(task.task_id)), 2)

    def test_update_missing_task_raises(self) -> None:
        task = make_task("missing", task_id="missing-task")
        event = make_created_event(task)

        with self.assertRaises(TaskNotFoundError):
            self.repository.update_with_event(
                task,
                event,
                expected_version=0,
            )

    def test_update_validates_event_reference(self) -> None:
        task = self.manager.create_task("validation")
        updated = self.manager.transition_task(
            task.task_id,
            TaskStatus.PLANNING,
        )
        event = TaskEvent(
            task_id="other-task",
            task_version=updated.version,
            event_type=TaskEventType.TASK_TRANSITIONED,
            from_status=task.status,
            to_status=updated.status,
            occurred_at=updated.updated_at,
        )

        with self.assertRaises(ValueError):
            self.repository.update_with_event(
                updated,
                event,
                expected_version=task.version,
            )

    def test_list_events_orders_by_sequence(self) -> None:
        task = self.manager.create_task("events")
        self.manager.transition_task(task.task_id, TaskStatus.PLANNING)
        self.manager.transition_task(task.task_id, TaskStatus.PLANNED)
        self.manager.pause_task(task.task_id)

        events = self.repository.list_events(task.task_id)

        self.assertEqual(
            [event.event_type for event in events],
            [
                TaskEventType.TASK_CREATED,
                TaskEventType.TASK_TRANSITIONED,
                TaskEventType.TASK_TRANSITIONED,
                TaskEventType.TASK_PAUSED,
            ],
        )
        self.assertEqual(
            [event.task_version for event in events],
            [0, 1, 2, 3],
        )
        self.assertEqual(self.repository.list_events("unknown"), [])

    def test_deleting_task_cascades_to_events(self) -> None:
        task = self.manager.create_task("cascade")
        self.manager.transition_task(task.task_id, TaskStatus.PLANNING)
        self.assertGreater(
            len(self.repository.list_events(task.task_id)),
            0,
        )

        with self.session_factory() as session:
            session.execute(
                delete(AgentTaskRecord).where(
                    AgentTaskRecord.task_id == task.task_id
                )
            )
            session.commit()

        self.assertIsNone(self.repository.get(task.task_id))
        self.assertEqual(self.repository.list_events(task.task_id), [])

    def test_failed_event_contains_error_payload(self) -> None:
        error = make_error()
        task = self.manager.create_task("failure event")
        self.manager.fail_task(task.task_id, error)

        events = self.repository.list_events(task.task_id)
        failed_event = events[-1]

        self.assertEqual(failed_event.event_type, TaskEventType.TASK_FAILED)
        self.assertEqual(failed_event.payload["error"]["code"], error.code)
        self.assertEqual(
            failed_event.payload["error"]["message"],
            error.message,
        )


if __name__ == "__main__":
    unittest.main()
