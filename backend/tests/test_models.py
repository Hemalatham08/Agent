import unittest
from datetime import timedelta

from pydantic import ValidationError

from backend.agent.models import (
    Action,
    ActionType,
    AgentTask,
    ErrorCategory,
    TaskError,
    TaskStatus,
    ToolResult,
    VerificationResult,
    VerificationStatus,
    utc_now,
)
from backend.agent.runtime.context import AgentState, ExecutionContext


def make_error() -> TaskError:
    return TaskError(code="test_error", message="something failed")


class TaskErrorTests(unittest.TestCase):
    def test_valid_error(self) -> None:
        error = make_error()
        self.assertEqual(error.category, ErrorCategory.INTERNAL)
        self.assertFalse(error.recoverable)
        self.assertFalse(error.retryable)
        self.assertEqual(error.details, {})

    def test_blank_code_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            TaskError(code="   ", message="message")

    def test_blank_message_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            TaskError(code="code", message="   ")

    def test_extra_field_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            TaskError(code="code", message="message", unexpected=True)


class ActionTests(unittest.TestCase):
    def test_valid_action(self) -> None:
        action = Action(tool_name="read_data")
        self.assertTrue(action.action_id)
        self.assertEqual(action.action_type, ActionType.READ)
        self.assertEqual(action.arguments, {})
        self.assertFalse(action.requires_approval)

    def test_blank_tool_name_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            Action(tool_name="   ")

    def test_extra_field_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            Action(tool_name="read_data", unexpected=True)


class ToolResultTests(unittest.TestCase):
    def test_successful_result(self) -> None:
        now = utc_now()
        result = ToolResult(
            tool_name="read_data",
            success=True,
            output={"rows": 2},
            started_at=now,
            finished_at=now + timedelta(milliseconds=5),
            duration_ms=5.0,
        )
        self.assertTrue(result.success)
        self.assertIsNone(result.error)

    def test_failed_result_requires_error(self) -> None:
        with self.assertRaises(ValidationError):
            ToolResult(tool_name="read_data", success=False)

    def test_successful_result_rejects_error(self) -> None:
        with self.assertRaises(ValidationError):
            ToolResult(
                tool_name="read_data",
                success=True,
                error=make_error(),
            )

    def test_finished_at_must_not_precede_started_at(self) -> None:
        now = utc_now()
        with self.assertRaises(ValidationError):
            ToolResult(
                tool_name="read_data",
                success=False,
                error=make_error(),
                started_at=now,
                finished_at=now - timedelta(milliseconds=1),
            )

    def test_negative_duration_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            ToolResult(
                tool_name="read_data",
                success=True,
                duration_ms=-1,
            )


class VerificationResultTests(unittest.TestCase):
    def test_passed_verification(self) -> None:
        result = VerificationResult(
            status=VerificationStatus.PASSED,
            passed=True,
            message="verified",
        )
        self.assertTrue(result.passed)

    def test_passed_status_requires_passed_flag(self) -> None:
        with self.assertRaises(ValidationError):
            VerificationResult(
                status=VerificationStatus.PASSED,
                passed=False,
                message="verified",
            )

    def test_failed_status_rejects_passed_flag(self) -> None:
        with self.assertRaises(ValidationError):
            VerificationResult(
                status=VerificationStatus.FAILED,
                passed=True,
                message="failed",
            )

    def test_uncertain_status_rejects_passed_flag(self) -> None:
        with self.assertRaises(ValidationError):
            VerificationResult(
                status=VerificationStatus.UNCERTAIN,
                passed=True,
                message="uncertain",
            )

    def test_uncertain_status(self) -> None:
        result = VerificationResult(
            status=VerificationStatus.UNCERTAIN,
            passed=False,
            message="uncertain",
        )
        self.assertFalse(result.passed)

    def test_blank_message_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            VerificationResult(
                status=VerificationStatus.PASSED,
                passed=True,
                message="   ",
            )


class AgentTaskTests(unittest.TestCase):
    def test_defaults(self) -> None:
        task = AgentTask(goal="test goal")
        self.assertTrue(task.task_id)
        self.assertEqual(task.status, TaskStatus.CREATED)
        self.assertEqual(task.version, 0)
        self.assertEqual(task.iteration_count, 0)
        self.assertEqual(task.tool_call_count, 0)
        self.assertIsNone(task.started_at)
        self.assertIsNone(task.completed_at)
        self.assertIsNone(task.paused_from)
        self.assertIsNone(task.error)
        self.assertGreaterEqual(task.updated_at, task.created_at)

    def test_blank_goal_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            AgentTask(goal="   ")

    def test_extra_field_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            AgentTask(goal="test goal", unexpected=True)

    def test_task_is_frozen(self) -> None:
        task = AgentTask(goal="test goal")
        with self.assertRaises(ValidationError):
            task.status = TaskStatus.PLANNING

    def test_completed_requires_completed_at(self) -> None:
        with self.assertRaises(ValidationError):
            AgentTask(goal="test goal", status=TaskStatus.COMPLETED)

    def test_completed_rejects_error(self) -> None:
        with self.assertRaises(ValidationError):
            AgentTask(
                goal="test goal",
                status=TaskStatus.COMPLETED,
                completed_at=utc_now(),
                error=make_error(),
            )

    def test_failed_requires_error(self) -> None:
        with self.assertRaises(ValidationError):
            AgentTask(goal="test goal", status=TaskStatus.FAILED)

    def test_failed_with_error(self) -> None:
        task = AgentTask(
            goal="test goal",
            status=TaskStatus.FAILED,
            error=make_error(),
        )
        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertIsNotNone(task.error)

    def test_non_failed_task_rejects_error(self) -> None:
        with self.assertRaises(ValidationError):
            AgentTask(goal="test goal", error=make_error())

    def test_paused_requires_paused_from(self) -> None:
        with self.assertRaises(ValidationError):
            AgentTask(goal="test goal", status=TaskStatus.PAUSED)

    def test_paused_rejects_invalid_paused_from(self) -> None:
        for source in (
            TaskStatus.CREATED,
            TaskStatus.PAUSED,
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        ):
            with self.subTest(source=source.value):
                with self.assertRaises(ValidationError):
                    AgentTask(
                        goal="test goal",
                        status=TaskStatus.PAUSED,
                        paused_from=source,
                    )

    def test_paused_with_valid_paused_from(self) -> None:
        task = AgentTask(
            goal="test goal",
            status=TaskStatus.PAUSED,
            paused_from=TaskStatus.EXECUTING,
        )
        self.assertEqual(task.paused_from, TaskStatus.EXECUTING)

    def test_non_paused_task_rejects_paused_from(self) -> None:
        with self.assertRaises(ValidationError):
            AgentTask(
                goal="test goal",
                paused_from=TaskStatus.PLANNED,
            )

    def test_non_terminal_task_rejects_completed_at(self) -> None:
        with self.assertRaises(ValidationError):
            AgentTask(
                goal="test goal",
                completed_at=utc_now(),
            )

    def test_updated_at_must_not_precede_created_at(self) -> None:
        now = utc_now()
        with self.assertRaises(ValidationError):
            AgentTask(
                goal="test goal",
                created_at=now,
                updated_at=now - timedelta(seconds=1),
            )

    def test_negative_counters_are_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            AgentTask(goal="test goal", iteration_count=-1)
        with self.assertRaises(ValidationError):
            AgentTask(goal="test goal", tool_call_count=-1)

    def test_cancelled_task_is_valid(self) -> None:
        task = AgentTask(goal="test goal", status=TaskStatus.CANCELLED)
        self.assertEqual(task.status, TaskStatus.CANCELLED)


class AgentStateTests(unittest.TestCase):
    def test_valid_state(self) -> None:
        state = AgentState(task_id="task-1")
        self.assertEqual(state.status, TaskStatus.CREATED)
        self.assertEqual(state.observations, [])
        self.assertEqual(state.pending_actions, [])
        self.assertIsNone(state.current_action)

    def test_blank_task_id_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            AgentState(task_id="   ")

    def test_extra_field_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            AgentState(task_id="task-1", unexpected=True)

    def test_invalid_nested_observation_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            AgentState(
                task_id="task-1",
                observations=[{"tool_name": "read_data", "success": False}],
            )


class ExecutionContextTests(unittest.TestCase):
    def test_valid_context(self) -> None:
        now = utc_now()
        context = ExecutionContext(
            task_id="task-1",
            max_iterations=5,
            max_tool_calls=20,
            started_at=now,
            deadline=now + timedelta(hours=1),
        )
        self.assertEqual(context.attempt, 1)
        self.assertGreater(context.deadline, context.started_at)

    def test_limits_are_required(self) -> None:
        with self.assertRaises(ValidationError):
            ExecutionContext(task_id="task-1", max_tool_calls=20)
        with self.assertRaises(ValidationError):
            ExecutionContext(task_id="task-1", max_iterations=5)

    def test_limits_must_be_positive(self) -> None:
        with self.assertRaises(ValidationError):
            ExecutionContext(
                task_id="task-1",
                max_iterations=0,
                max_tool_calls=20,
            )
        with self.assertRaises(ValidationError):
            ExecutionContext(
                task_id="task-1",
                max_iterations=5,
                max_tool_calls=0,
            )

    def test_deadline_must_not_precede_started_at(self) -> None:
        now = utc_now()
        with self.assertRaises(ValidationError):
            ExecutionContext(
                task_id="task-1",
                max_iterations=5,
                max_tool_calls=20,
                started_at=now,
                deadline=now - timedelta(seconds=1),
            )

    def test_attempt_must_be_positive(self) -> None:
        with self.assertRaises(ValidationError):
            ExecutionContext(
                task_id="task-1",
                attempt=0,
                max_iterations=5,
                max_tool_calls=20,
            )


if __name__ == "__main__":
    unittest.main()
