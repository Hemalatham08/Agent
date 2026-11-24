"""Regression tests for final-answer completeness after budget exhaustion.

These tests verify that when the tool-call budget is exhausted, the synthesis
path reliably includes all relevant successful ERP outputs via the deterministic
fallback, rather than accepting a potentially incomplete model-generated answer.

The normal in-loop final_answer path is intentionally left unchanged.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from backend.agent.erp.config import ErpDatabaseConfig
from backend.agent.erp.platform import ErpToolPlatform
from backend.agent.llm.client import OllamaClient
from backend.agent.llm.config import LlmConfig
from backend.agent.orchestration.models import ToolCallSummary
from backend.agent.orchestration.orchestrator import AgentOrchestrator
from backend.agent.tools.contracts import ToolExecutionStatus
from backend.ai_providers.gemini.client import GeminiClient
from backend.ai_providers.gemini.config import GeminiConfig
from backend.tests.erp_support import create_erp_fixture_db

# Sixth product inserted to reach the six-product scenario required by the
# regression (the shared fixture seeds five products).
_PRODUCT_ROW = (
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
)


class TestFinalAnswerCompleteness(unittest.TestCase):
    """Final-answer completeness regressions for the budget-exhaustion path."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "fixture_erp.db"
        create_erp_fixture_db(self.db_path)
        self._insert_sixth_product()
        self.erp_config = ErpDatabaseConfig(self.db_path, query_timeout_seconds=5.0)
        self.platform = ErpToolPlatform.from_config(self.erp_config)

    def tearDown(self) -> None:
        self.platform.close()
        self.temp_dir.cleanup()

    def _insert_sixth_product(self) -> None:
        connection = sqlite3.connect(self.db_path)
        try:
            connection.execute(
                "INSERT INTO products VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                _PRODUCT_ROW,
            )
            connection.commit()
        finally:
            connection.close()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _make_ollama_orchestrator(
        self,
        responses: list[dict | Exception | httpx.Response],
        *,
        max_tool_calls: int = 5,
    ) -> AgentOrchestrator:
        """Build an Ollama-backed orchestrator driven by scripted responses."""
        resp_iter = iter(responses)

        def mock_handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/tags":
                return httpx.Response(200, json={"models": [{"name": "llama3.2:latest"}]})
            if request.url.path == "/api/chat":
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
            runner=self.platform.runner,
            registry=self.platform.registry,
            max_tool_calls=max_tool_calls,
        )

    def _make_fake_gemini_response(
        self, function_calls=None, text="Final answer"
    ):
        """Create a fake Gemini response with optional function calls."""
        parts = []
        if function_calls:
            for fc in function_calls:
                parts.append(SimpleNamespace(text=None, function_call=fc))
        else:
            parts.append(SimpleNamespace(text=text, function_call=None))
        content = SimpleNamespace(parts=parts, role="model")
        candidate = SimpleNamespace(
            content=content,
            finish_reason="STOP",
            safety_ratings=[],
        )
        return SimpleNamespace(
            candidates=[candidate],
            model_version="gemini-3.5-flash-lite",
        )

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    def test_budget_exhaustion_six_products_partial_inventory(self) -> None:
        """Six products searched, only four inventory lookups complete before
        budget exhaustion; the fallback must list every product without
        inventing stock for the unlooked-up products."""
        responses = [
            {
                "thought": "Search all products",
                "action": "call_tool",
                "tool_name": "erp.products.search",
                "arguments": {},
            },
            {
                "thought": "Check stock PRD001",
                "action": "call_tool",
                "tool_name": "erp.inventory.get",
                "arguments": {"product_id": "PRD001"},
            },
            {
                "thought": "Check stock PRD002",
                "action": "call_tool",
                "tool_name": "erp.inventory.get",
                "arguments": {"product_id": "PRD002"},
            },
            {
                "thought": "Check stock PRD003",
                "action": "call_tool",
                "tool_name": "erp.inventory.get",
                "arguments": {"product_id": "PRD003"},
            },
            {
                "thought": "Check stock PRD004",
                "action": "call_tool",
                "tool_name": "erp.inventory.get",
                "arguments": {"product_id": "PRD004"},
            },
            {
                "thought": "Incomplete subset answer",
                "action": "final_answer",
                "final_answer": "Only PRD001 and PRD002 were fully checked; "
                "stock for the rest could not be completed due to tool-call limits.",
            },
        ]
        orchestrator = self._make_ollama_orchestrator(responses, max_tool_calls=5)
        res = orchestrator.process_question("list all products and available stock")

        self.assertEqual(res.status, "completed")
        self.assertEqual(res.iterations, 5)
        self.assertEqual(len(res.tool_calls), 5)
        # All six products are listed from the successful product search.
        for pid in ("PRD001", "PRD002", "PRD003", "PRD004", "PRD005", "PRD006"):
            self.assertIn(pid, res.answer)
        # Real verified stock data for the products that were looked up.
        self.assertIn("On hand", res.answer)
        # The model's incomplete subset answer was overridden by the fallback.
        self.assertNotIn("Only PRD001 and PRD002 were fully checked", res.answer)
        # PRD005 and PRD006 were never looked up: they appear as products but
        # carry no on_hand_qty inventory entry (missing data != zero stock).
        self.assertNotIn('"product_id": "PRD005", "on_hand_qty"', res.answer)
        self.assertNotIn('"product_id": "PRD006", "on_hand_qty"', res.answer)

    def test_model_subset_final_answer_is_overridden_by_fallback(self) -> None:
        """When the model's synthesis answer mentions only a subset of the
        successfully retrieved products, the deterministic fallback is used and
        includes every successful product."""
        responses = [
            {
                "thought": "Search products",
                "action": "call_tool",
                "tool_name": "erp.products.search",
                "arguments": {},
            },
            {
                "thought": "Check stock PRD001",
                "action": "call_tool",
                "tool_name": "erp.inventory.get",
                "arguments": {"product_id": "PRD001"},
            },
            {
                "thought": "Subset answer",
                "action": "final_answer",
                "final_answer": "PRD001 has stock. Other products were not checked.",
            },
        ]
        orchestrator = self._make_ollama_orchestrator(responses, max_tool_calls=2)
        res = orchestrator.process_question("list all products and available stock")

        self.assertEqual(res.status, "completed")
        self.assertEqual(res.iterations, 2)
        self.assertEqual(len(res.tool_calls), 2)
        # Fallback includes ALL products from the successful search.
        for pid in ("PRD001", "PRD002", "PRD003", "PRD004", "PRD005", "PRD006"):
            self.assertIn(pid, res.answer)
        # The model's incomplete subset text is not the final answer.
        self.assertNotIn("Other products were not checked", res.answer)

    def test_fallback_distinguishes_missing_data_from_zero_stock(self) -> None:
        """The fallback renders verified zero stock as zero but never invents
        stock data for a product whose lookup did not succeed."""
        summaries = [
            ToolCallSummary(
                tool_name="erp.inventory.get",
                arguments={"product_id": "PRD001"},
                status=ToolExecutionStatus.SUCCEEDED.value,
            )
        ]
        outputs = [
            # PRD001 looked up successfully: zero stock is shown as 0 (real data).
            ("erp.inventory.get", {"product_id": "PRD001", "on_hand_qty": 0}),
            # PRD002 was never looked up: it must not appear with invented data.
        ]
        answer = AgentOrchestrator._fallback_answer(summaries, outputs)

        self.assertIn("PRD001", answer)
        self.assertIn('"on_hand_qty": 0', answer)
        # Missing data (unlooked-up product) is not invented.
        self.assertNotIn("PRD002", answer)

    def test_gemini_native_batch_mixed_success_cancelled(self) -> None:
        """A Gemini native batch with mixed successful and cancelled calls:
        exactly two Gemini requests, two succeeded + one cancelled, and the
        fallback answer includes data from both successful calls."""
        fc1 = SimpleNamespace(id="call-1", name="erp.warehouses.list", args={})
        fc2 = SimpleNamespace(id="call-2", name="erp.products.search", args={})
        fc3 = SimpleNamespace(
            id="call-3", name="erp.inventory.get", args={"product_id": "PRD001"}
        )

        response1 = self._make_fake_gemini_response([fc1, fc2, fc3])
        response2 = self._make_fake_gemini_response(text="Final answer from model.")

        with patch(
            "backend.ai_providers.gemini.client.genai.Client"
        ) as mock_client_class:
            mock_client = mock_client_class.return_value
            mock_client.models.list.return_value = [
                SimpleNamespace(name="gemini-3.5-flash-lite", version="1")
            ]
            mock_client.models.generate_content.side_effect = [response1, response2]

            orchestrator = AgentOrchestrator(
                client=GeminiClient(
                    GeminiConfig(api_key="test-key-12345", model="gemini-3.5-flash-lite")
                ),
                runner=self.platform.runner,
                registry=self.platform.registry,
                max_tool_calls=2,
            )
            result = orchestrator.process_question("list products and warehouses")

        self.assertEqual(result.status, "completed")
        # Exactly two Gemini requests (no third request after budget exhaustion).
        self.assertEqual(mock_client.models.generate_content.call_count, 2)
        # Three tool call summaries: two succeeded, one cancelled (budget limit).
        self.assertEqual(len(result.tool_calls), 3)
        statuses = [tc.status for tc in result.tool_calls]
        self.assertEqual(statuses.count("succeeded"), 2)
        self.assertEqual(statuses.count("cancelled"), 1)
        # Fallback includes data from both successful calls in the batch.
        self.assertIn("warehouse", result.answer.lower())
        self.assertIn("PRD001", result.answer)

    def test_normal_in_loop_final_answer_unchanged(self) -> None:
        """The normal in-loop final_answer path is left untouched: the model's
        in-loop answer is used as-is and is not replaced by the fallback."""
        responses = [
            {
                "thought": "Search products",
                "action": "call_tool",
                "tool_name": "erp.products.search",
                "arguments": {},
            },
            {
                "thought": "Final answer",
                "action": "final_answer",
                "final_answer": "Here are the products: PRD001, PRD002, PRD003.",
            },
        ]
        orchestrator = self._make_ollama_orchestrator(responses, max_tool_calls=5)
        res = orchestrator.process_question("list all products")

        # In-loop path is untouched: the model's final answer is used verbatim.
        self.assertEqual(res.status, "completed")
        self.assertEqual(res.iterations, 2)
        self.assertEqual(len(res.tool_calls), 1)
        self.assertEqual(
            res.answer, "Here are the products: PRD001, PRD002, PRD003."
        )
