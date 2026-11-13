"""Phase 3G — Dispatch tool regressions for the "delivered elements" question.

Covers the live failure reported for POST /api/agent/chat with the
question "Give me the list of elements that are delivered":

* erp.dispatches.list failed with "Invalid argument: limit" (model sent
  limit=100; the schema never documented the 1-50 range);
* erp.dispatches.get failed validation (model sent so_id instead of
  dispatch_id);
* erp.dispatches.by_sales_order failed "Sales Order not found" (model
  invented so_id 12345);
* the tool-call budget was exhausted and the final answer fell back to
  "maximum number of tool calls was reached" even though a valid
  final_answer was produced (it was discarded because the model emitted
  "arguments": null).
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
import httpx

from backend.agent.erp.config import ErpDatabaseConfig
from backend.agent.erp.definitions import ERP_TOOL_DEFINITIONS
from backend.agent.erp.errors import ErpInvalidArgumentsError, ErpNotFoundError
from backend.agent.erp.handlers import ErpToolHandlers
from backend.agent.erp.registration import register_erp_tools
from backend.agent.erp.runner import ErpToolRunner
from backend.agent.erp.service import ErpReadService
from backend.agent.erp.sqlite_adapter import SqliteErpReadAdapter
from backend.agent.llm.client import OllamaClient
from backend.agent.llm.config import LlmConfig
from backend.agent.llm.models import ToolSelectionDecision
from backend.agent.models import utc_now
from backend.agent.orchestration.orchestrator import (
    AgentOrchestrator,
    normalize_tool_arguments,
)
from backend.agent.orchestration.prompts import build_system_prompt
from backend.agent.tools.contracts import ToolExecutionContext
from backend.agent.tools.executor import ToolExecutor
from backend.agent.tools.registry import ToolRegistry
from backend.tests.erp_support import create_erp_fixture_db


def _make_service(root: Path) -> ErpReadService:
    database_path = create_erp_fixture_db(root / "erp.db")
    return ErpReadService(SqliteErpReadAdapter(database_path))


class DispatchListArgumentsTests(unittest.TestCase):
    """Scenarios 1-3: list dispatches with omitted, valid, and invalid limit."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.service = _make_service(Path(self._tmp.name))

    def test_list_with_omitted_optional_arguments_uses_defaults(self) -> None:
        result = self.service.list_dispatches()
        self.assertEqual(result.row_count, 2)
        self.assertFalse(result.truncated)

    def test_list_with_valid_limit_succeeds(self) -> None:
        for limit in (1, 2, 20, 50):
            with self.subTest(limit=limit):
                result = self.service.list_dispatches(limit=limit)
                self.assertEqual(result.row_count, min(limit, 2))
                self.assertEqual(result.truncated, limit < 2)

    def test_list_with_invalid_limit_reports_valid_range(self) -> None:
        for limit in (0, -1, 51, 100):
            with self.subTest(limit=limit):
                with self.assertRaises(ErpInvalidArgumentsError) as ctx:
                    self.service.list_dispatches(limit=limit)
                # The error must teach the model the accepted range so its
                # retry can succeed instead of flailing.
                self.assertIn("between 1 and 50", str(ctx.exception))

    def test_list_with_non_integer_limit_reports_valid_range(self) -> None:
        with self.assertRaises(ErpInvalidArgumentsError) as ctx:
            self.service.list_dispatches(limit=True)
        self.assertIn("between 1 and 50", str(ctx.exception))


class DispatchDetailAndSalesOrderLookupTests(unittest.TestCase):
    """Scenarios 4-7: dispatch detail and by-sales-order lookups."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.service = _make_service(Path(self._tmp.name))

    def test_dispatch_detail_with_valid_id(self) -> None:
        result = self.service.get_dispatch("DSP001")
        self.assertEqual(result.dispatch_id, "DSP001")
        self.assertEqual(result.so_id, "SO001")
        self.assertEqual(result.items_row_count, 2)

    def test_dispatch_detail_with_unknown_id_is_not_found(self) -> None:
        with self.assertRaises(ErpNotFoundError):
            self.service.get_dispatch("DSP999")

    def test_dispatch_detail_with_blank_id_is_invalid_argument(self) -> None:
        with self.assertRaises(ErpInvalidArgumentsError):
            self.service.get_dispatch("   ")

    def test_by_sales_order_with_valid_id(self) -> None:
        result = self.service.get_dispatches_by_sales_order("SO001")
        self.assertEqual(result.so_id, "SO001")
        self.assertEqual(result.dispatches_row_count, 1)
        self.assertEqual(result.dispatches[0].dispatch_id, "DSP001")

    def test_by_sales_order_with_nonexistent_id_is_not_found(self) -> None:
        with self.assertRaises(ErpNotFoundError) as ctx:
            self.service.get_dispatches_by_sales_order("SO999")
        self.assertEqual(ctx.exception.details["resource"], "sales_order")


class DispatchHandlerEnvelopeTests(unittest.TestCase):
    """Handler-level envelopes for the failure shapes the model produced."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.handlers = ErpToolHandlers(_make_service(Path(self._tmp.name))).as_mapping()

    def _invoke(self, tool_name: str, arguments: dict) -> dict:
        return self.handlers[tool_name](
            arguments,
            ToolExecutionContext(
                execution_id="exec-1",
                tool_name=tool_name,
                started_at=utc_now(),
                timeout_seconds=5.0,
            ),
        )

    def test_limit_out_of_range_envelope_names_the_range(self) -> None:
        envelope = self._invoke("erp.dispatches.list", {"limit": 100})
        self.assertIs(envelope["ok"], False)
        self.assertEqual(envelope["error"]["code"], "erp_invalid_arguments")
        self.assertIn("between 1 and 50", envelope["error"]["message"])

    def test_dispatch_detail_missing_required_argument_envelope(self) -> None:
        # The model sent {"so_id": "12345"} to erp.dispatches.get.
        envelope = self._invoke("erp.dispatches.get", {"so_id": "12345"})
        self.assertIs(envelope["ok"], False)
        self.assertEqual(envelope["error"]["code"], "erp_invalid_arguments")

    def test_dispatch_list_with_string_limit_envelope(self) -> None:
        envelope = self._invoke("erp.dispatches.list", {"limit": "20"})
        self.assertIs(envelope["ok"], False)
        self.assertEqual(envelope["error"]["code"], "erp_invalid_arguments")


class NormalizeToolArgumentsTests(unittest.TestCase):
    """Unit tests for schema-driven model-argument normalization."""

    def _definition(self, name: str):
        for definition in ERP_TOOL_DEFINITIONS:
            if definition.name == name:
                return definition
        raise AssertionError(f"unknown tool {name}")

    def test_null_arguments_are_dropped(self) -> None:
        normalized = normalize_tool_arguments(
            {"so_id": None, "limit": None},
            self._definition("erp.dispatches.list"),
        )
        self.assertEqual(normalized, {})

    def test_quoted_integer_limit_is_coerced(self) -> None:
        normalized = normalize_tool_arguments(
            {"limit": "20"},
            self._definition("erp.dispatches.list"),
        )
        self.assertEqual(normalized, {"limit": 20})

    def test_integral_float_limit_is_coerced(self) -> None:
        normalized = normalize_tool_arguments(
            {"limit": 20.0},
            self._definition("erp.dispatches.list"),
        )
        self.assertEqual(normalized, {"limit": 20})

    def test_numeric_identifier_is_coerced_to_string(self) -> None:
        normalized = normalize_tool_arguments(
            {"so_id": 12345},
            self._definition("erp.dispatches.by_sales_order"),
        )
        self.assertEqual(normalized, {"so_id": "12345"})

    def test_unusable_values_are_dropped_not_executed(self) -> None:
        normalized = normalize_tool_arguments(
            {"limit": "all", "carrier": True},
            self._definition("erp.dispatches.list"),
        )
        self.assertEqual(normalized, {})

    def test_undeclared_properties_are_preserved_for_reporting(self) -> None:
        normalized = normalize_tool_arguments(
            {"foo": "bar"},
            self._definition("erp.dispatches.list"),
        )
        self.assertEqual(normalized, {"foo": "bar"})

    def test_non_mapping_arguments_become_empty(self) -> None:
        normalized = normalize_tool_arguments("not-a-dict", self._definition("erp.dispatches.list"))
        self.assertEqual(normalized, {})

    def test_valid_arguments_pass_through_unchanged(self) -> None:
        arguments = {"so_id": "SO001", "status": "Dispatched", "limit": 5}
        normalized = normalize_tool_arguments(
            arguments,
            self._definition("erp.dispatches.list"),
        )
        self.assertEqual(normalized, arguments)


class ToolSelectionDecisionNullArgumentsTests(unittest.TestCase):
    """The decision protocol allows "arguments": null; it must not crash."""

    def test_null_arguments_are_accepted_for_final_answer(self) -> None:
        decision = ToolSelectionDecision.model_validate(
            {
                "thought": "done",
                "action": "final_answer",
                "tool_name": None,
                "arguments": None,
                "final_answer": "Dispatch records retrieved.",
            }
        )
        self.assertIsNone(decision.arguments)
        self.assertEqual(decision.final_answer, "Dispatch records retrieved.")

    def test_null_arguments_are_accepted_for_tool_call(self) -> None:
        decision = ToolSelectionDecision.model_validate(
            {
                "thought": "list",
                "action": "call_tool",
                "tool_name": "erp.dispatches.list",
                "arguments": None,
            }
        )
        self.assertIsNone(decision.arguments)


class _ScriptedOllamaHarness(unittest.TestCase):
    """Shared harness: fixture ERP platform + scripted Ollama responses."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.db_path = Path(self.temp_dir.name) / "fixture_erp.db"
        create_erp_fixture_db(self.db_path)

        self.erp_config = ErpDatabaseConfig(self.db_path, query_timeout_seconds=5.0)
        self.adapter = SqliteErpReadAdapter(self.erp_config)
        self.service = ErpReadService(self.adapter)

        self.registry = ToolRegistry()
        self.executor = ToolExecutor(self.registry)
        self.registration = register_erp_tools(self.registry, self.executor, self.service)
        self.runner = ErpToolRunner(self.executor)
        self.addCleanup(self.registration.unregister)
        self.addCleanup(self.executor.shutdown, True)

        self.chat_requests: list[dict[str, Any]] = []

    def _create_orchestrator(
        self,
        responses: list[dict[str, Any] | str],
        *,
        max_tool_calls: int = 5,
    ) -> AgentOrchestrator:
        resp_iter = iter(responses)

        def mock_handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/tags":
                return httpx.Response(200, json={"models": [{"name": "llama3.2:latest"}]})

            if request.url.path == "/api/chat":
                self.chat_requests.append(json.loads(request.content))
                try:
                    resp_data = next(resp_iter)
                except StopIteration:
                    resp_data = {
                        "thought": "No more scripted responses",
                        "action": "final_answer",
                        "final_answer": "No further information.",
                    }
                if isinstance(resp_data, str):
                    content = resp_data
                else:
                    content = json.dumps(resp_data)
                return httpx.Response(
                    200,
                    json={
                        "model": "llama3.2",
                        "message": {"role": "assistant", "content": content},
                    },
                )
            return httpx.Response(404, text="Not found")

        transport = httpx.MockTransport(mock_handler)
        http_client = httpx.Client(transport=transport)
        self.addCleanup(http_client.close)
        client = OllamaClient(LlmConfig(), http_client=http_client)

        return AgentOrchestrator(
            client=client,
            runner=self.runner,
            registry=self.registry,
            max_tool_calls=max_tool_calls,
        )

    def _last_user_message(self) -> str:
        payload = self.chat_requests[-1]
        messages = payload["messages"]
        user_messages = [m for m in messages if m["role"] == "user"]
        return user_messages[-1]["content"]


class DispatchScenarioOrchestratorTests(_ScriptedOllamaHarness):
    """Orchestrator-level regressions for the reported live failure."""

    def test_model_limit_out_of_range_recoverable_via_feedback(self) -> None:
        # Scenario 3 at the agent level: the model sends limit=100 (as the
        # live llama3.2 run did), the tool fails with the documented range,
        # and the retry succeeds without exhausting the budget.
        orchestrator = self._create_orchestrator(
            [
                {
                    "thought": "List delivered elements",
                    "action": "call_tool",
                    "tool_name": "erp.dispatches.list",
                    "arguments": {"limit": 100},
                },
                {
                    "thought": "Retry with a valid limit",
                    "action": "call_tool",
                    "tool_name": "erp.dispatches.list",
                    "arguments": {"limit": 20},
                },
                {
                    "thought": "Answer with dispatch records",
                    "action": "final_answer",
                    "final_answer": (
                        "The ERP shows 2 dispatch records (DSP001, DSP002). These "
                        "establish warehouse dispatch, not confirmed customer delivery."
                    ),
                },
            ]
        )
        res = orchestrator.process_question("Give me the list of elements that are delivered")
        self.assertEqual(res.status, "completed")
        self.assertEqual(len(res.tool_calls), 2)
        self.assertEqual(res.tool_calls[0].status, "failed")
        self.assertIn("between 1 and 50", res.tool_calls[0].error or "")
        self.assertEqual(res.tool_calls[1].status, "succeeded")
        # The corrective feedback sent to the model (the request for the
        # second round) must carry the valid range.
        feedback_text = "\n".join(
            m["content"] for m in self.chat_requests[1]["messages"]
        )
        self.assertIn("between 1 and 50", feedback_text)

    def test_model_string_limit_is_normalized_before_execution(self) -> None:
        # Scenario 2/normalization: a quoted limit no longer fails validation.
        orchestrator = self._create_orchestrator(
            [
                {
                    "thought": "List dispatches",
                    "action": "call_tool",
                    "tool_name": "erp.dispatches.list",
                    "arguments": {"limit": "20"},
                },
                {
                    "thought": "Answer",
                    "action": "final_answer",
                    "final_answer": "There are 2 dispatch records.",
                },
            ]
        )
        res = orchestrator.process_question("List the dispatches")
        self.assertEqual(res.status, "completed")
        self.assertEqual(len(res.tool_calls), 1)
        self.assertEqual(res.tool_calls[0].status, "succeeded")
        self.assertEqual(res.tool_calls[0].arguments, {"limit": 20})

    def test_model_null_arguments_are_treated_as_omitted(self) -> None:
        # Scenario 1 at the agent level: the model emits nulls for every
        # optional argument (a pattern llama3.2 produces).
        orchestrator = self._create_orchestrator(
            [
                {
                    "thought": "List dispatches",
                    "action": "call_tool",
                    "tool_name": "erp.dispatches.list",
                    "arguments": {"limit": None, "so_id": None, "status": None, "carrier": None},
                },
                {
                    "thought": "Answer",
                    "action": "final_answer",
                    "final_answer": "There are 2 dispatch records.",
                },
            ]
        )
        res = orchestrator.process_question("List the dispatches")
        self.assertEqual(res.status, "completed")
        self.assertEqual(res.tool_calls[0].status, "succeeded")
        self.assertEqual(res.tool_calls[0].arguments, {})

    def test_wrong_argument_tool_call_gets_actionable_feedback(self) -> None:
        # Scenario 5 at the agent level: the model called
        # erp.dispatches.get with so_id (as the live run did). The
        # feedback must name both problems so the next round is correct.
        orchestrator = self._create_orchestrator(
            [
                {
                    "thought": "Get dispatch for the order",
                    "action": "call_tool",
                    "tool_name": "erp.dispatches.get",
                    "arguments": {"so_id": "12345"},
                },
                {
                    "thought": "Use dispatch_id from the list output",
                    "action": "call_tool",
                    "tool_name": "erp.dispatches.get",
                    "arguments": {"dispatch_id": "DSP001"},
                },
                {
                    "thought": "Answer",
                    "action": "final_answer",
                    "final_answer": "Dispatch DSP001 was sent via BlueDart.",
                },
            ]
        )
        res = orchestrator.process_question("Show me the dispatch for the order")
        self.assertEqual(res.status, "completed")
        self.assertEqual(res.tool_calls[0].status, "failed")
        feedback = self._last_user_message()
        # Feedback is sent after the second call; find the earlier one.
        self.assertEqual(res.tool_calls[1].status, "succeeded")
        feedback_rounds = [
            req for req in self.chat_requests
        ]
        # The corrective feedback (round 2 request) must contain the issues.
        second_request_messages = feedback_rounds[1]["messages"]
        feedback_text = "\n".join(m["content"] for m in second_request_messages)
        self.assertIn("missing required argument: dispatch_id", feedback_text)
        self.assertIn("unexpected argument: so_id", feedback_text)

    def test_invented_sales_order_id_gets_anti_guessing_feedback(self) -> None:
        # Scenario 7/11 at the agent level: the model invented so_id
        # 12345 (as the live run did). Feedback must forbid guessing.
        orchestrator = self._create_orchestrator(
            [
                {
                    "thought": "Look up dispatches for the order",
                    "action": "call_tool",
                    "tool_name": "erp.dispatches.by_sales_order",
                    "arguments": {"so_id": "12345"},
                },
                {
                    "thought": "List dispatches without guessing IDs",
                    "action": "call_tool",
                    "tool_name": "erp.dispatches.list",
                    "arguments": {},
                },
                {
                    "thought": "Answer from real records",
                    "action": "final_answer",
                    "final_answer": (
                        "The ERP contains 2 dispatch records: DSP001 (SO001) and "
                        "DSP002 (SO002). Dispatch is not confirmed delivery."
                    ),
                },
            ]
        )
        res = orchestrator.process_question("Give me the list of elements that are delivered")
        self.assertEqual(res.status, "completed")
        self.assertEqual(res.tool_calls[0].status, "failed")
        self.assertEqual(res.tool_calls[0].error, "Sales Order not found")
        # Feedback after the failed call must steer away from guessed IDs.
        second_request_messages = self.chat_requests[1]["messages"]
        feedback_text = "\n".join(m["content"] for m in second_request_messages)
        self.assertIn("Do not guess identifiers", feedback_text)
        # The recovery call must use real arguments from tool output.
        self.assertEqual(res.tool_calls[1].tool_name, "erp.dispatches.list")
        self.assertEqual(res.tool_calls[1].arguments, {})

    def test_delivered_elements_question_answered_from_single_list_call(self) -> None:
        # Scenarios 8 and 9: the natural-language dispatch-list question is
        # answered by exactly one erp.dispatches.list call, with no
        # unnecessary detail or by-sales-order calls.
        orchestrator = self._create_orchestrator(
            [
                {
                    "thought": (
                        "User asks for delivered elements. Dispatch records are the "
                        "grounded evidence; one unfiltered list call suffices."
                    ),
                    "action": "call_tool",
                    "tool_name": "erp.dispatches.list",
                    "arguments": {},
                },
                {
                    "thought": "Present dispatch records and the delivery caveat",
                    "action": "final_answer",
                    "final_answer": (
                        "The ERP contains 2 dispatch records: DSP001 (SO001, BlueDart, "
                        "tracking BD10001, Partially Dispatched, 2026-10-04) and DSP002 "
                        "(SO002, DTDC, tracking DT20002, Dispatched, 2026-10-06). These "
                        "records establish warehouse dispatch; the ERP does not establish "
                        "confirmed customer delivery."
                    ),
                },
            ]
        )
        res = orchestrator.process_question(
            "Give me the list of elements that are delivered"
        )
        self.assertEqual(res.status, "completed")
        self.assertEqual(len(res.tool_calls), 1)
        self.assertEqual(res.tool_calls[0].tool_name, "erp.dispatches.list")
        self.assertEqual(res.tool_calls[0].status, "succeeded")
        self.assertEqual(res.tool_calls[0].arguments, {})
        self.assertIn("dispatch", res.answer.lower())
        self.assertIn("does not establish confirmed", res.answer.lower())

    def test_successful_list_survives_unrelated_tool_failure(self) -> None:
        # Scenario 10: a successful list result remains usable when an
        # unrelated dispatch tool call fails.
        orchestrator = self._create_orchestrator(
            [
                {
                    "thought": "List all dispatches",
                    "action": "call_tool",
                    "tool_name": "erp.dispatches.list",
                    "arguments": {},
                },
                {
                    "thought": "Also check dispatches for a guessed order",
                    "action": "call_tool",
                    "tool_name": "erp.dispatches.by_sales_order",
                    "arguments": {"so_id": "12345"},
                },
                {
                    "thought": "Answer from the successful list data",
                    "action": "final_answer",
                    "final_answer": (
                        "The ERP contains 2 dispatch records: DSP001 (SO001, BlueDart) "
                        "and DSP002 (SO002, DTDC). Dispatch records establish warehouse "
                        "dispatch, not confirmed customer delivery."
                    ),
                },
            ]
        )
        res = orchestrator.process_question("Give me the list of elements that are delivered")
        self.assertEqual(res.status, "completed")
        self.assertEqual(res.tool_calls[0].status, "succeeded")
        self.assertEqual(res.tool_calls[1].status, "failed")
        self.assertIn("DSP001", res.answer)
        self.assertIn("DSP002", res.answer)

    def test_fallback_preserves_successful_data_and_delivery_note(self) -> None:
        # Scenario 10 (deterministic path): when the final synthesis round
        # cannot produce a final_answer, the successful list data is still
        # returned together with the dispatch/delivery distinction.
        orchestrator = self._create_orchestrator(
            [
                {
                    "thought": "List all dispatches",
                    "action": "call_tool",
                    "tool_name": "erp.dispatches.list",
                    "arguments": {},
                },
                {
                    "thought": "Check an unrelated order",
                    "action": "call_tool",
                    "tool_name": "erp.dispatches.by_sales_order",
                    "arguments": {"so_id": "12345"},
                },
                "this is not valid json at all",
            ],
            max_tool_calls=2,
        )
        res = orchestrator.process_question("Give me the list of elements that are delivered")
        self.assertEqual(res.status, "incomplete")
        self.assertEqual(res.tool_calls[0].status, "succeeded")
        self.assertEqual(res.tool_calls[1].status, "failed")
        # Successful data is preserved and usable.
        self.assertIn("DSP001", res.answer)
        self.assertIn("DSP002", res.answer)
        # Dispatch vs confirmed delivery is still distinguished.
        self.assertIn("confirmed customer delivery", res.answer)

    def test_budget_counts_executions_not_validation_failures(self) -> None:
        # Scenario 12: pre-flight validation failures must not consume the
        # tool-call budget; actual handler executions must.
        responses: list[dict[str, Any] | str] = [
            {
                "thought": f"Try call {i}",
                "action": "call_tool",
                "tool_name": "erp.dispatches.get",
                "arguments": {"foo": i},
            }
            for i in range(5)
        ]
        # After the invalid rounds, one valid execution, then synthesis.
        responses.append(
            {
                "thought": "Use the list tool",
                "action": "call_tool",
                "tool_name": "erp.dispatches.list",
                "arguments": {},
            }
        )
        responses.append(
            {
                "thought": "Final answer from data",
                "action": "final_answer",
                "final_answer": "There are 2 dispatch records.",
            }
        )
        orchestrator = self._create_orchestrator(
            responses,
            max_tool_calls=2,
        )
        res = orchestrator.process_question("List dispatches")
        # Five pre-flight failures plus one real execution (budget is 2).
        self.assertEqual(len(res.tool_calls), 6)
        self.assertEqual(res.status, "completed")
        for summary in res.tool_calls[:5]:
            self.assertEqual(summary.status, "failed")
        self.assertEqual(res.tool_calls[5].status, "succeeded")

    def test_budget_limits_actual_tool_executions(self) -> None:
        # Scenario 12: the model keeps requesting calls; executed tool
        # calls never exceed the budget and the answer is still produced.
        responses: list[dict[str, Any] | str] = [
            {
                "thought": f"Call {i}",
                "action": "call_tool",
                "tool_name": "erp.dispatches.list",
                "arguments": {"limit": i + 1},
            }
            for i in range(10)
        ]
        # The synthesis round consumes the response right after the budget
        # is exhausted (the 4th scripted response).
        responses.insert(
            3,
            {
                "thought": "Answer from retrieved data",
                "action": "final_answer",
                "final_answer": "Retrieved dispatch records: DSP001 and DSP002.",
            },
        )
        orchestrator = self._create_orchestrator(responses, max_tool_calls=3)
        res = orchestrator.process_question("List everything")
        self.assertEqual(len(res.tool_calls), 3)
        for summary in res.tool_calls:
            self.assertEqual(summary.status, "succeeded")
        self.assertEqual(res.status, "completed")
        self.assertIn("DSP001", res.answer)

    def test_llm_round_cap_ends_in_synthesized_answer(self) -> None:
        # Scenario 12 (round cap): unparseable model output never loops
        # forever; the synthesis round still produces an answer. A greeting
        # keeps this focused on the round cap rather than ERP grounding.
        orchestrator = self._create_orchestrator(
            [
                "not json",
                "still not json",
                "nope",
                {
                    "thought": "Answer despite unparseable rounds",
                    "action": "final_answer",
                    "final_answer": "Hello! How can I help?",
                },
            ],
            max_tool_calls=1,
        )
        res = orchestrator.process_question("Hello")
        self.assertEqual(res.iterations, 3)
        self.assertEqual(res.tool_calls, [])
        self.assertEqual(res.status, "completed")
        self.assertEqual(res.answer, "Hello! How can I help?")

    def test_unknown_action_produces_corrective_feedback(self) -> None:
        orchestrator = self._create_orchestrator(
            [
                {
                    "thought": "Confused action",
                    "action": "dance",
                },
                {
                    "thought": "Corrected",
                    "action": "final_answer",
                    "final_answer": "There are 2 dispatch records.",
                },
            ]
        )
        res = orchestrator.process_question("List dispatches")
        self.assertEqual(res.status, "error")
        self.assertEqual(res.error, "missing_tool_evidence")
        feedback_text = "\n".join(
            m["content"] for m in self.chat_requests[1]["messages"]
        )
        self.assertIn("Unknown action 'dance'", feedback_text)


class DispatchPromptGuidanceTests(unittest.TestCase):
    """Prompt-level guarantees for scenarios 9 and 11."""

    def _prompt(self) -> str:
        return build_system_prompt(
            [d.model_dump() for d in ERP_TOOL_DEFINITIONS]
        )

    def test_prompt_teaches_limit_range_and_default(self) -> None:
        prompt = self._prompt()
        self.assertIn("between 1 and 50", prompt)
        self.assertIn("default 20", prompt)

    def test_prompt_prefers_list_tool_for_list_questions(self) -> None:
        prompt = self._prompt()
        self.assertIn("preferred tool", prompt)
        self.assertIn("exactly ONE `erp.dispatches.list` call", prompt)

    def test_prompt_forbids_invented_identifiers(self) -> None:
        prompt = self._prompt()
        self.assertIn("NEVER invent or guess identifiers", prompt)
        self.assertIn("SO001", prompt)
        self.assertIn("DSP001", prompt)

    def test_prompt_documents_dispatch_statuses(self) -> None:
        prompt = self._prompt()
        self.assertIn("'Dispatched' and 'Partially Dispatched'", prompt)
        self.assertIn("never filter dispatches by status 'delivered'", prompt)

    def test_dispatch_tool_descriptions_document_requirements(self) -> None:
        by_name = {d.name: d for d in ERP_TOOL_DEFINITIONS}
        self.assertIn("between 1 and 50", by_name["erp.dispatches.list"].description)
        self.assertIn("dispatch_id", by_name["erp.dispatches.get"].description)
        self.assertIn("so_id", by_name["erp.dispatches.by_sales_order"].description)
        self.assertIn("DSP001", by_name["erp.dispatches.get"].description)
        self.assertIn("SO001", by_name["erp.dispatches.by_sales_order"].description)


if __name__ == "__main__":
    unittest.main()
