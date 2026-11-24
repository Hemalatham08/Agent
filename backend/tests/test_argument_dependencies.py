"""Tests for Phase 2 argument dependency injection.

These tests cover the pure ``$steps`` resolver, Ollama/Qwen3 integration, and
Gemini native ``call_tools`` batching. They do not modify or replace any
existing tests.
"""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
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
from backend.agent.orchestration.dependencies import (
    DependencyStep,
    format_dependency_feedback,
    resolve_argument_dependencies,
)
from backend.agent.orchestration.orchestrator import AgentOrchestrator
from backend.agent.tools.contracts import (
    ToolDefinition,
    ToolExecutionStatus,
)
from backend.agent.tools.validation import validate_arguments
from backend.ai_providers.gemini.adapter import GeminiLlmClientAdapter
from backend.ai_providers.gemini.config import GeminiConfig
from backend.tests.erp_support import create_erp_fixture_db


def _definition(name: str) -> ToolDefinition:
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


class TestDependencyReferenceResolution(unittest.TestCase):
    """Pure resolver behavior for valid references."""

    def test_resolves_flat_product_id(self) -> None:
        resolved, issues = resolve_argument_dependencies(
            {"product_id": "$steps.step_1.product_id"},
            _definition("erp.products.get"),
            [
                _step(
                    1,
                    "erp.products.get",
                    {"product_id": "PRD001", "product_name": "Hex Bolt M10"},
                )
            ],
        )

        self.assertEqual(issues, [])
        self.assertEqual(resolved, {"product_id": "PRD001"})

    def test_resolves_nested_items_index(self) -> None:
        resolved, issues = resolve_argument_dependencies(
            {"product_id": "$steps.step_1.items[1].product_id"},
            _definition("erp.inventory.get"),
            [
                _step(
                    1,
                    "erp.products.search",
                    {
                        "items": [
                            {"product_id": "PRD001"},
                            {"product_id": "PRD002"},
                        ],
                        "row_count": 2,
                        "truncated": False,
                    },
                )
            ],
        )

        self.assertEqual(issues, [])
        self.assertEqual(resolved, {"product_id": "PRD002"})

    def test_resolves_order_customer_id(self) -> None:
        resolved, issues = resolve_argument_dependencies(
            {"query": "$steps.step_1.order.customer_id"},
            _definition("erp.sales_orders.search"),
            [
                _step(
                    1,
                    "erp.sales_orders.get",
                    {
                        "order": {
                            "so_id": "SO001",
                            "customer_id": "CUS001",
                        },
                        "items": [],
                    },
                )
            ],
        )

        self.assertEqual(issues, [])
        self.assertEqual(resolved, {"query": "CUS001"})

    def test_resolves_multiple_references(self) -> None:
        resolved, issues = resolve_argument_dependencies(
            {
                "product_id": "$steps.step_1.items[0].product_id",
                "warehouse_id": "$steps.step_2.items[0].warehouse_id",
            },
            _definition("erp.inventory.get"),
            [
                _step(
                    1,
                    "erp.products.search",
                    {"items": [{"product_id": "PRD001"}]},
                ),
                _step(
                    2,
                    "erp.warehouses.list",
                    {"items": [{"warehouse_id": "WH001"}]},
                ),
            ],
        )

        self.assertEqual(issues, [])
        self.assertEqual(
            resolved,
            {"product_id": "PRD001", "warehouse_id": "WH001"},
        )

    def test_preserves_literal_arguments(self) -> None:
        resolved, issues = resolve_argument_dependencies(
            {
                "product_id": "PRD001",
                "warehouse_id": "$steps.step_1.items[0].warehouse_id",
                "query": "$step_not_a_reference",
            },
            _definition("erp.inventory.get"),
            [
                _step(
                    1,
                    "erp.warehouses.list",
                    {"items": [{"warehouse_id": "WH002"}]},
                )
            ],
        )

        self.assertEqual(issues, [])
        self.assertEqual(resolved["product_id"], "PRD001")
        self.assertEqual(resolved["warehouse_id"], "WH002")
        # Only the reserved "$steps." prefix is treated as a reference.
        self.assertEqual(resolved["query"], "$step_not_a_reference")

    def test_does_not_mutate_inputs_or_outputs(self) -> None:
        arguments = {
            "product_id": "$steps.step_1.product_id",
            "limit": 5,
        }
        argument_snapshot = copy.deepcopy(arguments)
        output = {"product_id": "PRD001", "items": [{"sku": "HEX-M10-SS304"}]}
        output_snapshot = copy.deepcopy(output)
        steps = [_step(1, "erp.products.get", output)]

        resolved, issues = resolve_argument_dependencies(
            arguments,
            _definition("erp.products.get"),
            steps,
        )

        self.assertEqual(issues, [])
        self.assertEqual(arguments, argument_snapshot)
        self.assertEqual(output, output_snapshot)
        self.assertEqual(resolved, {"product_id": "PRD001", "limit": 5})

    def test_resolved_value_still_fails_schema_enum_validation(self) -> None:
        definition = _definition("erp.finance.sales_summary")
        resolved, issues = resolve_argument_dependencies(
            {"group_by": "$steps.step_1.key"},
            definition,
            [_step(1, "erp.finance.sales_summary", {"key": "not_allowed"})],
        )

        self.assertEqual(issues, [])
        self.assertEqual(resolved, {"group_by": "not_allowed"})
        schema_issues = validate_arguments(
            resolved,
            definition.input_schema,
        )
        self.assertTrue(
            any(issue.keyword == "enum" for issue in schema_issues)
        )


class TestDependencyReferenceRejection(unittest.TestCase):
    """Pure resolver behavior for invalid references."""

    def test_rejects_failed_step(self) -> None:
        _, issues = resolve_argument_dependencies(
            {"product_id": "$steps.step_1.product_id"},
            _definition("erp.products.get"),
            [
                _step(
                    1,
                    "erp.products.get",
                    None,
                    status=ToolExecutionStatus.FAILED.value,
                )
            ],
        )

        self.assertTrue(issues)
        self.assertEqual(issues[0].code, "step_not_successful")

    def test_rejects_cancelled_step(self) -> None:
        _, issues = resolve_argument_dependencies(
            {"product_id": "$steps.step_1.product_id"},
            _definition("erp.products.get"),
            [
                _step(
                    1,
                    "erp.products.get",
                    None,
                    status=ToolExecutionStatus.CANCELLED.value,
                )
            ],
        )

        self.assertTrue(issues)
        self.assertEqual(issues[0].code, "step_not_successful")

    def test_rejects_forward_reference(self) -> None:
        _, issues = resolve_argument_dependencies(
            {"product_id": "$steps.step_2.product_id"},
            _definition("erp.products.get"),
            [_step(1, "erp.products.get", {"product_id": "PRD001"})],
        )

        self.assertTrue(issues)
        self.assertEqual(issues[0].code, "unknown_step")

    def test_rejects_missing_key(self) -> None:
        _, issues = resolve_argument_dependencies(
            {"product_id": "$steps.step_1.product_name"},
            _definition("erp.products.get"),
            [_step(1, "erp.products.get", {"product_id": "PRD001"})],
        )

        self.assertTrue(issues)
        self.assertEqual(issues[0].code, "path_not_found")
        self.assertIn("product_name", issues[0].message)

    def test_rejects_out_of_range_index(self) -> None:
        _, issues = resolve_argument_dependencies(
            {"product_id": "$steps.step_1.items[2].product_id"},
            _definition("erp.inventory.get"),
            [
                _step(
                    1,
                    "erp.products.search",
                    {"items": [{"product_id": "PRD001"}]},
                )
            ],
        )

        self.assertTrue(issues)
        self.assertEqual(issues[0].code, "index_out_of_range")

    def test_rejects_private_key_segments(self) -> None:
        for reference in (
            "$steps.step_1.__class__",
            "$steps.step_1._secret",
        ):
            with self.subTest(reference=reference):
                _, issues = resolve_argument_dependencies(
                    {"product_id": reference},
                    _definition("erp.products.get"),
                    [_step(1, "erp.products.get", {"product_id": "PRD001"})],
                )
                self.assertTrue(issues)
                self.assertEqual(issues[0].code, "invalid_reference")

    def test_rejects_malformed_references(self) -> None:
        malformed = (
            "$steps.step_1",
            "$steps.step_0.product_id",
            "$steps.step_01.product_id",
            "$steps.foo.product_id",
            "$steps.step_1.items[-1].product_id",
            "$steps.step_1..product_id",
        )
        for reference in malformed:
            with self.subTest(reference=reference):
                _, issues = resolve_argument_dependencies(
                    {"product_id": reference},
                    _definition("erp.products.get"),
                    [_step(1, "erp.products.get", {"product_id": "PRD001"})],
                )
                self.assertTrue(issues)
                self.assertEqual(issues[0].code, "invalid_reference")

    def test_rejects_oversized_reference(self) -> None:
        reference = "$steps.step_1." + ("a" * 300)
        _, issues = resolve_argument_dependencies(
            {"product_id": reference},
            _definition("erp.products.get"),
            [_step(1, "erp.products.get", {"a": "PRD001"})],
        )

        self.assertTrue(issues)
        self.assertEqual(issues[0].code, "reference_too_long")

    def test_rejects_too_many_path_segments(self) -> None:
        reference = "$steps.step_1." + ".".join(["a"] * 9)
        _, issues = resolve_argument_dependencies(
            {"product_id": reference},
            _definition("erp.products.get"),
            [_step(1, "erp.products.get", {})],
        )

        self.assertTrue(issues)
        self.assertEqual(issues[0].code, "invalid_path")

    def test_rejects_too_many_references(self) -> None:
        definition = ToolDefinition(
            name="test.tool",
            description="test",
            input_schema={
                "type": "object",
                "properties": {
                    f"arg_{index}": {"type": "string"}
                    for index in range(17)
                },
                "additionalProperties": False,
            },
        )
        arguments = {
            f"arg_{index}": "$steps.step_1.value" for index in range(17)
        }

        _, issues = resolve_argument_dependencies(
            arguments,
            definition,
            [_step(1, "test.tool", {"value": "x"})],
        )

        self.assertTrue(issues)
        self.assertTrue(
            any(issue.code == "too_many_references" for issue in issues)
        )

    def test_rejects_type_mismatch(self) -> None:
        _, issues = resolve_argument_dependencies(
            {"product_id": "$steps.step_1.product_id"},
            _definition("erp.products.get"),
            [
                _step(
                    1,
                    "erp.products.get",
                    {"product_id": ["PRD001"]},
                )
            ],
        )

        self.assertTrue(issues)
        self.assertEqual(issues[0].code, "type_mismatch")

    def test_rejects_null_for_required_string(self) -> None:
        _, issues = resolve_argument_dependencies(
            {"product_id": "$steps.step_1.product_id"},
            _definition("erp.products.get"),
            [_step(1, "erp.products.get", {"product_id": None})],
        )

        self.assertTrue(issues)
        self.assertEqual(issues[0].code, "type_mismatch")

    def test_feedback_mentions_reference_and_guidance(self) -> None:
        _, issues = resolve_argument_dependencies(
            {"product_id": "$steps.step_2.product_id"},
            _definition("erp.products.get"),
            [_step(1, "erp.products.get", {"product_id": "PRD001"})],
        )

        feedback = format_dependency_feedback(issues)
        self.assertIn("unresolved dependency references", feedback)
        self.assertIn("$steps.step_2.product_id", feedback)
        self.assertIn("Do not guess identifiers", feedback)


class _PlatformHarness(unittest.TestCase):
    """Shared fixture ERP platform for orchestrator integration tests."""

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


class TestOllamaDependencyInjection(_PlatformHarness):
    """Ollama single-call integration with resolved references."""

    def _orchestrator(
        self,
        responses: list[dict[str, Any]],
        *,
        max_tool_calls: int = 5,
    ) -> tuple[AgentOrchestrator, list[dict[str, Any]]]:
        resp_iter = iter(responses)
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
                    payload = next(resp_iter)
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
            runner=self.platform.runner,
            registry=self.platform.registry,
            max_tool_calls=max_tool_calls,
        )
        return orchestrator, chat_requests

    def test_multi_step_product_inventory_flow(self) -> None:
        orchestrator, _ = self._orchestrator(
            [
                {
                    "thought": "Find the product",
                    "action": "call_tool",
                    "tool_name": "erp.products.search",
                    "arguments": {"query": "Hex Bolt", "limit": 5},
                },
                {
                    "thought": "Check inventory",
                    "action": "call_tool",
                    "tool_name": "erp.inventory.get",
                    "arguments": {
                        "product_id": "$steps.step_1.items[0].product_id"
                    },
                },
                {
                    "thought": "Answer",
                    "action": "final_answer",
                    "final_answer": "Hex Bolt M10 has stock.",
                },
            ]
        )

        res = orchestrator.process_question(
            "How much stock do we have for Hex Bolt M10?"
        )

        self.assertEqual(res.status, "completed")
        self.assertEqual(
            [summary.tool_name for summary in res.tool_calls],
            ["erp.products.search", "erp.inventory.get"],
        )
        self.assertEqual(
            res.tool_calls[1].arguments["product_id"],
            "PRD001",
        )
        self.assertEqual(res.tool_calls[1].status, "succeeded")

    def test_flat_resolution_from_products_get(self) -> None:
        orchestrator, _ = self._orchestrator(
            [
                {
                    "thought": "Get the product",
                    "action": "call_tool",
                    "tool_name": "erp.products.get",
                    "arguments": {"product_id": "PRD001"},
                },
                {
                    "thought": "Check inventory",
                    "action": "call_tool",
                    "tool_name": "erp.inventory.get",
                    "arguments": {
                        "product_id": "$steps.step_1.product_id"
                    },
                },
                {
                    "thought": "Answer",
                    "action": "final_answer",
                    "final_answer": "PRD001 has stock.",
                },
            ]
        )

        res = orchestrator.process_question("Check PRD001 inventory")

        self.assertEqual(res.status, "completed")
        self.assertEqual(
            res.tool_calls[1].arguments["product_id"],
            "PRD001",
        )

    def test_literal_arguments_still_work(self) -> None:
        orchestrator, _ = self._orchestrator(
            [
                {
                    "thought": "Get the product",
                    "action": "call_tool",
                    "tool_name": "erp.products.get",
                    "arguments": {"product_id": "PRD002"},
                },
            ]
        )

        res = orchestrator.process_question("Get product PRD002")

        self.assertEqual(res.status, "completed")
        self.assertEqual(len(res.tool_calls), 1)
        self.assertEqual(res.tool_calls[0].status, "succeeded")
        self.assertEqual(res.tool_calls[0].arguments["product_id"], "PRD002")

    def test_unresolved_reference_returns_feedback_without_executing(self) -> None:
        orchestrator, chat_requests = self._orchestrator(
            [
                {
                    "thought": "Reference a missing step",
                    "action": "call_tool",
                    "tool_name": "erp.inventory.get",
                    "arguments": {
                        "product_id": "$steps.step_1.product_id"
                    },
                },
                {
                    "thought": "Fallback",
                    "action": "call_tool",
                    "tool_name": "erp.warehouses.list",
                    "arguments": {},
                },
            ]
        )

        res = orchestrator.process_question("Check inventory")

        self.assertEqual(res.status, "completed")
        self.assertEqual(
            [summary.tool_name for summary in res.tool_calls],
            ["erp.warehouses.list"],
        )
        feedback = "\n".join(
            message["content"] for message in chat_requests[1]["messages"]
        )
        self.assertIn("unresolved dependency references", feedback)
        self.assertIn("$steps.step_1.product_id", feedback)

    def test_failed_step_cannot_be_referenced(self) -> None:
        orchestrator, chat_requests = self._orchestrator(
            [
                {
                    "thought": "Try a missing product",
                    "action": "call_tool",
                    "tool_name": "erp.products.get",
                    "arguments": {"product_id": "PRD999"},
                },
                {
                    "thought": "Reference the failed step",
                    "action": "call_tool",
                    "tool_name": "erp.inventory.get",
                    "arguments": {
                        "product_id": "$steps.step_1.product_id"
                    },
                },
                {
                    "thought": "Fallback",
                    "action": "call_tool",
                    "tool_name": "erp.warehouses.list",
                    "arguments": {},
                },
            ]
        )

        res = orchestrator.process_question("Get product PRD999 inventory")

        self.assertEqual(
            [summary.tool_name for summary in res.tool_calls],
            ["erp.products.get", "erp.warehouses.list"],
        )
        self.assertEqual(res.tool_calls[0].status, "failed")
        self.assertEqual(res.tool_calls[1].status, "succeeded")
        feedback = "\n".join(
            message["content"] for message in chat_requests[2]["messages"]
        )
        self.assertIn("step_1", feedback)
        self.assertIn("cannot be referenced", feedback)

    def test_dependency_failure_does_not_consume_tool_budget(self) -> None:
        orchestrator, _ = self._orchestrator(
            [
                {
                    "thought": "Bad reference",
                    "action": "call_tool",
                    "tool_name": "erp.inventory.get",
                    "arguments": {
                        "product_id": "$steps.step_1.product_id"
                    },
                },
                {
                    "thought": "Valid call",
                    "action": "call_tool",
                    "tool_name": "erp.warehouses.list",
                    "arguments": {},
                },
            ],
            max_tool_calls=1,
        )

        res = orchestrator.process_question("Check inventory")

        self.assertEqual(res.status, "completed")
        self.assertEqual(len(res.tool_calls), 1)
        self.assertEqual(res.tool_calls[0].tool_name, "erp.warehouses.list")

    def test_duplicate_resolved_call_is_rejected(self) -> None:
        orchestrator, chat_requests = self._orchestrator(
            [
                {
                    "thought": "Find product",
                    "action": "call_tool",
                    "tool_name": "erp.products.search",
                    "arguments": {"query": "Hex Bolt", "limit": 5},
                },
                {
                    "thought": "Check inventory",
                    "action": "call_tool",
                    "tool_name": "erp.inventory.get",
                    "arguments": {
                        "product_id": "$steps.step_1.items[0].product_id"
                    },
                },
                {
                    "thought": "Repeat the same resolved call",
                    "action": "call_tool",
                    "tool_name": "erp.inventory.get",
                    "arguments": {
                        "product_id": "$steps.step_1.items[0].product_id"
                    },
                },
                {
                    "thought": "Answer",
                    "action": "final_answer",
                    "final_answer": "Inventory checked.",
                },
            ]
        )

        res = orchestrator.process_question("Check Hex Bolt inventory")

        self.assertEqual(res.status, "completed")
        self.assertEqual(
            [summary.tool_name for summary in res.tool_calls],
            ["erp.products.search", "erp.inventory.get"],
        )
        feedback = "\n".join(
            message["content"] for message in chat_requests[3]["messages"]
        )
        self.assertIn("already called", feedback)

    def test_reference_cannot_authorize_unknown_tool(self) -> None:
        orchestrator, _ = self._orchestrator(
            [
                {
                    "thought": "Try an unknown tool with a reference",
                    "action": "call_tool",
                    "tool_name": "erp.fake.tool",
                    "arguments": {
                        "product_id": "$steps.step_1.product_id"
                    },
                },
                {
                    "thought": "Fallback",
                    "action": "call_tool",
                    "tool_name": "erp.warehouses.list",
                    "arguments": {},
                },
            ]
        )

        res = orchestrator.process_question("List warehouses")

        self.assertEqual(
            [summary.tool_name for summary in res.tool_calls],
            ["erp.warehouses.list"],
        )


class TestQwen3DependencyCompatibility(_PlatformHarness):
    """Qwen3 (llama.cpp) integration with resolved references."""

    @staticmethod
    def _completion(content: str) -> dict[str, Any]:
        return {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "model": "qwen3-test",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
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

    def _orchestrator(
        self,
        decisions: list[dict[str, Any]],
    ) -> AgentOrchestrator:
        decision_iter = iter(decisions)

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
                    json=self._completion(json.dumps(decision)),
                )
            return httpx.Response(404, text="Not found")

        http_client = httpx.Client(transport=httpx.MockTransport(handler))
        self.addCleanup(http_client.close)
        client = LlamaCppClient(LlamaCppConfig(), http_client=http_client)
        return AgentOrchestrator(
            client=client,
            runner=self.platform.runner,
            registry=self.platform.registry,
        )

    def test_qwen3_resolves_step_reference(self) -> None:
        orchestrator = self._orchestrator(
            [
                {
                    "thought": "Find product",
                    "action": "call_tool",
                    "tool_name": "erp.products.search",
                    "arguments": {"query": "Hex Bolt", "limit": 5},
                },
                {
                    "thought": "Check inventory",
                    "action": "call_tool",
                    "tool_name": "erp.inventory.get",
                    "arguments": {
                        "product_id": "$steps.step_1.items[0].product_id"
                    },
                },
                {
                    "thought": "Answer",
                    "action": "final_answer",
                    "final_answer": "Inventory checked.",
                },
            ]
        )

        res = orchestrator.process_question("Check Hex Bolt inventory")

        self.assertEqual(res.status, "completed")
        self.assertEqual(
            res.tool_calls[1].arguments["product_id"],
            "PRD001",
        )

    def test_qwen3_without_references_remains_unchanged(self) -> None:
        orchestrator = self._orchestrator(
            [
                {
                    "thought": "List warehouses",
                    "action": "call_tool",
                    "tool_name": "erp.warehouses.list",
                    "arguments": {},
                },
            ]
        )

        res = orchestrator.process_question("List all warehouses")

        self.assertEqual(res.status, "completed")
        self.assertEqual(len(res.tool_calls), 1)
        self.assertEqual(res.tool_calls[0].tool_name, "erp.warehouses.list")


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
    """Minimal Gemini client double; no network or SDK calls."""

    def __init__(self, responses: list[SimpleNamespace]) -> None:
        self._responses = iter(responses)
        self.calls = 0

    def chat(self, messages, **kwargs):  # type: ignore[no-untyped-def]
        self.calls += 1
        try:
            return next(self._responses)
        except StopIteration:
            return _gemini_response(content="Done.")

    def validate_availability(self) -> None:
        return None

    def close(self) -> None:
        return None


class TestGeminiBatchDependencyCompatibility(_PlatformHarness):
    """Gemini native ``call_tools`` batching with resolved references."""

    def _adapter(self, client: _ScriptedGeminiClient) -> GeminiLlmClientAdapter:
        return GeminiLlmClientAdapter(
            GeminiConfig(api_key="test-key-12345"),
            client=client,  # type: ignore[arg-type]
            tool_registry=self.platform.registry,
        )

    def _orchestrator(
        self,
        client: _ScriptedGeminiClient,
    ) -> AgentOrchestrator:
        return AgentOrchestrator(
            client=self._adapter(client),
            runner=self.platform.runner,
            registry=self.platform.registry,
        )

    def test_gemini_batch_without_references_unchanged(self) -> None:
        client = _ScriptedGeminiClient(
            [
                _gemini_response(
                    function_calls=[
                        {
                            "id": "call-1",
                            "name": "erp.warehouses.list",
                            "arguments": {},
                            "thought_signature": None,
                        }
                    ]
                ),
                _gemini_response(content="There are warehouses."),
            ]
        )
        orchestrator = self._orchestrator(client)

        res = orchestrator.process_question("List all warehouses")

        self.assertEqual(res.status, "completed")
        self.assertEqual(len(res.tool_calls), 1)
        self.assertEqual(res.tool_calls[0].tool_name, "erp.warehouses.list")

    def test_gemini_batch_resolves_previous_turn_reference(self) -> None:
        client = _ScriptedGeminiClient(
            [
                _gemini_response(
                    function_calls=[
                        {
                            "id": "call-1",
                            "name": "erp.products.search",
                            "arguments": {"query": "Hex Bolt", "limit": 5},
                            "thought_signature": None,
                        }
                    ]
                ),
                _gemini_response(
                    function_calls=[
                        {
                            "id": "call-2",
                            "name": "erp.inventory.get",
                            "arguments": {
                                "product_id": (
                                    "$steps.step_1.items[0].product_id"
                                )
                            },
                            "thought_signature": None,
                        }
                    ]
                ),
                _gemini_response(content="Inventory checked."),
            ]
        )
        orchestrator = self._orchestrator(client)

        res = orchestrator.process_question("Check Hex Bolt inventory")

        self.assertEqual(res.status, "completed")
        self.assertEqual(
            [summary.tool_name for summary in res.tool_calls],
            ["erp.products.search", "erp.inventory.get"],
        )
        self.assertEqual(
            res.tool_calls[1].arguments["product_id"],
            "PRD001",
        )

    def test_gemini_intra_batch_sequential_reference(self) -> None:
        client = _ScriptedGeminiClient(
            [
                _gemini_response(
                    function_calls=[
                        {
                            "id": "call-1",
                            "name": "erp.products.search",
                            "arguments": {"query": "Hex Bolt", "limit": 5},
                            "thought_signature": None,
                        },
                        {
                            "id": "call-2",
                            "name": "erp.inventory.get",
                            "arguments": {
                                "product_id": (
                                    "$steps.step_1.items[0].product_id"
                                )
                            },
                            "thought_signature": None,
                        },
                    ]
                ),
                _gemini_response(content="Inventory checked."),
            ]
        )
        orchestrator = self._orchestrator(client)

        res = orchestrator.process_question("Check Hex Bolt inventory")

        self.assertEqual(res.status, "completed")
        self.assertEqual(
            [summary.tool_name for summary in res.tool_calls],
            ["erp.products.search", "erp.inventory.get"],
        )
        self.assertEqual(
            res.tool_calls[1].arguments["product_id"],
            "PRD001",
        )

    def test_gemini_intra_batch_forward_reference_rejected(self) -> None:
        client = _ScriptedGeminiClient(
            [
                _gemini_response(
                    function_calls=[
                        {
                            "id": "call-1",
                            "name": "erp.inventory.get",
                            "arguments": {
                                "product_id": (
                                    "$steps.step_2.items[0].product_id"
                                )
                            },
                            "thought_signature": None,
                        },
                        {
                            "id": "call-2",
                            "name": "erp.products.search",
                            "arguments": {"query": "Hex Bolt", "limit": 5},
                            "thought_signature": None,
                        },
                    ]
                ),
                _gemini_response(content="Done."),
            ]
        )
        orchestrator = self._orchestrator(client)

        res = orchestrator.process_question("Check Hex Bolt inventory")

        self.assertEqual(
            [summary.tool_name for summary in res.tool_calls],
            ["erp.products.search"],
        )

    def test_gemini_native_payload_shape_unchanged(self) -> None:
        client = _ScriptedGeminiClient(
            [
                _gemini_response(
                    function_calls=[
                        {
                            "id": "call-1",
                            "name": "erp.warehouses.list",
                            "arguments": {},
                            "thought_signature": None,
                        }
                    ]
                )
            ]
        )

        response = self._adapter(client).chat(
            [ChatMessageForTest.user("List warehouses")]
        )
        payload = json.loads(response.content)

        self.assertEqual(payload["action"], "call_tools")
        self.assertNotIn("execution_plan", payload)


class ChatMessageForTest:
    """Small helper to build provider-neutral chat messages."""

    @staticmethod
    def user(content: str):
        from backend.agent.llm.models import ChatMessage, ChatRole

        return ChatMessage(role=ChatRole.USER, content=content)


if __name__ == "__main__":
    unittest.main()
