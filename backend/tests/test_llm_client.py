from __future__ import annotations

import unittest
import httpx

from backend.agent.llm.client import OllamaClient
from backend.agent.llm.config import LlmConfig
from backend.agent.llm.errors import (
    LlmConnectionError,
    LlmModelNotFoundError,
    LlmResponseError,
    LlmTimeoutError,
)
from backend.agent.llm.models import ChatMessage, ChatRole


class TestLlmConfig(unittest.TestCase):
    def test_default_config(self) -> None:
        cfg = LlmConfig()
        self.assertEqual(cfg.base_url, "http://localhost:11434")
        self.assertEqual(cfg.model, "llama3.2")
        self.assertEqual(cfg.timeout_seconds, 30.0)
        self.assertEqual(cfg.max_tool_calls, 5)

    def test_trailing_slash_stripped(self) -> None:
        cfg = LlmConfig(base_url="http://localhost:11434/")
        self.assertEqual(cfg.base_url, "http://localhost:11434")

    def test_invalid_scheme(self) -> None:
        with self.assertRaises(ValueError):
            LlmConfig(base_url="ftp://localhost:11434")

    def test_invalid_timeout(self) -> None:
        with self.assertRaises(ValueError):
            LlmConfig(timeout_seconds=-1)

    def test_invalid_max_calls(self) -> None:
        with self.assertRaises(ValueError):
            LlmConfig(max_tool_calls=0)


class TestOllamaClient(unittest.TestCase):
    def test_health_check_success(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/tags")
            return httpx.Response(200, json={"models": [{"name": "llama3.2:latest"}]})

        transport = httpx.MockTransport(handler)
        client = httpx.Client(transport=transport)
        llm = OllamaClient(LlmConfig(), http_client=client)

        self.assertTrue(llm.is_healthy())

    def test_health_check_failure(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="Internal server error")

        transport = httpx.MockTransport(handler)
        client = httpx.Client(transport=transport)
        llm = OllamaClient(LlmConfig(), http_client=client)

        self.assertFalse(llm.is_healthy())

    def test_list_models_and_availability(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "models": [
                        {"name": "llama3.2:latest", "size": 2000000000},
                        {"name": "qwen2.5:7b", "size": 4000000000},
                    ]
                },
            )

        transport = httpx.MockTransport(handler)
        client = httpx.Client(transport=transport)
        llm = OllamaClient(LlmConfig(model="llama3.2"), http_client=client)

        models = llm.list_models()
        self.assertEqual(len(models), 2)
        self.assertEqual(models[0].name, "llama3.2:latest")

        self.assertTrue(llm.is_model_available("llama3.2"))
        self.assertTrue(llm.is_model_available("llama3.2:latest"))
        self.assertTrue(llm.is_model_available("qwen2.5:7b"))
        self.assertFalse(llm.is_model_available("mistral"))

        # Should not raise
        llm.validate_availability()

    def test_validate_availability_missing_model_raises(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"models": [{"name": "qwen2.5:7b"}]})

        transport = httpx.MockTransport(handler)
        client = httpx.Client(transport=transport)
        llm = OllamaClient(LlmConfig(model="llama3.2"), http_client=client)

        with self.assertRaises(LlmModelNotFoundError) as ctx:
            llm.validate_availability()
        self.assertIn("llama3.2", str(ctx.exception))
        self.assertIn("qwen2.5:7b", str(ctx.exception))

    def test_chat_success(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/chat")
            return httpx.Response(
                200,
                json={
                    "model": "llama3.2",
                    "message": {"role": "assistant", "content": "Hello! I can help you with your ERP."},
                    "total_duration": 150000000,
                    "prompt_eval_count": 10,
                    "eval_count": 12,
                },
            )

        transport = httpx.MockTransport(handler)
        client = httpx.Client(transport=transport)
        llm = OllamaClient(LlmConfig(), http_client=client)

        resp = llm.chat([ChatMessage(role=ChatRole.USER, content="Hello")])
        self.assertEqual(resp.content, "Hello! I can help you with your ERP.")
        self.assertEqual(resp.model, "llama3.2")
        self.assertAlmostEqual(resp.duration_ms, 150.0)
        self.assertEqual(resp.eval_count, 12)

    def test_chat_connection_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Connection refused")

        transport = httpx.MockTransport(handler)
        client = httpx.Client(transport=transport)
        llm = OllamaClient(LlmConfig(), http_client=client)

        with self.assertRaises(LlmConnectionError) as ctx:
            llm.chat([ChatMessage(role=ChatRole.USER, content="Hello")])
        self.assertIn("Cannot connect to local Ollama service", str(ctx.exception))

    def test_chat_timeout(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("Timed out")

        transport = httpx.MockTransport(handler)
        client = httpx.Client(transport=transport)
        llm = OllamaClient(LlmConfig(timeout_seconds=5.0), http_client=client)

        with self.assertRaises(LlmTimeoutError) as ctx:
            llm.chat([ChatMessage(role=ChatRole.USER, content="Hello")])
        self.assertIn("timed out after 5.0 seconds", str(ctx.exception))

    def test_chat_404_model_not_found(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, text="model not found")

        transport = httpx.MockTransport(handler)
        client = httpx.Client(transport=transport)
        llm = OllamaClient(LlmConfig(model="missing-model"), http_client=client)

        with self.assertRaises(LlmModelNotFoundError):
            llm.chat([ChatMessage(role=ChatRole.USER, content="Hello")])

    def test_chat_server_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="Internal crash")

        transport = httpx.MockTransport(handler)
        client = httpx.Client(transport=transport)
        llm = OllamaClient(LlmConfig(), http_client=client)

        with self.assertRaises(LlmResponseError) as ctx:
            llm.chat([ChatMessage(role=ChatRole.USER, content="Hello")])
        self.assertEqual(ctx.exception.status_code, 500)


if __name__ == "__main__":
    unittest.main()

