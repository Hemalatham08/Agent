from __future__ import annotations

from typing import Any
import httpx

from backend.agent.llm.config import LlmConfig
from backend.agent.llm.errors import (
    LlmConnectionError,
    LlmModelNotFoundError,
    LlmResponseError,
    LlmTimeoutError,
)
from backend.agent.llm.models import ChatMessage, LLMResponse, ModelInfo


class OllamaClient:
    """Client for local Ollama service interactions."""

    def __init__(self, config: LlmConfig, *, http_client: httpx.Client | None = None) -> None:
        self.config = config
        self._owned_client = http_client is None
        self._client = http_client or httpx.Client(timeout=config.timeout_seconds)

    def close(self) -> None:
        if self._owned_client:
            self._client.close()

    def __enter__(self) -> OllamaClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def is_healthy(self) -> bool:
        """Return True if Ollama service is reachable, False otherwise."""
        try:
            response = self._client.get(f"{self.config.base_url}/api/tags")
            return response.status_code == 200
        except Exception:
            return False

    def list_models(self) -> list[ModelInfo]:
        """List all models currently installed locally in Ollama."""
        try:
            response = self._client.get(f"{self.config.base_url}/api/tags")
        except (httpx.ConnectError, httpx.ConnectTimeout) as err:
            raise LlmConnectionError(self.config.base_url, str(err)) from err
        except httpx.TimeoutException as err:
            raise LlmTimeoutError(self.config.timeout_seconds) from err
        except Exception as err:
            raise LlmConnectionError(self.config.base_url, str(err)) from err

        if response.status_code != 200:
            raise LlmResponseError(
                f"Failed to list Ollama models: HTTP {response.status_code}",
                status_code=response.status_code,
            )

        try:
            payload = response.json()
            models_raw = payload.get("models", [])
            return [
                ModelInfo(
                    name=m.get("name", ""),
                    modified_at=m.get("modified_at"),
                    size=m.get("size"),
                )
                for m in models_raw
                if m.get("name")
            ]
        except Exception as err:
            raise LlmResponseError(f"Malformed response when listing models: {err}") from err

    def is_model_available(self, model_name: str | None = None) -> bool:
        """Check if target model is installed locally."""
        target = (model_name or self.config.model).strip().lower()
        target_base = target.split(":")[0]

        installed = self.list_models()
        for item in installed:
            name = item.name.lower()
            name_base = name.split(":")[0]
            if name == target or name_base == target or (name == f"{target}:latest"):
                return True
            if name_base == target_base and ":" not in target:
                return True
        return False

    def validate_availability(self) -> None:
        """Ensure Ollama service is reachable and configured model is available."""
        installed = self.list_models()
        available_names = [m.name for m in installed]

        target = self.config.model.strip().lower()
        target_base = target.split(":")[0]

        found = False
        for name in available_names:
            nl = name.lower()
            if nl == target or nl.split(":")[0] == target or nl == f"{target}:latest":
                found = True
                break
            if nl.split(":")[0] == target_base and ":" not in target:
                found = True
                break

        if not found:
            raise LlmModelNotFoundError(self.config.model, available_names)

    def chat(
        self,
        messages: list[ChatMessage],
        *,
        format: str | None = None,
        temperature: float = 0.0,
        timeout: float | None = None,
    ) -> LLMResponse:
        """Send chat messages to Ollama and return assistant response."""
        url = f"{self.config.base_url}/api/chat"
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": [{"role": m.role.value, "content": m.content} for m in messages],
            "stream": False,
            "options": {
                "temperature": temperature,
            },
        }
        if format:
            payload["format"] = format

        req_timeout = timeout if timeout is not None else self.config.timeout_seconds

        try:
            response = self._client.post(url, json=payload, timeout=req_timeout)
        except (httpx.ConnectError, httpx.ConnectTimeout) as err:
            raise LlmConnectionError(self.config.base_url, str(err)) from err
        except httpx.TimeoutException as err:
            raise LlmTimeoutError(req_timeout) from err
        except Exception as err:
            raise LlmConnectionError(self.config.base_url, str(err)) from err

        if response.status_code == 404:
            raise LlmModelNotFoundError(self.config.model)

        if response.status_code != 200:
            raise LlmResponseError(
                f"Ollama chat error (HTTP {response.status_code}): {response.text}",
                status_code=response.status_code,
            )

        try:
            data = response.json()
            message_data = data.get("message", {})
            content = message_data.get("content", "")
            duration_ns = data.get("total_duration")
            duration_ms = (duration_ns / 1_000_000.0) if duration_ns is not None else None

            return LLMResponse(
                content=content,
                model=data.get("model", self.config.model),
                duration_ms=duration_ms,
                prompt_eval_count=data.get("prompt_eval_count"),
                eval_count=data.get("eval_count"),
            )
        except Exception as err:
            raise LlmResponseError(f"Failed to parse Ollama chat response: {err}") from err
