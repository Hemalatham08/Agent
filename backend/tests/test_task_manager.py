import unittest
from datetime import datetime, timedelta, timezone

from pydantic import ValidationError

from backend.agent.errors import ConcurrencyError, TaskNotFoundError
from backend.agent.events import TaskEvent, TaskEventType
from backend.agent.models import TaskStatus
from backend.agent.runtime.state import TransitionError
from backend.tests.support import (
    PersistenceTestCase,
    make_error,
)


class TaskManagerTests(PersistenceTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.base = datetime(2026, 1, 2, tzinfo=timezone.utc)

    def test_create_task_defaults_and_event(self) -> None:
        task = self.manager.create_task("new goal", at=self.base)

        self.assertEqual(task.status, TaskStatus.CREATED)
        self.assertEqual(task.version, 0)
        self.assertEqual(task.metadata, {})
        self.assertIsNone(task.session_id)
        self.assertEqual(task.created_at, self.base)
        self.assertEqual(task.updated_at, self.base)

        events = self.manager.list_events(task.task_id)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, TaskEventType.TASK_CREATED)
        self.assertIsNone(events[0].from_status)
        self.assertEqual(events[0].to_status, TaskStatus.CREATED)
        self.assertEqual(events[0].task_version, 0)

    def test_full_lifecycle(self) -> None:
        task = self.manager.create_task("full lifecycle", at=self.base)
        statuses = [
            TaskStatus.PLANNING,
            TaskStatus.PLANNED,
            TaskStatus.EXECUTING,
            TaskStatus.WAITING_APPROVAL,
            TaskStatus.EXECUTING,
            TaskStatus.VERIFYING,
            TaskStatus.COMPLETED,
        ]

        current = task
        for index, status in enumerate(statuses, start=1):
            current = self.manager.transition_task(
                task.task_id,
                status,
                at=self.base + timedelta(seconds=index),
            )
            self.assertEqual(current.status, status)
            self.assertEqual(current.version, index)

        self.assertEqual(
            current.started_at,
            self.base + timedelta(seconds=3),
        )
        self.assertEqual(
            current.completed_at,
            self.base + timedelta(seconds=7),
        )

        events = self.manager.list_events(task.task_id)
        self.assertEqual(
            [event.event_type for event in events],
            [
                TaskEventType.TASK_CREATED,
                TaskEventType.TASK_TRANSITIONED,
                TaskEventType.TASK_TRANSITIONED,
                TaskEventType.TASK_TRANSITIONED,
                TaskEventType.TASK_TRANSITIONED,
                TaskEventType.TASK_TRANSITIONED,
                TaskEventType.TASK_TRANSITIONED,
                TaskEventType.TASK_COMPLETED,
            ],
        )
        self.assertEqual(
            [event.to_status for event in events],
            [TaskStatus.CREATED, *statuses],
        )
        self.assertEqual(
            [event.task_version for event in events],
            list(range(8)),
        )

    def test_pause_and_resume_restore_exact_status(self) -> None:
        task = self.manager.create_task("pause", at=self.base)
        self.manager.transition_task(
            task.task_id,
            TaskStatus.PLANNING,
            at=self.base + timedelta(seconds=1),
        )
        self.manager.transition_task(
            task.task_id,
            TaskStatus.PLANNED,
            at=self.base + timedelta(seconds=2),
        )

        paused = self.manager.pause_task(
            task.task_id,
            at=self.base + timedelta(seconds=3),
        )
        self.assertEqual(paused.status, TaskStatus.PAUSED)
        self.assertEqual(paused.paused_from, TaskStatus.PLANNED)

        resumed = self.manager.resume_task(
            task.task_id,
            at=self.base + timedelta(seconds=4),
        )
        self.assertEqual(resumed.status, TaskStatus.PLANNED)
        self.assertIsNone(resumed.paused_from)

        event_types = [
            event.event_type
            for event in self.manager.list_events(task.task_id)
        ]
        self.assertEqual(
            event_types,
            [
                TaskEventType.TASK_CREATED,
                TaskEventType.TASK_TRANSITIONED,
                TaskEventType.TASK_TRANSITIONED,
                TaskEventType.TASK_PAUSED,
                TaskEventType.TASK_RESUMED,
            ],
        )

    def test_pause_from_created_is_rejected(self) -> None:
        task = self.manager.create_task("cannot pause", at=self.base)

        with self.assertRaises(TransitionError):
            self.manager.pause_task(task.task_id)

        current = self.manager.get_task(task.task_id)
        self.assertEqual(current.status, TaskStatus.CREATED)
        self.assertEqual(current.version, 0)
        self.assertEqual(len(self.manager.list_events(task.task_id)), 1)

    def test_resume_non_paused_task_is_rejected(self) -> None:
        task = self.manager.create_task("not paused", at=self.base)
        self.manager.transition_task(
            task.task_id,
            TaskStatus.PLANNING,
            at=self.base + timedelta(seconds=1),
        )

        with self.assertRaises(TransitionError):
            self.manager.resume_task(task.task_id)

        current = self.manager.get_task(task.task_id)
        self.assertEqual(current.status, TaskStatus.PLANNING)
        self.assertEqual(current.version, 1)

    def test_fail_task_requires_and_persists_error(self) -> None:
        error = make_error()
        task = self.manager.create_task("failure", at=self.base)

        failed = self.manager.fail_task(
            task.task_id,
            error,
            at=self.base + timedelta(seconds=1),
        )

        self.assertEqual(failed.status, TaskStatus.FAILED)
        self.assertEqual(failed.error, error)
        self.assertEqual(failed.version, 1)
        self.assertEqual(
            failed.completed_at,
            self.base + timedelta(seconds=1),
        )
        event = self.manager.list_events(task.task_id)[-1]
        self.assertEqual(event.event_type, TaskEventType.TASK_FAILED)
        self.assertEqual(event.payload["error"]["code"], error.code)

    def test_transition_to_failed_without_error_is_rejected(self) -> None:
        task = self.manager.create_task("failure", at=self.base)

        with self.assertRaises(TransitionError):
            self.manager.transition_task(
                task.task_id,
                TaskStatus.FAILED,
                at=self.base + timedelta(seconds=1),
            )

        current = self.manager.get_task(task.task_id)
        self.assertEqual(current.status, TaskStatus.CREATED)
        self.assertEqual(current.version, 0)
        self.assertEqual(len(self.manager.list_events(task.task_id)), 1)

    def test_complete_only_from_verifying(self) -> None:
        task = self.manager.create_task("incomplete", at=self.base)
        self.manager.transition_task(
            task.task_id,
            TaskStatus.PLANNING,
            at=self.base + timedelta(seconds=1),
        )

        with self.assertRaises(TransitionError):
            self.manager.complete_task(task.task_id)

        current = self.manager.get_task(task.task_id)
        self.assertEqual(current.status, TaskStatus.PLANNING)
        self.assertEqual(current.version, 1)

    def test_cancel_task_and_terminal_rejection(self) -> None:
        task = self.manager.create_task("cancel", at=self.base)

        cancelled = self.manager.cancel_task(
            task.task_id,
            at=self.base + timedelta(seconds=1),
        )
        self.assertEqual(cancelled.status, TaskStatus.CANCELLED)
        self.assertEqual(cancelled.version, 1)
        self.assertIsNotNone(cancelled.completed_at)
        self.assertEqual(
            self.manager.list_events(task.task_id)[-1].event_type,
            TaskEventType.TASK_CANCELLED,
        )

        with self.assertRaises(TransitionError):
            self.manager.cancel_task(task.task_id)

        current = self.manager.get_task(task.task_id)
        self.assertEqual(current.status, TaskStatus.CANCELLED)
        self.assertEqual(current.version, 1)

    def test_expected_version_mismatch_is_rejected(self) -> None:
        task = self.manager.create_task("versioned", at=self.base)
        current = self.manager.transition_task(
            task.task_id,
            TaskStatus.PLANNING,
            at=self.base + timedelta(seconds=1),
        )
        self.assertEqual(current.version, 1)

        with self.assertRaises(ConcurrencyError) as context:
            self.manager.transition_task(
                task.task_id,
                TaskStatus.PLANNED,
                expected_version=0,
                at=self.base + timedelta(seconds=2),
            )

        self.assertEqual(context.exception.expected_version, 0)
        self.assertEqual(context.exception.actual_version, 1)
        current = self.manager.get_task(task.task_id)
        self.assertEqual(current.status, TaskStatus.PLANNING)
        self.assertEqual(current.version, 1)
        self.assertEqual(len(self.manager.list_events(task.task_id)), 2)

    def test_missing_task_operations_raise_not_found(self) -> None:
        operations = {
            "get": lambda: self.manager.get_task("missing"),
            "transition": lambda: self.manager.transition_task(
                "missing",
                TaskStatus.PLANNING,
            ),
            "pause": lambda: self.manager.pause_task("missing"),
            "resume": lambda: self.manager.resume_task("missing"),
            "fail": lambda: self.manager.fail_task("missing", make_error()),
            "complete": lambda: self.manager.complete_task("missing"),
            "cancel": lambda: self.manager.cancel_task("missing"),
            "events": lambda: self.manager.list_events("missing"),
        }

        for name, operation in operations.items():
            with self.subTest(operation=name):
                with self.assertRaises(TaskNotFoundError):
                    operation()

    def test_list_tasks_uses_repository_filters(self) -> None:
        first = self.manager.create_task(
            "first",
            session_id="session-1",
            at=self.base,
        )
        self.manager.create_task(
            "second",
            session_id="session-2",
            at=self.base + timedelta(seconds=1),
        )
        self.manager.transition_task(
            first.task_id,
            TaskStatus.PLANNING,
            at=self.base + timedelta(seconds=2),
        )

        planning = self.manager.list_tasks(status=TaskStatus.PLANNING)
        session_two = self.manager.list_tasks(session_id="session-2")

        self.assertEqual([task.task_id for task in planning], [first.task_id])
        self.assertEqual(len(session_two), 1)
        self.assertEqual(session_two[0].goal, "second")


class TaskEventValidationTests(unittest.TestCase):
    def test_created_event_requires_created_target(self) -> None:
        with self.assertRaises(ValidationError):
            TaskEvent(
                task_id="task",
                task_version=0,
                event_type=TaskEventType.TASK_CREATED,
                from_status=TaskStatus.PLANNING,
                to_status=TaskStatus.CREATED,
            )

        with self.assertRaises(ValidationError):
            TaskEvent(
                task_id="task",
                task_version=0,
                event_type=TaskEventType.TASK_CREATED,
                from_status=None,
                to_status=TaskStatus.PLANNING,
            )

    def test_transitioned_event_rejects_dedicated_targets(self) -> None:
        for target in (
            TaskStatus.PAUSED,
            TaskStatus.FAILED,
            TaskStatus.COMPLETED,
            TaskStatus.CANCELLED,
        ):
            with self.subTest(target=target):
                with self.assertRaises(ValidationError):
                    TaskEvent(
                        task_id="task",
                        task_version=1,
                        event_type=TaskEventType.TASK_TRANSITIONED,
                        from_status=TaskStatus.CREATED,
                        to_status=target,
                    )

    def test_resumed_event_requires_paused_source(self) -> None:
        with self.assertRaises(ValidationError):
            TaskEvent(
                task_id="task",
                task_version=1,
                event_type=TaskEventType.TASK_RESUMED,
                from_status=TaskStatus.PLANNING,
                to_status=TaskStatus.PLANNED,
            )


if __name__ == "__main__":
    unittest.main()
