from __future__ import annotations

import threading
import unittest
from unittest.mock import MagicMock

from backend.agent.llm.config import LlmConfig
from backend.agent.llm.errors import LlmConnectionError
from backend.agent.llm.llamacpp import LlamaCppConfig
from backend.agent.llm.models import ChatMessage, ChatRole, LLMResponse
from backend.agent.services.ai_model_manager import (
    ProviderUnavailableError,
    RuntimeAiModelManager,
)


class FakeClient:
    def __init__(
        self,
        provider: str,
        config: LlmConfig | LlamaCppConfig,
        *,
        available: bool = True,
    ) -> None:
        self.provider = provider
        self.config = config
        self.available = available
        self.closed = False
        self.chat_calls = 0
        self._count_lock = threading.Lock()
        self.entered_count = 0
        self.expected_inflight = 0
        self.all_entered = threading.Event()
        self.release = threading.Event()
        self.block_chat = False

    def validate_availability(self) -> None:
        if not self.available:
            raise LlmConnectionError(
                self.config.base_url,
                "provider is down",
                service_name=self.provider,
            )

    def chat(
        self,
        messages: list[ChatMessage],
        *,
        format: str | None = None,
        temperature: float = 0.0,
        timeout: float | None = None,
    ) -> LLMResponse:
        with self._count_lock:
            self.chat_calls += 1
            self.entered_count += 1
            if (
                self.expected_inflight
                and self.entered_count >= self.expected_inflight
            ):
                self.all_entered.set()

        if self.block_chat:
            self.release.wait(5.0)

        return LLMResponse(content="ok", model=self.config.model)

    def close(self) -> None:
        self.closed = True


class FakeClientRegistry:
    def __init__(self) -> None:
        self.availability = {"ollama": True, "llamacpp": True}
        self.created: list[FakeClient] = []
        self.by_provider: dict[str, FakeClient] = {}

    def __call__(
        self,
        provider: str,
        config: LlmConfig | LlamaCppConfig,
    ) -> FakeClient:
        client = FakeClient(
            provider,
            config,
            available=self.availability[provider],
        )
        self.created.append(client)
        self.by_provider[provider] = client
        return client


class TestRuntimeAiModelManager(unittest.TestCase):
    def _create_manager(
        self,
    ) -> tuple[RuntimeAiModelManager, FakeClientRegistry]:
        registry = FakeClientRegistry()
        manager = RuntimeAiModelManager(
            MagicMock(),
            provider="ollama",
            client_factory=registry,
        )
        self.addCleanup(manager.close)
        return manager, registry

    def test_lists_supported_providers_and_active(self) -> None:
        manager, _ = self._create_manager()

        infos = manager.list_providers()

        self.assertEqual(
            [info.provider for info in infos],
            ["ollama", "llamacpp"],
        )
        self.assertTrue(infos[0].active)
        self.assertFalse(infos[1].active)
        self.assertEqual(infos[0].model, "llama3.2")
        self.assertEqual(infos[0].base_url, "http://127.0.0.1:11434")
        self.assertEqual(infos[1].model, "qwen3-1.7b")
        self.assertEqual(infos[1].base_url, "http://127.0.0.1:11435")
        self.assertTrue(all(info.available for info in infos))

    def test_list_reports_unavailable_provider_with_reason(self) -> None:
        manager, registry = self._create_manager()
        registry.availability["llamacpp"] = False

        infos = manager.list_providers()

        llamacpp = next(info for info in infos if info.provider == "llamacpp")
        self.assertFalse(llamacpp.available)
        self.assertIn("provider is down", llamacpp.reason or "")

    def test_active_descriptor(self) -> None:
        manager, _ = self._create_manager()

        info = manager.active_descriptor()

        self.assertEqual(info.provider, "ollama")
        self.assertEqual(info.model, "llama3.2")
        self.assertTrue(info.active)
        self.assertTrue(info.available)

    def test_successful_switch_closes_previous_when_idle(self) -> None:
        manager, registry = self._create_manager()
        previous = registry.created[0]

        info = manager.switch("llamacpp")

        self.assertEqual(info.provider, "llamacpp")
        self.assertEqual(info.model, "qwen3-1.7b")
        self.assertTrue(info.active)
        self.assertEqual(manager.active_provider, "llamacpp")
        self.assertEqual(manager.active_model, "qwen3-1.7b")
        self.assertTrue(previous.closed)

    def test_switch_back_to_ollama(self) -> None:
        manager, registry = self._create_manager()

        first = manager.switch("llamacpp")
        self.assertEqual(first.provider, "llamacpp")
        llamacpp_client = registry.by_provider["llamacpp"]

        second = manager.switch("ollama")

        self.assertEqual(second.provider, "ollama")
        self.assertEqual(second.model, "llama3.2")
        self.assertTrue(second.active)
        self.assertEqual(manager.active_provider, "ollama")
        self.assertEqual(manager.active_model, "llama3.2")
        self.assertTrue(llamacpp_client.closed)
        self.assertFalse(registry.by_provider["ollama"].closed)

    def test_unknown_provider_raises(self) -> None:
        manager, _ = self._create_manager()

        with self.assertRaises(ValueError):
            manager.switch("openai")

    def test_unavailable_switch_preserves_previous_provider(self) -> None:
        manager, registry = self._create_manager()
        previous = registry.created[0]
        registry.availability["llamacpp"] = False

        with self.assertRaises(ProviderUnavailableError) as ctx:
            manager.switch("llamacpp")

        self.assertIn("Qwen3", str(ctx.exception))
        self.assertEqual(manager.active_provider, "ollama")
        self.assertFalse(previous.closed)
        # The validation probe must be cleaned up too.
        self.assertTrue(registry.by_provider["llamacpp"].closed)

    def test_in_flight_request_defers_old_client_close(self) -> None:
        manager, registry = self._create_manager()
        previous = registry.created[0]
        previous.block_chat = True
        previous.expected_inflight = 1

        result: list[LLMResponse] = []
        worker = threading.Thread(
            target=lambda: result.append(
                manager.client.chat(
                    [ChatMessage(role=ChatRole.USER, content="Hello")]
                )
            )
        )
        worker.start()
        self.assertTrue(previous.all_entered.wait(2.0))

        manager.switch("llamacpp")
        self.assertEqual(manager.active_provider, "llamacpp")
        self.assertFalse(previous.closed)

        previous.release.set()
        worker.join(5.0)
        self.assertFalse(worker.is_alive())
        self.assertEqual(len(result), 1)
        self.assertTrue(previous.closed)

    def test_concurrent_requests_survive_switch(self) -> None:
        manager, registry = self._create_manager()
        previous = registry.created[0]
        previous.block_chat = True
        previous.expected_inflight = 3

        results: list[LLMResponse] = []
        lock = threading.Lock()

        def ask() -> None:
            response = manager.client.chat(
                [ChatMessage(role=ChatRole.USER, content="Hello")]
            )
            with lock:
                results.append(response)

        workers = [threading.Thread(target=ask) for _ in range(3)]
        for worker in workers:
            worker.start()

        self.assertTrue(previous.all_entered.wait(3.0))

        manager.switch("llamacpp")
        self.assertFalse(previous.closed)

        previous.release.set()
        for worker in workers:
            worker.join(5.0)
            self.assertFalse(worker.is_alive())

        self.assertEqual(len(results), 3)
        self.assertTrue(previous.closed)

        next_response = manager.client.chat(
            [ChatMessage(role=ChatRole.USER, content="Again")]
        )
        self.assertEqual(next_response.model, "qwen3-1.7b")

    def test_close_defers_active_client_until_inflight_finishes(self) -> None:
        manager, registry = self._create_manager()
        active = registry.created[0]
        active.block_chat = True
        active.expected_inflight = 1

        worker = threading.Thread(
            target=lambda: manager.client.chat(
                [ChatMessage(role=ChatRole.USER, content="Hello")]
            )
        )
        worker.start()
        self.assertTrue(active.all_entered.wait(2.0))

        manager.close()
        self.assertFalse(active.closed)

        active.release.set()
        worker.join(5.0)
        self.assertFalse(worker.is_alive())
        self.assertTrue(active.closed)


if __name__ == "__main__":
    unittest.main()
