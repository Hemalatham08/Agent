import json
import unittest
from datetime import timedelta

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


class ModelSerializationTests(unittest.TestCase):
    def test_created_task_json_round_trip(self) -> None:
        task = AgentTask(goal="test goal")
        payload = task.model_dump_json()
        restored = AgentTask.model_validate_json(payload)

        self.assertEqual(restored.model_dump(), task.model_dump())

        raw = json.loads(payload)
        self.assertEqual(raw["status"], "created")
        self.assertTrue(
            raw["created_at"].endswith("Z")
            or raw["created_at"].endswith("+00:00")
        )

    def test_completed_task_json_round_trip(self) -> None:
        task = AgentTask(
            goal="finished",
            status=TaskStatus.COMPLETED,
            completed_at=utc_now(),
        )
        restored = AgentTask.model_validate_json(task.model_dump_json())

        self.assertEqual(restored.model_dump(), task.model_dump())
        self.assertEqual(
            json.loads(task.model_dump_json())["status"],
            "completed",
        )

    def test_failed_task_json_round_trip(self) -> None:
        error = TaskError(
            code="tool_failure",
            message="tool failed",
            category=ErrorCategory.TOOL,
            details={"tool": "read_data"},
        )
        task = AgentTask(
            goal="failed",
            status=TaskStatus.FAILED,
            error=error,
            completed_at=utc_now(),
        )
        restored = AgentTask.model_validate_json(task.model_dump_json())

        self.assertEqual(restored.model_dump(), task.model_dump())
        self.assertEqual(restored.error, error)
        self.assertEqual(
            json.loads(task.model_dump_json())["status"],
            "failed",
        )

    def test_task_python_round_trip(self) -> None:
        task = AgentTask(goal="test goal")
        restored = AgentTask.model_validate(task.model_dump())
        self.assertEqual(restored, task)

    def test_action_json_round_trip(self) -> None:
        action = Action(
            tool_name="read_data",
            arguments={"record_id": "1"},
            requires_approval=True,
        )
        restored = Action.model_validate_json(action.model_dump_json())

        self.assertEqual(restored, action)
        self.assertEqual(
            json.loads(action.model_dump_json())["action_type"],
            "read",
        )
        self.assertEqual(restored.action_type, ActionType.READ)

    def test_tool_result_json_round_trip(self) -> None:
        started = utc_now()
        error = TaskError(code="tool_failure", message="tool failed")
        result = ToolResult(
            tool_name="read_data",
            success=False,
            error=error,
            started_at=started,
            finished_at=started + timedelta(milliseconds=5),
            duration_ms=5.0,
        )
        restored = ToolResult.model_validate_json(result.model_dump_json())

        self.assertEqual(restored, result)
        self.assertEqual(restored.error, error)

    def test_verification_result_json_round_trip(self) -> None:
        verification = VerificationResult(
            status=VerificationStatus.PASSED,
            passed=True,
            message="verified",
            checks={"data_present": True},
        )
        restored = VerificationResult.model_validate_json(
            verification.model_dump_json()
        )

        self.assertEqual(restored, verification)
        self.assertEqual(
            json.loads(verification.model_dump_json())["status"],
            "passed",
        )

    def test_agent_state_json_round_trip(self) -> None:
        action = Action(tool_name="read_data")
        started = utc_now()
        result = ToolResult(
            tool_name="read_data",
            success=True,
            output={"rows": 1},
            started_at=started,
            finished_at=started + timedelta(milliseconds=1),
        )
        verification = VerificationResult(
            status=VerificationStatus.PASSED,
            passed=True,
            message="verified",
        )
        state = AgentState(
            task_id="task-1",
            status=TaskStatus.EXECUTING,
            current_action=action,
            observations=[result],
            pending_actions=[action],
            last_verification=verification,
        )
        restored = AgentState.model_validate_json(state.model_dump_json())

        self.assertEqual(restored, state)

    def test_execution_context_json_round_trip(self) -> None:
        started = utc_now()
        context = ExecutionContext(
            task_id="task-1",
            max_iterations=5,
            max_tool_calls=20,
            started_at=started,
            deadline=started + timedelta(hours=1),
        )
        restored = ExecutionContext.model_validate_json(
            context.model_dump_json()
        )

        self.assertEqual(restored, context)
        self.assertEqual(restored.attempt, 1)


if __name__ == "__main__":
    unittest.main()
