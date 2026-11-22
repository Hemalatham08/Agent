"""Regression tests for Gemini failures after successful ERP analytics tools.

The observed failure was:

1. Gemini requested a financial analytics function.
2. The ERP tool succeeded and returned verified data.
3. The follow-up ``generateContent`` call returned HTTP 503.
4. The orchestrator fell back to raw JSON instead of a usable answer.

These tests use fakes only; no real Gemini or ERP network calls are made.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from google.genai import errors as genai_errors

from backend.agent.erp.config import ErpDatabaseConfig
from backend.agent.erp.platform import ErpToolPlatform
from backend.agent.orchestration.orchestrator import AgentOrchestrator
from backend.agent.services.agent_service import AgentService
from backend.ai_providers.gemini.adapter import GeminiLlmClientAdapter
from backend.ai_providers.gemini.client import GeminiClient
from backend.ai_providers.gemini.config import GeminiConfig
from backend.ai_providers.gemini.errors import (
    GeminiQuotaError,
    GeminiResponseError,
)
from backend.ai_providers.gemini.models import (
    GeminiChatMessage,
    GeminiChatRole,
    GeminiResponse,
)
from backend.tests.analytics_support import create_analytics_fixture_db


def _make_config() -> GeminiConfig:
    return GeminiConfig(api_key="test-key-12345", model="gemini-3.5-flash-lite")


def _fake_generate_response(text: str = "Recovered") -> SimpleNamespace:
    return SimpleNamespace(
        text=text,
        model_version="gemini-3.5-flash-lite",
        candidates=[SimpleNamespace(finish_reason="STOP", safety_ratings=[])],
    )


class GeminiRetryTests(unittest.TestCase):
    """HTTP 503/429 are retried with bounded backoff; other errors are not."""

    def test_chat_retries_503_then_succeeds(self) -> None:
        client = GeminiClient(_make_config())
        with (
            patch(
                "backend.ai_providers.gemini.client.genai.Client"
            ) as mock_client_class,
            patch("backend.ai_providers.gemini.client.time.sleep") as mock_sleep,
        ):
            generate = mock_client_class.return_value.models.generate_content
            generate.side_effect = [
                genai_errors.ServerError(
                    503,
                    {"error": {"message": "service unavailable", "code": 503}},
                    None,
                ),
                _fake_generate_response("Recovered after 503"),
            ]

            response = client.chat(
                [GeminiChatMessage(role=GeminiChatRole.USER, content="Q")]
            )

        self.assertEqual(response.content, "Recovered after 503")
        self.assertEqual(generate.call_count, 2)
        mock_sleep.assert_called_once()
        self.assertGreater(mock_sleep.call_args.args[0], 0)

    def test_chat_503_exhausts_bounded_retries(self) -> None:
        client = GeminiClient(_make_config())
        with (
            patch(
                "backend.ai_providers.gemini.client.genai.Client"
            ) as mock_client_class,
            patch("backend.ai_providers.gemini.client.time.sleep") as mock_sleep,
        ):
            generate = mock_client_class.return_value.models.generate_content
            generate.side_effect = genai_errors.ServerError(
                503,
                {"error": {"message": "service unavailable", "code": 503}},
                None,
            )

            with self.assertRaises(GeminiResponseError):
                client.chat([GeminiChatMessage(role=GeminiChatRole.USER, content="Q")])

        # Exactly three attempts: one initial request plus two retries.
        self.assertEqual(generate.call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)

    def test_chat_429_exhausts_bounded_retries(self) -> None:
        client = GeminiClient(_make_config())
        with (
            patch(
                "backend.ai_providers.gemini.client.genai.Client"
            ) as mock_client_class,
            patch("backend.ai_providers.gemini.client.time.sleep") as mock_sleep,
        ):
            generate = mock_client_class.return_value.models.generate_content
            generate.side_effect = genai_errors.ClientError(
                429,
                {"error": {"message": "quota exceeded", "code": 429}},
                None,
            )

            with self.assertRaises(GeminiQuotaError):
                client.chat([GeminiChatMessage(role=GeminiChatRole.USER, content="Q")])

        self.assertEqual(generate.call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)

    def test_chat_non_retryable_error_fails_immediately(self) -> None:
        client = GeminiClient(_make_config())
        with (
            patch(
                "backend.ai_providers.gemini.client.genai.Client"
            ) as mock_client_class,
            patch("backend.ai_providers.gemini.client.time.sleep") as mock_sleep,
        ):
            generate = mock_client_class.return_value.models.generate_content
            generate.side_effect = genai_errors.ServerError(
                500,
                {"error": {"message": "internal", "code": 500}},
                None,
            )

            with self.assertRaises(GeminiResponseError):
                client.chat([GeminiChatMessage(role=GeminiChatRole.USER, content="Q")])

        self.assertEqual(generate.call_count, 1)
        mock_sleep.assert_not_called()


class _ScriptedGeminiClient:
    """Return scripted native responses, or raise scripted errors."""

    def __init__(self, responses: list[object]) -> None:
        self._responses = list(responses)
        self.captured_messages: list[GeminiChatMessage] = []
        self.call_count = 0

    def chat(self, messages, **kwargs):
        self.call_count += 1
        self.captured_messages = list(messages)
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def validate_availability(self) -> None:
        return None

    def close(self) -> None:
        return None


def _function_call(
    call_id: str,
    name: str,
    arguments: dict,
) -> dict:
    return {
        "id": call_id,
        "name": name,
        "arguments": arguments,
        "thought_signature": None,
    }


def _function_call_response(*calls: dict) -> GeminiResponse:
    return GeminiResponse(
        content="",
        model="gemini-3.5-flash-lite",
        request_duration_ms=10.0,
        finish_reason="STOP",
        function_calls=list(calls),
    )


class GeminiAnalyticsFailureTests(unittest.TestCase):
    """A 503 after tool execution must preserve charts and verified data."""

    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp_dir.cleanup)
        database_path = create_analytics_fixture_db(
            Path(self._temp_dir.name) / "erp.db"
        )
        self.platform = ErpToolPlatform.from_config(
            ErpDatabaseConfig(database_path, query_timeout_seconds=5.0)
        )
        self.addCleanup(self.platform.close)

    def _service(
        self, responses: list[object]
    ) -> tuple[AgentService, _ScriptedGeminiClient]:
        fake = _ScriptedGeminiClient(responses)
        adapter = GeminiLlmClientAdapter(
            _make_config(),
            client=fake,  # type: ignore[arg-type]
            tool_registry=self.platform.registry,
        )
        orchestrator = AgentOrchestrator(
            client=adapter,
            runner=self.platform.runner,
            registry=self.platform.registry,
            max_tool_calls=5,
        )
        service = AgentService(
            platform=self.platform,
            client=adapter,
            orchestrator=orchestrator,
        )
        return service, fake

    def test_503_after_sales_summary_returns_chart_and_grounded_fallback(
        self,
    ) -> None:
        service, fake = self._service(
            [
                _function_call_response(
                    _function_call(
                        "call-fin-1",
                        "erp.finance.sales_summary",
                        {"group_by": "product", "basis": "booked"},
                    )
                ),
                GeminiResponseError("Gemini service error. Please try again later."),
            ]
        )

        result = service.answer_question("What is our total revenue by product?")

        self.assertEqual(result.status, "incomplete")
        self.assertEqual(result.error, "llm_error")
        self.assertEqual(len(result.tool_calls), 1)
        summary = result.tool_calls[0]
        self.assertEqual(summary.tool_name, "erp.finance.sales_summary")
        self.assertEqual(summary.status, "succeeded")
        self.assertIsInstance(summary.output, dict)
        self.assertEqual(summary.output["totals"]["revenue"], 14150.0)

        # The chart is derived from the successfully retrieved analytics rows.
        self.assertEqual(len(result.charts), 1)
        chart = result.charts[0]
        self.assertEqual(chart["title"], "Sales revenue by product (booked)")
        self.assertEqual(chart["x_field"], "key")
        self.assertEqual(chart["y_fields"], ["revenue"])
        self.assertEqual(len(chart["data"]), 6)
        self.assertEqual(chart["data"][0]["x"], "PRD005")
        self.assertEqual(chart["data"][0]["revenue"], 2860.0)

        # The fallback is a useful summary table, not a raw JSON dump.
        self.assertIn("encountered an error before a final answer", result.answer)
        self.assertIn("Sales summary by product (basis: booked)", result.answer)
        self.assertIn("Revenue: 14,150.00", result.answer)
        self.assertIn("| PRD005 |", result.answer)
        self.assertNotIn('"totals":', result.answer)
        self.assertNotIn('"rows":', result.answer)
        self.assertNotIn('"row_count":', result.answer)

        # The follow-up request rebuilt a valid native function-call turn and
        # fed the verified ERP output back with the matching function call id.
        self.assertEqual(fake.call_count, 2)
        self.assertEqual(
            [message.role for message in fake.captured_messages],
            [
                GeminiChatRole.SYSTEM,
                GeminiChatRole.USER,
                GeminiChatRole.MODEL,
                GeminiChatRole.TOOL,
            ],
        )
        model_message = fake.captured_messages[2]
        self.assertEqual(model_message.function_calls[0]["id"], "call-fin-1")
        self.assertEqual(
            model_message.function_calls[0]["name"],
            "erp.finance.sales_summary",
        )
        tool_message = fake.captured_messages[3]
        self.assertEqual(tool_message.call_id, "call-fin-1")
        self.assertEqual(tool_message.tool_name, "erp.finance.sales_summary")
        self.assertEqual(
            json.loads(tool_message.content)["output"]["totals"]["revenue"],
            14150.0,
        )

    def test_503_after_multiple_analytics_calls_preserves_all_results(
        self,
    ) -> None:
        service, fake = self._service(
            [
                _function_call_response(
                    _function_call(
                        "call-sales",
                        "erp.finance.sales_summary",
                        {"group_by": "product", "basis": "booked"},
                    ),
                    _function_call(
                        "call-purchase",
                        "erp.finance.purchase_summary",
                        {"group_by": "supplier", "basis": "ordered"},
                    ),
                ),
                GeminiResponseError("Gemini service error. Please try again later."),
            ]
        )

        result = service.answer_question(
            "Show revenue by product and purchase spend by supplier"
        )

        self.assertEqual(result.status, "incomplete")
        self.assertEqual(result.error, "llm_error")
        self.assertEqual(
            [call.tool_name for call in result.tool_calls],
            [
                "erp.finance.sales_summary",
                "erp.finance.purchase_summary",
            ],
        )
        self.assertTrue(all(call.status == "succeeded" for call in result.tool_calls))

        # Both successful analytics results remain chartable.
        self.assertEqual(len(result.charts), 2)
        self.assertEqual(
            [chart["title"] for chart in result.charts],
            [
                "Sales revenue by product (booked)",
                "Purchase ordered value by supplier",
            ],
        )

        # Both summaries are present and no raw JSON was substituted.
        self.assertIn("Sales summary by product (basis: booked)", result.answer)
        self.assertIn("Purchase summary by supplier (basis: ordered)", result.answer)
        self.assertIn("| SUP003 |", result.answer)
        self.assertNotIn('"totals":', result.answer)
        self.assertNotIn('"rows":', result.answer)

        # Both function responses are paired with the correct call ids.
        tool_messages = [
            message
            for message in fake.captured_messages
            if message.role is GeminiChatRole.TOOL
        ]
        self.assertEqual(
            [(message.call_id, message.tool_name) for message in tool_messages],
            [
                ("call-sales", "erp.finance.sales_summary"),
                ("call-purchase", "erp.finance.purchase_summary"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
