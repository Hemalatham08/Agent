from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx

from backend.agent.erp.config import ErpDatabaseConfig
from backend.agent.erp.registration import register_erp_tools
from backend.agent.erp.runner import ErpToolRunner
from backend.agent.erp.service import ErpReadService
from backend.agent.erp.sqlite_adapter import SqliteErpReadAdapter
from backend.agent.llm.client import OllamaClient
from backend.agent.llm.config import LlmConfig
from backend.agent.models import utc_now
from backend.agent.orchestration.orchestrator import AgentOrchestrator
from backend.agent.tools.contracts import (
    ToolExecutionResult,
    ToolExecutionStatus,
)
from backend.agent.tools.executor import ToolExecutor
from backend.agent.tools.registry import ToolRegistry
from backend.tests.erp_support import create_erp_fixture_db


class TestAgentOrchestrator(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "fixture_erp.db"
        create_erp_fixture_db(self.db_path)

        self.erp_config = ErpDatabaseConfig(self.db_path, query_timeout_seconds=5.0)
        self.adapter = SqliteErpReadAdapter(self.erp_config)
        self.service = ErpReadService(self.adapter)

        self.registry = ToolRegistry()
        self.executor = ToolExecutor(self.registry)
        self.registration = register_erp_tools(self.registry, self.executor, self.service)
        self.runner = ErpToolRunner(self.executor)

    def tearDown(self) -> None:
        self.registration.unregister()
        self.executor.shutdown(wait=True)
        self.temp_dir.cleanup()

    def _create_orchestrator(
        self,
        responses: list[dict[str, Any] | Exception | httpx.Response],
        *,
        max_tool_calls: int = 5,
        chat_calls: list[dict[str, Any]] | None = None,
    ) -> AgentOrchestrator:
        resp_iter = iter(responses)

        def mock_handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/tags":
                return httpx.Response(200, json={"models": [{"name": "llama3.2:latest"}]})

            if request.url.path == "/api/chat":
                if chat_calls is not None:
                    chat_calls.append(json.loads(request.content))
                try:
                    resp_data = next(resp_iter)
                except StopIteration:
                    resp_data = {
                        "thought": "No more responses",
                        "action": "final_answer",
                        "final_answer": "No further information.",
                    }
                if isinstance(resp_data, Exception):
                    raise resp_data
                if isinstance(resp_data, httpx.Response):
                    return resp_data
                return httpx.Response(
                    200,
                    json={
                        "model": "llama3.2",
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(resp_data),
                        },
                    },
                )

            return httpx.Response(404, text="Not found")

        transport = httpx.MockTransport(mock_handler)
        http_client = httpx.Client(transport=transport)
        client = OllamaClient(LlmConfig(), http_client=http_client)

        return AgentOrchestrator(
            client=client,
            runner=self.runner,
            registry=self.registry,
            max_tool_calls=max_tool_calls,
        )

    def test_empty_question(self) -> None:
        orchestrator = self._create_orchestrator([])
        res = orchestrator.process_question("   ")
        self.assertEqual(res.status, "completed")
        self.assertIn("Please provide a business question", res.answer)
        self.assertEqual(len(res.tool_calls), 0)

    def test_direct_final_answer(self) -> None:
        orchestrator = self._create_orchestrator(
            [
                {
                    "thought": "This is a greeting",
                    "action": "final_answer",
                    "final_answer": "Hello! I am your ERP assistant.",
                }
            ]
        )
        res = orchestrator.process_question("Hello")
        self.assertEqual(res.status, "completed")
        self.assertEqual(res.answer, "Hello! I am your ERP assistant.")
        self.assertEqual(len(res.tool_calls), 0)

    def test_product_count_is_derived_from_registered_tool_output(self) -> None:
        chat_calls: list[dict[str, Any]] = []
        orchestrator = self._create_orchestrator(
            [
                {
                    "thought": "Count products",
                    "action": "call_tool",
                    "tool_name": "erp.products.count",
                    "arguments": {},
                },
                {
                    "thought": "Answer",
                    "action": "final_answer",
                    "final_answer": "There are 123 products.",
                },
            ],
            chat_calls=chat_calls,
        )

        res = orchestrator.process_question("How many products do we have?")

        expected_count = self.service.count_products().product_count
        self.assertEqual(res.status, "completed")
        self.assertIsNone(res.error)
        self.assertEqual(
            res.answer,
            f"There are {expected_count} products in the ERP.",
        )
        self.assertNotIn("123", res.answer)
        self.assertEqual(len(chat_calls), 1)
        self.assertEqual(res.iterations, 1)
        self.assertEqual(len(res.tool_calls), 1)
        self.assertEqual(res.tool_calls[0].tool_name, "erp.products.count")
        self.assertEqual(res.tool_calls[0].arguments, {})
        self.assertEqual(res.tool_calls[0].status, "succeeded")

    def test_product_count_short_circuit_uses_current_database_value(self) -> None:
        connection = sqlite3.connect(self.db_path)
        try:
            connection.execute(
                "INSERT INTO products VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "PRD006",
                    "HEX-M12-SS316",
                    "Hex Bolt M12",
                    "Bolts",
                    "Stainless Steel",
                    "M12",
                    "SS316",
                    "pieces",
                    9.0,
                    14.0,
                    300,
                ),
            )
            connection.commit()
        finally:
            connection.close()

        chat_calls: list[dict[str, Any]] = []
        orchestrator = self._create_orchestrator(
            [
                {
                    "thought": "Count products",
                    "action": "call_tool",
                    "tool_name": "erp.products.count",
                    "arguments": {},
                },
            ],
            chat_calls=chat_calls,
        )

        res = orchestrator.process_question("What is the total number of products?")

        expected_count = self.service.count_products().product_count
        self.assertEqual(expected_count, 6)
        self.assertEqual(res.status, "completed")
        self.assertEqual(
            res.answer,
            f"There are {expected_count} products in the ERP.",
        )
        self.assertEqual(len(chat_calls), 1)
        self.assertEqual(len(res.tool_calls), 1)
        self.assertEqual(res.tool_calls[0].tool_name, "erp.products.count")
        self.assertEqual(res.tool_calls[0].status, "succeeded")

    def test_product_count_without_tool_evidence_is_rejected(self) -> None:
        orchestrator = self._create_orchestrator(
            [
                {
                    "thought": "Answer directly",
                    "action": "final_answer",
                    "final_answer": "There are 123 products.",
                }
            ]
        )

        res = orchestrator.process_question("How many products do we have?")

        self.assertEqual(res.status, "error")
        self.assertEqual(res.error, "missing_tool_evidence")
        self.assertNotIn("123", res.answer)

    def test_failed_product_count_cannot_support_final_answer(self) -> None:
        orchestrator = self._create_orchestrator(
            [
                {
                    "thought": "Count products",
                    "action": "call_tool",
                    "tool_name": "erp.products.count",
                    "arguments": {"limit": 10},
                },
                {
                    "thought": "Answer despite failure",
                    "action": "final_answer",
                    "final_answer": "There are 123 products.",
                },
            ]
        )

        res = orchestrator.process_question("How many products do we have?")

        self.assertEqual(res.status, "error")
        self.assertEqual(res.error, "tool_evidence_failed")
        self.assertEqual(res.tool_calls[0].status, "failed")
        self.assertNotIn("123", res.answer)

    def test_unrelated_successful_tool_cannot_support_product_count(self) -> None:
        orchestrator = self._create_orchestrator(
            [
                {
                    "thought": "List warehouses",
                    "action": "call_tool",
                    "tool_name": "erp.warehouses.list",
                    "arguments": {},
                },
                {
                    "thought": "Answer product count",
                    "action": "final_answer",
                    "final_answer": "There are 123 products.",
                },
            ]
        )

        res = orchestrator.process_question("How many products do we have?")

        self.assertEqual(res.status, "error")
        self.assertEqual(res.error, "missing_tool_evidence")
        self.assertEqual(res.tool_calls[0].status, "succeeded")
        self.assertNotIn("123", res.answer)

    def test_unsupported_erp_domain_without_tool_is_rejected(self) -> None:
        orchestrator = self._create_orchestrator(
            [
                {
                    "thought": "Answer directly",
                    "action": "final_answer",
                    "final_answer": "The outstanding balance is 1000.",
                }
            ]
        )

        res = orchestrator.process_question("What is the outstanding invoice balance?")

        self.assertEqual(res.status, "error")
        self.assertEqual(res.error, "unsupported_capability")
        self.assertNotIn("1000", res.answer)

    def test_pending_purchase_orders_are_unsupported(self) -> None:
        orchestrator = self._create_orchestrator(
            [
                {
                    "thought": "Answer directly",
                    "action": "final_answer",
                    "final_answer": "PO001 for supplier Acme is pending.",
                }
            ]
        )

        res = orchestrator.process_question("Show pending purchase orders.")

        self.assertEqual(res.status, "error")
        self.assertEqual(res.error, "unsupported_capability")
        self.assertNotIn("PO001", res.answer)

    def test_create_product_request_is_unsupported(self) -> None:
        orchestrator = self._create_orchestrator(
            [
                {
                    "thought": "Answer directly",
                    "action": "final_answer",
                    "final_answer": "Created product Bolt.",
                }
            ]
        )

        res = orchestrator.process_question("Create product Bolt.")

        self.assertEqual(res.status, "error")
        self.assertEqual(res.error, "unsupported_capability")
        self.assertIn("no approved read-only tool", res.answer)

    def test_product_count_tool_cannot_support_product_listing(self) -> None:
        orchestrator = self._create_orchestrator(
            [
                {
                    "thought": "Count products",
                    "action": "call_tool",
                    "tool_name": "erp.products.count",
                    "arguments": {},
                },
                {
                    "thought": "Answer product detail",
                    "action": "final_answer",
                    "final_answer": "PRD001 is Hex Bolt M10.",
                },
            ]
        )

        res = orchestrator.process_question("Show product details for PRD001.")

        self.assertEqual(res.status, "error")
        self.assertEqual(res.error, "missing_tool_evidence")
        self.assertEqual(res.tool_calls[0].status, "succeeded")
        self.assertNotIn("Hex Bolt M10", res.answer)

    def test_product_count_grounding_applies_before_budget_exhaustion(self) -> None:
        orchestrator = self._create_orchestrator(
            [
                {
                    "thought": "Count products",
                    "action": "call_tool",
                    "tool_name": "erp.products.count",
                    "arguments": {},
                },
                {
                    "thought": "Answer after budget exhaustion",
                    "action": "final_answer",
                    "final_answer": "There are 123 products.",
                },
            ],
            max_tool_calls=1,
        )

        res = orchestrator.process_question("How many products do we have?")

        self.assertEqual(res.status, "completed")
        self.assertEqual(res.answer, "There are 5 products in the ERP.")
        self.assertEqual(len(res.tool_calls), 1)
        self.assertNotIn("123", res.answer)

    def test_list_all_products_succeeds_with_one_search_call(self) -> None:
        orchestrator = self._create_orchestrator(
            [
                {
                    "thought": "List all products in one call",
                    "action": "call_tool",
                    "tool_name": "erp.products.search",
                    "arguments": {},
                },
                {
                    "thought": "Present all retrieved products",
                    "action": "final_answer",
                    "final_answer": (
                        "PRD003, PRD005, PRD001, PRD002, PRD004"
                    ),
                },
            ]
        )

        res = orchestrator.process_question("List all products.")

        self.assertEqual(res.status, "completed")
        self.assertEqual(len(res.tool_calls), 1)
        self.assertEqual(res.tool_calls[0].tool_name, "erp.products.search")
        self.assertEqual(res.tool_calls[0].status, "succeeded")
        for product_id in ("PRD001", "PRD002", "PRD003", "PRD004", "PRD005"):
            self.assertIn(product_id, res.answer)
        self.assertNotIn("maximum allowed tool calls", res.answer.lower())

    def test_list_all_products_displays_all_six_records(self) -> None:
        connection = sqlite3.connect(self.db_path)
        try:
            connection.execute(
                "INSERT INTO products VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "PRD006",
                    "HEX-M12-SS316",
                    "Hex Bolt M12",
                    "Bolts",
                    "Stainless Steel",
                    "M12",
                    "SS316",
                    "pieces",
                    9.0,
                    14.0,
                    300,
                ),
            )
            connection.commit()
        finally:
            connection.close()

        def mock_handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/tags":
                return httpx.Response(
                    200,
                    json={"models": [{"name": "llama3.2:latest"}]},
                )
            if request.url.path == "/api/chat":
                messages = json.loads(request.content)["messages"]
                last_content = messages[-1]["content"]
                marker = "Tool `erp.products.search` output:\n"
                if marker in last_content:
                    payload = last_content.split(marker, 1)[1]
                    product_ids = [
                        item["product_id"]
                        for item in json.loads(payload)["items"]
                    ]
                    decision = {
                        "thought": "Present all retrieved products",
                        "action": "final_answer",
                        "final_answer": "Products: " + ", ".join(product_ids),
                    }
                else:
                    decision = {
                        "thought": "List all products in one call",
                        "action": "call_tool",
                        "tool_name": "erp.products.search",
                        "arguments": {},
                    }
                return httpx.Response(
                    200,
                    json={
                        "model": "llama3.2",
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(decision),
                        },
                    },
                )
            return httpx.Response(404, text="Not found")

        http_client = httpx.Client(
            transport=httpx.MockTransport(mock_handler)
        )
        client = OllamaClient(LlmConfig(), http_client=http_client)
        orchestrator = AgentOrchestrator(
            client=client,
            runner=self.runner,
            registry=self.registry,
        )

        res = orchestrator.process_question("List all products.")

        self.assertEqual(res.status, "completed")
        self.assertEqual(len(res.tool_calls), 1)
        for product_id in (
            "PRD001",
            "PRD002",
            "PRD003",
            "PRD004",
            "PRD005",
            "PRD006",
        ):
            self.assertIn(product_id, res.answer)

    def test_tool_call_exhaustion_produces_honest_message(self) -> None:
        responses: list[dict[str, Any]] = [
            {
                "thought": f"Search {index}",
                "action": "call_tool",
                "tool_name": "erp.products.search",
                "arguments": {"query": f"term{index}"},
            }
            for index in range(5)
        ]
        responses.append(
            {
                "thought": "No final answer available",
                "action": "final_answer",
                "final_answer": "",
            }
        )
        orchestrator = self._create_orchestrator(responses)

        res = orchestrator.process_question("List all products.")

        self.assertEqual(res.status, "incomplete")
        self.assertEqual(len(res.tool_calls), 5)
        self.assertIn("tool-call limit was reached", res.answer)
        self.assertIn("erp.products.search", res.answer)

    def test_llm_timeout_after_successful_tool_preserves_results(self) -> None:
        orchestrator = self._create_orchestrator(
            [
                {
                    "thought": "List all products",
                    "action": "call_tool",
                    "tool_name": "erp.products.search",
                    "arguments": {},
                },
                httpx.ReadTimeout("timed out"),
            ]
        )

        res = orchestrator.process_question("List all products.")

        self.assertEqual(res.status, "incomplete")
        self.assertEqual(res.error, "llm_timeout")
        self.assertEqual(len(res.tool_calls), 1)
        self.assertEqual(res.tool_calls[0].status, "succeeded")
        self.assertIn("PRD001", res.answer)
        self.assertIn("timed out before a final answer", res.answer)

    def test_llm_error_after_successful_tool_preserves_results(self) -> None:
        orchestrator = self._create_orchestrator(
            [
                {
                    "thought": "List all products",
                    "action": "call_tool",
                    "tool_name": "erp.products.search",
                    "arguments": {},
                },
                httpx.Response(500, text="chat failed"),
            ]
        )

        res = orchestrator.process_question("List all products")

        self.assertEqual(res.status, "incomplete")
        self.assertEqual(res.error, "llm_error")
        self.assertEqual(len(res.tool_calls), 1)
        self.assertEqual(res.tool_calls[0].status, "succeeded")
        self.assertIn("PRD001", res.answer)
        self.assertIn("encountered an error before a final answer", res.answer)

    def test_llm_timeout_without_successful_tool_keeps_generic_error(self) -> None:
        orchestrator = self._create_orchestrator(
            [
                {
                    "thought": "Try an invalid dispatch limit",
                    "action": "call_tool",
                    "tool_name": "erp.dispatches.list",
                    "arguments": {"limit": 100},
                },
                httpx.ReadTimeout("timed out"),
            ]
        )

        res = orchestrator.process_question("Give me the list of elements that are delivered")

        self.assertEqual(res.status, "error")
        self.assertEqual(res.error, "llm_timeout")
        self.assertEqual(len(res.tool_calls), 1)
        self.assertEqual(res.tool_calls[0].status, "failed")
        self.assertIn("timed out while processing your question", res.answer)
        self.assertNotIn("successfully retrieved", res.answer)

    def test_llm_timeout_after_mixed_results_preserves_only_success(self) -> None:
        orchestrator = self._create_orchestrator(
            [
                {
                    "thought": "List products",
                    "action": "call_tool",
                    "tool_name": "erp.products.search",
                    "arguments": {},
                },
                {
                    "thought": "Check an unknown product",
                    "action": "call_tool",
                    "tool_name": "erp.inventory.get",
                    "arguments": {"product_id": "PRD999"},
                },
                httpx.ReadTimeout("timed out"),
            ]
        )

        res = orchestrator.process_question("List all products.")

        self.assertEqual(res.status, "incomplete")
        self.assertEqual(res.error, "llm_timeout")
        self.assertEqual(res.tool_calls[0].status, "succeeded")
        self.assertEqual(res.tool_calls[1].status, "failed")
        self.assertIn("PRD001", res.answer)
        self.assertIn("Tool calls that did not return data", res.answer)
        self.assertIn("erp.inventory.get", res.answer)
        self.assertNotIn("PRD999", res.answer)

    def test_product_count_short_circuit_avoids_followup_llm_timeout(self) -> None:
        chat_calls: list[dict[str, Any]] = []
        orchestrator = self._create_orchestrator(
            [
                {
                    "thought": "Count products",
                    "action": "call_tool",
                    "tool_name": "erp.products.count",
                    "arguments": {},
                },
                httpx.ReadTimeout("timed out"),
            ],
            chat_calls=chat_calls,
        )

        res = orchestrator.process_question("How many products do we have?")

        self.assertEqual(res.status, "completed")
        self.assertIsNone(res.error)
        self.assertEqual(res.answer, "There are 5 products in the ERP.")
        self.assertEqual(len(chat_calls), 1)
        self.assertEqual(len(res.tool_calls), 1)
        self.assertEqual(res.tool_calls[0].status, "succeeded")

    def test_warehouse_list_is_rendered_deterministically(self) -> None:
        chat_calls: list[dict[str, Any]] = []
        orchestrator = self._create_orchestrator(
            [
                {
                    "thought": "List warehouses",
                    "action": "call_tool",
                    "tool_name": "erp.warehouses.list",
                    "arguments": {},
                },
                {
                    "thought": "Invent a list",
                    "action": "final_answer",
                    "final_answer": "There are 99 warehouses including WH999.",
                },
            ],
            chat_calls=chat_calls,
        )

        res = orchestrator.process_question("List all warehouses")

        self.assertEqual(res.status, "completed")
        self.assertIsNone(res.error)
        self.assertEqual(len(chat_calls), 1)
        self.assertEqual(res.iterations, 1)
        self.assertEqual(len(res.tool_calls), 1)
        self.assertEqual(res.tool_calls[0].tool_name, "erp.warehouses.list")
        self.assertEqual(res.tool_calls[0].status, "succeeded")
        self.assertIn("Main Warehouse", res.answer)
        self.assertIn("WH001", res.answer)
        self.assertIn("Chennai", res.answer)
        self.assertIn("Secondary Warehouse", res.answer)
        self.assertIn("WH002", res.answer)
        self.assertIn("Coimbatore", res.answer)
        self.assertNotIn("999", res.answer)

    def test_warehouse_list_empty_result_is_truthful(self) -> None:
        connection = sqlite3.connect(self.db_path)
        try:
            connection.execute("DELETE FROM inventory")
            connection.execute("DELETE FROM warehouses")
            connection.commit()
        finally:
            connection.close()

        chat_calls: list[dict[str, Any]] = []
        orchestrator = self._create_orchestrator(
            [
                {
                    "thought": "List warehouses",
                    "action": "call_tool",
                    "tool_name": "erp.warehouses.list",
                    "arguments": {},
                },
            ],
            chat_calls=chat_calls,
        )

        res = orchestrator.process_question("List all warehouses")

        self.assertEqual(res.status, "completed")
        self.assertIsNone(res.error)
        self.assertEqual(res.answer, "There are no warehouses in the ERP.")
        self.assertEqual(len(chat_calls), 1)
        self.assertEqual(len(res.tool_calls), 1)
        self.assertEqual(res.tool_calls[0].status, "succeeded")

    def test_failed_warehouse_list_cannot_support_final_answer(self) -> None:
        orchestrator = self._create_orchestrator(
            [
                {
                    "thought": "List warehouses with an invalid argument",
                    "action": "call_tool",
                    "tool_name": "erp.warehouses.list",
                    "arguments": {"limit": 10},
                },
                {
                    "thought": "Answer despite failure",
                    "action": "final_answer",
                    "final_answer": "There is one warehouse: Main Warehouse (WH001).",
                },
            ]
        )

        res = orchestrator.process_question("List all warehouses")

        self.assertEqual(res.status, "error")
        self.assertEqual(res.error, "tool_evidence_failed")
        self.assertEqual(res.tool_calls[0].status, "failed")
        self.assertNotIn("WH001", res.answer)
        self.assertNotIn("Main Warehouse", res.answer)

    def test_malformed_warehouse_output_does_not_invent_records(self) -> None:
        now = utc_now()
        malformed = ToolExecutionResult(
            execution_id="exec-malformed-warehouses",
            tool_name="erp.warehouses.list",
            status=ToolExecutionStatus.SUCCEEDED,
            output={"items": [{"warehouse_id": "WH001"}], "row_count": 1},
            started_at=now,
            finished_at=now,
            duration_ms=1.0,
        )
        orchestrator = self._create_orchestrator(
            [
                {
                    "thought": "List warehouses",
                    "action": "call_tool",
                    "tool_name": "erp.warehouses.list",
                    "arguments": {},
                },
                {
                    "thought": "Answer from raw output",
                    "action": "final_answer",
                    "final_answer": "Main Warehouse (WH001) in Chennai.",
                },
            ]
        )

        with patch.object(self.runner, "execute", return_value=malformed):
            res = orchestrator.process_question("List all warehouses")

        self.assertEqual(res.status, "error")
        self.assertEqual(res.error, "invalid_tool_evidence")
        self.assertNotIn("WH001", res.answer)
        self.assertNotIn("Main Warehouse", res.answer)

    def test_warehouse_stock_question_is_not_deterministic(self) -> None:
        chat_calls: list[dict[str, Any]] = []
        orchestrator = self._create_orchestrator(
            [
                {
                    "thought": "Check warehouse stock",
                    "action": "call_tool",
                    "tool_name": "erp.warehouses.list",
                    "arguments": {},
                },
                {
                    "thought": "Summarize stock",
                    "action": "final_answer",
                    "final_answer": "WH002 has the lowest stock.",
                },
            ],
            chat_calls=chat_calls,
        )

        res = orchestrator.process_question("Which warehouse has the lowest stock?")

        self.assertEqual(res.status, "completed")
        self.assertEqual(len(chat_calls), 2)
        self.assertEqual(res.answer, "WH002 has the lowest stock.")

    def test_unrelated_warehouse_question_is_not_deterministic(self) -> None:
        chat_calls: list[dict[str, Any]] = []
        orchestrator = self._create_orchestrator(
            [
                {
                    "thought": "Look up warehouse details",
                    "action": "call_tool",
                    "tool_name": "erp.warehouses.list",
                    "arguments": {},
                },
                {
                    "thought": "Answer the warehouse question",
                    "action": "final_answer",
                    "final_answer": "The main warehouse is in Chennai.",
                },
            ],
            chat_calls=chat_calls,
        )

        res = orchestrator.process_question("What is the address of the main warehouse?")

        self.assertEqual(res.status, "completed")
        self.assertEqual(len(chat_calls), 2)
        self.assertEqual(res.answer, "The main warehouse is in Chennai.")
        self.assertNotIn("There are 2 warehouses in the ERP:", res.answer)

    def test_successful_single_tool_call(self) -> None:
        orchestrator = self._create_orchestrator(
            [
                # First step: decide to call warehouses.list
                {
                    "thought": "Need to list all warehouses",
                    "action": "call_tool",
                    "tool_name": "erp.warehouses.list",
                    "arguments": {},
                },
                # Second step: produce final answer grounded in returned warehouses
                {
                    "thought": "I have the warehouses list now",
                    "action": "final_answer",
                    "final_answer": "There are 2 warehouses: Main Warehouse in Chennai and Secondary Warehouse in Coimbatore.",
                },
            ]
        )
        res = orchestrator.process_question("List all warehouses")
        self.assertEqual(res.status, "completed")
        self.assertEqual(len(res.tool_calls), 1)
        self.assertEqual(res.tool_calls[0].tool_name, "erp.warehouses.list")
        self.assertEqual(res.tool_calls[0].status, "succeeded")
        self.assertIn("Main Warehouse", res.answer)

    def test_multiple_sequential_tool_calls(self) -> None:
        orchestrator = self._create_orchestrator(
            [
                # Step 1: search for bolts
                {
                    "thought": "Search for bolt products",
                    "action": "call_tool",
                    "tool_name": "erp.products.search",
                    "arguments": {"query": "Hex Bolt", "limit": 5},
                },
                # Step 2: get inventory for PRD001
                {
                    "thought": "Check inventory for PRD001",
                    "action": "call_tool",
                    "tool_name": "erp.inventory.get",
                    "arguments": {"product_id": "PRD001"},
                },
                # Step 3: final answer
                {
                    "thought": "Summarize stock",
                    "action": "final_answer",
                    "final_answer": "Hex Bolt M10 (PRD001) has 350 free stock in Main Warehouse and 160 in Secondary Warehouse.",
                },
            ]
        )
        res = orchestrator.process_question("How much stock do we have for Hex Bolt M10?")
        self.assertEqual(res.status, "completed")
        self.assertEqual(len(res.tool_calls), 2)
        self.assertEqual(res.tool_calls[0].tool_name, "erp.products.search")
        self.assertEqual(res.tool_calls[1].tool_name, "erp.inventory.get")
        self.assertIn("350 free stock", res.answer)

    def test_detect_repeated_identical_tool_call(self) -> None:
        orchestrator = self._create_orchestrator(
            [
                # Step 1: call inventory low_stock
                {
                    "thought": "Check low stock",
                    "action": "call_tool",
                    "tool_name": "erp.inventory.low_stock",
                    "arguments": {"limit": 10},
                },
                # Step 2: model attempts repeated identical call with same arguments
                {
                    "thought": "Check low stock again with identical args",
                    "action": "call_tool",
                    "tool_name": "erp.inventory.low_stock",
                    "arguments": {"limit": 10},
                },
                # Step 3: model provides answer after repeated call rejection notice
                {
                    "thought": "Answering now",
                    "action": "final_answer",
                    "final_answer": "Identified low-stock items across warehouses.",
                },
            ]
        )
        res = orchestrator.process_question("Which items are low in stock?")
        self.assertEqual(res.status, "completed")
        # Notice: only 1 tool call was actually executed; repeated was blocked!
        self.assertEqual(len(res.tool_calls), 1)

    def test_unknown_tool_handled(self) -> None:
        orchestrator = self._create_orchestrator(
            [
                # Step 1: model tries to call non-existent tool
                {
                    "thought": "Try calling unapproved tool",
                    "action": "call_tool",
                    "tool_name": "erp.dispatches.delete_all",
                    "arguments": {},
                },
                # Step 2: model realizes tool does not exist, provides final explanation
                {
                    "thought": "Explain capability",
                    "action": "final_answer",
                    "final_answer": "The requested operation is not supported by the ERP tools.",
                },
            ]
        )
        res = orchestrator.process_question("Delete dispatches")
        self.assertEqual(res.status, "error")
        self.assertEqual(res.error, "unsupported_capability")
        self.assertEqual(len(res.tool_calls), 0)
        self.assertIn("no approved read-only tool", res.answer)

    def test_max_tool_calls_bounded(self) -> None:
        # Construct an infinite tool call loop attempt
        loop_calls = [
            {
                "thought": f"Calling warehouse iteration {i}",
                "action": "call_tool",
                "tool_name": "erp.products.search",
                "arguments": {"query": f"query_{i}", "limit": 1},
            }
            for i in range(10)
        ]
        # max_tool_calls is 3
        orchestrator = self._create_orchestrator(loop_calls, max_tool_calls=3)
        res = orchestrator.process_question("Search everything in loop")
        self.assertLessEqual(len(res.tool_calls), 3)

    def test_ollama_unavailable_returns_actionable_error(self) -> None:
        def failing_handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Connection refused")

        transport = httpx.MockTransport(failing_handler)
        http_client = httpx.Client(transport=transport)
        client = OllamaClient(LlmConfig(), http_client=http_client)

        orchestrator = AgentOrchestrator(
            client=client,
            runner=self.runner,
            registry=self.registry,
        )
        res = orchestrator.process_question("What products exist?")
        self.assertEqual(res.status, "error")
        self.assertIn("unable to reach the local Ollama service", res.answer)


class TestFinancialRouting(unittest.TestCase):
    """Financial questions route to the aggregate finance tools."""

    def test_required_tool_evidence_routes_financial_terms(self) -> None:
        from backend.agent.orchestration.orchestrator import _required_tool_evidence

        self.assertEqual(
            _required_tool_evidence("What is our total revenue?"),
            ("erp.finance.sales_summary",),
        )
        self.assertEqual(
            _required_tool_evidence("Total sales by customer"),
            ("erp.finance.sales_summary",),
        )
        self.assertEqual(
            _required_tool_evidence("Invoiced revenue by month"),
            ("erp.finance.sales_summary",),
        )
        self.assertEqual(
            _required_tool_evidence("How much did we spend on purchases?"),
            ("erp.finance.purchase_summary",),
        )
        self.assertEqual(
            _required_tool_evidence("Purchase spend by supplier"),
            ("erp.finance.purchase_summary",),
        )
        self.assertEqual(
            _required_tool_evidence("Stock movement flow by warehouse"),
            ("erp.warehouse.movement_summary",),
        )
        self.assertEqual(
            _required_tool_evidence("What is our order fill rate?"),
            ("erp.fulfillment.summary",),
        )

    def test_unsupported_financial_domains_stay_unsupported(self) -> None:
        from backend.agent.orchestration.orchestrator import _required_tool_evidence

        # Individual pending purchase orders and outstanding balances are not
        # exposed by the aggregate purchase/sales tools.
        self.assertEqual(_required_tool_evidence("Show pending purchase orders."), ())
        self.assertEqual(
            _required_tool_evidence("What is the outstanding invoice balance?"), ()
        )
        self.assertEqual(_required_tool_evidence("Create product Bolt."), ())
        self.assertEqual(_required_tool_evidence("Delete dispatches"), ())


if __name__ == "__main__":
    unittest.main()
