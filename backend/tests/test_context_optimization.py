"""Tests for Phase 3A bounded model-facing tool output.

These tests cover the projection helper, the message formatter, Phase 2 raw
output protection, and Ollama / Qwen3 / Gemini integration. They do not modify
or replace any existing tests.
"""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx

from backend.agent.erp.config import ErpDatabaseConfig
from backend.agent.erp.definitions import ERP_TOOL_DEFINITIONS_BY_NAME
from backend.agent.erp.platform import ErpToolPlatform
from backend.agent.llm.client import OllamaClient
from backend.agent.llm.config import LlmConfig
from backend.agent.llm.llamacpp import LlamaCppClient, LlamaCppConfig
from backend.agent.orchestration.context import (
    MAX_NESTED_LIST_ITEMS,
    MAX_TOOL_OUTPUT_MESSAGE_CHARS,
    MAX_TOP_LEVEL_LIST_ITEMS,
    estimate_tokens,
    format_tool_output_message,
    project_tool_output,
)
from backend.agent.orchestration.dependencies import (
    DependencyStep,
    resolve_argument_dependencies,
)
from backend.agent.orchestration.models import ToolCallSummary
from backend.agent.orchestration.orchestrator import AgentOrchestrator
from backend.agent.tools.contracts import (
    ToolDefinition,
    ToolExecutionResult,
    ToolExecutionStatus,
)
from backend.agent.tools.registry import ToolRegistry
from backend.ai_providers.gemini.adapter import (
    GeminiLlmClientAdapter,
    _tool_feedback_payload,
)
from backend.ai_providers.gemini.config import GeminiConfig
from backend.ai_providers.gemini.models import GeminiChatRole
from backend.tests.erp_support import create_erp_fixture_db


def _definition(name: str) -> Any:
    return ERP_TOOL_DEFINITIONS_BY_NAME[name]


def _step(
    number: int,
    tool_name: str,
    output: Any | None,
    *,
    status: str = ToolExecutionStatus.SUCCEEDED.value,
) -> DependencyStep:
    return DependencyStep(
        step_number=number,
        tool_name=tool_name,
        status=status,
        output=output,
    )


def _product(index: int) -> dict[str, Any]:
    return {
        "product_id": f"PRD{index:03d}",
        "sku": f"SKU-{index:03d}",
        "product_name": f"Product {index}",
        "category": "Bolts",
        "material": "Stainless Steel",
        "size": "M10",
        "grade": "SS304",
        "unit": "pieces",
    }


def _inventory_row(index: int) -> dict[str, Any]:
    return {
        "product_id": f"PRD{index:03d}",
        "product_name": f"Product {index}",
        "warehouse_id": f"WH{index % 2 + 1:03d}",
        "warehouse_name": "Warehouse",
        "on_hand_qty": 100,
        "reserved_qty": 10,
        "free_stock": 90,
        "reorder_level": 50,
        "low_stock": False,
    }


def _sales_order(index: int, item_count: int = 10) -> dict[str, Any]:
    return {
        "order": {
            "so_id": f"SO{index:03d}",
            "customer_id": f"CUS{index:03d}",
            "customer_name": f"Customer {index}",
            "order_date": "2026-01-01",
            "required_date": "2026-01-05",
            "status": "Pending",
        },
        "items": [
            {
                "product_id": f"PRD{item:03d}",
                "product_name": f"Product {item}",
                "ordered_qty": 10,
            }
            for item in range(item_count)
        ],
        "items_row_count": item_count,
        "items_truncated": False,
    }


def _sales_order_search(
    count: int = 20,
    item_count: int = 10,
) -> dict[str, Any]:
    return {
        "items": [_sales_order(index, item_count) for index in range(count)],
        "row_count": count,
        "truncated": False,
    }


def _inventory_result(count: int = 50) -> dict[str, Any]:
    return {
        "items": [_inventory_row(index) for index in range(count)],
        "row_count": count,
        "truncated": False,
    }


def _analytics_result(count: int = 20) -> dict[str, Any]:
    return {
        "group_by": "month",
        "basis": "dispatched",
        "currency": "INR",
        "rows": [
            {
                "key": f"2026-{index:02d}",
                "label": f"2026-{index:02d}",
                "orders": 3,
                "units": 100,
                "revenue": 1200.0,
                "cost": 800.0,
                "gross_profit": 400.0,
                "gross_margin_pct": 33.3,
            }
            for index in range(1, count + 1)
        ],
        "totals": {
            "orders": 60,
            "units": 2000,
            "revenue": 24000.0,
            "cost": 16000.0,
            "gross_profit": 8000.0,
            "gross_margin_pct": 33.3,
        },
        "row_count": count,
        "truncated": False,
        "notes": ["Standard cost basis"],
    }


def _payload_after_prefix(message: str, tool_name: str) -> Any:
    prefix = f"Tool `{tool_name}` output:\n"
    if not message.startswith(prefix):
        raise AssertionError(f"missing exact tool output prefix: {prefix!r}")
    return json.loads(message[len(prefix) :])


class _StaticRunner:
    """Return one prepared successful result without touching the ERP."""

    def __init__(self, output: Any) -> None:
        self.output = output
        self.calls = 0

    def execute(self, request: Any) -> ToolExecutionResult:
        self.calls += 1
        now = datetime.now(timezone.utc)
        return ToolExecutionResult(
            execution_id=f"exec-{self.calls}",
            tool_name=request.tool_name,
            status=ToolExecutionStatus.SUCCEEDED,
            output=self.output,
            started_at=now,
            finished_at=now,
            duration_ms=1.0,
        )


def _large_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="test.large_result",
            description="Return a large result for context projection tests.",
            input_schema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        )
    )
    return registry


class TestProjectionBasics(unittest.TestCase):
    """Pure projection and message-formatting behavior."""

    def test_exact_existing_tool_output_message_prefix(self) -> None:
        message = format_tool_output_message(
            "erp.products.search",
            {"items": [], "row_count": 0, "truncated": False},
        )
        payload = _payload_after_prefix(message, "erp.products.search")

        self.assertEqual(payload["row_count"], 0)
        self.assertEqual(payload["items"], [])

    def test_projection_is_valid_json_for_common_shapes(self) -> None:
        outputs = (
            {},
            [],
            None,
            42,
            "plain text",
            {"items": [_product(index) for index in range(3)]},
            [_product(index) for index in range(3)],
            {"nested": {"items": [{"value": 1}, {"value": 2}]}},
        )
        for output in outputs:
            with self.subTest(output=output):
                projected = project_tool_output("test.tool", output)
                json.dumps(projected)

    def test_preserves_totals_and_row_count(self) -> None:
        output = _analytics_result()
        projected = project_tool_output("erp.finance.sales_summary", output)

        self.assertEqual(projected["row_count"], 20)
        self.assertEqual(projected["totals"], output["totals"])
        self.assertEqual(projected["notes"], output["notes"])
        self.assertEqual(projected["group_by"], "month")
        self.assertEqual(projected["basis"], "dispatched")
        self.assertEqual(projected["currency"], "INR")

    def test_preserves_erp_truncation_indicators(self) -> None:
        output = {
            "items": [_product(index) for index in range(20)],
            "row_count": 100,
            "truncated": True,
        }
        projected = project_tool_output("erp.products.search", output)

        self.assertIs(projected["truncated"], True)
        self.assertEqual(projected["row_count"], 100)
        self.assertIs(projected["context_truncated"], True)

    def test_preserves_nested_erp_truncation_indicators(self) -> None:
        order = _sales_order(1, 10)
        order["items_truncated"] = True
        order["items_row_count"] = 100
        output = {"items": [order], "row_count": 1, "truncated": False}

        projected = project_tool_output("erp.sales_orders.get", output)
        projected_order = projected["items"][0]

        self.assertIs(projected_order["items_truncated"], True)
        self.assertEqual(projected_order["items_row_count"], 100)
        self.assertEqual(projected_order["order"]["so_id"], "SO001")

    def test_top_level_list_limit(self) -> None:
        output = _inventory_result(50)
        projected = project_tool_output("erp.inventory.list", output)

        self.assertEqual(len(projected["items"]), MAX_TOP_LEVEL_LIST_ITEMS)
        self.assertIs(projected["context_truncated"], True)
        self.assertEqual(
            projected["context_items_shown"],
            MAX_TOP_LEVEL_LIST_ITEMS,
        )
        self.assertEqual(
            projected["context_items_omitted"],
            50 - MAX_TOP_LEVEL_LIST_ITEMS,
        )
        self.assertEqual(projected["row_count"], 50)

    def test_top_level_list_output_is_bounded(self) -> None:
        output = [_product(index) for index in range(20)]
        projected = project_tool_output("test.tool", output)

        self.assertEqual(len(projected["items"]), MAX_TOP_LEVEL_LIST_ITEMS)
        self.assertIs(projected["context_truncated"], True)
        self.assertEqual(
            projected["context_items_omitted"],
            20 - MAX_TOP_LEVEL_LIST_ITEMS,
        )

    def test_nested_list_limit(self) -> None:
        output = _sales_order_search(count=3, item_count=10)
        projected = project_tool_output("erp.sales_orders.search", output)

        self.assertEqual(len(projected["items"]), 3)
        for order in projected["items"]:
            self.assertEqual(len(order["items"]), MAX_NESTED_LIST_ITEMS)
            self.assertIs(order["context_truncated"], True)
            self.assertEqual(
                order["context_items_shown"],
                MAX_NESTED_LIST_ITEMS,
            )
            self.assertEqual(
                order["context_items_omitted"],
                10 - MAX_NESTED_LIST_ITEMS,
            )

        # Root metadata still advertises that nested data was bounded.
        self.assertIs(projected["context_truncated"], True)
        self.assertEqual(
            projected["context_items_omitted"],
            3 * (10 - MAX_NESTED_LIST_ITEMS),
        )

    def test_context_metadata_distinguishes_truncation(self) -> None:
        output = {
            "items": [_product(index) for index in range(20)],
            "row_count": 100,
            "truncated": True,
        }
        projected = project_tool_output("erp.products.search", output)

        self.assertIs(projected["truncated"], True)
        self.assertIs(projected["context_truncated"], True)
        self.assertIn("not ERP-level", projected["context_note"])
        self.assertIn("omitted records do not exist", projected["context_note"])

    def test_small_output_has_no_context_metadata(self) -> None:
        output = {"items": [_product(0)], "row_count": 1, "truncated": False}
        projected = project_tool_output("erp.products.search", output)

        self.assertNotIn("context_truncated", projected)
        self.assertNotIn("context_items_shown", projected)
        self.assertNotIn("context_items_omitted", projected)

    def test_original_output_is_not_mutated(self) -> None:
        output = _sales_order_search(count=20, item_count=10)
        snapshot = copy.deepcopy(output)

        project_tool_output("erp.sales_orders.search", output)
        format_tool_output_message("erp.sales_orders.search", output)

        self.assertEqual(output, snapshot)

    def test_empty_and_scalar_outputs(self) -> None:
        self.assertEqual(project_tool_output("test.tool", {}), {})
        self.assertEqual(project_tool_output("test.tool", []), [])
        self.assertEqual(project_tool_output("test.tool", 42), 42)
        self.assertEqual(project_tool_output("test.tool", "ok"), "ok")
        self.assertIsNone(project_tool_output("test.tool", None))

        message = format_tool_output_message("test.tool", {})
        self.assertEqual(
            _payload_after_prefix(message, "test.tool"),
            {},
        )

    def test_scalar_string_is_bounded(self) -> None:
        message = format_tool_output_message("test.tool", "x" * 100_000)

        self.assertLessEqual(len(message), MAX_TOOL_OUTPUT_MESSAGE_CHARS)
        payload = _payload_after_prefix(message, "test.tool")
        self.assertIs(payload["context_truncated"], True)
        self.assertIn("value", payload)
        self.assertLess(len(payload["value"]), 100_000)

    def test_estimate_tokens(self) -> None:
        self.assertEqual(estimate_tokens(""), 0)
        self.assertEqual(estimate_tokens("abcd"), 1)
        self.assertEqual(estimate_tokens("a" * 400), 100)


class TestProjectionSizeBounds(unittest.TestCase):
    """Strict size limits for realistic and pathological outputs."""

    def test_large_sales_order_result_is_bounded(self) -> None:
        output = _sales_order_search(count=50, item_count=100)
        message = format_tool_output_message(
            "erp.sales_orders.search",
            output,
        )

        self.assertLessEqual(len(message), MAX_TOOL_OUTPUT_MESSAGE_CHARS)
        payload = _payload_after_prefix(message, "erp.sales_orders.search")
        self.assertEqual(payload["row_count"], 50)
        self.assertLessEqual(
            len(payload["items"]),
            MAX_TOP_LEVEL_LIST_ITEMS,
        )
        for order in payload["items"]:
            self.assertLessEqual(
                len(order["items"]),
                MAX_NESTED_LIST_ITEMS,
            )
        self.assertIs(payload["context_truncated"], True)
        self.assertGreater(payload["context_items_omitted"], 0)

    def test_large_inventory_result_is_bounded(self) -> None:
        output = _inventory_result(50)
        message = format_tool_output_message("erp.inventory.list", output)

        self.assertLessEqual(len(message), MAX_TOOL_OUTPUT_MESSAGE_CHARS)
        payload = _payload_after_prefix(message, "erp.inventory.list")
        self.assertEqual(payload["row_count"], 50)
        self.assertLessEqual(
            len(payload["items"]),
            MAX_TOP_LEVEL_LIST_ITEMS,
        )
        self.assertIs(payload["context_truncated"], True)

    def test_strict_maximum_message_size(self) -> None:
        orders = []
        for index in range(50):
            order = _sales_order(index, 100)
            order["order"]["customer_name"] = "N" * 5000
            orders.append(order)

        output = {
            "items": orders,
            "row_count": 50,
            "truncated": True,
            "notes": ["N" * 5000 for _ in range(20)],
            "totals": {"orders": 50, "revenue": 1.0},
        }
        message = format_tool_output_message(
            "erp.sales_orders.search",
            output,
        )

        self.assertLessEqual(len(message), MAX_TOOL_OUTPUT_MESSAGE_CHARS)
        payload = _payload_after_prefix(message, "erp.sales_orders.search")
        self.assertEqual(payload["row_count"], 50)
        self.assertIs(payload["truncated"], True)
        self.assertEqual(payload["totals"]["orders"], 50)
        self.assertLessEqual(len(payload["notes"]), 5)

    def test_final_compact_preserves_nested_header(self) -> None:
        output = {
            "order": {
                "so_id": "SO001",
                "customer_id": "CUS001",
                "customer_name": "N" * 100_000,
                "order_date": "2026-01-01",
                "required_date": "2026-01-05",
                "status": "Pending",
            },
            "items": [
                {
                    "product_id": f"PRD{index:03d}",
                    "product_name": "Item",
                    "ordered_qty": 1,
                }
                for index in range(100)
            ],
            "items_row_count": 100,
            "items_truncated": True,
        }
        message = format_tool_output_message(
            "erp.sales_orders.get",
            output,
        )

        self.assertLessEqual(len(message), MAX_TOOL_OUTPUT_MESSAGE_CHARS)
        payload = _payload_after_prefix(message, "erp.sales_orders.get")
        self.assertEqual(payload["order"]["so_id"], "SO001")
        self.assertEqual(payload["items_row_count"], 100)
        self.assertIs(payload["items_truncated"], True)
        self.assertLess(len(payload["order"]["customer_name"]), 100_000)

    def test_pathological_output_is_bounded(self) -> None:
        output = {
            "payload": "x" * 200_000,
            "row_count": 1,
            "truncated": False,
        }
        message = format_tool_output_message("test.tool", output)

        self.assertLessEqual(len(message), MAX_TOOL_OUTPUT_MESSAGE_CHARS)
        payload = _payload_after_prefix(message, "test.tool")
        self.assertEqual(payload["row_count"], 1)
        self.assertIs(payload["truncated"], False)
        self.assertIn("payload", payload)
        self.assertLess(len(payload["payload"]), 200_000)


class TestPhase2Protection(unittest.TestCase):
    """Phase 2 must continue to read the full raw output."""

    def test_phase2_resolves_field_omitted_from_model_view(self) -> None:
        output = {
            "items": [
                {
                    "product_id": f"PRD{index:03d}",
                    "product_name": f"Product {index}",
                }
                for index in range(20)
            ],
            "row_count": 20,
            "truncated": False,
        }
        steps = [
            _step(1, "erp.products.search", output),
        ]

        resolved, issues = resolve_argument_dependencies(
            {"product_id": "$steps.step_1.items[15].product_id"},
            _definition("erp.inventory.get"),
            steps,
        )

        self.assertEqual(issues, [])
        self.assertEqual(resolved, {"product_id": "PRD015"})

        projected = project_tool_output("erp.products.search", output)
        self.assertEqual(len(projected["items"]), MAX_TOP_LEVEL_LIST_ITEMS)
        self.assertNotIn("PRD015", json.dumps(projected))

    def test_phase2_raw_output_remains_unchanged(self) -> None:
        output = _sales_order_search(count=20, item_count=10)
        snapshot = copy.deepcopy(output)
        step = _step(1, "erp.sales_orders.search", output)

        message = format_tool_output_message(
            "erp.sales_orders.search",
            output,
        )
        projected = project_tool_output("erp.sales_orders.search", output)

        self.assertEqual(step.output, snapshot)
        self.assertEqual(output, snapshot)
        self.assertEqual(len(output["items"]), 20)
        self.assertLessEqual(len(projected["items"]), 10)
        self.assertLessEqual(len(message), MAX_TOOL_OUTPUT_MESSAGE_CHARS)

    def test_step_numbering_remains_unchanged(self) -> None:
        steps = [
            _step(
                1,
                "erp.products.get",
                None,
                status=ToolExecutionStatus.FAILED.value,
            ),
            _step(
                2,
                "erp.products.get",
                {"product_id": "PRD001"},
            ),
        ]

        resolved, issues = resolve_argument_dependencies(
            {"product_id": "$steps.step_2.product_id"},
            _definition("erp.products.get"),
            steps,
        )
        self.assertEqual(issues, [])
        self.assertEqual(resolved, {"product_id": "PRD001"})

        _, failed_issues = resolve_argument_dependencies(
            {"product_id": "$steps.step_1.product_id"},
            _definition("erp.products.get"),
            steps,
        )
        self.assertTrue(failed_issues)
        self.assertEqual(failed_issues[0].code, "step_not_successful")


class _PlatformHarness(unittest.TestCase):
    """Shared fixture ERP platform for provider integration tests."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.db_path = Path(self.temp_dir.name) / "fixture_erp.db"
        create_erp_fixture_db(self.db_path)

        self.erp_config = ErpDatabaseConfig(
            self.db_path,
            query_timeout_seconds=5.0,
        )
        self.platform = ErpToolPlatform.from_config(self.erp_config)
        self.addCleanup(self.platform.close)

    def _ollama_orchestrator(
        self,
        responses: list[dict[str, Any]],
        *,
        runner: Any | None = None,
        registry: ToolRegistry | None = None,
        max_tool_calls: int = 5,
    ) -> tuple[AgentOrchestrator, list[dict[str, Any]]]:
        response_iter = iter(responses)
        chat_requests: list[dict[str, Any]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/tags":
                return httpx.Response(
                    200,
                    json={"models": [{"name": "llama3.2:latest"}]},
                )
            if request.url.path == "/api/chat":
                chat_requests.append(json.loads(request.content))
                try:
                    payload = next(response_iter)
                except StopIteration:
                    payload = {
                        "thought": "No more scripted responses",
                        "action": "final_answer",
                        "final_answer": "No further information.",
                    }
                return httpx.Response(
                    200,
                    json={
                        "model": "llama3.2",
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(payload),
                        },
                    },
                )
            return httpx.Response(404, text="Not found")

        http_client = httpx.Client(transport=httpx.MockTransport(handler))
        self.addCleanup(http_client.close)
        client = OllamaClient(LlmConfig(), http_client=http_client)
        orchestrator = AgentOrchestrator(
            client=client,
            runner=runner or self.platform.runner,
            registry=registry or self.platform.registry,
            max_tool_calls=max_tool_calls,
        )
        return orchestrator, chat_requests

    def _qwen_orchestrator(
        self,
        decisions: list[dict[str, Any]],
    ) -> tuple[AgentOrchestrator, list[dict[str, Any]]]:
        decision_iter = iter(decisions)
        chat_requests: list[dict[str, Any]] = []

        def completion(content: str) -> dict[str, Any]:
            return {
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "model": "qwen3-test",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": content,
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                },
                "timings": {"prompt_ms": 1.0, "predicted_ms": 1.0},
            }

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/v1/models":
                return httpx.Response(
                    200,
                    json={
                        "object": "list",
                        "data": [{"id": "qwen3-1.7b", "object": "model"}],
                    },
                )
            if request.url.path == "/v1/chat/completions":
                chat_requests.append(json.loads(request.content))
                try:
                    decision = next(decision_iter)
                except StopIteration:
                    decision = {
                        "thought": "No more scripted responses",
                        "action": "final_answer",
                        "final_answer": "No further information.",
                    }
                return httpx.Response(
                    200,
                    json=completion(json.dumps(decision)),
                )
            return httpx.Response(404, text="Not found")

        http_client = httpx.Client(transport=httpx.MockTransport(handler))
        self.addCleanup(http_client.close)
        client = LlamaCppClient(LlamaCppConfig(), http_client=http_client)
        orchestrator = AgentOrchestrator(
            client=client,
            runner=self.platform.runner,
            registry=self.platform.registry,
        )
        return orchestrator, chat_requests


class TestOllamaProjectionIntegration(_PlatformHarness):
    """Ollama receives bounded JSON with the existing prefix."""

    def test_ollama_message_compatibility(self) -> None:
        orchestrator, chat_requests = self._ollama_orchestrator(
            [
                {
                    "thought": "List products",
                    "action": "call_tool",
                    "tool_name": "erp.products.search",
                    "arguments": {"limit": 20},
                },
                {
                    "thought": "Answer",
                    "action": "final_answer",
                    "final_answer": "Products listed.",
                },
            ]
        )

        result = orchestrator.process_question("List products")

        self.assertEqual(result.status, "completed")
        tool_message = chat_requests[1]["messages"][-1]["content"]
        payload = _payload_after_prefix(
            tool_message,
            "erp.products.search",
        )
        self.assertIn("items", payload)
        self.assertLessEqual(len(tool_message), MAX_TOOL_OUTPUT_MESSAGE_CHARS)

        raw_output = result.tool_calls[0].output
        self.assertIsInstance(raw_output, dict)
        self.assertEqual(len(raw_output["items"]), 5)
        self.assertNotIn("context_truncated", raw_output)

    def test_ollama_large_output_is_bounded_and_raw_is_preserved(self) -> None:
        output = _sales_order_search(count=50, item_count=100)
        runner = _StaticRunner(output)
        registry = _large_registry()
        orchestrator, chat_requests = self._ollama_orchestrator(
            [
                {
                    "thought": "Get large result",
                    "action": "call_tool",
                    "tool_name": "test.large_result",
                    "arguments": {},
                },
                {
                    "thought": "Answer",
                    "action": "final_answer",
                    "final_answer": "Done.",
                },
            ],
            runner=runner,
            registry=registry,
        )

        result = orchestrator.process_question("Get the large result")

        self.assertEqual(result.status, "completed")
        tool_message = chat_requests[1]["messages"][-1]["content"]
        payload = _payload_after_prefix(tool_message, "test.large_result")
        self.assertLessEqual(len(tool_message), MAX_TOOL_OUTPUT_MESSAGE_CHARS)
        self.assertIs(payload["context_truncated"], True)
        self.assertEqual(payload["row_count"], 50)
        self.assertLessEqual(len(payload["items"]), 10)

        # The full raw output remains available for grounding and Phase 2.
        self.assertEqual(result.tool_calls[0].output, output)
        self.assertEqual(len(result.tool_calls[0].output["items"]), 50)


class TestQwen3ProjectionIntegration(_PlatformHarness):
    """Qwen3 (llama.cpp) receives bounded JSON with the existing prefix."""

    def test_qwen3_message_compatibility(self) -> None:
        orchestrator, chat_requests = self._qwen_orchestrator(
            [
                {
                    "thought": "List sales orders",
                    "action": "call_tool",
                    "tool_name": "erp.sales_orders.search",
                    "arguments": {},
                },
                {
                    "thought": "Answer",
                    "action": "final_answer",
                    "final_answer": "Sales orders listed.",
                },
            ]
        )

        result = orchestrator.process_question("List sales orders")

        self.assertEqual(result.status, "completed")
        tool_message = chat_requests[1]["messages"][-1]["content"]
        payload = _payload_after_prefix(
            tool_message,
            "erp.sales_orders.search",
        )
        self.assertIn("items", payload)
        self.assertLessEqual(len(tool_message), MAX_TOOL_OUTPUT_MESSAGE_CHARS)
        self.assertEqual(len(result.tool_calls[0].output["items"]), 2)


def _gemini_response(
    *,
    content: str = "",
    function_calls: list[dict[str, Any]] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        content=content,
        model="gemini-test",
        duration_ms=1.0,
        request_duration_ms=1.0,
        finish_reason="STOP",
        truncated=False,
        function_calls=function_calls or [],
    )


class _ScriptedGeminiClient:
    """Minimal Gemini client double that records converted messages."""

    def __init__(self, responses: list[SimpleNamespace]) -> None:
        self._responses = iter(responses)
        self.messages: list[list[Any]] = []
        self.calls = 0

    def chat(self, messages, **kwargs):  # type: ignore[no-untyped-def]
        self.calls += 1
        self.messages.append(list(messages))
        try:
            return next(self._responses)
        except StopIteration:
            return _gemini_response(content="Done.")

    def validate_availability(self) -> None:
        return None

    def close(self) -> None:
        return None


class TestGeminiProjectionIntegration(_PlatformHarness):
    """Gemini's adapter parses the bounded JSON and keeps native batches."""

    def test_gemini_projected_json_parsing(self) -> None:
        output = _inventory_result(50)
        message = format_tool_output_message("erp.inventory.list", output)
        payload = _tool_feedback_payload("erp.inventory.list", message)

        self.assertIn("output", payload)
        self.assertEqual(payload["output"]["row_count"], 50)
        self.assertIs(payload["output"]["context_truncated"], True)

    def test_gemini_native_batch_regression(self) -> None:
        client = _ScriptedGeminiClient(
            [
                _gemini_response(
                    function_calls=[
                        {
                            "id": "call-1",
                            "name": "erp.products.search",
                            "arguments": {"limit": 20},
                            "thought_signature": None,
                        }
                    ]
                ),
                _gemini_response(content="Products listed."),
            ]
        )
        adapter = GeminiLlmClientAdapter(
            GeminiConfig(api_key="test-key-12345"),
            client=client,  # type: ignore[arg-type]
            tool_registry=self.platform.registry,
        )
        orchestrator = AgentOrchestrator(
            client=adapter,
            runner=self.platform.runner,
            registry=self.platform.registry,
        )

        result = orchestrator.process_question("List products")

        self.assertEqual(result.status, "completed")
        self.assertEqual(len(result.tool_calls), 1)
        self.assertEqual(result.tool_calls[0].tool_name, "erp.products.search")

        tool_messages = [
            message
            for message in client.messages[1]
            if message.role is GeminiChatRole.TOOL
        ]
        self.assertEqual(len(tool_messages), 1)
        self.assertLessEqual(
            len(tool_messages[0].content),
            MAX_TOOL_OUTPUT_MESSAGE_CHARS,
        )
        payload = json.loads(tool_messages[0].content)
        self.assertIn("output", payload)
        self.assertEqual(len(payload["output"]["items"]), 5)

    def test_gemini_large_batch_output_is_bounded(self) -> None:
        output = _sales_order_search(count=50, item_count=100)
        runner = _StaticRunner(output)
        registry = _large_registry()
        client = _ScriptedGeminiClient(
            [
                _gemini_response(
                    function_calls=[
                        {
                            "id": "call-1",
                            "name": "test.large_result",
                            "arguments": {},
                            "thought_signature": None,
                        }
                    ]
                ),
                _gemini_response(content="Done."),
            ]
        )
        adapter = GeminiLlmClientAdapter(
            GeminiConfig(api_key="test-key-12345"),
            client=client,  # type: ignore[arg-type]
            tool_registry=registry,
        )
        orchestrator = AgentOrchestrator(
            client=adapter,
            runner=runner,
            registry=registry,
        )

        result = orchestrator.process_question("Get the large result")

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.tool_calls[0].output, output)
        self.assertEqual(len(result.tool_calls[0].output["items"]), 50)

        tool_messages = [
            message
            for message in client.messages[1]
            if message.role is GeminiChatRole.TOOL
        ]
        self.assertEqual(len(tool_messages), 1)
        self.assertLessEqual(
            len(tool_messages[0].content),
            MAX_TOOL_OUTPUT_MESSAGE_CHARS,
        )
        payload = json.loads(tool_messages[0].content)
        self.assertIs(payload["output"]["context_truncated"], True)


class TestFallbackCompatibility(unittest.TestCase):
    """The deterministic fallback still uses the raw output and its own cap."""

    def test_existing_fallback_behavior_remains_unchanged(self) -> None:
        output = _sales_order_search(count=50, item_count=100)
        summary = ToolCallSummary(
            tool_name="erp.sales_orders.search",
            arguments={},
            status=ToolExecutionStatus.SUCCEEDED.value,
            output=output,
        )

        answer = AgentOrchestrator._fallback_answer(
            [summary],
            [("erp.sales_orders.search", output)],
        )

        self.assertIn("erp.sales_orders.search", answer)
        self.assertIn("... (truncated)", answer)
        self.assertNotIn("context_truncated", answer)
        self.assertNotIn("context_items_omitted", answer)


if __name__ == "__main__":
    unittest.main()
