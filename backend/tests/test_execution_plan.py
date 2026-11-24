"""Tests for optional structured execution planning (Phase 1).

The execution plan is advisory metadata on ``ToolSelectionDecision``. It must
never authorize a tool call, bypass validation, or change the existing
sequential execution loop. These tests cover Ollama, Qwen3 (llama.cpp), and
Gemini native ``call_tools`` compatibility.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx

from backend.agent.erp.config import ErpDatabaseConfig
from backend.agent.erp.platform import ErpToolPlatform
from backend.agent.llm.client import OllamaClient
from backend.agent.llm.config import LlmConfig
from backend.agent.llm.llamacpp import LlamaCppClient, LlamaCppConfig
from backend.agent.llm.models import (
    ChatMessage,
    ChatRole,
    ToolSelectionDecision,
)
from backend.agent.orchestration.orchestrator import (
    AgentOrchestrator,
    _validate_execution_plan,
)
from backend.ai_providers.gemini.adapter import GeminiLlmClientAdapter
from backend.ai_providers.gemini.config import GeminiConfig
from backend.tests.erp_support import create_erp_fixture_db


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


class TestExecutionPlanValidation(_PlatformHarness):
    """Schema and validator behavior for the optional plan field."""

    def test_decision_accepts_execution_plan(self) -> None:
        decision = ToolSelectionDecision.model_validate(
            {
                "thought": "Plan a multi-step lookup",
                "action": "call_tool",
                "tool_name": "erp.products.search",
                "arguments": {"query": "bolt"},
                "execution_plan": [
                    "Search for the requested product",
                    "Check inventory for the matching product",
                ],
            }
        )

        self.assertEqual(
            decision.execution_plan,
            [
                "Search for the requested product",
                "Check inventory for the matching product",
            ],
        )

    def test_decision_without_execution_plan_is_backward_compatible(self) -> None:
        decision = ToolSelectionDecision.model_validate(
            {
                "thought": "Direct answer",
                "action": "final_answer",
                "final_answer": "Hello.",
            }
        )

        self.assertIsNone(decision.execution_plan)

    def test_validate_execution_plan_accepts_none_and_empty(self) -> None:
        self.assertEqual(
            _validate_execution_plan(None, self.platform.registry),
            (None, None),
        )
        self.assertEqual(
            _validate_execution_plan([], self.platform.registry),
            (None, None),
        )

    def test_validate_execution_plan_normalizes_short_strings(self) -> None:
        plan, error = _validate_execution_plan(
            ["  Search products  ", "", "Check inventory"],
            self.platform.registry,
        )

        self.assertIsNone(error)
        self.assertEqual(plan, ["Search products", "Check inventory"])

    def test_validate_execution_plan_rejects_non_list(self) -> None:
        plan, error = _validate_execution_plan(
            "not a list",
            self.platform.registry,
        )

        self.assertIsNone(plan)
        self.assertIn("JSON array", error or "")

    def test_validate_execution_plan_rejects_non_string_entries(self) -> None:
        plan, error = _validate_execution_plan(
            [123],
            self.platform.registry,
        )

        self.assertIsNone(plan)
        self.assertIn("short string", error or "")

    def test_validate_execution_plan_rejects_unknown_tool_references(self) -> None:
        plan, error = _validate_execution_plan(
            ["Call erp.fake.tool to fetch data"],
            self.platform.registry,
        )

        self.assertIsNone(plan)
        self.assertIn("erp.fake.tool", error or "")

    def test_validate_execution_plan_accepts_registered_tool_references(self) -> None:
        plan, error = _validate_execution_plan(
            ["Call erp.warehouses.list to enumerate warehouses"],
            self.platform.registry,
        )

        self.assertIsNone(error)
        self.assertEqual(
            plan,
            ["Call erp.warehouses.list to enumerate warehouses"],
        )

    def test_validate_execution_plan_rejects_too_many_steps(self) -> None:
        plan, error = _validate_execution_plan(
            [f"Step {index}" for index in range(9)],
            self.platform.registry,
        )

        self.assertIsNone(plan)
        self.assertIn("at most 8 steps", error or "")


class TestOllamaExecutionPlanIntegration(_PlatformHarness):
    """Ollama decision flows with and without an execution plan."""

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

    def test_decision_without_plan_runs_standard_flow(self) -> None:
        orchestrator, _ = self._orchestrator(
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
        self.assertIn("Main Warehouse", res.answer)

    def test_plan_accompanying_call_tool_executes_normally(self) -> None:
        orchestrator, _ = self._orchestrator(
            [
                {
                    "thought": "List warehouses",
                    "action": "call_tool",
                    "tool_name": "erp.warehouses.list",
                    "arguments": {},
                    "execution_plan": [
                        "List warehouses to answer the question",
                    ],
                },
            ]
        )

        res = orchestrator.process_question("List all warehouses")

        self.assertEqual(res.status, "completed")
        self.assertEqual(len(res.tool_calls), 1)
        self.assertEqual(res.tool_calls[0].tool_name, "erp.warehouses.list")
        self.assertIn("Main Warehouse", res.answer)

    def test_plan_accompanying_final_answer_is_accepted(self) -> None:
        orchestrator, _ = self._orchestrator(
            [
                {
                    "thought": "Greeting",
                    "action": "final_answer",
                    "final_answer": "Hello! I am your ERP assistant.",
                    "execution_plan": ["No tool is needed for a greeting"],
                }
            ]
        )

        res = orchestrator.process_question("Hello")

        self.assertEqual(res.status, "completed")
        self.assertEqual(res.answer, "Hello! I am your ERP assistant.")
        self.assertEqual(len(res.tool_calls), 0)

    def test_empty_execution_plan_is_treated_as_absent(self) -> None:
        orchestrator, _ = self._orchestrator(
            [
                {
                    "thought": "Count products",
                    "action": "call_tool",
                    "tool_name": "erp.products.count",
                    "arguments": {},
                    "execution_plan": [],
                },
            ]
        )

        res = orchestrator.process_question("How many products do we have?")

        self.assertEqual(res.status, "completed")
        self.assertEqual(len(res.tool_calls), 1)
        self.assertEqual(res.tool_calls[0].status, "succeeded")

    def test_multi_step_plan_keeps_sequential_execution(self) -> None:
        orchestrator, _ = self._orchestrator(
            [
                {
                    "thought": "Search products",
                    "action": "call_tool",
                    "tool_name": "erp.products.search",
                    "arguments": {"query": "Hex Bolt", "limit": 5},
                    "execution_plan": [
                        "Search for the requested product",
                        "Check inventory for the matching product",
                    ],
                },
                {
                    "thought": "Check inventory",
                    "action": "call_tool",
                    "tool_name": "erp.inventory.get",
                    "arguments": {"product_id": "PRD001"},
                    "execution_plan": [
                        "Search for the requested product",
                        "Check inventory for the matching product",
                    ],
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

    def test_invalid_plan_type_triggers_corrective_feedback(self) -> None:
        orchestrator, chat_requests = self._orchestrator(
            [
                {
                    "thought": "List warehouses with a bad plan",
                    "action": "call_tool",
                    "tool_name": "erp.warehouses.list",
                    "arguments": {},
                    "execution_plan": "not a list",
                },
                {
                    "thought": "Corrected",
                    "action": "call_tool",
                    "tool_name": "erp.warehouses.list",
                    "arguments": {},
                },
            ]
        )

        res = orchestrator.process_question("List all warehouses")

        self.assertEqual(res.status, "completed")
        # The invalid first turn must not execute a tool.
        self.assertEqual(len(res.tool_calls), 1)
        self.assertEqual(len(chat_requests), 2)
        feedback = "\n".join(
            message["content"] for message in chat_requests[1]["messages"]
        )
        self.assertIn("execution plan is invalid", feedback)
        self.assertIn("JSON array", feedback)

    def test_invalid_plan_unknown_tool_triggers_feedback(self) -> None:
        orchestrator, chat_requests = self._orchestrator(
            [
                {
                    "thought": "Invent a tool in the plan",
                    "action": "call_tool",
                    "tool_name": "erp.warehouses.list",
                    "arguments": {},
                    "execution_plan": ["Call erp.fake.tool first"],
                },
                {
                    "thought": "Corrected",
                    "action": "call_tool",
                    "tool_name": "erp.warehouses.list",
                    "arguments": {},
                },
            ]
        )

        res = orchestrator.process_question("List all warehouses")

        self.assertEqual(res.status, "completed")
        self.assertEqual(len(res.tool_calls), 1)
        feedback = "\n".join(
            message["content"] for message in chat_requests[1]["messages"]
        )
        self.assertIn("erp.fake.tool", feedback)

    def test_invalid_plan_is_ignored_after_one_correction(self) -> None:
        orchestrator, chat_requests = self._orchestrator(
            [
                {
                    "thought": "Bad plan one",
                    "action": "call_tool",
                    "tool_name": "erp.warehouses.list",
                    "arguments": {},
                    "execution_plan": "not a list",
                },
                {
                    "thought": "Bad plan two",
                    "action": "call_tool",
                    "tool_name": "erp.warehouses.list",
                    "arguments": {},
                    "execution_plan": ["Call erp.fake.tool"],
                },
            ]
        )

        res = orchestrator.process_question("List all warehouses")

        # After one corrective round the invalid plan is ignored and the
        # requested tool call proceeds under normal validation.
        self.assertEqual(res.status, "completed")
        self.assertEqual(len(res.tool_calls), 1)
        self.assertEqual(res.tool_calls[0].tool_name, "erp.warehouses.list")
        self.assertEqual(len(chat_requests), 2)

    def test_invalid_plan_cannot_authorize_an_unknown_tool(self) -> None:
        orchestrator, _ = self._orchestrator(
            [
                {
                    "thought": "Plan an unknown tool and call it",
                    "action": "call_tool",
                    "tool_name": "erp.fake.tool",
                    "arguments": {},
                    "execution_plan": ["Call erp.fake.tool"],
                },
                {
                    "thought": "Corrected",
                    "action": "call_tool",
                    "tool_name": "erp.warehouses.list",
                    "arguments": {},
                },
            ]
        )

        res = orchestrator.process_question("List all warehouses")

        self.assertEqual(res.status, "completed")
        self.assertEqual(
            [summary.tool_name for summary in res.tool_calls],
            ["erp.warehouses.list"],
        )
        self.assertNotIn("erp.fake.tool", {
            summary.tool_name for summary in res.tool_calls
        })


class TestQwen3ExecutionPlanCompatibility(_PlatformHarness):
    """Qwen3 (llama.cpp) decisions without a plan remain unchanged."""

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

    def test_qwen3_without_plan_remains_compatible(self) -> None:
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
        self.assertIn("Main Warehouse", res.answer)

    def test_qwen3_with_plan_remains_compatible(self) -> None:
        orchestrator = self._orchestrator(
            [
                {
                    "thought": "Plan and list",
                    "action": "call_tool",
                    "tool_name": "erp.warehouses.list",
                    "arguments": {},
                    "execution_plan": ["List warehouses"],
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


class TestGeminiNativeBatchCompatibility(_PlatformHarness):
    """Gemini's native ``call_tools`` protocol is unchanged."""

    def _adapter(self, client: _ScriptedGeminiClient) -> GeminiLlmClientAdapter:
        return GeminiLlmClientAdapter(
            GeminiConfig(api_key="test-key-12345"),
            client=client,  # type: ignore[arg-type]
            tool_registry=self.platform.registry,
        )

    def test_native_call_tools_executes_without_a_plan(self) -> None:
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
        orchestrator = AgentOrchestrator(
            client=self._adapter(client),
            runner=self.platform.runner,
            registry=self.platform.registry,
        )

        res = orchestrator.process_question("List all warehouses")

        self.assertEqual(res.status, "completed")
        self.assertEqual(len(res.tool_calls), 1)
        self.assertEqual(res.tool_calls[0].tool_name, "erp.warehouses.list")
        self.assertIn("Main Warehouse", res.answer)
        self.assertEqual(client.calls, 1)

    def test_call_tools_payload_has_no_execution_plan(self) -> None:
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
            [ChatMessage(role=ChatRole.USER, content="List warehouses")]
        )
        payload = json.loads(response.content)

        self.assertEqual(payload["action"], "call_tools")
        self.assertNotIn("execution_plan", payload)
        decision = ToolSelectionDecision.model_validate(payload)
        self.assertIsNone(decision.execution_plan)


if __name__ == "__main__":
    unittest.main()
