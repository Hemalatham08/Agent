from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.agent.llm.ai_models_api import register_ai_model_routes, router
from backend.agent.services.ai_model_manager import RuntimeAiModelManager
from backend.tests.test_ai_model_manager import FakeClientRegistry


class TestAiModelsApi(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = FakeClientRegistry()
        self.manager = RuntimeAiModelManager(
            MagicMock(),
            provider="ollama",
            client_factory=self.registry,
        )
        self.addCleanup(self.manager.close)

        app = FastAPI()
        app.state.ai_model_manager = self.manager
        app.include_router(router)
        self.client = TestClient(app)

    def _headers(self, token: str = "secret") -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def test_list_models(self) -> None:
        response = self.client.get("/ai/models")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(
            [provider["provider"] for provider in body["providers"]],
            ["ollama", "llamacpp"],
        )
        self.assertEqual(body["active"]["provider"], "ollama")
        self.assertEqual(body["active"]["model"], "llama3.2")
        self.assertEqual(body["active"]["base_url"], "http://127.0.0.1:11434")

        ollama = next(
            provider
            for provider in body["providers"]
            if provider["provider"] == "ollama"
        )
        llamacpp = next(
            provider
            for provider in body["providers"]
            if provider["provider"] == "llamacpp"
        )
        self.assertEqual(ollama["model"], "llama3.2")
        self.assertEqual(ollama["base_url"], "http://127.0.0.1:11434")
        self.assertEqual(llamacpp["model"], "qwen3-1.7b")
        self.assertEqual(llamacpp["base_url"], "http://127.0.0.1:11435")

        for provider in body["providers"]:
            self.assertIn("available", provider)
            self.assertIn("active", provider)
            self.assertIn("reason", provider)

    def test_get_active_model(self) -> None:
        response = self.client.get("/ai/models/active")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["provider"], "ollama")
        self.assertEqual(body["model"], "llama3.2")
        self.assertTrue(body["active"])
        self.assertTrue(body["available"])

    def test_switch_requires_authentication(self) -> None:
        with patch.dict(os.environ, {"AI_SWITCH_TOKEN": "secret"}, clear=False):
            response = self.client.post(
                "/ai/models/switch",
                json={"provider": "llamacpp"},
            )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.manager.active_provider, "ollama")

    def test_switch_rejects_invalid_token(self) -> None:
        with patch.dict(os.environ, {"AI_SWITCH_TOKEN": "secret"}, clear=False):
            response = self.client.post(
                "/ai/models/switch",
                json={"provider": "llamacpp"},
                headers=self._headers("wrong"),
            )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.manager.active_provider, "ollama")

    def test_switch_disabled_without_configured_token(self) -> None:
        with patch.dict(os.environ, {"AI_SWITCH_TOKEN": ""}, clear=False):
            response = self.client.post(
                "/ai/models/switch",
                json={"provider": "llamacpp"},
                headers=self._headers(),
            )

        self.assertEqual(response.status_code, 403)
        self.assertIn("disabled", response.json()["detail"])
        self.assertEqual(self.manager.active_provider, "ollama")

    def test_successful_switch(self) -> None:
        with patch.dict(os.environ, {"AI_SWITCH_TOKEN": "secret"}, clear=False):
            response = self.client.post(
                "/ai/models/switch",
                json={"provider": "llamacpp"},
                headers=self._headers(),
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["provider"], "llamacpp")
        self.assertEqual(body["model"], "qwen3-1.7b")
        self.assertEqual(body["base_url"], "http://127.0.0.1:11435")
        self.assertTrue(body["active"])
        self.assertEqual(body["previous_provider"], "ollama")

        active = self.client.get("/ai/models/active").json()
        self.assertEqual(active["provider"], "llamacpp")
        self.assertEqual(active["model"], "qwen3-1.7b")

    def test_switch_from_llamacpp_back_to_ollama(self) -> None:
        with patch.dict(os.environ, {"AI_SWITCH_TOKEN": "secret"}, clear=False):
            first = self.client.post(
                "/ai/models/switch",
                json={"provider": "llamacpp"},
                headers=self._headers(),
            )
            second = self.client.post(
                "/ai/models/switch",
                json={"provider": "ollama"},
                headers=self._headers(),
            )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["provider"], "llamacpp")

        self.assertEqual(second.status_code, 200)
        body = second.json()
        self.assertEqual(body["provider"], "ollama")
        self.assertEqual(body["model"], "llama3.2")
        self.assertEqual(body["base_url"], "http://127.0.0.1:11434")
        self.assertTrue(body["active"])
        self.assertEqual(body["previous_provider"], "llamacpp")

        active = self.client.get("/ai/models/active").json()
        self.assertEqual(active["provider"], "ollama")
        self.assertEqual(active["model"], "llama3.2")

    def test_unavailable_provider_returns_conflict_and_preserves_active(self) -> None:
        self.registry.availability["llamacpp"] = False

        with patch.dict(os.environ, {"AI_SWITCH_TOKEN": "secret"}, clear=False):
            response = self.client.post(
                "/ai/models/switch",
                json={"provider": "llamacpp"},
                headers=self._headers(),
            )

        self.assertEqual(response.status_code, 409)
        self.assertIn("unavailable", response.json()["detail"])
        self.assertEqual(self.manager.active_provider, "ollama")

    def test_unknown_provider_returns_bad_request(self) -> None:
        with patch.dict(os.environ, {"AI_SWITCH_TOKEN": "secret"}, clear=False):
            response = self.client.post(
                "/ai/models/switch",
                json={"provider": "openai"},
                headers=self._headers(),
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.manager.active_provider, "ollama")

    def test_register_routes_keeps_app_routes_flat(self) -> None:
        app = FastAPI()
        app.state.ai_model_manager = self.manager

        register_ai_model_routes(app)

        self.assertTrue(all(hasattr(route, "path") for route in app.routes))
        with TestClient(app) as client:
            response = client.get("/ai/models")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["active"]["provider"], "ollama")


if __name__ == "__main__":
    unittest.main()
