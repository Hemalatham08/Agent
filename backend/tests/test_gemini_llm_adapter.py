"""Tests for the Gemini LlmClient adapter bridge.

These tests use a fake Gemini client, so no network access or google-genai
SDK calls are made. They focus on the provider-neutral protocol expected by
``AgentOrchestrator`` and on rebuilding native Gemini turns.
"""

from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from backend.agent.llm.errors import (
    LlmModelNotFoundError,
    LlmTimeoutError,
)
from backend.agent.llm.models import ChatMessage, ChatRole
from backend.ai_providers.gemini.adapter import GeminiLlmClientAdapter
from backend.ai_providers.gemini.config import GeminiConfig
from backend.ai_providers.gemini.errors import (
    GeminiModelNotFoundError,
    GeminiTimeoutError,
)
from backend.ai_providers.gemini.models import (
    GeminiChatMessage,
    GeminiChatRole,
)


def _response(
    *,
    content: str = "",
    function_calls: list[dict] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        content=content,
        model="gemini-3.5-flash-lite",
        duration_ms=12.0,
        request_duration_ms=10.0,
        finish_reason="STOP",
        truncated=False,
        function_calls=function_calls or [],
    )


class FakeGeminiClient:
    def __init__(self, response: SimpleNamespace) -> None:
        self.response = response
        self.captured_messages: list[GeminiChatMessage] = []
        self.captured_kwargs: dict = {}
        self.closed = False
        self.validated = 0
        self.error: Exception | None = None

    def chat(self, messages, **kwargs):
        self.captured_messages = list(messages)
        self.captured_kwargs = kwargs
        return self.response

    def validate_availability(self) -> None:
        self.validated += 1
        if self.error is not None:
            raise self.error

    def close(self) -> None:
        self.closed = True


def _adapter(client: FakeGeminiClient, *, registry=None) -> GeminiLlmClientAdapter:
    return GeminiLlmClientAdapter(
        GeminiConfig(api_key="test-key-12345"),
        client=client,  # type: ignore[arg-type]
        tool_registry=registry,
    )


class GeminiLlmAdapterDecisionTests(unittest.TestCase):
    def test_text_response_becomes_final_answer(self) -> None:
        client = FakeGeminiClient(_response(content="Hello from Gemini."))
        response = _adapter(client).chat(
            [ChatMessage(role=ChatRole.USER, content="Hi")]
        )

        payload = json.loads(response.content)
        self.assertEqual(payload["action"], "final_answer")
        self.assertEqual(payload["final_answer"], "Hello from Gemini.")
        self.assertEqual(response.model, "gemini-3.5-flash-lite")

    def test_json_final_answer_is_unwrapped(self) -> None:
        raw = json.dumps(
            {"action": "final_answer", "final_answer": "Wrapped answer"}
        )
        client = FakeGeminiClient(_response(content=raw))
        response = _adapter(client).chat(
            [ChatMessage(role=ChatRole.USER, content="Hi")]
        )

        payload = json.loads(response.content)
        self.assertEqual(payload["final_answer"], "Wrapped answer")

    def test_function_calls_become_call_tools_decision(self) -> None:
        client = FakeGeminiClient(
            _response(
                function_calls=[
                    {
                        "id": "call-alpha",
                        "name": "erp.warehouses.list",
                        "arguments": {},
                        "thought_signature": None,
                    },
                    {
                        "id": "call-beta",
                        "name": "erp.products.count",
                        "arguments": {},
                        "thought_signature": None,
                    },
                ]
            )
        )
        response = _adapter(client).chat(
            [ChatMessage(role=ChatRole.USER, content="List warehouses and count")]
        )

        payload = json.loads(response.content)
        self.assertEqual(payload["action"], "call_tools")
        self.assertEqual(
            [(call["id"], call["tool_name"]) for call in payload["tool_calls"]],
            [
                ("call-alpha", "erp.warehouses.list"),
                ("call-beta", "erp.products.count"),
            ],
        )

    def test_function_call_without_id_gets_generated_id(self) -> None:
        client = FakeGeminiClient(
            _response(
                function_calls=[
                    {"name": "erp.warehouses.list", "arguments": {}}
                ]
            )
        )
        response = _adapter(client).chat(
            [ChatMessage(role=ChatRole.USER, content="List warehouses")]
        )

        payload = json.loads(response.content)
        self.assertEqual(payload["tool_calls"][0]["id"], "gemini-call-1")

    def test_registered_tools_are_forwarded_to_client(self) -> None:
        client = FakeGeminiClient(_response(content="ok"))
        registry = MagicMock()
        registry.list_tools.return_value = [object()]
        sentinel = [object()]

        with patch(
            "backend.ai_providers.gemini.adapter.to_gemini_tools",
            return_value=sentinel,
        ):
            _adapter(client, registry=registry).chat(
                [ChatMessage(role=ChatRole.USER, content="Hi")]
            )

        self.assertIs(client.captured_kwargs["tools"], sentinel)
        registry.list_tools.assert_called_once()


class GeminiLlmAdapterTurnRebuildTests(unittest.TestCase):
    def test_history_rebuilds_function_call_and_response_turns(self) -> None:
        client = FakeGeminiClient(_response(content="Done"))
        call_decision = json.dumps(
            {
                "thought": "",
                "action": "call_tools",
                "tool_calls": [
                    {
                        "id": "call-1",
                        "tool_name": "erp.products.search",
                        "arguments": {"query": "bolt"},
                        "thought_signature": None,
                    }
                ],
                "tool_name": None,
                "arguments": None,
                "final_answer": None,
            }
        )
        messages = [
            ChatMessage(role=ChatRole.SYSTEM, content="System rules"),
            ChatMessage(role=ChatRole.USER, content="Search products"),
            ChatMessage(role=ChatRole.ASSISTANT, content=call_decision),
            ChatMessage(
                role=ChatRole.USER,
                content=(
                    "Tool `erp.products.search` output:\n"
                    '{"items": [], "row_count": 0}'
                ),
            ),
        ]

        _adapter(client).chat(messages)

        roles = [message.role for message in client.captured_messages]
        self.assertEqual(
            roles,
            [
                GeminiChatRole.SYSTEM,
                GeminiChatRole.USER,
                GeminiChatRole.MODEL,
                GeminiChatRole.TOOL,
            ],
        )
        self.assertIn(
            "GEMINI NATIVE TOOL MODE",
            client.captured_messages[0].content,
        )

        model_message = client.captured_messages[2]
        self.assertEqual(model_message.function_calls[0]["id"], "call-1")
        self.assertEqual(
            model_message.function_calls[0]["name"], "erp.products.search"
        )
        self.assertEqual(
            model_message.function_calls[0]["arguments"], {"query": "bolt"}
        )

        tool_message = client.captured_messages[3]
        self.assertEqual(tool_message.call_id, "call-1")
        self.assertEqual(tool_message.tool_name, "erp.products.search")
        self.assertEqual(
            json.loads(tool_message.content),
            {"output": {"items": [], "row_count": 0}},
        )

    def test_multiple_calls_keep_their_own_response_ids(self) -> None:
        client = FakeGeminiClient(_response(content="Done"))
        call_decision = json.dumps(
            {
                "thought": "",
                "action": "call_tools",
                "tool_calls": [
                    {
                        "id": "call-a",
                        "tool_name": "erp.warehouses.list",
                        "arguments": {},
                        "thought_signature": None,
                    },
                    {
                        "id": "call-b",
                        "tool_name": "erp.products.count",
                        "arguments": {},
                        "thought_signature": None,
                    },
                ],
                "tool_name": None,
                "arguments": None,
                "final_answer": None,
            }
        )
        messages = [
            ChatMessage(role=ChatRole.USER, content="Do both"),
            ChatMessage(role=ChatRole.ASSISTANT, content=call_decision),
            ChatMessage(role=ChatRole.USER, content="Tool `erp.warehouses.list` output:\n{}"),
            ChatMessage(role=ChatRole.USER, content="Tool `erp.products.count` output:\n{}"),
        ]

        _adapter(client).chat(messages)

        responses = [
            message
            for message in client.captured_messages
            if message.role is GeminiChatRole.TOOL
        ]
        self.assertEqual(
            [(message.call_id, message.tool_name) for message in responses],
            [
                ("call-a", "erp.warehouses.list"),
                ("call-b", "erp.products.count"),
            ],
        )


class GeminiLlmAdapterErrorTests(unittest.TestCase):
    def test_model_not_found_translates_with_configured_model(self) -> None:
        client = FakeGeminiClient(_response())
        client.error = GeminiModelNotFoundError("model missing")
        adapter = _adapter(client)

        with self.assertRaises(LlmModelNotFoundError) as ctx:
            adapter.validate_availability()

        self.assertEqual(ctx.exception.model_name, "gemini-3.5-flash-lite")
        self.assertEqual(ctx.exception.service_name, "Gemini")

    def test_timeout_translates_to_llm_timeout(self) -> None:
        client = FakeGeminiClient(_response())
        client.error = GeminiTimeoutError("timed out")
        adapter = _adapter(client)

        with self.assertRaises(LlmTimeoutError) as ctx:
            adapter.validate_availability()

        self.assertEqual(ctx.exception.service_name, "Gemini")

    def test_close_delegates_to_gemini_client(self) -> None:
        client = FakeGeminiClient(_response())
        adapter = _adapter(client)

        adapter.close()

        self.assertTrue(client.closed)


if __name__ == "__main__":
    unittest.main()
