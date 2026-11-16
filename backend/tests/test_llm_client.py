from __future__ import annotations

import json
import unittest
from unittest.mock import patch
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
        self.assertEqual(cfg.base_url, "http://127.0.0.1:11434")
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
    def _logged_metrics(self, captured) -> dict[str, object]:
        message = captured.records[-1].getMessage()
        event, payload = message.split(" ", 1)
        self.assertEqual(event, "ollama_chat")
        return json.loads(payload)

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

    def test_chat_records_all_timing_and_token_metadata(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/chat")
            body = json.loads(request.content)
            self.assertFalse(body["stream"])
            self.assertNotIn("num_predict", body.get("options", {}))
            return httpx.Response(
                200,
                json={
                    "model": "llama3.2:latest",
                    "message": {"role": "assistant", "content": "hello"},
                    "done": True,
                    "done_reason": "stop",
                    "total_duration": 2_000_000_000,
                    "load_duration": 200_000_000,
                    "prompt_eval_count": 100,
                    "prompt_eval_duration": 300_000_000,
                    "eval_count": 50,
                    "eval_duration": 1_400_000_000,
                },
            )

        transport = httpx.MockTransport(handler)
        client = httpx.Client(transport=transport)
        llm = OllamaClient(LlmConfig(), http_client=client)

        with patch(
            "backend.agent.llm.client._elapsed_ms",
            return_value=250.0,
        ):
            with self.assertLogs("backend.agent.llm.client", level="INFO") as captured:
                resp = llm.chat(
                    [ChatMessage(role=ChatRole.USER, content="SECRET_CUSTOMER_DATA")]
                )

        self.assertEqual(resp.duration_ms, 2000.0)
        self.assertEqual(resp.request_duration_ms, 250.0)
        self.assertEqual(resp.total_duration_ns, 2_000_000_000)
        self.assertEqual(resp.load_duration_ns, 200_000_000)
        self.assertEqual(resp.prompt_eval_count, 100)
        self.assertEqual(resp.prompt_eval_duration_ns, 300_000_000)
        self.assertEqual(resp.eval_count, 50)
        self.assertEqual(resp.eval_duration_ns, 1_400_000_000)
        self.assertEqual(resp.done_reason, "stop")
        self.assertFalse(resp.truncated)

        metrics = self._logged_metrics(captured)
        self.assertEqual(metrics["outcome"], "completed")
        self.assertEqual(metrics["model"], "llama3.2:latest")
        self.assertEqual(metrics["request_ms"], 250.0)
        self.assertEqual(metrics["total_ms"], 2000.0)
        self.assertEqual(metrics["load_ms"], 200.0)
        self.assertEqual(metrics["prompt_eval_count"], 100)
        self.assertEqual(metrics["prompt_eval_ms"], 300.0)
        self.assertEqual(metrics["eval_count"], 50)
        self.assertEqual(metrics["eval_ms"], 1400.0)
        self.assertEqual(metrics["done_reason"], "stop")
        self.assertFalse(metrics["truncated"])
        self.assertFalse(metrics["failed"])
        self.assertIsNone(metrics["error_type"])
        self.assertEqual(metrics["status_code"], 200)
        self.assertNotIn("SECRET_CUSTOMER_DATA", captured.records[-1].getMessage())

    def test_chat_missing_optional_metadata_does_not_fail(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "model": "llama3.2",
                    "message": {"role": "assistant", "content": "hello"},
                },
            )

        transport = httpx.MockTransport(handler)
        client = httpx.Client(transport=transport)
        llm = OllamaClient(LlmConfig(), http_client=client)

        with patch(
            "backend.agent.llm.client._elapsed_ms",
            return_value=130.0,
        ):
            with self.assertLogs("backend.agent.llm.client", level="INFO") as captured:
                resp = llm.chat([ChatMessage(role=ChatRole.USER, content="Hello")])

        self.assertIsNone(resp.duration_ms)
        self.assertEqual(resp.request_duration_ms, 130.0)
        self.assertIsNone(resp.total_duration_ns)
        self.assertIsNone(resp.load_duration_ns)
        self.assertIsNone(resp.prompt_eval_count)
        self.assertIsNone(resp.prompt_eval_duration_ns)
        self.assertIsNone(resp.eval_count)
        self.assertIsNone(resp.eval_duration_ns)
        self.assertIsNone(resp.done_reason)
        self.assertFalse(resp.truncated)

        metrics = self._logged_metrics(captured)
        self.assertEqual(metrics["outcome"], "completed")
        self.assertEqual(metrics["request_ms"], 130.0)
        self.assertIsNone(metrics["total_ms"])
        self.assertIsNone(metrics["load_ms"])
        self.assertIsNone(metrics["prompt_eval_count"])
        self.assertIsNone(metrics["eval_count"])
        self.assertIsNone(metrics["done_reason"])
        self.assertFalse(metrics["truncated"])
        self.assertFalse(metrics["failed"])

    def test_chat_records_truncation_from_done_reason_length(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "model": "llama3.2",
                    "message": {"role": "assistant", "content": '{"partial":'},
                    "done_reason": "length",
                    "total_duration": 500_000_000,
                    "eval_count": 256,
                    "eval_duration": 400_000_000,
                },
            )

        transport = httpx.MockTransport(handler)
        client = httpx.Client(transport=transport)
        llm = OllamaClient(LlmConfig(), http_client=client)

        with patch(
            "backend.agent.llm.client._elapsed_ms",
            return_value=500.0,
        ):
            with self.assertLogs("backend.agent.llm.client", level="INFO") as captured:
                resp = llm.chat([ChatMessage(role=ChatRole.USER, content="Hello")])

        self.assertEqual(resp.content, '{"partial":')
        self.assertEqual(resp.done_reason, "length")
        self.assertTrue(resp.truncated)

        metrics = self._logged_metrics(captured)
        self.assertEqual(metrics["outcome"], "truncated")
        self.assertEqual(metrics["done_reason"], "length")
        self.assertTrue(metrics["truncated"])
        self.assertFalse(metrics["failed"])
        self.assertEqual(metrics["status_code"], 200)

    def test_chat_timeout_is_instrumented(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("Timed out")

        transport = httpx.MockTransport(handler)
        client = httpx.Client(transport=transport)
        llm = OllamaClient(LlmConfig(timeout_seconds=5.0), http_client=client)

        with patch(
            "backend.agent.llm.client._elapsed_ms",
            return_value=250.0,
        ):
            with self.assertLogs("backend.agent.llm.client", level="INFO") as captured:
                with self.assertRaises(LlmTimeoutError):
                    llm.chat(
                        [ChatMessage(role=ChatRole.USER, content="SECRET_CUSTOMER_DATA")]
                    )

        metrics = self._logged_metrics(captured)
        self.assertEqual(metrics["outcome"], "timeout")
        self.assertEqual(metrics["model"], "llama3.2")
        self.assertEqual(metrics["request_ms"], 250.0)
        self.assertTrue(metrics["failed"])
        self.assertEqual(metrics["error_type"], "LlmTimeoutError")
        self.assertIsNone(metrics["status_code"])
        self.assertIsNone(metrics["done_reason"])
        self.assertIsNone(metrics["truncated"])
        self.assertNotIn("SECRET_CUSTOMER_DATA", captured.records[-1].getMessage())

    def test_chat_http_error_is_instrumented(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="Internal crash")

        transport = httpx.MockTransport(handler)
        client = httpx.Client(transport=transport)
        llm = OllamaClient(LlmConfig(), http_client=client)

        with patch(
            "backend.agent.llm.client._elapsed_ms",
            return_value=250.0,
        ):
            with self.assertLogs("backend.agent.llm.client", level="INFO") as captured:
                with self.assertRaises(LlmResponseError):
                    llm.chat([ChatMessage(role=ChatRole.USER, content="Hello")])

        metrics = self._logged_metrics(captured)
        self.assertEqual(metrics["outcome"], "error")
        self.assertEqual(metrics["model"], "llama3.2")
        self.assertEqual(metrics["request_ms"], 250.0)
        self.assertTrue(metrics["failed"])
        self.assertEqual(metrics["error_type"], "LlmResponseError")
        self.assertEqual(metrics["status_code"], 500)

    def test_chat_connection_error_is_instrumented(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Connection refused")

        transport = httpx.MockTransport(handler)
        client = httpx.Client(transport=transport)
        llm = OllamaClient(LlmConfig(), http_client=client)

        with patch(
            "backend.agent.llm.client._elapsed_ms",
            return_value=250.0,
        ):
            with self.assertLogs("backend.agent.llm.client", level="INFO") as captured:
                with self.assertRaises(LlmConnectionError):
                    llm.chat([ChatMessage(role=ChatRole.USER, content="Hello")])

        metrics = self._logged_metrics(captured)
        self.assertEqual(metrics["outcome"], "error")
        self.assertEqual(metrics["model"], "llama3.2")
        self.assertEqual(metrics["request_ms"], 250.0)
        self.assertTrue(metrics["failed"])
        self.assertEqual(metrics["error_type"], "LlmConnectionError")
        self.assertIsNone(metrics["status_code"])

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

