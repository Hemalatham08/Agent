from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
import httpx

from backend.agent.erp.config import ErpDatabaseConfig
from backend.agent.erp.definitions import ERP_TOOL_DEFINITIONS
from backend.agent.erp.registration import register_erp_tools
from backend.agent.erp.runner import ErpToolRunner
from backend.agent.erp.service import ErpReadService
from backend.agent.erp.sqlite_adapter import SqliteErpReadAdapter
from backend.agent.llm.client import OllamaClient
from backend.agent.llm.config import LlmConfig
from backend.agent.orchestration.orchestrator import AgentOrchestrator
from backend.agent.orchestration.prompts import build_system_prompt
from backend.agent.tools.executor import ToolExecutor
from backend.agent.tools.registry import ToolRegistry
from backend.tests.erp_support import create_erp_fixture_db


class TestBusinessQuestions(unittest.TestCase):
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

    def _create_orchestrator(self, responses: list[dict[str, Any]]) -> AgentOrchestrator:
        resp_iter = iter(responses)

        def mock_handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/tags":
                return httpx.Response(200, json={"models": [{"name": "llama3.2:latest"}]})

            if request.url.path == "/api/chat":
                resp_data = next(resp_iter)
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
        )

    def test_question_list_all_warehouses(self) -> None:
        orchestrator = self._create_orchestrator(
            [
                {
                    "thought": "Need to list warehouses",
                    "action": "call_tool",
                    "tool_name": "erp.warehouses.list",
                    "arguments": {},
                },
                {
                    "thought": "Summarize warehouses grounded in results",
                    "action": "final_answer",
                    "final_answer": "We have 2 warehouses: Main Warehouse (WH001) in Chennai and Secondary Warehouse (WH002) in Coimbatore.",
                },
            ]
        )
        res = orchestrator.process_question("List all warehouses.")
        self.assertEqual(res.status, "completed")
        self.assertEqual(len(res.tool_calls), 1)
        self.assertEqual(res.tool_calls[0].tool_name, "erp.warehouses.list")
        self.assertEqual(res.tool_calls[0].status, "succeeded")
        self.assertIn("Main Warehouse", res.answer)
        self.assertIn("WH001", res.answer)

    def test_question_low_stock_products(self) -> None:
        orchestrator = self._create_orchestrator(
            [
                {
                    "thought": "Find products with low stock",
                    "action": "call_tool",
                    "tool_name": "erp.inventory.low_stock",
                    "arguments": {"limit": 10},
                },
                {
                    "thought": "Format low stock response",
                    "action": "final_answer",
                    "final_answer": "The following products are at or below reorder level: Hex Bolt M10 (PRD001) in WH001 (free stock: 350, reorder level: 500) and WH002 (free stock: 160).",
                },
            ]
        )
        res = orchestrator.process_question("Which products are low in stock?")
        self.assertEqual(res.status, "completed")
        self.assertEqual(len(res.tool_calls), 1)
        self.assertEqual(res.tool_calls[0].tool_name, "erp.inventory.low_stock")
        self.assertIn("Hex Bolt M10", res.answer)

    def test_question_product_details(self) -> None:
        orchestrator = self._create_orchestrator(
            [
                {
                    "thought": "Search for Hex Bolt",
                    "action": "call_tool",
                    "tool_name": "erp.products.search",
                    "arguments": {"query": "Hex Bolt", "limit": 5},
                },
                {
                    "thought": "Format product details",
                    "action": "final_answer",
                    "final_answer": "Found Hex Bolt M10 (PRD001): Category: Bolts, Material: Stainless Steel, Grade: SS304, Size: M10.",
                },
            ]
        )
        res = orchestrator.process_question("Show me product Hex Bolt details.")
        self.assertEqual(res.status, "completed")
        self.assertEqual(len(res.tool_calls), 1)
        self.assertEqual(res.tool_calls[0].tool_name, "erp.products.search")
        self.assertIn("PRD001", res.answer)

    def test_question_sales_order_details(self) -> None:
        orchestrator = self._create_orchestrator(
            [
                {
                    "thought": "Retrieve sales order SO001",
                    "action": "call_tool",
                    "tool_name": "erp.sales_orders.get",
                    "arguments": {"so_id": "SO001"},
                },
                {
                    "thought": "Format sales order details",
                    "action": "final_answer",
                    "final_answer": "Sales Order SO001 for Sri Venkateswara Engineering is 'Partially Dispatched' and contains 100 units of Hex Bolt M10 and 100 units of Hex Nut M10.",
                },
            ]
        )
        res = orchestrator.process_question("Show me sales order SO001.")
        self.assertEqual(res.status, "completed")
        self.assertEqual(len(res.tool_calls), 1)
        self.assertEqual(res.tool_calls[0].tool_name, "erp.sales_orders.get")
        self.assertIn("Sri Venkateswara Engineering", res.answer)

    def test_question_delivered_elements_uses_dispatch_tools(self) -> None:
        # Primary business question: "Give me the list of elements that are delivered."
        # The agent must use dispatch tools (NOT sales orders or inventory) and
        # must distinguish dispatched quantities from confirmed delivery.
        orchestrator = self._create_orchestrator(
            [
                {
                    "thought": (
                        "User asks for delivered elements. The ERP tracks dispatch records, "
                        "not confirmed customer delivery. I will list dispatches and their items."
                    ),
                    "action": "call_tool",
                    "tool_name": "erp.dispatches.list",
                    "arguments": {"limit": 20},
                },
                {
                    "thought": (
                        "I have the dispatch records. I need the item-level dispatched "
                        "quantities, so I fetch details for each dispatch."
                    ),
                    "action": "call_tool",
                    "tool_name": "erp.dispatches.get",
                    "arguments": {"dispatch_id": "DSP001"},
                },
                {
                    "thought": (
                        "I now have item-level dispatched quantities grounded in dispatch "
                        "records. I must present them as dispatched, not delivered."
                    ),
                    "action": "final_answer",
                    "final_answer": (
                        "The ERP contains dispatch records, but it does not establish confirmed "
                        "customer delivery. The following items have been dispatched: "
                        "Hex Bolt M10 (PRD001) - 100 units dispatched via BlueDart (tracking BD10001) "
                        "on 2026-10-04, and Hex Nut M10 (PRD002) - 40 units dispatched (partial; "
                        "50 picked). These records show warehouse dispatch to the carrier, "
                        "not proof of delivery to the customer."
                    ),
                },
            ]
        )
        res = orchestrator.process_question(
            "Give me the list of elements that are delivered."
        )
        self.assertEqual(res.status, "completed")
        self.assertEqual(len(res.tool_calls), 2)
        self.assertEqual(res.tool_calls[0].tool_name, "erp.dispatches.list")
        self.assertEqual(res.tool_calls[0].status, "succeeded")
        self.assertEqual(res.tool_calls[1].tool_name, "erp.dispatches.get")
        self.assertIn("dispatched", res.answer.lower())
        self.assertIn("does not establish confirmed", res.answer.lower())

    def test_question_show_all_dispatches(self) -> None:
        orchestrator = self._create_orchestrator(
            [
                {
                    "thought": "List dispatch records",
                    "action": "call_tool",
                    "tool_name": "erp.dispatches.list",
                    "arguments": {},
                },
                {
                    "thought": "Summarize dispatches grounded in results",
                    "action": "final_answer",
                    "final_answer": (
                        "There are 2 dispatch records: DSP001 (SO001, BlueDart, 2026-10-04, "
                        "Partially Dispatched) and DSP002 (SO002, DTDC, 2026-10-06, Dispatched)."
                    ),
                },
            ]
        )
        res = orchestrator.process_question("Show me all dispatches.")
        self.assertEqual(res.status, "completed")
        self.assertEqual(len(res.tool_calls), 1)
        self.assertEqual(res.tool_calls[0].tool_name, "erp.dispatches.list")
        self.assertEqual(res.tool_calls[0].status, "succeeded")
        self.assertIn("DSP001", res.answer)
        self.assertIn("DSP002", res.answer)

    def test_question_dispatch_details_by_id(self) -> None:
        orchestrator = self._create_orchestrator(
            [
                {
                    "thought": "Fetch dispatch DSP001 details",
                    "action": "call_tool",
                    "tool_name": "erp.dispatches.get",
                    "arguments": {"dispatch_id": "DSP001"},
                },
                {
                    "thought": "Summarize dispatch details",
                    "action": "final_answer",
                    "final_answer": (
                        "Dispatch DSP001 against SO001 was sent on 2026-10-04 via BlueDart "
                        "(tracking BD10001) and is Partially Dispatched. Items: Hex Bolt M10 "
                        "(100 dispatched of 100 picked) and Hex Nut M10 (40 dispatched of 50 picked)."
                    ),
                },
            ]
        )
        res = orchestrator.process_question("Show dispatch details for DSP001.")
        self.assertEqual(res.status, "completed")
        self.assertEqual(len(res.tool_calls), 1)
        self.assertEqual(res.tool_calls[0].tool_name, "erp.dispatches.get")
        self.assertIn("BlueDart", res.answer)

    def test_question_items_dispatched_against_sales_order(self) -> None:
        orchestrator = self._create_orchestrator(
            [
                {
                    "thought": "Fetch dispatches for sales order SO001",
                    "action": "call_tool",
                    "tool_name": "erp.dispatches.by_sales_order",
                    "arguments": {"so_id": "SO001"},
                },
                {
                    "thought": "Summarize item-level dispatched quantities",
                    "action": "final_answer",
                    "final_answer": (
                        "Sales order SO001 has one dispatch (DSP001, BlueDart, tracking BD10001, "
                        "Partially Dispatched). Dispatched items: Hex Bolt M10 (100 units) and "
                        "Hex Nut M10 (40 of 50 picked units)."
                    ),
                },
            ]
        )
        res = orchestrator.process_question(
            "Which items were dispatched against SO001?"
        )
        self.assertEqual(res.status, "completed")
        self.assertEqual(len(res.tool_calls), 1)
        self.assertEqual(
            res.tool_calls[0].tool_name,
            "erp.dispatches.by_sales_order",
        )
        self.assertIn("Hex Bolt M10", res.answer)

    def test_question_unknown_dispatch_reports_not_found(self) -> None:
        orchestrator = self._create_orchestrator(
            [
                {
                    "thought": "Fetch dispatch DSP999 details",
                    "action": "call_tool",
                    "tool_name": "erp.dispatches.get",
                    "arguments": {"dispatch_id": "DSP999"},
                },
                {
                    "thought": (
                        "The dispatch was not found. I must say so truthfully "
                        "instead of inventing a dispatch record."
                    ),
                    "action": "final_answer",
                    "final_answer": (
                        "No dispatch record exists for DSP999. The ERP contains dispatch "
                        "records, but it does not establish confirmed customer delivery."
                    ),
                },
            ]
        )
        res = orchestrator.process_question("Show dispatch details for DSP999.")
        self.assertEqual(res.status, "error")
        self.assertEqual(res.error, "tool_evidence_failed")
        self.assertEqual(len(res.tool_calls), 1)
        self.assertEqual(res.tool_calls[0].status, "failed")
        self.assertIn("could not retrieve verified ERP data", res.answer)

    def test_delivery_answer_must_not_fabricate_delivery(self) -> None:
        # Delivery-vs-dispatch safety: even if the model is asked directly about
        # delivered items, the grounded answer must present dispatch records and
        # state that confirmed customer delivery is not tracked. The orchestrator
        # must never substitute sales-order status as delivery evidence.
        orchestrator = self._create_orchestrator(
            [
                {
                    "thought": (
                        "User asks about delivered items. Dispatch records are the closest "
                        "grounded evidence; sales order status is not delivery evidence."
                    ),
                    "action": "call_tool",
                    "tool_name": "erp.dispatches.list",
                    "arguments": {"status": "Dispatched"},
                },
                {
                    "thought": "Ground the answer in dispatch records only",
                    "action": "final_answer",
                    "final_answer": (
                        "The ERP contains dispatch records, but it does not establish confirmed "
                        "customer delivery. Fully dispatched record: DSP002 (SO002) via DTDC "
                        "with tracking DT20002 on 2026-10-06, containing 10 units of 100% "
                        "Steel Plate. No delivery receipts or proof-of-delivery data exist "
                        "in this ERP."
                    ),
                },
            ]
        )
        res = orchestrator.process_question("Which products were delivered today?")
        self.assertEqual(res.status, "completed")
        self.assertEqual(len(res.tool_calls), 1)
        self.assertEqual(res.tool_calls[0].tool_name, "erp.dispatches.list")
        self.assertEqual(res.tool_calls[0].arguments, {"status": "Dispatched"})
        self.assertIn("does not establish confirmed", res.answer.lower())
        self.assertIn("proof-of-delivery", res.answer.lower())


class TestDispatchPromptSemantics(unittest.TestCase):
    """The dynamic system prompt must teach the dispatch/delivery distinction."""

    def test_system_prompt_exposes_dispatch_tools(self) -> None:
        prompt = build_system_prompt(
            [d.model_dump() for d in ERP_TOOL_DEFINITIONS]
        )
        for tool_name in (
            "erp.dispatches.get",
            "erp.dispatches.list",
            "erp.dispatches.by_sales_order",
        ):
            self.assertIn(tool_name, prompt)

    def test_system_prompt_distinguishes_dispatched_from_delivered(self) -> None:
        prompt = build_system_prompt(
            [d.model_dump() for d in ERP_TOOL_DEFINITIONS]
        )
        self.assertIn("Dispatched quantity", prompt)
        self.assertIn("Delivered quantity", prompt)
        self.assertIn("does not establish confirmed customer delivery", prompt)
        self.assertIn("NEVER fabricate delivery", prompt)

    def test_system_prompt_forbids_sales_order_status_as_delivery_evidence(self) -> None:
        prompt = build_system_prompt(
            [d.model_dump() for d in ERP_TOOL_DEFINITIONS]
        )
        self.assertIn(
            "NEVER use sales order status alone as delivery evidence",
            prompt,
        )


class TestProductPromptSemantics(unittest.TestCase):
    """The system prompt must teach single-call product listing."""

    def test_system_prompt_documents_single_call_product_listing(self) -> None:
        prompt = build_system_prompt(
            [d.model_dump() for d in ERP_TOOL_DEFINITIONS]
        )
        self.assertIn("erp.products.search", prompt)
        self.assertIn("no `query` argument", prompt)
        self.assertIn("Do not search for each product separately", prompt)


if __name__ == "__main__":
    unittest.main()
