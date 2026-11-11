from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
import httpx

from backend.agent.erp.config import ErpDatabaseConfig
from backend.agent.erp.registration import register_erp_tools
from backend.agent.erp.runner import ErpToolRunner
from backend.agent.erp.service import ErpReadService
from backend.agent.erp.sqlite_adapter import SqliteErpReadAdapter
from backend.agent.llm.client import OllamaClient
from backend.agent.llm.config import LlmConfig
from backend.agent.orchestration.orchestrator import AgentOrchestrator
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
        responses: list[dict[str, Any]],
        *,
        max_tool_calls: int = 5,
    ) -> AgentOrchestrator:
        resp_iter = iter(responses)

        def mock_handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/tags":
                return httpx.Response(200, json={"models": [{"name": "llama3.2:latest"}]})

            if request.url.path == "/api/chat":
                try:
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
                except StopIteration:
                    return httpx.Response(
                        200,
                        json={
                            "model": "llama3.2",
                            "message": {
                                "role": "assistant",
                                "content": json.dumps(
                                    {
                                        "thought": "No more responses",
                                        "action": "final_answer",
                                        "final_answer": "No further information.",
                                    }
                                ),
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
        self.assertEqual(res.status, "completed")
        self.assertEqual(len(res.tool_calls), 0)
        self.assertIn("not supported", res.answer)

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


if __name__ == "__main__":
    unittest.main()

