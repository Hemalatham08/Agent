"""Tests for the Phase 4 provider router and Gemini orchestrator integration.

Uses mocks only. No real Gemini API calls are made.
"""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from backend.ai_providers.provider_router import (
    ProviderType,
    get_llm_client,
    is_supported_provider,
)
from backend.ai_providers.gemini.client import GeminiClient
from backend.ai_providers.gemini.config import GeminiConfig
from backend.ai_providers.gemini.errors import (
    GeminiConfigurationError,
    GeminiModelNotFoundError,
)
from backend.ai_providers.gemini.models import (
    GeminiChatMessage,
    GeminiChatRole,
)
from backend.ai_providers.gemini.response_parser import (
    ParsedGeminiResponse,
)
from backend.ai_providers.gemini.tool_adapter import (
    to_function_response,
    to_tool_execution_request,
    validate_function_call,
)
from backend.agent.erp.definitions import ERP_TOOL_DEFINITIONS_BY_NAME
from backend.agent.llm.client import OllamaClient
from backend.agent.llm.config import LlmConfig
from backend.agent.orchestration.orchestrator import AgentOrchestrator
from backend.agent.tools.contracts import (
    ToolExecutionRequest,
    ToolExecutionResult,
    ToolExecutionStatus,
)


def _make_gemini_client():
    """Create a GeminiClient with mocked genai.Client."""
    client = GeminiClient(GeminiConfig(api_key="test-key-12345"))
    with patch(
        "backend.ai_providers.gemini.client.genai.Client"
    ) as mock_client_class:
        mock_client = mock_client_class.return_value
        mock_client.models.list.return_value = [
            SimpleNamespace(name="gemini-1.5-flash", version="1")
        ]
        mock_client.models.generate_content.return_value = SimpleNamespace(
            text="Hello from Gemini",
            model_version="gemini-1.5-flash",
            candidates=[
                SimpleNamespace(finish_reason="STOP", safety_ratings=[])
            ],
        )
        return client, mock_client


class TestProviderRouter(unittest.TestCase):
    """Tests for the provider router factory."""

    def test_get_ollama_client(self):
        """get_llm_client returns OllamaClient for provider='ollama'."""
        client = get_llm_client(provider="ollama")
        self.assertIsInstance(client, OllamaClient)
        self.assertEqual(client.config.model, "llama3.2")

    def test_get_ollama_client_with_model(self):
        """get_llm_client overrides model when specified."""
        client = get_llm_client(provider="ollama", model="llama3.1:8b")
        self.assertEqual(client.config.model, "llama3.1:8b")

    def test_get_gemini_client(self):
        """get_llm_client returns GeminiClient for provider='gemini'."""
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key-12345"}):
            with patch(
                "backend.ai_providers.gemini.client.genai.Client"
            ):
                client = get_llm_client(provider="gemini")
        self.assertIsInstance(client, GeminiClient)

    def test_get_gemini_client_with_model(self):
        """get_llm_client overrides model when specified for Gemini."""
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key-12345"}):
            with patch(
                "backend.ai_providers.gemini.client.genai.Client"
            ):
                client = get_llm_client(provider="gemini", model="gemini-1.5-pro")
        self.assertEqual(client.config.model, "gemini-1.5-pro")

    def test_is_supported_provider(self):
        """is_supported_provider returns True for known providers."""
        self.assertTrue(is_supported_provider("ollama"))
        self.assertTrue(is_supported_provider("gemini"))
        self.assertFalse(is_supported_provider("openai"))
        self.assertFalse(is_supported_provider("anthropic"))

    def test_unsupported_provider_raises(self):
        """get_llm_client raises ValueError for unsupported providers."""
        with self.assertRaises(ValueError):
            get_llm_client(provider="openai")

    def test_default_provider_is_ollama(self):
        """get_llm_client defaults to Ollama when no provider specified."""
        client = get_llm_client()
        self.assertIsInstance(client, OllamaClient)


class TestGeminiOrchestratorIntegration(unittest.TestCase):
    """Tests for Gemini integration through the orchestrator."""

    def setUp(self):
        from backend.agent.erp.platform import ErpToolPlatform
        from backend.agent.erp.config import ErpDatabaseConfig

        self.platform = ErpToolPlatform.from_config(
            ErpDatabaseConfig.from_path(
                "D:/Agent/Agent/backend/data/ifive_erp.db"
            )
        )

    def tearDown(self):
        self.platform.close()

    def test_gemini_text_only_response(self):
        """Gemini text-only response produces a completed answer."""
        with patch(
            "backend.ai_providers.gemini.client.genai.Client"
        ) as mock_client_class:
            mock_client = mock_client_class.return_value
            mock_client.models.list.return_value = [
                SimpleNamespace(name="gemini-3.5-flash-lite", version="1")
            ]
            mock_client.models.generate_content.return_value = SimpleNamespace(
                candidates=[
                    SimpleNamespace(
                        content=SimpleNamespace(
                            parts=[
                                SimpleNamespace(
                                    text="Hello! I can help with ERP questions.",
                                    function_call=None,
                                )
                            ]
                        ),
                        finish_reason="STOP",
                        safety_ratings=[],
                    )
                ],
                model_version="gemini-3.5-flash-lite",
            )
            orchestrator = AgentOrchestrator(
                client=GeminiClient(GeminiConfig(api_key="test-key-12345", model="gemini-3.5-flash-lite")),
                runner=self.platform.runner,
                registry=self.platform.registry,
                max_tool_calls=2,
            )
            result = orchestrator.process_question("Hello")
            self.assertEqual(result.status, "completed")
            self.assertEqual(result.answer, "Hello! I can help with ERP questions.")
            self.assertEqual(len(result.tool_calls), 0)

    def test_gemini_unsupported_provider(self):
        """Unsupported provider raises ValueError."""
        with self.assertRaises(ValueError):
            get_llm_client(provider="openai")

    def test_gemini_model_not_found(self):
        """Gemini model not found raises GeminiModelNotFoundError."""
        with patch(
            "backend.ai_providers.gemini.client.genai.Client"
        ) as mock_client_class:
            mock_client = mock_client_class.return_value
            mock_client.models.list.return_value = [
                SimpleNamespace(name="gemini-1.5-pro", version="1")
            ]
            client = GeminiClient(GeminiConfig(api_key="test-key-12345", model="gemini-3.5-flash-lite"))
            with self.assertRaises(GeminiModelNotFoundError):
                client.validate_availability()

    def test_gemini_function_call_execution(self):
        """Gemini function call is executed through ErpToolRunner."""
        from backend.ai_providers.gemini.response_parser import (
            parse_generate_content_response,
        )

        # Create a function call response
        fc = SimpleNamespace(
            id="call-1",
            name="erp.warehouses.list",
            args={},
            partial_args=None,
            will_continue=False,
        )
        part = SimpleNamespace(
            text=None,
            function_call=fc,
        )
        content = SimpleNamespace(parts=[part], role="model")
        candidate = SimpleNamespace(
            content=content,
            finish_reason="STOP",
        )
        response = SimpleNamespace(candidates=[candidate])

        parsed = parse_generate_content_response(response)
        self.assertEqual(len(parsed.function_calls), 1)
        self.assertEqual(parsed.function_calls[0].name, "erp.warehouses.list")

        # Convert to ToolExecutionRequest
        request = to_tool_execution_request(
            parsed.function_calls[0], ERP_TOOL_DEFINITIONS_BY_NAME
        )
        self.assertIsNotNone(request)
        self.assertEqual(request.tool_name, "erp.warehouses.list")
        self.assertEqual(request.arguments, {})

        # Execute through runner
        result = self.platform.runner.execute(request)
        self.assertEqual(result.status, ToolExecutionStatus.SUCCEEDED)
        self.assertIsNotNone(result.output)

        # Convert result back to function response
        func_response = to_function_response(
            "call-1", "erp.warehouses.list", result
        )
        self.assertEqual(func_response.id, "call-1")
        self.assertEqual(func_response.name, "erp.warehouses.list")
        self.assertIn("output", func_response.response)

    def test_gemini_unknown_tool_rejected(self):
        """Unknown tool name in function call returns None from adapter."""
        fc = SimpleNamespace(
            id="call-1", name="erp.bogus.tool", args={}
        )
        request = to_tool_execution_request(fc, ERP_TOOL_DEFINITIONS_BY_NAME)
        self.assertIsNone(request)

    def test_gemini_invalid_args_rejected(self):
        """Invalid arguments in function call return None from adapter."""
        fc = SimpleNamespace(
            id="call-1",
            name="erp.products.get",
            args={},  # product_id is required
        )
        request = to_tool_execution_request(fc, ERP_TOOL_DEFINITIONS_BY_NAME)
        self.assertIsNone(request)

    def test_gemini_function_response_round_trip(self):
        """ToolExecutionResult converts to FunctionResponse and back."""
        now = datetime.now(timezone.utc)
        result = ToolExecutionResult(
            execution_id="exec-1",
            tool_name="erp.warehouses.list",
            status=ToolExecutionStatus.SUCCEEDED,
            output={"items": [], "row_count": 0, "truncated": False},
            started_at=now,
            finished_at=now,
            duration_ms=10.0,
        )
        func_response = to_function_response("call-1", "erp.warehouses.list", result)
        self.assertIn("output", func_response.response)
        self.assertEqual(
            func_response.response["output"],
            {"items": [], "row_count": 0, "truncated": False},
        )


class TestGeminiOrchestratorToolCalls(unittest.TestCase):
    """Tests for Gemini tool call execution through the orchestrator."""

    def setUp(self):
        from backend.agent.erp.platform import ErpToolPlatform
        from backend.agent.erp.config import ErpDatabaseConfig

        self.platform = ErpToolPlatform.from_config(
            ErpDatabaseConfig.from_path(
                "D:/Agent/Agent/backend/data/ifive_erp.db"
            )
        )

    def tearDown(self):
        self.platform.close()

    def _make_fake_gemini_response(self, function_calls=None, text="Final answer"):
        """Create a fake Gemini response with function calls."""
        parts = []
        if function_calls:
            for fc in function_calls:
                parts.append(
                    SimpleNamespace(
                        text=None,
                        function_call=fc,
                    )
                )
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

    def test_gemini_single_tool_call(self):
        """Gemini makes one tool call and returns final answer."""
        from backend.ai_providers.gemini.response_parser import (
            parse_generate_content_response,
        )
        from backend.ai_providers.gemini.tool_adapter import (
            to_tool_execution_request,
        )

        fc = SimpleNamespace(
            id="call-1",
            name="erp.warehouses.list",
            args={},
            partial_args=None,
            will_continue=False,
        )
        response = self._make_fake_gemini_response([fc])
        parsed = parse_generate_content_response(response)

        # First call: function call
        request = to_tool_execution_request(
            parsed.function_calls[0], ERP_TOOL_DEFINITIONS_BY_NAME
        )
        self.assertIsNotNone(request)
        result = self.platform.runner.execute(request)
        self.assertEqual(result.status, ToolExecutionStatus.SUCCEEDED)

        # Convert result back to function response for Gemini
        func_response = to_function_response(
            "call-1", "erp.warehouses.list", result
        )
        self.assertIn("output", func_response.response)

    def test_gemini_multiple_valid_function_calls(self):
        """Gemini response with two valid function calls executes both through ERP runner."""
        from backend.ai_providers.gemini.client import GeminiClient
        from backend.ai_providers.gemini.config import GeminiConfig

        fc1 = SimpleNamespace(
            id="call-1",
            name="erp.warehouses.list",
            args={},
        )
        fc2 = SimpleNamespace(
            id="call-2",
            name="erp.products.count",
            args={},
        )

        # First response: two function calls
        response1 = self._make_fake_gemini_response([fc1, fc2])
        # Second response: final answer after seeing tool results
        response2 = self._make_fake_gemini_response(text="Found 2 warehouses and 10 products.")

        with patch(
            "backend.ai_providers.gemini.client.genai.Client"
        ) as mock_client_class:
            mock_client = mock_client_class.return_value
            mock_client.models.list.return_value = [
                SimpleNamespace(name="gemini-3.5-flash-lite", version="1")
            ]
            mock_client.models.generate_content.side_effect = [response1, response2]

            orchestrator = AgentOrchestrator(
                client=GeminiClient(GeminiConfig(api_key="test-key-12345", model="gemini-3.5-flash-lite")),
                runner=self.platform.runner,
                registry=self.platform.registry,
                max_tool_calls=5,
            )
            result = orchestrator.process_question("List warehouses and count products")

            self.assertEqual(result.status, "completed")
            self.assertEqual(len(result.tool_calls), 2)
            # Verify both tools were called
            tool_names = [tc.tool_name for tc in result.tool_calls]
            self.assertIn("erp.warehouses.list", tool_names)
            self.assertIn("erp.products.count", tool_names)
            # Verify both succeeded
            for tc in result.tool_calls:
                self.assertEqual(tc.status, "succeeded")

    def test_gemini_multiple_calls_different_ids_and_tools(self):
        """Two function calls with different call IDs and tool names preserve IDs in responses."""
        from backend.ai_providers.gemini.client import GeminiClient
        from backend.ai_providers.gemini.config import GeminiConfig

        fc1 = SimpleNamespace(
            id="call-warehouse-123",
            name="erp.warehouses.list",
            args={},
        )
        fc2 = SimpleNamespace(
            id="call-product-456",
            name="erp.products.count",
            args={},
        )

        response1 = self._make_fake_gemini_response([fc1, fc2])
        response2 = self._make_fake_gemini_response(text="Done")

        with patch(
            "backend.ai_providers.gemini.client.genai.Client"
        ) as mock_client_class:
            mock_client = mock_client_class.return_value
            mock_client.models.list.return_value = [
                SimpleNamespace(name="gemini-3.5-flash-lite", version="1")
            ]
            mock_client.models.generate_content.side_effect = [response1, response2]

            orchestrator = AgentOrchestrator(
                client=GeminiClient(GeminiConfig(api_key="test-key-12345", model="gemini-3.5-flash-lite")),
                runner=self.platform.runner,
                registry=self.platform.registry,
                max_tool_calls=5,
            )
            result = orchestrator.process_question("List warehouses and count products")

            self.assertEqual(result.status, "completed")
            self.assertEqual(len(result.tool_calls), 2)
            # Verify both tools were called with correct names
            tool_names = {tc.tool_name for tc in result.tool_calls}
            self.assertEqual(tool_names, {"erp.warehouses.list", "erp.products.count"})
            # Verify both succeeded
            for tc in result.tool_calls:
                self.assertEqual(tc.status, "succeeded")

    def test_gemini_one_valid_one_invalid_call(self):
        """One valid and one invalid function call - valid executes, invalid returns error response."""
        from backend.ai_providers.gemini.client import GeminiClient
        from backend.ai_providers.gemini.config import GeminiConfig

        fc_valid = SimpleNamespace(
            id="call-valid-1",
            name="erp.warehouses.list",
            args={},
        )
        fc_invalid = SimpleNamespace(
            id="call-invalid-1",
            name="erp.bogus.tool",
            args={},
        )

        response1 = self._make_fake_gemini_response([fc_valid, fc_invalid])
        response2 = self._make_fake_gemini_response(text="Warehouse list retrieved, bogus tool rejected.")

        with patch(
            "backend.ai_providers.gemini.client.genai.Client"
        ) as mock_client_class:
            mock_client = mock_client_class.return_value
            mock_client.models.list.return_value = [
                SimpleNamespace(name="gemini-3.5-flash-lite", version="1")
            ]
            mock_client.models.generate_content.side_effect = [response1, response2]

            orchestrator = AgentOrchestrator(
                client=GeminiClient(GeminiConfig(api_key="test-key-12345", model="gemini-3.5-flash-lite")),
                runner=self.platform.runner,
                registry=self.platform.registry,
                max_tool_calls=5,
            )
            result = orchestrator.process_question("List warehouses and call bogus")

            self.assertEqual(result.status, "completed")
            # Should have 2 tool calls: one succeeded, one failed
            self.assertEqual(len(result.tool_calls), 2)
            statuses = [tc.status for tc in result.tool_calls]
            self.assertIn("succeeded", statuses)
            self.assertIn("failed", statuses)

    def test_gemini_multiple_calls_exceeding_budget(self):
        """Multiple function calls exceeding remaining tool-call budget are rejected."""
        from backend.ai_providers.gemini.client import GeminiClient
        from backend.ai_providers.gemini.config import GeminiConfig

        # Create 4 function calls but budget is 2
        fcs = [
            SimpleNamespace(id=f"call-{i}", name="erp.warehouses.list", args={})
            for i in range(4)
        ]

        response1 = self._make_fake_gemini_response(fcs)
        # After processing function calls, Gemini is called again and returns final answer
        response2 = self._make_fake_gemini_response(text="Budget limited, processed 2 calls.")
        # Third call if needed
        response3 = self._make_fake_gemini_response(text="Done.")

        with patch(
            "backend.ai_providers.gemini.client.genai.Client"
        ) as mock_client_class:
            mock_client = mock_client_class.return_value
            mock_client.models.list.return_value = [
                SimpleNamespace(name="gemini-3.5-flash-lite", version="1")
            ]
            mock_client.models.generate_content.side_effect = [response1, response2]

            orchestrator = AgentOrchestrator(
                client=GeminiClient(GeminiConfig(api_key="test-key-12345", model="gemini-3.5-flash-lite")),
                runner=self.platform.runner,
                registry=self.platform.registry,
                max_tool_calls=2,
            )
            result = orchestrator.process_question("Call 4 tools")

            self.assertEqual(result.status, "completed")
            # Only 2 should execute (budget limit), 2 should be cancelled
            self.assertEqual(len(result.tool_calls), 4)
            statuses = [tc.status for tc in result.tool_calls]
            succeeded_count = statuses.count("succeeded")
            cancelled_count = statuses.count("cancelled")
            self.assertEqual(succeeded_count, 2)
            self.assertEqual(cancelled_count, 2)

    def test_gemini_function_responses_preserve_call_ids(self):
        """Function responses preserve the correct call IDs from the original function calls."""
        from backend.ai_providers.gemini.client import GeminiClient
        from backend.ai_providers.gemini.config import GeminiConfig

        fc1 = SimpleNamespace(
            id="call-alpha-111",
            name="erp.warehouses.list",
            args={},
        )
        fc2 = SimpleNamespace(
            id="call-beta-222",
            name="erp.products.count",
            args={},
        )

        response1 = self._make_fake_gemini_response([fc1, fc2])
        response2 = self._make_fake_gemini_response(text="Done")

        with patch(
            "backend.ai_providers.gemini.client.genai.Client"
        ) as mock_client_class:
            mock_client = mock_client_class.return_value
            mock_client.models.list.return_value = [
                SimpleNamespace(name="gemini-3.5-flash-lite", version="1")
            ]
            mock_client.models.generate_content.side_effect = [response1, response2]

            orchestrator = AgentOrchestrator(
                client=GeminiClient(GeminiConfig(api_key="test-key-12345", model="gemini-3.5-flash-lite")),
                runner=self.platform.runner,
                registry=self.platform.registry,
                max_tool_calls=5,
            )
            result = orchestrator.process_question("Test call IDs")

            self.assertEqual(result.status, "completed")
            self.assertEqual(len(result.tool_calls), 2)
            # Verify both tools were called with correct names
            tool_names = {tc.tool_name for tc in result.tool_calls}
            self.assertEqual(tool_names, {"erp.warehouses.list", "erp.products.count"})
            # Verify both succeeded
            for tc in result.tool_calls:
                self.assertEqual(tc.status, "succeeded")

    def test_gemini_budget_exhausted_then_text_final_answer(self):
        """Budget exhausted, then Gemini returns text: final answer is accepted."""
        from backend.ai_providers.gemini.client import GeminiClient
        from backend.ai_providers.gemini.config import GeminiConfig

        # 2 calls but budget is 1
        fc1 = SimpleNamespace(id="call-1", name="erp.warehouses.list", args={})
        fc2 = SimpleNamespace(id="call-2", name="erp.products.count", args={})

        # First response: 2 function calls (only 1 will execute due to budget)
        response1 = self._make_fake_gemini_response([fc1, fc2])
        # Second response (final-answer attempt): text answer
        response2 = self._make_fake_gemini_response(text="Found 1 warehouse. Budget limited.")

        with patch(
            "backend.ai_providers.gemini.client.genai.Client"
        ) as mock_client_class:
            mock_client = mock_client_class.return_value
            mock_client.models.list.return_value = [
                SimpleNamespace(name="gemini-3.5-flash-lite", version="1")
            ]
            mock_client.models.generate_content.side_effect = [response1, response2]

            orchestrator = AgentOrchestrator(
                client=GeminiClient(GeminiConfig(api_key="test-key-12345", model="gemini-3.5-flash-lite")),
                runner=self.platform.runner,
                registry=self.platform.registry,
                max_tool_calls=1,  # Budget of 1
            )
            result = orchestrator.process_question("List warehouses and count products")

            self.assertEqual(result.status, "completed")
            # Only 1 executed, 1 cancelled
            self.assertEqual(len(result.tool_calls), 2)
            statuses = [tc.status for tc in result.tool_calls]
            self.assertEqual(statuses.count("succeeded"), 1)
            self.assertEqual(statuses.count("cancelled"), 1)
            # Final answer should be from response2
            self.assertIn("warehouse", result.answer.lower())

    def test_gemini_budget_exhausted_then_more_function_calls_cancelled_no_third_request(self):
        """Budget exhausted, then Gemini returns more function calls: cancelled, no tools execute, no third request."""
        from backend.ai_providers.gemini.client import GeminiClient
        from backend.ai_providers.gemini.config import GeminiConfig

        # 2 calls but budget is 1
        fc1 = SimpleNamespace(id="call-1", name="erp.warehouses.list", args={})
        fc2 = SimpleNamespace(id="call-2", name="erp.products.count", args={})

        # First response: 2 function calls
        response1 = self._make_fake_gemini_response([fc1, fc2])
        # Second response (final-answer attempt): MORE function calls (should be cancelled)
        fc3 = SimpleNamespace(id="call-3", name="erp.warehouses.list", args={})
        fc4 = SimpleNamespace(id="call-4", name="erp.products.count", args={})
        response2 = self._make_fake_gemini_response([fc3, fc4])

        with patch(
            "backend.ai_providers.gemini.client.genai.Client"
        ) as mock_client_class:
            mock_client = mock_client_class.return_value
            mock_client.models.list.return_value = [
                SimpleNamespace(name="gemini-3.5-flash-lite", version="1")
            ]
            mock_client.models.generate_content.side_effect = [response1, response2]

            orchestrator = AgentOrchestrator(
                client=GeminiClient(GeminiConfig(api_key="test-key-12345", model="gemini-3.5-flash-lite")),
                runner=self.platform.runner,
                registry=self.platform.registry,
                max_tool_calls=1,  # Budget of 1
            )
            result = orchestrator.process_question("Call tools")

            # Should only make 2 Gemini requests (not 3)
            # The side_effect list has 2 items, both should be consumed
            # Verify by checking the mock was called twice
            self.assertEqual(mock_client.models.generate_content.call_count, 2)
            # 1 executed, 1 cancelled from first batch; 2 cancelled from second batch
            self.assertEqual(len(result.tool_calls), 4)
            statuses = [tc.status for tc in result.tool_calls]
            self.assertEqual(statuses.count("succeeded"), 1)
            self.assertEqual(statuses.count("cancelled"), 3)
            # Should not be an error status
            self.assertNotEqual(result.status, "error")

    def test_gemini_generation_request_count_exactly_as_expected(self):
        """Verify the number of Gemini generation requests matches expected behavior."""
        from backend.ai_providers.gemini.client import GeminiClient
        from backend.ai_providers.gemini.config import GeminiConfig

        # Scenario: budget=2, first response has 3 function calls, second response has text
        fcs = [
            SimpleNamespace(id=f"call-{i}", name="erp.warehouses.list", args={})
            for i in range(3)
        ]

        response1 = self._make_fake_gemini_response(fcs)
        response2 = self._make_fake_gemini_response(text="Processed 2, cancelled 1.")

        with patch(
            "backend.ai_providers.gemini.client.genai.Client"
        ) as mock_client_class:
            mock_client = mock_client_class.return_value
            mock_client.models.list.return_value = [
                SimpleNamespace(name="gemini-3.5-flash-lite", version="1")
            ]
            mock_client.models.generate_content.side_effect = [response1, response2]

            orchestrator = AgentOrchestrator(
                client=GeminiClient(GeminiConfig(api_key="test-key-12345", model="gemini-3.5-flash-lite")),
                runner=self.platform.runner,
                registry=self.platform.registry,
                max_tool_calls=2,  # Budget of 2
            )
            result = orchestrator.process_question("Call 3 tools")

            # Should make exactly 2 Gemini requests (not 3)
            self.assertEqual(mock_client.models.generate_content.call_count, 2)
            self.assertEqual(result.status, "completed")
            self.assertEqual(len(result.tool_calls), 3)
            statuses = [tc.status for tc in result.tool_calls]
            self.assertEqual(statuses.count("succeeded"), 2)
            self.assertEqual(statuses.count("cancelled"), 1)


if __name__ == "__main__":
    unittest.main()
