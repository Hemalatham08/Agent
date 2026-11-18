from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx

from backend.agent.erp.config import ErpDatabaseConfig
from backend.agent.erp.platform import ErpToolPlatform
from backend.agent.llm.client import OllamaClient
from backend.agent.llm.config import LlmConfig
from backend.agent.llm.errors import (
    LlmConnectionError,
    LlmModelNotFoundError,
    LlmResponseError,
    LlmTimeoutError,
)
from backend.agent.llm.llamacpp import LlamaCppClient, LlamaCppConfig
from backend.agent.llm.models import ChatMessage, ChatRole
from backend.agent.llm.provider import create_llm_client, resolve_provider_name
from backend.agent.services.agent_service import AgentService
from backend.agent.tools.contracts import ToolExecutionRequest
from backend.tests.erp_support import create_erp_fixture_db

_QWEN_MODEL_PATH = "C:\\LocalAI\\models\\Qwen_Qwen3-1.7B-Q4_K_M.gguf"


def _completion(
    content: str,
    *,
    finish_reason: str = "stop",
    prompt_tokens: int = 10,
    completion_tokens: int = 5,
    include_usage: bool = True,
    include_timings: bool = True,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "model": _QWEN_MODEL_PATH,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": finish_reason,
            }
        ],
    }
    if include_usage:
        payload["usage"] = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        }
    if include_timings:
        payload["timings"] = {
            "prompt_ms": 120.5,
            "predicted_ms": 250.25,
        }
    return payload


def _models_payload(model_id: str = _QWEN_MODEL_PATH) -> dict[str, Any]:
    return {"object": "list", "data": [{"id": model_id, "object": "model"}]}


class TestLlamaCppConfig(unittest.TestCase):
    def test_default_config(self) -> None:
        cfg = LlamaCppConfig()
        self.assertEqual(cfg.base_url, "http://127.0.0.1:11435")
        self.assertEqual(cfg.model, "qwen3-1.7b")
        self.assertEqual(cfg.timeout_seconds, 180.0)
        self.assertEqual(cfg.max_tool_calls, 5)
        self.assertFalse(cfg.enable_thinking)

    def test_trailing_slash_stripped(self) -> None:
        cfg = LlamaCppConfig(base_url="http://localhost:11435/")
        self.assertEqual(cfg.base_url, "http://localhost:11435")

    def test_invalid_scheme(self) -> None:
        with self.assertRaises(ValueError):
            LlamaCppConfig(base_url="ftp://localhost:11435")

    def test_invalid_timeout(self) -> None:
        with self.assertRaises(ValueError):
            LlamaCppConfig(timeout_seconds=-1)

    def test_invalid_max_calls(self) -> None:
        with self.assertRaises(ValueError):
            LlamaCppConfig(max_tool_calls=0)

    def test_from_env_overrides(self) -> None:
        with patch.dict(
            os.environ,
            {
                "LLAMACPP_BASE_URL": "http://localhost:9000/",
                "LLAMACPP_MODEL": "my-qwen",
                "LLAMACPP_TIMEOUT_SECONDS": "12.5",
                "LLAMACPP_ENABLE_THINKING": "true",
                "AGENT_MAX_TOOL_CALLS": "7",
            },
            clear=False,
        ):
            cfg = LlamaCppConfig.from_env()

        self.assertEqual(cfg.base_url, "http://localhost:9000")
        self.assertEqual(cfg.model, "my-qwen")
        self.assertEqual(cfg.timeout_seconds, 12.5)
        self.assertEqual(cfg.max_tool_calls, 7)
        self.assertTrue(cfg.enable_thinking)

    def test_from_env_defaults_when_blank(self) -> None:
        with patch.dict(
            os.environ,
            {
                "LLAMACPP_BASE_URL": "",
                "LLAMACPP_MODEL": "",
                "LLAMACPP_TIMEOUT_SECONDS": "",
                "LLAMACPP_ENABLE_THINKING": "",
                "AGENT_MAX_TOOL_CALLS": "",
            },
            clear=False,
        ):
            cfg = LlamaCppConfig.from_env()

        self.assertEqual(cfg.base_url, "http://127.0.0.1:11435")
        self.assertEqual(cfg.model, "qwen3-1.7b")
        self.assertEqual(cfg.timeout_seconds, 180.0)
        self.assertEqual(cfg.max_tool_calls, 5)
        self.assertFalse(cfg.enable_thinking)


class TestLlamaCppClient(unittest.TestCase):
    def _client(
        self,
        handler,
        config: LlamaCppConfig | None = None,
    ) -> tuple[LlamaCppClient, httpx.Client]:
        transport = httpx.MockTransport(handler)
        http_client = httpx.Client(transport=transport)
        return LlamaCppClient(config or LlamaCppConfig(), http_client=http_client), http_client

    def _logged_metrics(self, captured) -> dict[str, object]:
        message = captured.records[-1].getMessage()
        event, payload = message.split(" ", 1)
        self.assertEqual(event, "llamacpp_chat")
        return json.loads(payload)

    def test_health_check_success(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/health")
            return httpx.Response(200, json={"status": "ok"})

        llm, http_client = self._client(handler)
        self.addCleanup(http_client.close)

        self.assertTrue(llm.is_healthy())

    def test_health_check_falls_back_to_models_endpoint(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/health":
                return httpx.Response(404, text="Not found")
            self.assertEqual(request.url.path, "/v1/models")
            return httpx.Response(200, json=_models_payload())

        llm, http_client = self._client(handler)
        self.addCleanup(http_client.close)

        self.assertTrue(llm.is_healthy())

    def test_health_check_failure(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, text="Loading model")

        llm, http_client = self._client(handler)
        self.addCleanup(http_client.close)

        self.assertFalse(llm.is_healthy())

    def test_health_check_connection_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Connection refused")

        llm, http_client = self._client(handler)
        self.addCleanup(http_client.close)

        self.assertFalse(llm.is_healthy())

    def test_list_models_openai_format(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/v1/models")
            return httpx.Response(200, json=_models_payload())

        llm, http_client = self._client(handler)
        self.addCleanup(http_client.close)

        models = llm.list_models()
        self.assertEqual(len(models), 1)
        self.assertEqual(models[0].name, _QWEN_MODEL_PATH)

    def test_list_models_accepts_ollama_style_payload(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"models": [{"name": _QWEN_MODEL_PATH}]})

        llm, http_client = self._client(handler)
        self.addCleanup(http_client.close)

        models = llm.list_models()
        self.assertEqual([m.name for m in models], [_QWEN_MODEL_PATH])

    def test_list_models_malformed_response(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"unexpected": True})

        llm, http_client = self._client(handler)
        self.addCleanup(http_client.close)

        with self.assertRaises(LlmResponseError):
            llm.list_models()

    def test_validate_availability_matches_full_gguf_path(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_models_payload())

        llm, http_client = self._client(handler)
        self.addCleanup(http_client.close)

        # Should not raise: configured short name matches the served GGUF path.
        llm.validate_availability()
        self.assertTrue(llm.is_model_available("qwen3"))
        self.assertTrue(llm.is_model_available("Qwen_Qwen3-1.7B"))

    def test_validate_availability_missing_model_raises(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_models_payload("some-other-model.gguf"))

        llm, http_client = self._client(handler)
        self.addCleanup(http_client.close)

        with self.assertRaises(LlmModelNotFoundError) as ctx:
            llm.validate_availability()
        self.assertIn("qwen3-1.7b", str(ctx.exception))
        self.assertIn("some-other-model.gguf", str(ctx.exception))
        self.assertIn("llama.cpp", str(ctx.exception))

    def test_validate_availability_connection_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Connection refused")

        llm, http_client = self._client(handler)
        self.addCleanup(http_client.close)

        with self.assertRaises(LlmConnectionError) as ctx:
            llm.validate_availability()
        self.assertIn("llama.cpp", str(ctx.exception))

    def test_chat_success_and_payload(self) -> None:
        captured: list[dict[str, Any]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/v1/chat/completions")
            captured.append(json.loads(request.content))
            return httpx.Response(
                200,
                json=_completion('{"action":"final_answer","final_answer":"Hello"}'),
            )

        llm, http_client = self._client(handler)
        self.addCleanup(http_client.close)

        resp = llm.chat(
            [ChatMessage(role=ChatRole.USER, content="Hello")],
            format="json",
        )

        self.assertEqual(resp.content, '{"action":"final_answer","final_answer":"Hello"}')
        self.assertEqual(resp.model, _QWEN_MODEL_PATH)
        self.assertEqual(resp.prompt_eval_count, 10)
        self.assertEqual(resp.eval_count, 5)
        self.assertEqual(resp.done_reason, "stop")
        self.assertFalse(resp.truncated)
        self.assertIsNotNone(resp.duration_ms)

        payload = captured[0]
        self.assertEqual(payload["model"], "qwen3-1.7b")
        self.assertEqual(payload["messages"], [{"role": "user", "content": "Hello"}])
        self.assertFalse(payload["stream"])
        self.assertEqual(payload["temperature"], 0.0)
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertEqual(
            payload["chat_template_kwargs"],
            {"enable_thinking": False},
        )

    def test_chat_without_format_omits_response_format(self) -> None:
        captured: list[dict[str, Any]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(json.loads(request.content))
            return httpx.Response(200, json=_completion("hello"))

        llm, http_client = self._client(handler)
        self.addCleanup(http_client.close)

        llm.chat([ChatMessage(role=ChatRole.USER, content="Hello")])
        self.assertNotIn("response_format", captured[0])

    def test_chat_enables_thinking_when_configured(self) -> None:
        captured: list[dict[str, Any]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(json.loads(request.content))
            return httpx.Response(200, json=_completion("hello"))

        llm, http_client = self._client(
            handler,
            LlamaCppConfig(enable_thinking=True),
        )
        self.addCleanup(http_client.close)

        llm.chat([ChatMessage(role=ChatRole.USER, content="Hello")])
        self.assertEqual(
            captured[0]["chat_template_kwargs"],
            {"enable_thinking": True},
        )

    def test_chat_records_metrics_without_prompt_content(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_completion("hello"))

        llm, http_client = self._client(handler)
        self.addCleanup(http_client.close)

        with patch("backend.agent.llm.llamacpp._elapsed_ms", return_value=250.0):
            with self.assertLogs("backend.agent.llm.llamacpp", level="INFO") as captured:
                llm.chat(
                    [ChatMessage(role=ChatRole.USER, content="SECRET_CUSTOMER_DATA")]
                )

        metrics = self._logged_metrics(captured)
        self.assertEqual(metrics["outcome"], "completed")
        self.assertEqual(metrics["model"], _QWEN_MODEL_PATH)
        self.assertEqual(metrics["request_ms"], 250.0)
        self.assertEqual(metrics["prompt_eval_count"], 10)
        self.assertEqual(metrics["eval_count"], 5)
        self.assertEqual(metrics["prompt_eval_ms"], 120.5)
        self.assertEqual(metrics["eval_ms"], 250.25)
        self.assertEqual(metrics["done_reason"], "stop")
        self.assertFalse(metrics["truncated"])
        self.assertFalse(metrics["failed"])
        self.assertIsNone(metrics["error_type"])
        self.assertEqual(metrics["status_code"], 200)
        self.assertNotIn("SECRET_CUSTOMER_DATA", captured.records[-1].getMessage())

    def test_chat_missing_usage_metadata_does_not_fail(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=_completion(
                    "hello",
                    include_usage=False,
                    include_timings=False,
                ),
            )

        llm, http_client = self._client(handler)
        self.addCleanup(http_client.close)

        resp = llm.chat([ChatMessage(role=ChatRole.USER, content="Hello")])
        self.assertIsNone(resp.prompt_eval_count)
        self.assertIsNone(resp.eval_count)
        self.assertEqual(resp.done_reason, "stop")
        self.assertFalse(resp.truncated)

    def test_chat_records_truncation_from_length_finish_reason(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=_completion('{"partial":', finish_reason="length"),
            )

        llm, http_client = self._client(handler)
        self.addCleanup(http_client.close)

        with patch("backend.agent.llm.llamacpp._elapsed_ms", return_value=500.0):
            with self.assertLogs("backend.agent.llm.llamacpp", level="INFO") as captured:
                resp = llm.chat([ChatMessage(role=ChatRole.USER, content="Hello")])

        self.assertEqual(resp.done_reason, "length")
        self.assertTrue(resp.truncated)
        metrics = self._logged_metrics(captured)
        self.assertEqual(metrics["outcome"], "truncated")
        self.assertTrue(metrics["truncated"])

    def test_chat_timeout_is_instrumented(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("Timed out")

        llm, http_client = self._client(
            handler,
            LlamaCppConfig(timeout_seconds=5.0),
        )
        self.addCleanup(http_client.close)

        with patch("backend.agent.llm.llamacpp._elapsed_ms", return_value=250.0):
            with self.assertLogs("backend.agent.llm.llamacpp", level="INFO") as captured:
                with self.assertRaises(LlmTimeoutError) as ctx:
                    llm.chat(
                        [ChatMessage(role=ChatRole.USER, content="SECRET_CUSTOMER_DATA")]
                    )

        self.assertIn("llama.cpp", str(ctx.exception))
        self.assertIn("timed out after 5.0 seconds", str(ctx.exception))
        metrics = self._logged_metrics(captured)
        self.assertEqual(metrics["outcome"], "timeout")
        self.assertTrue(metrics["failed"])
        self.assertEqual(metrics["error_type"], "LlmTimeoutError")
        self.assertNotIn("SECRET_CUSTOMER_DATA", captured.records[-1].getMessage())

    def test_chat_connection_error_is_instrumented(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Connection refused")

        llm, http_client = self._client(handler)
        self.addCleanup(http_client.close)

        with patch("backend.agent.llm.llamacpp._elapsed_ms", return_value=250.0):
            with self.assertLogs("backend.agent.llm.llamacpp", level="INFO") as captured:
                with self.assertRaises(LlmConnectionError) as ctx:
                    llm.chat([ChatMessage(role=ChatRole.USER, content="Hello")])

        self.assertIn("llama.cpp", str(ctx.exception))
        metrics = self._logged_metrics(captured)
        self.assertEqual(metrics["outcome"], "error")
        self.assertTrue(metrics["failed"])
        self.assertEqual(metrics["error_type"], "LlmConnectionError")

    def test_chat_404_model_not_found(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"error": "model not found"})

        llm, http_client = self._client(
            handler,
            LlamaCppConfig(model="missing-model"),
        )
        self.addCleanup(http_client.close)

        with self.assertRaises(LlmModelNotFoundError):
            llm.chat([ChatMessage(role=ChatRole.USER, content="Hello")])

    def test_chat_http_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="Internal crash")

        llm, http_client = self._client(handler)
        self.addCleanup(http_client.close)

        with self.assertRaises(LlmResponseError) as ctx:
            llm.chat([ChatMessage(role=ChatRole.USER, content="Hello")])
        self.assertEqual(ctx.exception.status_code, 500)

    def test_chat_malformed_json(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="not json")

        llm, http_client = self._client(handler)
        self.addCleanup(http_client.close)

        with self.assertRaises(LlmResponseError):
            llm.chat([ChatMessage(role=ChatRole.USER, content="Hello")])

    def test_chat_empty_choices(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"choices": []})

        llm, http_client = self._client(handler)
        self.addCleanup(http_client.close)

        with self.assertRaises(LlmResponseError):
            llm.chat([ChatMessage(role=ChatRole.USER, content="Hello")])


class TestProviderSelection(unittest.TestCase):
    def test_default_provider_is_ollama(self) -> None:
        with patch.dict(os.environ, {"LLM_PROVIDER": ""}, clear=False):
            self.assertEqual(resolve_provider_name(), "ollama")

    def test_environment_selects_llamacpp(self) -> None:
        with patch.dict(os.environ, {"LLM_PROVIDER": "llamacpp"}, clear=False):
            self.assertEqual(resolve_provider_name(), "llamacpp")

    def test_qwen_aliases_resolve_to_llamacpp(self) -> None:
        self.assertEqual(resolve_provider_name("qwen"), "llamacpp")
        self.assertEqual(resolve_provider_name("qwen3"), "llamacpp")
        self.assertEqual(resolve_provider_name("llama.cpp"), "llamacpp")

    def test_invalid_provider_raises(self) -> None:
        with self.assertRaises(ValueError):
            resolve_provider_name("openai")

    def test_create_ollama_client(self) -> None:
        transport = httpx.MockTransport(lambda request: httpx.Response(200))
        http_client = httpx.Client(transport=transport)

        client = create_llm_client("ollama", http_client=http_client)
        self.assertIsInstance(client, OllamaClient)
        self.assertIsInstance(client.config, LlmConfig)

    def test_create_llamacpp_client(self) -> None:
        transport = httpx.MockTransport(lambda request: httpx.Response(200))
        http_client = httpx.Client(transport=transport)
        config = LlamaCppConfig()

        client = create_llm_client("qwen", llamacpp_config=config, http_client=http_client)
        self.assertIsInstance(client, LlamaCppClient)
        self.assertIs(client.config, config)


class TestAgentServiceProviderSelection(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "fixture_erp.db"
        create_erp_fixture_db(self.db_path)

        self.erp_config = ErpDatabaseConfig(self.db_path, query_timeout_seconds=5.0)
        self.platform = ErpToolPlatform.from_config(self.erp_config)

    def tearDown(self) -> None:
        self.platform.close()
        self.temp_dir.cleanup()

    def test_default_provider_remains_ollama(self) -> None:
        with patch.dict(os.environ, {"LLM_PROVIDER": ""}, clear=False):
            service = AgentService.from_platform(self.platform)
        self.addCleanup(service.close)

        self.assertIsInstance(service.client, OllamaClient)
        self.assertIs(service.orchestrator.client, service.client)
        self.assertEqual(service.orchestrator.max_tool_calls, 5)

    def test_explicit_llamacpp_provider(self) -> None:
        config = LlamaCppConfig(max_tool_calls=3)
        service = AgentService.from_platform(
            self.platform,
            provider="llamacpp",
            llamacpp_config=config,
        )
        self.addCleanup(service.close)

        self.assertIsInstance(service.client, LlamaCppClient)
        self.assertIs(service.orchestrator.client, service.client)
        self.assertEqual(service.orchestrator.max_tool_calls, 3)

    def test_environment_selects_llamacpp_provider(self) -> None:
        with patch.dict(os.environ, {"LLM_PROVIDER": "llamacpp"}, clear=False):
            service = AgentService.from_platform(
                self.platform,
                llamacpp_config=LlamaCppConfig(),
            )
        self.addCleanup(service.close)

        self.assertIsInstance(service.client, LlamaCppClient)

    def test_injected_client_takes_precedence(self) -> None:
        transport = httpx.MockTransport(lambda request: httpx.Response(200))
        http_client = httpx.Client(transport=transport)
        self.addCleanup(http_client.close)
        injected = OllamaClient(LlmConfig(), http_client=http_client)

        service = AgentService.from_platform(
            self.platform,
            provider="llamacpp",
            llm_client=injected,
        )
        self.addCleanup(service.close)

        self.assertIs(service.client, injected)


class TestQwen3OrchestratorIntegration(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "fixture_erp.db"
        create_erp_fixture_db(self.db_path)

        self.erp_config = ErpDatabaseConfig(self.db_path, query_timeout_seconds=5.0)
        self.platform = ErpToolPlatform.from_config(self.erp_config)

    def tearDown(self) -> None:
        self.platform.close()
        self.temp_dir.cleanup()

    def _create_service(
        self,
        responses: list[dict[str, Any]],
        *,
        available: bool = True,
    ) -> tuple[AgentService, list[dict[str, Any]]]:
        resp_iter = iter(responses)
        chat_requests: list[dict[str, Any]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/v1/models":
                if not available:
                    raise httpx.ConnectError("Connection refused")
                return httpx.Response(200, json=_models_payload())

            if request.url.path == "/v1/chat/completions":
                chat_requests.append(json.loads(request.content))
                try:
                    decision = next(resp_iter)
                except StopIteration:
                    decision = {
                        "thought": "No more scripted responses",
                        "action": "final_answer",
                        "final_answer": "No further information.",
                    }
                return httpx.Response(
                    200,
                    json=_completion(json.dumps(decision)),
                )

            return httpx.Response(404, text="Not found")

        transport = httpx.MockTransport(handler)
        http_client = httpx.Client(transport=transport)
        self.addCleanup(http_client.close)

        client = LlamaCppClient(LlamaCppConfig(), http_client=http_client)
        service = AgentService.from_platform(self.platform, llm_client=client)
        self.addCleanup(service.close)
        return service, chat_requests

    def test_qwen3_produces_direct_final_answer(self) -> None:
        service, chat_requests = self._create_service(
            [
                {
                    "thought": "Greeting",
                    "action": "final_answer",
                    "final_answer": "Hello! I am your iFive ERP assistant.",
                }
            ]
        )

        result = service.answer_question("Hello")

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.answer, "Hello! I am your iFive ERP assistant.")
        self.assertEqual(len(result.tool_calls), 0)
        self.assertEqual(len(chat_requests), 1)
        self.assertEqual(
            chat_requests[0]["response_format"],
            {"type": "json_object"},
        )

    def test_qwen3_tool_selection_uses_erp_tools_and_grounds_answer(self) -> None:
        service, _ = self._create_service(
            [
                {
                    "thought": "List warehouses using the approved tool",
                    "action": "call_tool",
                    "tool_name": "erp.warehouses.list",
                    "arguments": {},
                },
                {
                    "thought": "Answer",
                    "action": "final_answer",
                    "final_answer": "I think there are warehouses, but I am guessing.",
                },
            ]
        )

        result = service.answer_question("List all warehouses")

        self.assertEqual(result.status, "completed")
        self.assertEqual(len(result.tool_calls), 1)
        self.assertEqual(result.tool_calls[0].tool_name, "erp.warehouses.list")
        self.assertEqual(result.tool_calls[0].status, "succeeded")
        # The authoritative warehouse list comes from the tool, not the model.
        self.assertIn("Main Warehouse", result.answer)
        self.assertNotIn("guessing", result.answer)

    def test_qwen3_product_count_comes_from_erp_tool_not_model_text(self) -> None:
        service, _ = self._create_service(
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
                    "final_answer": "There are 999 products in the ERP.",
                },
            ]
        )

        direct = self.platform.runner.execute(
            ToolExecutionRequest(tool_name="erp.products.count", arguments={})
        )
        expected_count = direct.output["product_count"]

        result = service.answer_question("How many products are there?")

        self.assertEqual(result.status, "completed")
        self.assertEqual(
            result.answer,
            f"There are {expected_count} products in the ERP.",
        )

    def test_qwen3_unavailable_reports_llamacpp_provider(self) -> None:
        service, _ = self._create_service([], available=False)

        result = service.answer_question("Hello")

        self.assertEqual(result.status, "error")
        self.assertEqual(result.error, "llamacpp_unavailable")
        self.assertIn("llama.cpp", result.answer)
        self.assertNotIn("Ollama", result.answer)


if __name__ == "__main__":
    unittest.main()
