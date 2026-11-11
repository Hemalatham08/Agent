import json
import unittest
from concurrent.futures import ThreadPoolExecutor as FuturesThreadPool
from threading import Barrier, Event, Lock, Thread
from time import perf_counter, sleep

import backend.agent.tools as tool_package
from backend.agent.models import ErrorCategory
from backend.agent.tools import (
    DuplicateHandlerError,
    HandlerNotFoundError,
    ToolDefinition,
    ToolExecutionContext,
    ToolExecutionRequest,
    ToolExecutionStatus,
    ToolExecutor,
    ToolHandlerError,
    ToolRegistry,
)


def make_definition(
    name: str = "echo",
    input_schema: dict | None = None,
) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=f"Tool {name}.",
        input_schema=input_schema
        or {
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        },
    )


def make_request(
    *,
    tool_name: str = "echo",
    arguments: dict | None = None,
    execution_id: str = "exec-1",
    metadata: dict | None = None,
) -> ToolExecutionRequest:
    return ToolExecutionRequest(
        execution_id=execution_id,
        tool_name=tool_name,
        arguments={"value": "original"} if arguments is None else arguments,
        metadata={} if metadata is None else metadata,
    )


class ExecutorTestCase(unittest.TestCase):
    def create_executor(
        self,
        *,
        definitions: list[ToolDefinition] | None = None,
        handlers: dict | None = None,
        max_workers: int = 2,
        default_timeout: float | None = None,
        include_exception_messages: bool = False,
    ) -> tuple[ToolExecutor, ToolRegistry]:
        registry = ToolRegistry()
        for definition in (
            [make_definition()] if definitions is None else definitions
        ):
            registry.register(definition)
        executor = ToolExecutor(
            registry,
            max_workers=max_workers,
            default_timeout=default_timeout,
            include_exception_messages=include_exception_messages,
        )
        for name, handler in (handlers or {}).items():
            executor.register_handler(name, handler)
        self.addCleanup(executor.shutdown)
        return executor, registry

    def setUp(self) -> None:
        self.definition = make_definition()
        self.executor, self.registry = self.create_executor(
            definitions=[self.definition]
        )

    def register_default(self, handler) -> None:
        self.executor.register_handler("echo", handler)


class ToolHandlerRegistrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.executor = ToolExecutor(ToolRegistry())
        self.addCleanup(self.executor.shutdown)

    def test_register_get_has_and_unregister(self) -> None:
        def handler(arguments: dict, context: ToolExecutionContext) -> dict:
            return {"value": arguments["value"]}

        self.assertFalse(self.executor.has_handler("echo"))

        self.executor.register_handler(" echo ", handler)

        self.assertTrue(self.executor.has_handler("echo"))
        self.assertIs(self.executor.get_handler("echo"), handler)
        self.assertIs(self.executor.unregister_handler("echo"), handler)
        self.assertFalse(self.executor.has_handler("echo"))

    def test_get_missing_handler_raises(self) -> None:
        with self.assertRaises(HandlerNotFoundError) as context:
            self.executor.get_handler("missing")

        self.assertEqual(context.exception.tool_name, "missing")

    def test_unregister_missing_handler_raises(self) -> None:
        with self.assertRaises(HandlerNotFoundError) as context:
            self.executor.unregister_handler("missing")

        self.assertEqual(context.exception.tool_name, "missing")

    def test_duplicate_registration_preserves_original(self) -> None:
        def first(arguments: dict, context: ToolExecutionContext) -> dict:
            return {"handler": "first"}

        def second(arguments: dict, context: ToolExecutionContext) -> dict:
            return {"handler": "second"}

        self.executor.register_handler("echo", first)

        with self.assertRaises(DuplicateHandlerError) as context:
            self.executor.register_handler("echo", second)

        self.assertEqual(context.exception.tool_name, "echo")
        self.assertIs(self.executor.get_handler("echo"), first)

    def test_re_register_after_unregister(self) -> None:
        def first(arguments: dict, context: ToolExecutionContext) -> dict:
            return {"handler": "first"}

        def second(arguments: dict, context: ToolExecutionContext) -> dict:
            return {"handler": "second"}

        self.executor.register_handler("echo", first)
        self.executor.unregister_handler("echo")
        self.executor.register_handler("echo", second)

        self.assertIs(self.executor.get_handler("echo"), second)

    def test_concurrent_duplicate_registration_allows_one_success(
        self,
    ) -> None:
        def handler(arguments: dict, context: ToolExecutionContext) -> dict:
            return {}

        worker_count = 8
        barrier = Barrier(worker_count)

        def attempt(_: int) -> str:
            barrier.wait()
            try:
                self.executor.register_handler("echo", handler)
            except DuplicateHandlerError:
                return "duplicate"
            return "registered"

        with FuturesThreadPool(max_workers=worker_count) as pool:
            results = list(pool.map(attempt, range(worker_count)))

        self.assertEqual(results.count("registered"), 1)
        self.assertEqual(
            results.count("duplicate"),
            worker_count - 1,
        )
        self.assertTrue(self.executor.has_handler("echo"))

    def test_register_requires_callable_handler(self) -> None:
        with self.assertRaises(TypeError):
            self.executor.register_handler("echo", "not-callable")

    def test_register_rejects_blank_tool_name(self) -> None:
        def handler(arguments: dict, context: ToolExecutionContext) -> dict:
            return {}

        with self.assertRaises(ValueError):
            self.executor.register_handler("   ", handler)

    def test_handler_error_hierarchy(self) -> None:
        self.assertTrue(
            issubclass(DuplicateHandlerError, ToolHandlerError)
        )
        self.assertTrue(
            issubclass(HandlerNotFoundError, ToolHandlerError)
        )


class ToolExecutionTests(ExecutorTestCase):
    def test_successful_execution_passes_arguments_and_context(self) -> None:
        captured: dict = {}

        def handler(
            arguments: dict,
            context: ToolExecutionContext,
        ) -> dict:
            captured["arguments"] = arguments
            captured["context"] = context
            return {"value": arguments["value"]}

        self.register_default(handler)
        result = self.executor.execute(
            make_request(metadata={"request_id": "req-1"})
        )

        self.assertEqual(result.status, ToolExecutionStatus.SUCCEEDED)
        self.assertEqual(result.output, {"value": "original"})
        self.assertIsNone(result.error)
        self.assertEqual(result.execution_id, "exec-1")
        self.assertEqual(result.tool_name, "echo")
        self.assertIsNotNone(result.started_at)
        self.assertIsNotNone(result.finished_at)
        self.assertIsNotNone(result.duration_ms)
        self.assertGreaterEqual(result.duration_ms, 0)

        context = captured["context"]
        self.assertIsInstance(context, ToolExecutionContext)
        self.assertEqual(context.execution_id, "exec-1")
        self.assertEqual(context.tool_name, "echo")
        self.assertIsNone(context.timeout_seconds)
        self.assertEqual(context.metadata, {"request_id": "req-1"})
        self.assertIsNotNone(context.started_at.tzinfo)
        self.assertEqual(captured["arguments"], {"value": "original"})

    def test_successful_execution_allows_none_output(self) -> None:
        self.register_default(lambda arguments, context: None)

        result = self.executor.execute(make_request())

        self.assertEqual(result.status, ToolExecutionStatus.SUCCEEDED)
        self.assertIsNone(result.output)
        self.assertIsNone(result.error)

    def test_successful_execution_accepts_json_outputs(self) -> None:
        outputs = [
            None,
            True,
            3,
            3.5,
            "text",
            [1, {"nested": [2]}],
            {"value": None},
        ]

        for output in outputs:
            with self.subTest(output=output):
                executor, _ = self.create_executor(
                    handlers={
                        "echo": lambda arguments, context, value=output: value
                    }
                )
                result = executor.execute(make_request())
                self.assertEqual(
                    result.status,
                    ToolExecutionStatus.SUCCEEDED,
                )
                self.assertEqual(result.output, output)

    def test_tool_not_found_is_a_preflight_failure(self) -> None:
        result = self.executor.execute(
            make_request(tool_name="missing"),
        )

        self.assertEqual(result.status, ToolExecutionStatus.FAILED)
        self.assertEqual(result.error.code, "tool_not_found")
        self.assertEqual(result.error.category, ErrorCategory.NOT_FOUND)
        self.assertFalse(result.error.recoverable)
        self.assertFalse(result.error.retryable)
        self.assertIsNone(result.output)
        self.assertIsNone(result.started_at)
        self.assertIsNotNone(result.finished_at)
        self.assertIsNone(result.duration_ms)

    def test_handler_not_found_is_a_preflight_failure(self) -> None:
        result = self.executor.execute(make_request())

        self.assertEqual(result.status, ToolExecutionStatus.FAILED)
        self.assertEqual(result.error.code, "handler_not_found")
        self.assertEqual(result.error.category, ErrorCategory.NOT_FOUND)
        self.assertFalse(result.error.recoverable)
        self.assertFalse(result.error.retryable)
        self.assertIsNone(result.output)
        self.assertIsNone(result.started_at)
        self.assertIsNotNone(result.finished_at)
        self.assertIsNone(result.duration_ms)

    def test_invalid_arguments_are_a_preflight_failure(self) -> None:
        self.register_default(lambda arguments, context: {})
        secret = "SECRET-ARGUMENT-VALUE"

        result = self.executor.execute(
            make_request(
                arguments={
                    "value": {"nested": secret},
                    "extra": secret,
                }
            )
        )

        self.assertEqual(result.status, ToolExecutionStatus.FAILED)
        self.assertEqual(result.error.code, "invalid_arguments")
        self.assertEqual(
            result.error.category,
            ErrorCategory.VALIDATION,
        )
        self.assertTrue(result.error.recoverable)
        self.assertFalse(result.error.retryable)
        self.assertIsNone(result.output)
        self.assertIsNone(result.started_at)
        self.assertIsNotNone(result.finished_at)
        self.assertIsNone(result.duration_ms)

        issues = result.error.details["issues"]
        self.assertEqual(
            {(issue["path"], issue["keyword"]) for issue in issues},
            {
                ("value", "type"),
                ("extra", "additionalProperties"),
            },
        )
        self.assertNotIn(secret, result.model_dump_json())

    def test_invalid_tool_schema_is_a_preflight_failure(self) -> None:
        definition = make_definition(
            input_schema={
                "type": "object",
                "properties": {
                    "nested": {
                        "type": "object",
                        "properties": {
                            "value": {"type": "string"},
                        },
                    }
                },
            }
        )
        executor, _ = self.create_executor(
            definitions=[definition],
            handlers={definition.name: lambda arguments, context: {}},
        )

        result = executor.execute(
            make_request(tool_name=definition.name, arguments={})
        )

        self.assertEqual(result.status, ToolExecutionStatus.FAILED)
        self.assertEqual(result.error.code, "invalid_tool_schema")
        self.assertEqual(
            result.error.category,
            ErrorCategory.VALIDATION,
        )
        self.assertFalse(result.error.recoverable)
        self.assertFalse(result.error.retryable)
        self.assertIsNone(result.output)
        self.assertIsNone(result.started_at)
        self.assertIsNotNone(result.finished_at)
        self.assertIsNone(result.duration_ms)

    def test_handler_exception_becomes_handler_error(self) -> None:
        secret = "SECRET-EXCEPTION-MESSAGE"

        def handler(arguments: dict, context: ToolExecutionContext) -> dict:
            raise RuntimeError(secret)

        self.register_default(handler)
        result = self.executor.execute(make_request())

        self.assertEqual(result.status, ToolExecutionStatus.FAILED)
        self.assertEqual(result.error.code, "handler_error")
        self.assertEqual(result.error.category, ErrorCategory.TOOL)
        self.assertFalse(result.error.recoverable)
        self.assertFalse(result.error.retryable)
        self.assertIsNone(result.output)
        self.assertIsNotNone(result.started_at)
        self.assertIsNotNone(result.finished_at)
        self.assertIsNotNone(result.duration_ms)
        self.assertGreaterEqual(result.duration_ms, 0)
        self.assertEqual(
            result.error.details["exception_type"],
            "RuntimeError",
        )
        self.assertNotIn(secret, result.error.message)
        self.assertNotIn(secret, result.model_dump_json())

    def test_exception_messages_can_be_opted_in(self) -> None:
        def handler(arguments: dict, context: ToolExecutionContext) -> dict:
            raise RuntimeError("explicit detail")

        executor, _ = self.create_executor(
            handlers={"echo": handler},
            include_exception_messages=True,
        )

        result = executor.execute(make_request())

        self.assertEqual(result.error.code, "handler_error")
        self.assertIn("explicit detail", result.error.message)

    def test_handler_timeout_exception_is_handler_error(self) -> None:
        def handler(arguments: dict, context: ToolExecutionContext) -> dict:
            raise TimeoutError("raised by handler")

        self.register_default(handler)
        result = self.executor.execute(make_request(), timeout=1.0)

        self.assertEqual(result.status, ToolExecutionStatus.FAILED)
        self.assertEqual(result.error.code, "handler_error")
        self.assertEqual(
            result.error.details["exception_type"],
            "TimeoutError",
        )

    def test_base_exception_is_not_swallowed(self) -> None:
        def handler(arguments: dict, context: ToolExecutionContext) -> dict:
            raise KeyboardInterrupt("stop")

        self.register_default(handler)

        with self.assertRaises(KeyboardInterrupt):
            self.executor.execute(make_request())

    def test_invalid_outputs_become_invalid_output(self) -> None:
        outputs = [
            object(),
            {1, 2},
            (1, 2),
            float("nan"),
            float("inf"),
            b"bytes",
        ]

        for output in outputs:
            with self.subTest(output_type=type(output).__name__):
                executor, _ = self.create_executor(
                    handlers={
                        "echo": lambda arguments, context, value=output: value
                    }
                )
                result = executor.execute(make_request())

                self.assertEqual(
                    result.status,
                    ToolExecutionStatus.FAILED,
                )
                self.assertEqual(result.error.code, "invalid_output")
                self.assertEqual(result.error.category, ErrorCategory.TOOL)
                self.assertFalse(result.error.recoverable)
                self.assertFalse(result.error.retryable)
                self.assertIsNone(result.output)
                self.assertIsNotNone(result.started_at)
                self.assertIsNotNone(result.finished_at)
                self.assertIsNotNone(result.duration_ms)
                self.assertEqual(
                    result.error.details["output_type"],
                    type(output).__name__,
                )

    def test_success_result_is_json_serializable(self) -> None:
        self.register_default(
            lambda arguments, context: {
                "value": arguments["value"],
                "nested": {"count": 1},
            }
        )
        result = self.executor.execute(make_request())

        payload = json.loads(result.model_dump_json())

        self.assertEqual(payload["status"], "succeeded")
        self.assertEqual(payload["output"]["value"], "original")
        self.assertEqual(payload["error"], None)
        self.assertIsNotNone(payload["started_at"])
        self.assertIsNotNone(payload["finished_at"])

    def test_failure_result_is_json_serializable(self) -> None:
        self.register_default(lambda arguments, context: {})

        result = self.executor.execute(
            make_request(arguments={})
        )

        payload = json.loads(result.model_dump_json())

        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["error"]["code"], "invalid_arguments")
        self.assertEqual(payload["output"], None)

    def test_timestamps_and_duration_are_consistent(self) -> None:
        self.register_default(
            lambda arguments, context: {"value": arguments["value"]}
        )

        result = self.executor.execute(make_request())

        self.assertIsNotNone(result.started_at.tzinfo)
        self.assertIsNotNone(result.finished_at.tzinfo)
        self.assertLessEqual(result.started_at, result.finished_at)
        self.assertGreaterEqual(result.duration_ms, 0)

    def test_preflight_failures_do_not_call_handlers(self) -> None:
        calls: list[str] = []

        def handler(arguments: dict, context: ToolExecutionContext) -> dict:
            calls.append(context.execution_id)
            return {}

        self.register_default(handler)
        result = self.executor.execute(make_request(arguments={}))

        self.assertEqual(result.error.code, "invalid_arguments")
        self.assertEqual(calls, [])

    def test_handler_receives_deep_copies(self) -> None:
        request = make_request(
            arguments={"value": "original"},
            metadata={"nested": {"count": 1}},
        )

        def handler(
            arguments: dict,
            context: ToolExecutionContext,
        ) -> dict:
            arguments["value"] = "mutated"
            arguments["new"] = "value"
            context.metadata["nested"]["count"] = 2
            return {"seen": arguments["value"]}

        self.register_default(handler)
        result = self.executor.execute(request)

        self.assertEqual(result.output, {"seen": "mutated"})
        self.assertEqual(request.arguments, {"value": "original"})
        self.assertEqual(request.metadata, {"nested": {"count": 1}})

    def test_execute_does_not_mutate_the_request(self) -> None:
        request = make_request(
            arguments={"value": "original"},
            metadata={"nested": {"count": 1}},
        )
        original = request.model_dump(mode="json")

        self.register_default(
            lambda arguments, context: {
                "value": arguments["value"]
            }
        )
        self.executor.execute(request)

        self.assertEqual(request.model_dump(mode="json"), original)

    def test_result_output_is_isolated_from_handler_state(self) -> None:
        shared = {"nested": {"count": 1}}
        self.register_default(
            lambda arguments, context: shared
        )

        result = self.executor.execute(make_request())
        shared["nested"]["count"] = 2

        self.assertEqual(result.output["nested"]["count"], 1)

    def test_concurrent_execution_and_error_handling(self) -> None:
        def handler(arguments: dict, context: ToolExecutionContext) -> dict:
            sleep(0.001)
            if arguments["value"] == "boom":
                raise RuntimeError("boom")
            return {
                "value": arguments["value"],
                "execution_id": context.execution_id,
            }

        self.register_default(handler)
        values = ["0", "1", "2", "3", "boom", "5", "6", "7"]

        def run(value: str):
            return self.executor.execute(
                make_request(
                    execution_id=f"exec-{value}",
                    arguments={"value": value},
                )
            )

        with FuturesThreadPool(max_workers=len(values)) as pool:
            results = list(pool.map(run, values))

        by_value = {
            result.execution_id.removeprefix("exec-"): result
            for result in results
        }
        self.assertEqual(by_value["boom"].error.code, "handler_error")
        for value in values:
            result = by_value[value]
            if value == "boom":
                continue
            self.assertEqual(
                result.status,
                ToolExecutionStatus.SUCCEEDED,
            )
            self.assertEqual(
                result.output,
                {
                    "value": value,
                    "execution_id": f"exec-{value}",
                },
            )

    def test_removed_handler_is_no_longer_executable(self) -> None:
        self.register_default(lambda arguments, context: {})
        self.executor.unregister_handler("echo")

        result = self.executor.execute(make_request())

        self.assertEqual(result.error.code, "handler_not_found")

    def test_registry_and_executor_remain_separate(self) -> None:
        self.assertTrue(self.registry.exists("echo"))
        self.register_default(lambda arguments, context: {})
        self.registry.unregister("echo")

        result = self.executor.execute(make_request())

        self.assertEqual(result.error.code, "tool_not_found")
        self.assertTrue(self.executor.has_handler("echo"))


class ToolTimeoutTests(ExecutorTestCase):
    def test_omitted_timeout_inherits_executor_default(self) -> None:
        started = Event()
        release = Event()
        captured: dict = {}

        def handler(
            arguments: dict,
            context: ToolExecutionContext,
        ) -> dict:
            captured["context"] = context
            started.set()
            release.wait(2.0)
            return {"value": arguments["value"]}

        executor, _ = self.create_executor(
            handlers={"echo": handler},
            max_workers=1,
            default_timeout=0.05,
        )
        self.addCleanup(release.set)

        result = executor.execute(make_request())

        self.assertTrue(started.is_set())
        self.assertEqual(result.status, ToolExecutionStatus.CANCELLED)
        self.assertEqual(captured["context"].timeout_seconds, 0.05)
        release.set()

    def test_explicit_timeout_overrides_executor_default(self) -> None:
        started = Event()
        release = Event()
        captured: dict = {}

        def handler(
            arguments: dict,
            context: ToolExecutionContext,
        ) -> dict:
            captured["context"] = context
            started.set()
            release.wait(2.0)
            return {"value": arguments["value"]}

        executor, _ = self.create_executor(
            handlers={"echo": handler},
            max_workers=1,
            default_timeout=5.0,
        )
        self.addCleanup(release.set)

        result = executor.execute(make_request(), timeout=0.05)

        self.assertTrue(started.is_set())
        self.assertEqual(result.status, ToolExecutionStatus.CANCELLED)
        self.assertEqual(captured["context"].timeout_seconds, 0.05)
        release.set()

    def test_explicit_none_timeout_is_unlimited(self) -> None:
        captured: dict = {}

        def handler(
            arguments: dict,
            context: ToolExecutionContext,
        ) -> dict:
            captured["context"] = context
            sleep(0.05)
            return {"value": arguments["value"]}

        executor, _ = self.create_executor(
            handlers={"echo": handler},
            max_workers=1,
            default_timeout=0.01,
        )

        result = executor.execute(make_request(), timeout=None)

        self.assertEqual(result.status, ToolExecutionStatus.SUCCEEDED)
        self.assertIsNone(captured["context"].timeout_seconds)

    def test_timeout_result_uses_cancelled_contract(self) -> None:
        started = Event()
        release = Event()

        def handler(arguments: dict, context: ToolExecutionContext) -> dict:
            started.set()
            release.wait(2.0)
            return {"value": arguments["value"]}

        executor, _ = self.create_executor(
            handlers={"echo": handler},
            max_workers=1,
            default_timeout=0.05,
        )
        self.addCleanup(release.set)

        result = executor.execute(make_request())

        self.assertTrue(started.is_set())
        self.assertEqual(result.status, ToolExecutionStatus.CANCELLED)
        self.assertIsNone(result.output)
        self.assertIsNone(result.error)
        self.assertIsNotNone(result.started_at)
        self.assertIsNotNone(result.finished_at)
        self.assertGreaterEqual(result.duration_ms, 0)

        payload = json.loads(result.model_dump_json())
        self.assertEqual(payload["status"], "cancelled")
        self.assertIsNone(payload["error"])
        self.assertIsNone(payload["output"])
        release.set()

    def test_timeout_does_not_bound_preflight_validation(self) -> None:
        calls: list[str] = []

        def handler(arguments: dict, context: ToolExecutionContext) -> dict:
            calls.append(context.execution_id)
            return {}

        executor, _ = self.create_executor(
            handlers={"echo": handler},
            max_workers=1,
            default_timeout=1e-9,
        )

        result = executor.execute(
            make_request(arguments={})
        )

        self.assertEqual(result.status, ToolExecutionStatus.FAILED)
        self.assertEqual(result.error.code, "invalid_arguments")
        self.assertEqual(calls, [])

    def test_queue_wait_timeout_cancels_queued_handler(self) -> None:
        first_started = Event()
        release_first = Event()
        second_started = Event()
        first_results: dict = {}

        def slow_handler(
            arguments: dict,
            context: ToolExecutionContext,
        ) -> dict:
            first_started.set()
            release_first.wait(2.0)
            return {"value": "first"}

        def queued_handler(
            arguments: dict,
            context: ToolExecutionContext,
        ) -> dict:
            second_started.set()
            return {"value": "second"}

        executor, _ = self.create_executor(
            definitions=[make_definition("slow"), make_definition("queued")],
            handlers={
                "slow": slow_handler,
                "queued": queued_handler,
            },
            max_workers=1,
        )
        self.addCleanup(release_first.set)

        def run_first() -> None:
            first_results["result"] = executor.execute(
                make_request(
                    tool_name="slow",
                    arguments={"value": "first"},
                    execution_id="exec-first",
                ),
                timeout=None,
            )

        first_thread = Thread(target=run_first)
        first_thread.start()
        self.assertTrue(first_started.wait(1.0))

        result = executor.execute(
            make_request(
                tool_name="queued",
                arguments={"value": "second"},
                execution_id="exec-second",
            ),
            timeout=0.05,
        )

        self.assertEqual(result.status, ToolExecutionStatus.CANCELLED)
        self.assertFalse(second_started.is_set())

        release_first.set()
        first_thread.join(2.0)
        self.assertFalse(first_thread.is_alive())
        self.assertEqual(
            first_results["result"].status,
            ToolExecutionStatus.SUCCEEDED,
        )

        sleep(0.05)
        self.assertFalse(second_started.is_set())

    def test_running_handler_may_continue_after_timeout(self) -> None:
        started = Event()
        release = Event()
        completed = Event()
        side_effects: list[str] = []

        def handler(arguments: dict, context: ToolExecutionContext) -> dict:
            started.set()
            release.wait(2.0)
            side_effects.append("completed")
            completed.set()
            return {"value": arguments["value"]}

        executor, _ = self.create_executor(
            handlers={"echo": handler},
            max_workers=1,
            default_timeout=0.05,
        )
        self.addCleanup(release.set)

        result = executor.execute(make_request())

        self.assertTrue(started.is_set())
        self.assertEqual(result.status, ToolExecutionStatus.CANCELLED)
        self.assertFalse(completed.is_set())

        release.set()
        self.assertTrue(completed.wait(1.0))
        self.assertEqual(side_effects, ["completed"])

    def test_invalid_timeout_values_are_rejected(self) -> None:
        executor, _ = self.create_executor(
            handlers={"echo": lambda arguments, context: {}}
        )

        for value in (0, -1, True, "1", float("inf"), float("nan")):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    executor.execute(make_request(), timeout=value)


class ToolPoolTests(ExecutorTestCase):
    def test_bounded_worker_count_limits_concurrency(self) -> None:
        release = Event()
        lock = Lock()
        two_started = Event()
        active = 0
        max_active = 0
        results: list = []

        def handler(arguments: dict, context: ToolExecutionContext) -> dict:
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
                if active == 2:
                    two_started.set()
            release.wait(2.0)
            with lock:
                active -= 1
            return {"value": arguments["value"]}

        executor, _ = self.create_executor(
            handlers={"echo": handler},
            max_workers=2,
        )
        self.addCleanup(release.set)

        def run(index: int) -> None:
            result = executor.execute(
                make_request(
                    execution_id=f"exec-{index}",
                    arguments={"value": str(index)},
                ),
                timeout=None,
            )
            with lock:
                results.append(result)

        threads = [
            Thread(target=run, args=(index,))
            for index in range(4)
        ]
        for thread in threads:
            thread.start()

        self.assertTrue(two_started.wait(1.0))
        sleep(0.05)
        with lock:
            self.assertEqual(active, 2)

        release.set()
        for thread in threads:
            thread.join(2.0)
            self.assertFalse(thread.is_alive())

        self.assertEqual(len(results), 4)
        self.assertTrue(
            all(
                result.status is ToolExecutionStatus.SUCCEEDED
                for result in results
            )
        )
        self.assertEqual(max_active, 2)


class ToolShutdownTests(ExecutorTestCase):
    def test_shutdown_is_idempotent(self) -> None:
        executor, _ = self.create_executor()

        executor.shutdown()
        executor.shutdown()
        executor.shutdown(wait=False)
        executor.shutdown(wait=True)

    def test_execute_after_shutdown_raises(self) -> None:
        executor, _ = self.create_executor(
            handlers={"echo": lambda arguments, context: {}}
        )
        executor.shutdown()

        with self.assertRaises(RuntimeError):
            executor.execute(make_request())

    def test_shutdown_wait_false_does_not_wait_for_running_handler(
        self,
    ) -> None:
        started = Event()
        release = Event()
        results: dict = {}

        def handler(arguments: dict, context: ToolExecutionContext) -> dict:
            started.set()
            release.wait(2.0)
            return {"value": arguments["value"]}

        executor, _ = self.create_executor(
            handlers={"echo": handler},
            max_workers=1,
        )
        self.addCleanup(release.set)

        def run() -> None:
            results["result"] = executor.execute(
                make_request(),
                timeout=None,
            )

        thread = Thread(target=run)
        thread.start()
        self.assertTrue(started.wait(1.0))

        started_counter = perf_counter()
        executor.shutdown(wait=False)
        elapsed = perf_counter() - started_counter

        self.assertLess(elapsed, 0.5)
        self.assertTrue(thread.is_alive())

        release.set()
        thread.join(2.0)
        self.assertFalse(thread.is_alive())
        self.assertEqual(
            results["result"].status,
            ToolExecutionStatus.SUCCEEDED,
        )
        executor.shutdown(wait=True)

    def test_shutdown_wait_true_waits_for_running_handler(self) -> None:
        started = Event()
        release = Event()
        results: dict = {}

        def handler(arguments: dict, context: ToolExecutionContext) -> dict:
            started.set()
            release.wait(2.0)
            return {"value": arguments["value"]}

        executor, _ = self.create_executor(
            handlers={"echo": handler},
            max_workers=1,
        )
        self.addCleanup(release.set)

        def run() -> None:
            results["result"] = executor.execute(
                make_request(),
                timeout=None,
            )

        def release_later() -> None:
            sleep(0.1)
            release.set()

        thread = Thread(target=run)
        thread.start()
        self.assertTrue(started.wait(1.0))
        releaser = Thread(target=release_later)
        releaser.start()

        started_counter = perf_counter()
        executor.shutdown(wait=True)
        elapsed = perf_counter() - started_counter

        self.assertGreaterEqual(elapsed, 0.05)
        thread.join(2.0)
        releaser.join(2.0)
        self.assertFalse(thread.is_alive())
        self.assertEqual(
            results["result"].status,
            ToolExecutionStatus.SUCCEEDED,
        )


class ToolExecutorConfigurationTests(unittest.TestCase):
    def test_invalid_max_workers_are_rejected(self) -> None:
        for value in (0, -1, True, "2", 1.5):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    ToolExecutor(ToolRegistry(), max_workers=value)

    def test_invalid_default_timeouts_are_rejected(self) -> None:
        for value in (
            0,
            -1,
            True,
            "1",
            float("inf"),
            float("nan"),
        ):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    ToolExecutor(ToolRegistry(), default_timeout=value)


class ToolExecutorPackageTests(unittest.TestCase):
    def test_package_exports_executor_validation_and_errors(self) -> None:
        self.assertIs(tool_package.ToolExecutor, ToolExecutor)
        self.assertIs(tool_package.ToolHandlerError, ToolHandlerError)
        self.assertIs(
            tool_package.ToolExecutionContext,
            tool_package.contracts.ToolExecutionContext,
        )
        self.assertIs(
            tool_package.ToolArgumentIssue,
            tool_package.validation.ToolArgumentIssue,
        )
        self.assertIs(
            tool_package.validate_arguments,
            tool_package.validation.validate_arguments,
        )
        self.assertIs(
            tool_package.DuplicateHandlerError,
            DuplicateHandlerError,
        )
        self.assertIs(
            tool_package.HandlerNotFoundError,
            HandlerNotFoundError,
        )


if __name__ == "__main__":
    unittest.main()
