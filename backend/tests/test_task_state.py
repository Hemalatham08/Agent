import unittest
from datetime import datetime, timedelta

from backend.agent.models import (
    PAUSABLE_STATUSES,
    TERMINAL_STATUSES,
    AgentTask,
    TaskError,
    TaskStatus,
    utc_now,
)
from backend.agent.runtime.state import (
    ALLOWED_TRANSITIONS,
    TransitionError,
    cancel,
    complete,
    fail,
    pause,
    resume,
    transition_to,
    validate_transition,
)


def make_error() -> TaskError:
    return TaskError(code="test_error", message="something failed")


def make_task(
    status: TaskStatus,
    *,
    paused_from: TaskStatus | None = None,
    error: TaskError | None = None,
) -> AgentTask:
    values: dict[str, object] = {
        "goal": "test goal",
        "status": status,
    }

    if paused_from is not None:
        values["paused_from"] = paused_from
    if error is not None:
        values["error"] = error

    if status in {TaskStatus.EXECUTING, TaskStatus.WAITING_APPROVAL, TaskStatus.VERIFYING}:
        values["started_at"] = utc_now()

    if status is TaskStatus.COMPLETED:
        values["completed_at"] = utc_now()

    if status in {TaskStatus.FAILED, TaskStatus.CANCELLED}:
        values["completed_at"] = utc_now()

    return AgentTask(**values)


def make_valid_task(status: TaskStatus) -> AgentTask:
    if status is TaskStatus.PAUSED:
        return make_task(status, paused_from=TaskStatus.PLANNED)
    if status is TaskStatus.FAILED:
        return make_task(status, error=make_error())
    return make_task(status)


class TransitionMapTests(unittest.TestCase):
    def test_map_covers_every_status(self) -> None:
        self.assertEqual(set(ALLOWED_TRANSITIONS), set(TaskStatus))

    def test_terminal_states_have_no_outgoing_transitions(self) -> None:
        for status in TERMINAL_STATUSES:
            self.assertEqual(ALLOWED_TRANSITIONS[status], frozenset())

    def test_map_contains_no_self_transitions(self) -> None:
        for from_status, targets in ALLOWED_TRANSITIONS.items():
            self.assertNotIn(from_status, targets)

    def test_terminal_states_are_never_sources(self) -> None:
        for status in TERMINAL_STATUSES:
            self.assertNotIn(status, ALLOWED_TRANSITIONS[status])

    def test_pausable_statuses_are_non_terminal(self) -> None:
        self.assertTrue(PAUSABLE_STATUSES.isdisjoint(TERMINAL_STATUSES))


class AllowedTransitionTests(unittest.TestCase):
    def test_every_mapped_transition_succeeds(self) -> None:
        for from_status, targets in ALLOWED_TRANSITIONS.items():
            for to_status in targets:
                with self.subTest(
                    from_status=from_status.value,
                    to_status=to_status.value,
                ):
                    paused_from = None
                    if from_status is TaskStatus.PAUSED:
                        paused_from = (
                            to_status
                            if to_status in PAUSABLE_STATUSES
                            else TaskStatus.PLANNED
                        )

                    task = make_task(from_status, paused_from=paused_from)
                    error = make_error() if to_status is TaskStatus.FAILED else None
                    at = task.updated_at + timedelta(seconds=1)

                    updated = transition_to(
                        task,
                        to_status,
                        at=at,
                        error=error,
                    )

                    self.assertEqual(updated.status, to_status)
                    self.assertEqual(updated.version, task.version + 1)
                    self.assertEqual(updated.updated_at, at)

                    if to_status in TERMINAL_STATUSES:
                        self.assertEqual(updated.completed_at, at)
                    else:
                        self.assertIsNone(updated.completed_at)

                    if to_status is TaskStatus.PAUSED:
                        self.assertEqual(updated.paused_from, from_status)
                    elif to_status in TERMINAL_STATUSES:
                        self.assertIsNone(updated.paused_from)
                    elif from_status is TaskStatus.PAUSED:
                        self.assertIsNone(updated.paused_from)

                    if to_status is TaskStatus.EXECUTING:
                        self.assertIsNotNone(updated.started_at)

                    if to_status is TaskStatus.FAILED:
                        self.assertEqual(updated.error, error)
                    else:
                        self.assertIsNone(updated.error)

                    self.assertEqual(task.status, from_status)
                    self.assertEqual(task.version, 0)
                    self.assertGreaterEqual(task.updated_at, task.created_at)


class ForbiddenTransitionTests(unittest.TestCase):
    def test_every_unmapped_transition_fails(self) -> None:
        for from_status in TaskStatus:
            for to_status in TaskStatus:
                if to_status in ALLOWED_TRANSITIONS[from_status]:
                    continue

                with self.subTest(
                    from_status=from_status.value,
                    to_status=to_status.value,
                ):
                    task = make_valid_task(from_status)
                    error = make_error() if to_status is TaskStatus.FAILED else None

                    with self.assertRaises(TransitionError):
                        transition_to(
                            task,
                            to_status,
                            at=task.updated_at + timedelta(seconds=1),
                            error=error,
                        )

    def test_failed_transition_does_not_mutate_original(self) -> None:
        task = make_task(TaskStatus.CREATED)
        with self.assertRaises(TransitionError):
            transition_to(
                task,
                TaskStatus.COMPLETED,
                at=task.updated_at + timedelta(seconds=1),
            )
        self.assertEqual(task.status, TaskStatus.CREATED)
        self.assertEqual(task.version, 0)

    def test_paused_task_rejects_wrong_resume_target(self) -> None:
        for source in PAUSABLE_STATUSES:
            for target in PAUSABLE_STATUSES:
                if source is target:
                    continue
                with self.subTest(source=source.value, target=target.value):
                    task = make_task(TaskStatus.PAUSED, paused_from=source)
                    with self.assertRaises(TransitionError):
                        transition_to(
                            task,
                            target,
                            at=task.updated_at + timedelta(seconds=1),
                        )


class TerminalStateTests(unittest.TestCase):
    def test_terminal_states_reject_every_operation(self) -> None:
        for status in TERMINAL_STATUSES:
            task = make_valid_task(status)
            at = task.updated_at + timedelta(seconds=1)

            with self.subTest(status=status.value, operation="transition"):
                for target in TaskStatus:
                    with self.assertRaises(TransitionError):
                        transition_to(
                            task,
                            target,
                            at=at,
                            error=make_error() if target is TaskStatus.FAILED else None,
                        )

            with self.subTest(status=status.value, operation="pause"):
                with self.assertRaises(TransitionError):
                    pause(task, at=at)

            with self.subTest(status=status.value, operation="resume"):
                with self.assertRaises(TransitionError):
                    resume(task, at=at)

            with self.subTest(status=status.value, operation="cancel"):
                with self.assertRaises(TransitionError):
                    cancel(task, at=at)

            with self.subTest(status=status.value, operation="fail"):
                with self.assertRaises(TransitionError):
                    fail(task, make_error(), at=at)

            with self.subTest(status=status.value, operation="complete"):
                with self.assertRaises(TransitionError):
                    complete(task, at=at)


class PauseResumeTests(unittest.TestCase):
    def test_pause_and_resume_round_trip(self) -> None:
        for status in PAUSABLE_STATUSES:
            with self.subTest(status=status.value):
                task = make_task(status)
                paused_at = task.updated_at + timedelta(seconds=1)
                paused = pause(task, at=paused_at)

                self.assertEqual(paused.status, TaskStatus.PAUSED)
                self.assertEqual(paused.paused_from, status)
                self.assertIsNone(paused.completed_at)
                self.assertEqual(paused.version, task.version + 1)

                resumed_at = paused_at + timedelta(seconds=1)
                resumed = resume(paused, at=resumed_at)

                self.assertEqual(resumed.status, status)
                self.assertIsNone(resumed.paused_from)
                self.assertIsNone(resumed.completed_at)
                self.assertEqual(resumed.version, paused.version + 1)
                self.assertEqual(task.status, status)

    def test_pause_is_rejected_from_non_pausable_states(self) -> None:
        for status in TaskStatus:
            if status in PAUSABLE_STATUSES:
                continue
            with self.subTest(status=status.value):
                task = make_valid_task(status)
                with self.assertRaises(TransitionError):
                    pause(task, at=task.updated_at + timedelta(seconds=1))

    def test_resume_is_rejected_from_non_paused_states(self) -> None:
        for status in TaskStatus:
            if status is TaskStatus.PAUSED:
                continue
            with self.subTest(status=status.value):
                task = make_valid_task(status)
                with self.assertRaises(TransitionError):
                    resume(task, at=task.updated_at + timedelta(seconds=1))

    def test_resume_rejects_missing_paused_from(self) -> None:
        now = utc_now()
        task = AgentTask.model_construct(
            task_id="task-1",
            session_id=None,
            goal="test goal",
            status=TaskStatus.PAUSED,
            created_at=now,
            updated_at=now,
            started_at=None,
            completed_at=None,
            paused_from=None,
            iteration_count=0,
            tool_call_count=0,
            error=None,
            version=0,
            metadata={},
        )

        with self.assertRaises(TransitionError):
            resume(task, at=now + timedelta(seconds=1))

    def test_resume_rejects_invalid_paused_from(self) -> None:
        invalid_sources = (
            TaskStatus.CREATED,
            TaskStatus.PLANNING,
            TaskStatus.PAUSED,
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        )

        for source in invalid_sources:
            now = utc_now()
            task = AgentTask.model_construct(
                task_id="task-1",
                session_id=None,
                goal="test goal",
                status=TaskStatus.PAUSED,
                created_at=now,
                updated_at=now,
                started_at=None,
                completed_at=None,
                paused_from=source,
                iteration_count=0,
                tool_call_count=0,
                error=None,
                version=0,
                metadata={},
            )

            with self.subTest(source=source.value):
                with self.assertRaises(TransitionError):
                    resume(task, at=now + timedelta(seconds=1))


class CompletionTests(unittest.TestCase):
    def test_completion_from_verifying(self) -> None:
        task = make_task(TaskStatus.VERIFYING)
        at = task.updated_at + timedelta(seconds=1)
        completed = complete(task, at=at)

        self.assertEqual(completed.status, TaskStatus.COMPLETED)
        self.assertEqual(completed.completed_at, at)
        self.assertEqual(completed.version, task.version + 1)
        self.assertIsNone(completed.error)

    def test_completion_requires_verifying(self) -> None:
        for status in TaskStatus:
            if status is TaskStatus.VERIFYING:
                continue
            with self.subTest(status=status.value):
                task = make_valid_task(status)
                with self.assertRaises(TransitionError):
                    complete(task, at=task.updated_at + timedelta(seconds=1))

    def test_completion_rejects_naive_timestamp(self) -> None:
        task = make_task(TaskStatus.VERIFYING)
        with self.assertRaises(TransitionError):
            complete(task, at=datetime.now())

    def test_completion_rejects_backwards_timestamp(self) -> None:
        task = make_task(TaskStatus.VERIFYING)
        with self.assertRaises(TransitionError):
            complete(task, at=task.updated_at - timedelta(seconds=1))

    def test_completion_rejects_non_datetime_timestamp(self) -> None:
        task = make_task(TaskStatus.VERIFYING)
        with self.assertRaises(TransitionError):
            complete(task, at="2026-01-01T00:00:00+00:00")  # type: ignore[arg-type]

    def test_completion_defaults_to_current_timestamp(self) -> None:
        task = make_task(TaskStatus.VERIFYING)
        completed = complete(task)
        self.assertIsNotNone(completed.completed_at)
        self.assertIsNotNone(completed.completed_at.tzinfo)


class FailureTests(unittest.TestCase):
    def test_failure_requires_task_error(self) -> None:
        task = make_task(TaskStatus.EXECUTING)

        with self.assertRaises(TransitionError):
            fail(task, None)  # type: ignore[arg-type]

        with self.assertRaises(TransitionError):
            fail(task, "error")  # type: ignore[arg-type]

        with self.assertRaises(TransitionError):
            transition_to(
                task,
                TaskStatus.FAILED,
                at=task.updated_at + timedelta(seconds=1),
            )

        with self.assertRaises(TransitionError):
            transition_to(
                task,
                TaskStatus.FAILED,
                at=task.updated_at + timedelta(seconds=1),
                error="error",  # type: ignore[arg-type]
            )

    def test_failure_from_each_non_terminal_state(self) -> None:
        for status in TaskStatus:
            if status in TERMINAL_STATUSES:
                continue
            with self.subTest(status=status.value):
                task = make_valid_task(status)
                error = make_error()
                at = task.updated_at + timedelta(seconds=1)
                failed = fail(task, error, at=at)

                self.assertEqual(failed.status, TaskStatus.FAILED)
                self.assertEqual(failed.error, error)
                self.assertEqual(failed.completed_at, at)
                self.assertIsNone(failed.paused_from)
                self.assertEqual(failed.version, task.version + 1)

    def test_failure_is_rejected_from_terminal_states(self) -> None:
        for status in TERMINAL_STATUSES:
            with self.subTest(status=status.value):
                task = make_valid_task(status)
                with self.assertRaises(TransitionError):
                    fail(
                        task,
                        make_error(),
                        at=task.updated_at + timedelta(seconds=1),
                    )


class CancellationTests(unittest.TestCase):
    def test_cancellation_from_each_non_terminal_state(self) -> None:
        for status in TaskStatus:
            if status in TERMINAL_STATUSES:
                continue
            with self.subTest(status=status.value):
                task = make_valid_task(status)
                at = task.updated_at + timedelta(seconds=1)
                cancelled = cancel(task, at=at)

                self.assertEqual(cancelled.status, TaskStatus.CANCELLED)
                self.assertEqual(cancelled.completed_at, at)
                self.assertIsNone(cancelled.paused_from)
                self.assertEqual(cancelled.version, task.version + 1)

    def test_cancellation_is_rejected_from_terminal_states(self) -> None:
        for status in TERMINAL_STATUSES:
            with self.subTest(status=status.value):
                task = make_valid_task(status)
                with self.assertRaises(TransitionError):
                    cancel(task, at=task.updated_at + timedelta(seconds=1))


class TimestampAndTypingTests(unittest.TestCase):
    def test_transition_rejects_naive_timestamp(self) -> None:
        task = make_task(TaskStatus.CREATED)
        with self.assertRaises(TransitionError):
            transition_to(task, TaskStatus.PLANNING, at=datetime.now())

    def test_transition_rejects_backwards_timestamp(self) -> None:
        task = make_task(TaskStatus.CREATED)
        with self.assertRaises(TransitionError):
            transition_to(
                task,
                TaskStatus.PLANNING,
                at=task.updated_at - timedelta(seconds=1),
            )

    def test_transition_rejects_non_datetime_timestamp(self) -> None:
        task = make_task(TaskStatus.CREATED)
        with self.assertRaises(TransitionError):
            transition_to(
                task,
                TaskStatus.PLANNING,
                at="2026-01-01T00:00:00+00:00",  # type: ignore[arg-type]
            )

    def test_validate_transition_rejects_non_status_values(self) -> None:
        with self.assertRaises(TransitionError):
            validate_transition("created", TaskStatus.PLANNING)  # type: ignore[arg-type]
        with self.assertRaises(TransitionError):
            validate_transition(TaskStatus.CREATED, "planning")  # type: ignore[arg-type]

    def test_transition_requires_agent_task(self) -> None:
        with self.assertRaises(TransitionError):
            transition_to("not-a-task", TaskStatus.PLANNING)  # type: ignore[arg-type]

    def test_transition_error_exposes_statuses(self) -> None:
        task = make_task(TaskStatus.CREATED)
        with self.assertRaises(TransitionError) as context:
            transition_to(
                task,
                TaskStatus.COMPLETED,
                at=task.updated_at + timedelta(seconds=1),
            )

        self.assertEqual(context.exception.from_status, TaskStatus.CREATED)
        self.assertEqual(context.exception.to_status, TaskStatus.COMPLETED)


if __name__ == "__main__":
    unittest.main()
