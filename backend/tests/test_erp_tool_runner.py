from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from time import sleep

from backend.agent.erp.definitions import ERP_TOOL_DEFINITIONS
from backend.agent.erp.errors import (
    ErpDatabaseError,
    ErpInvalidArgumentsError,
    ErpNotFoundError,
    ErpPermissionDeniedError,
    ErpQueryTimeoutError,
)
from backend.agent.erp.registration import register_erp_tools
from backend.agent.erp.runner import ErpToolRunner
from backend.agent.erp.service import ErpReadService
from backend.agent.erp.sqlite_adapter import SqliteErpReadAdapter
from backend.agent.models import ErrorCategory
from backend.agent.tools.contracts import (
    ToolDefinition,
    ToolExecutionError,
    ToolExecutionRequest,
    ToolExecutionResult,
    ToolExecutionStatus,
)
from backend.agent.tools.executor import ToolExecutor
from backend.agent.tools.registry import ToolRegistry
from backend.tests.erp_support import create_erp_fixture_db

_NO_TIMEOUT = object()


def make_result(
    output: object = None,
    *,
    status: ToolExecutionStatus = ToolExecutionStatus.SUCCEEDED,
    error: ToolExecutionError | None = None,
    execution_id: str = "exec-1",
    tool_name: str = "erp.products.search",
) -> ToolExecutionResult:
    started_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    finished_at = datetime(2026, 1, 1, 0, 0, 1, tzinfo=timezone.utc)
    return ToolExecutionResult(
        execution_id=execution_id,
        tool_name=tool_name,
        status=status,
        output=output,
        error=error,
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=1000.0,
    )


class _StaticExecutor:
    def __init__(self, result: ToolExecutionResult) -> None:
        self.result = result
        self.timeouts: list[object] = []

    def execute(
        self,
        request: ToolExecutionRequest,
        timeout: object = _NO_TIMEOUT,
    ) -> ToolExecutionResult:
        self.timeouts.append(timeout)
        return self.result


class ErpToolRunnerSuccessTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp_dir.cleanup)
        database_path = create_erp_fixture_db(
            Path(self._temp_dir.name) / "erp.db"
        )
        self.service = ErpReadService(SqliteErpReadAdapter(database_path))
        self.registry = ToolRegistry()
        self.executor = ToolExecutor(self.registry)
        self.addCleanup(self.executor.shutdown)
        self.registration = register_erp_tools(
            self.registry,
            self.executor,
            self.service,
        )
        self.addCleanup(self.registration.unregister)
        self.runner = ErpToolRunner(self.executor)

    def test_successful_execution_for_all_registered_tools(self) -> None:
        cases = (
            ("erp.products.search", {"query": "M10"}),
            ("erp.products.get", {"product_id": "PRD001"}),
            ("erp.inventory.get", {"product_id": "PRD001"}),
            ("erp.warehouses.list", {}),
            ("erp.inventory.low_stock", {"limit": 10}),
            ("erp.sales_orders.get", {"so_id": "SO001"}),
            ("erp.dispatches.get", {"dispatch_id": "DSP001"}),
            ("erp.dispatches.list", {"limit": 20}),
            ("erp.dispatches.by_sales_order", {"so_id": "SO001"}),
        )
        for tool_name, arguments in cases:
            with self.subTest(tool=tool_name):
                request = ToolExecutionRequest(
                    execution_id=f"exec-{tool_name}",
                    tool_name=tool_name,
                    arguments=arguments,
                )
                result = self.runner.execute(request)

                self.assertEqual(result.status, ToolExecutionStatus.SUCCEEDED)
                self.assertIsNone(result.error)
                self.assertEqual(result.execution_id, request.execution_id)
                self.assertEqual(result.tool_name, tool_name)
                self.assertIsInstance(result.output, dict)
                self.assertNotIn("ok", result.output)
                self.assertIsNotNone(result.started_at)
                self.assertIsNotNone(result.finished_at)
                self.assertGreaterEqual(result.duration_ms or 0, 0)

    def test_success_output_is_data_not_internal_envelope(self) -> None:
        request = ToolExecutionRequest(
            tool_name="erp.products.search",
            arguments={"query": "M10"},
        )
        result = self.runner.execute(request)

        self.assertEqual(
            [item["product_id"] for item in result.output["items"]],
            ["PRD001", "PRD002"],
        )
        self.assertNotIn("ok", result.output)
        self.assertNotIn("data", result.output)


class ErpToolRunnerErrorTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp_dir.cleanup)
        database_path = create_erp_fixture_db(
            Path(self._temp_dir.name) / "erp.db"
        )
        self.service = ErpReadService(SqliteErpReadAdapter(database_path))
        self.registry = ToolRegistry()
        self.executor = ToolExecutor(self.registry)
        self.addCleanup(self.executor.shutdown)
        self.registration = register_erp_tools(
            self.registry,
            self.executor,
            self.service,
        )
        self.addCleanup(self.registration.unregister)
        self.runner = ErpToolRunner(self.executor)

    def test_erp_not_found_is_translated(self) -> None:
        result = self.runner.execute(
            ToolExecutionRequest(
                tool_name="erp.products.get",
                arguments={"product_id": "UNKNOWN"},
            )
        )

        self.assertEqual(result.status, ToolExecutionStatus.FAILED)
        self.assertIsNone(result.output)
        self.assertEqual(result.error.code, "erp_not_found")
        self.assertEqual(result.error.category, ErrorCategory.NOT_FOUND)
        self.assertTrue(result.error.recoverable)
        self.assertFalse(result.error.retryable)
        self.assertEqual(result.error.details, {"resource": "product"})

    def test_semantic_invalid_arguments_are_translated(self) -> None:
        result = self.runner.execute(
            ToolExecutionRequest(
                tool_name="erp.products.search",
                arguments={"query": "   "},
            )
        )

        self.assertEqual(result.status, ToolExecutionStatus.FAILED)
        self.assertEqual(result.error.code, "erp_invalid_arguments")
        self.assertEqual(result.error.category, ErrorCategory.VALIDATION)
        self.assertTrue(result.error.recoverable)
        self.assertFalse(result.error.retryable)

    def test_phase_3c_schema_failure_is_returned_unchanged(self) -> None:
        result = self.runner.execute(
            ToolExecutionRequest(
                tool_name="erp.products.search",
                arguments={"query": "M10", "sql": "SELECT 1"},
            )
        )

        self.assertEqual(result.status, ToolExecutionStatus.FAILED)
        self.assertEqual(result.error.code, "invalid_arguments")
        self.assertEqual(result.error.category, ErrorCategory.VALIDATION)
        self.assertTrue(result.error.recoverable)

    def test_tool_not_found_is_returned_unchanged(self) -> None:
        result = self.runner.execute(
            ToolExecutionRequest(tool_name="erp.products.missing")
        )

        self.assertEqual(result.status, ToolExecutionStatus.FAILED)
        self.assertEqual(result.error.code, "tool_not_found")
        self.assertEqual(result.error.category, ErrorCategory.NOT_FOUND)

    def test_handler_not_found_is_returned_unchanged(self) -> None:
        registry = ToolRegistry()
        registry.register(ERP_TOOL_DEFINITIONS[0])
        executor = ToolExecutor(registry)
        self.addCleanup(executor.shutdown)
        runner = ErpToolRunner(executor)

        result = runner.execute(
            ToolExecutionRequest(
                tool_name="erp.products.search",
                arguments={"query": "M10"},
            )
        )

        self.assertEqual(result.status, ToolExecutionStatus.FAILED)
        self.assertEqual(result.error.code, "handler_not_found")

    def test_unexpected_handler_exception_is_sanitized(self) -> None:
        registry = ToolRegistry()
        registry.register(
            ToolDefinition(
                name="test.raises",
                description="Raise an exception.",
                input_schema={
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            )
        )
        executor = ToolExecutor(registry)
        self.addCleanup(executor.shutdown)

        def handler(arguments: dict, context: object) -> None:
            raise RuntimeError("secret /tmp/erp.db")

        executor.register_handler("test.raises", handler)
        runner = ErpToolRunner(executor)
        result = runner.execute(
            ToolExecutionRequest(tool_name="test.raises")
        )

        self.assertEqual(result.status, ToolExecutionStatus.FAILED)
        self.assertEqual(result.error.code, "handler_error")
        self.assertEqual(result.error.category, ErrorCategory.TOOL)
        self.assertEqual(
            result.error.details,
            {"exception_type": "RuntimeError"},
        )
        self.assertNotIn("secret", result.error.message)


class ErpToolRunnerEnvelopeTests(unittest.TestCase):
    def _run_with_output(self, output: object) -> ToolExecutionResult:
        executor = _StaticExecutor(make_result(output))
        runner = ErpToolRunner(executor)  # type: ignore[arg-type]
        return runner.execute(
            ToolExecutionRequest(tool_name="erp.products.search")
        )

    def test_business_error_envelopes_are_translated(self) -> None:
        errors = (
            ErpInvalidArgumentsError("query"),
            ErpNotFoundError("product"),
            ErpDatabaseError(),
            ErpQueryTimeoutError(),
            ErpPermissionDeniedError(),
        )
        for error in errors:
            with self.subTest(code=error.code):
                result = self._run_with_output(error.to_envelope())

                self.assertEqual(result.status, ToolExecutionStatus.FAILED)
                self.assertIsNone(result.output)
                self.assertEqual(result.error.code, error.code)
                self.assertEqual(result.error.category, error.category)
                self.assertEqual(
                    result.error.recoverable,
                    error.recoverable,
                )
                self.assertEqual(result.error.retryable, error.retryable)
                self.assertEqual(result.error.details, error.details)

    def test_malformed_envelopes_fail_closed(self) -> None:
        malformed_outputs = (
            None,
            [],
            {},
            {"ok": True},
            {"ok": "yes", "data": {}},
            {"ok": 1, "data": {}},
            {"ok": True, "data": {"value": float("nan")}},
            {"ok": True, "data": {}, "extra": True},
            {"ok": False},
            {"ok": False, "error": {}},
            {
                "ok": False,
                "error": {
                    "code": " ",
                    "message": "bad",
                    "category": "internal",
                    "recoverable": False,
                    "retryable": False,
                    "details": {},
                },
            },
            {
                "ok": False,
                "error": {
                    "code": "secret",
                    "message": "bad",
                    "category": "not-a-category",
                    "recoverable": False,
                    "retryable": False,
                    "details": {},
                },
            },
            {
                "ok": False,
                "error": {
                    "code": "erp_internal_error",
                    "message": "bad",
                    "category": "internal",
                    "recoverable": 0,
                    "retryable": False,
                    "details": {},
                },
            },
            {
                "ok": False,
                "error": {
                    "code": "erp_internal_error",
                    "message": "bad",
                    "category": "internal",
                    "recoverable": False,
                    "retryable": False,
                    "details": {"value": float("nan")},
                },
            },
            {
                "ok": False,
                "error": {
                    "code": "erp_internal_error",
                    "message": "bad",
                    "category": "internal",
                    "recoverable": False,
                    "retryable": False,
                    "details": {},
                    "extra": True,
                },
            },
        )
        for output in malformed_outputs:
            with self.subTest(output=repr(output)):
                result = self._run_with_output(output)

                self.assertEqual(result.status, ToolExecutionStatus.FAILED)
                self.assertIsNone(result.output)
                self.assertEqual(result.error.code, "erp_internal_error")
                self.assertEqual(result.error.category, ErrorCategory.INTERNAL)
                self.assertFalse(result.error.recoverable)
                self.assertFalse(result.error.retryable)
                self.assertEqual(result.error.details, {})
                self.assertNotIn("secret", result.error.message)

    def test_success_translation_preserves_timing(self) -> None:
        source = make_result({"ok": True, "data": {"items": []}})
        executor = _StaticExecutor(source)
        runner = ErpToolRunner(executor)  # type: ignore[arg-type]
        result = runner.execute(
            ToolExecutionRequest(
                execution_id="exec-1",
                tool_name="erp.products.search",
            )
        )

        self.assertEqual(result.status, ToolExecutionStatus.SUCCEEDED)
        self.assertEqual(result.output, {"items": []})
        self.assertEqual(result.execution_id, source.execution_id)
        self.assertEqual(result.tool_name, source.tool_name)
        self.assertEqual(result.started_at, source.started_at)
        self.assertEqual(result.finished_at, source.finished_at)
        self.assertEqual(result.duration_ms, source.duration_ms)

    def test_error_translation_preserves_timing(self) -> None:
        source = make_result(
            ErpNotFoundError("product").to_envelope()
        )
        executor = _StaticExecutor(source)
        runner = ErpToolRunner(executor)  # type: ignore[arg-type]
        result = runner.execute(
            ToolExecutionRequest(
                execution_id="exec-1",
                tool_name="erp.products.search",
            )
        )

        self.assertEqual(result.status, ToolExecutionStatus.FAILED)
        self.assertEqual(result.execution_id, source.execution_id)
        self.assertEqual(result.tool_name, source.tool_name)
        self.assertEqual(result.started_at, source.started_at)
        self.assertEqual(result.finished_at, source.finished_at)
        self.assertEqual(result.duration_ms, source.duration_ms)

    def test_failed_and_cancelled_results_are_returned_unchanged(self) -> None:
        failed = make_result(
            status=ToolExecutionStatus.FAILED,
            error=ToolExecutionError(
                code="handler_error",
                message="failed",
                category=ErrorCategory.TOOL,
            ),
        )
        cancelled = make_result(status=ToolExecutionStatus.CANCELLED)

        for source in (failed, cancelled):
            with self.subTest(status=source.status):
                runner = ErpToolRunner(  # type: ignore[arg-type]
                    _StaticExecutor(source)
                )
                result = runner.execute(
                    ToolExecutionRequest(tool_name="erp.products.search")
                )
                self.assertIs(result, source)

    def test_timeout_is_forwarded_and_omission_inherits_executor_default(
        self,
    ) -> None:
        executor = _StaticExecutor(
            make_result({"ok": True, "data": {}})
        )
        runner = ErpToolRunner(executor)  # type: ignore[arg-type]
        request = ToolExecutionRequest(tool_name="erp.products.search")

        runner.execute(request, timeout=1.25)
        runner.execute(request, timeout=None)
        runner.execute(request)

        self.assertEqual(executor.timeouts[0], 1.25)
        self.assertIsNone(executor.timeouts[1])
        self.assertIs(executor.timeouts[2], _NO_TIMEOUT)


class ErpToolRunnerTimeoutTests(unittest.TestCase):
    def test_slow_handler_returns_cancelled_without_error(self) -> None:
        registry = ToolRegistry()
        registry.register(
            ToolDefinition(
                name="test.slow",
                description="Slow tool.",
                input_schema={
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            )
        )
        executor = ToolExecutor(registry)
        self.addCleanup(executor.shutdown)

        def handler(arguments: dict, context: object) -> dict:
            sleep(0.1)
            return {"ok": True, "data": {}}

        executor.register_handler("test.slow", handler)
        runner = ErpToolRunner(executor)
        result = runner.execute(
            ToolExecutionRequest(tool_name="test.slow"),
            timeout=0.01,
        )

        self.assertEqual(result.status, ToolExecutionStatus.CANCELLED)
        self.assertIsNone(result.error)
        self.assertIsNone(result.output)
        self.assertIsNotNone(result.started_at)
        self.assertIsNotNone(result.finished_at)
        self.assertGreaterEqual(result.duration_ms or 0, 0)


if __name__ == "__main__":
    unittest.main()
