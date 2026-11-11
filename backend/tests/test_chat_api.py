from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock
import httpx
from fastapi import HTTPException

from backend.agent.erp.config import ErpDatabaseConfig
from backend.agent.erp.platform import ErpToolPlatform
from backend.agent.llm.client import OllamaClient
from backend.agent.llm.config import LlmConfig
from backend.agent.services.agent_service import AgentService
from backend.main import (
    app,
    chat_endpoint,
    ChatRequest,
    home,
    products,
    product,
    inventory,
    low_stock,
    pending_sales,
    pending_purchase,
    dispatch_issues,
    quality_issues,
    unpaid_invoices,
    invoice_outstanding,
)
from backend.tests.erp_support import create_erp_fixture_db


class TestChatApi(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "fixture_erp.db"
        create_erp_fixture_db(self.db_path)

        self.erp_config = ErpDatabaseConfig(self.db_path, query_timeout_seconds=5.0)
        self.platform = ErpToolPlatform.from_config(self.erp_config)

    def tearDown(self) -> None:
        self.platform.close()
        self.temp_dir.cleanup()

    def _setup_service(self, responses: list[dict[str, Any]]) -> tuple[AgentService, MagicMock]:
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
                                        "thought": "No more",
                                        "action": "final_answer",
                                        "final_answer": "Finished.",
                                    }
                                ),
                            },
                        },
                    )
            return httpx.Response(404, text="Not found")

        transport = httpx.MockTransport(mock_handler)
        http_client = httpx.Client(transport=transport)
        llm_client = OllamaClient(LlmConfig(), http_client=http_client)

        agent_service = AgentService.from_platform(self.platform, llm_client=llm_client)

        req = MagicMock()
        req.app.state.erp_tools = self.platform
        req.app.state.agent_service = agent_service
        return agent_service, req

    def test_chat_empty_message_raises_400(self) -> None:
        _, req = self._setup_service([])
        with self.assertRaises(HTTPException) as ctx:
            chat_endpoint(ChatRequest(message="   "), req)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("must not be empty", ctx.exception.detail)

    def test_successful_chat_endpoint_api_agent_chat(self) -> None:
        _, req = self._setup_service(
            [
                {
                    "thought": "Call warehouse list",
                    "action": "call_tool",
                    "tool_name": "erp.warehouses.list",
                    "arguments": {},
                },
                {
                    "thought": "Produce answer",
                    "action": "final_answer",
                    "final_answer": "There are 2 warehouses: Main Warehouse and Secondary Warehouse.",
                },
            ]
        )
        response = chat_endpoint(ChatRequest(message="List all warehouses"), req)
        self.assertEqual(response.status, "completed")
        self.assertIn("Main Warehouse", response.answer)
        self.assertEqual(len(response.tool_calls), 1)
        self.assertEqual(response.tool_calls[0].tool_name, "erp.warehouses.list")
        self.assertEqual(response.tool_calls[0].status, "succeeded")
        self.assertEqual(response.model, "llama3.2")
        self.assertIsNone(response.error)

    def test_successful_chat_endpoint_alias_chat(self) -> None:
        _, req = self._setup_service(
            [
                {
                    "thought": "Answer directly",
                    "action": "final_answer",
                    "final_answer": "Hex Bolt M10 is in stock.",
                }
            ]
        )
        # Using frontend style `question`
        response = chat_endpoint(ChatRequest(question="Stock of Hex Bolt"), req)
        self.assertEqual(response.status, "completed")
        self.assertEqual(response.answer, "Hex Bolt M10 is in stock.")
        self.assertEqual(len(response.tool_calls), 0)

    def test_chat_model_unavailable_returns_sanitized_error(self) -> None:
        def failing_handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Ollama is down")

        transport = httpx.MockTransport(failing_handler)
        http_client = httpx.Client(transport=transport)
        llm_client = OllamaClient(LlmConfig(), http_client=http_client)

        agent_service = AgentService.from_platform(self.platform, llm_client=llm_client)

        req = MagicMock()
        req.app.state.erp_tools = self.platform
        req.app.state.agent_service = agent_service

        response = chat_endpoint(ChatRequest(message="Show low stock"), req)
        self.assertEqual(response.status, "error")
        self.assertIn("unable to reach the local Ollama service", response.answer)
        self.assertEqual(response.error, "ollama_unavailable")

    def test_chat_uninitialized_service_returns_503(self) -> None:
        req = MagicMock()
        req.app.state.agent_service = None
        req.app.state.erp_tools = None

        with self.assertRaises(HTTPException) as ctx:
            chat_endpoint(ChatRequest(message="Hello"), req)
        self.assertEqual(ctx.exception.status_code, 503)

    def test_existing_erp_routes_preserved(self) -> None:
        # Verify home
        home_res = home()
        self.assertEqual(home_res["status"], "running")

        # Verify products
        all_prods = products()
        self.assertIsInstance(all_prods, list)
        self.assertGreater(len(all_prods), 0)

        # Verify product detail
        prod_res = product(all_prods[0]["product_id"])
        self.assertIsNotNone(prod_res)

        # Verify inventory
        inv_res = inventory(all_prods[0]["product_id"])
        self.assertIsInstance(inv_res, list)

        # Verify low stock
        ls_res = low_stock()
        self.assertIsInstance(ls_res, list)

        # Verify pending sales
        sales_res = pending_sales()
        self.assertIsInstance(sales_res, list)

        # Verify pending purchase
        po_res = pending_purchase()
        self.assertIsInstance(po_res, list)

        # Verify dispatch issues
        disp_res = dispatch_issues()
        self.assertIsInstance(disp_res, list)

        # Verify quality issues
        qual_res = quality_issues()
        self.assertIsInstance(qual_res, list)

        # Verify unpaid invoices
        unpaid_res = unpaid_invoices()
        self.assertIsInstance(unpaid_res, list)

    def test_platform_registers_dispatch_tools(self) -> None:
        registered_names = {
            definition.name for definition in self.platform.registry.list_tools()
        }
        for tool_name in (
            "erp.dispatches.get",
            "erp.dispatches.list",
            "erp.dispatches.by_sales_order",
        ):
            self.assertIn(tool_name, registered_names)
            self.assertTrue(self.platform.executor.has_handler(tool_name))
            self.assertIs(
                self.platform.registry.get(tool_name).metadata.get("read_only"),
                True,
            )

    def test_app_routes_registered(self) -> None:
        registered_paths = {route.path for route in app.routes}
        self.assertIn("/api/agent/chat", registered_paths)
        self.assertIn("/chat", registered_paths)
        self.assertIn("/products", registered_paths)
        self.assertIn("/inventory/alerts/low-stock", registered_paths)
        self.assertIn("/sales/pending", registered_paths)
        self.assertIn("/accounting/unpaid", registered_paths)


if __name__ == "__main__":
    unittest.main()
