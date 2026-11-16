from __future__ import annotations

import json
import logging
import time
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


_LOGGER = logging.getLogger(__name__)


def _optional_int(data: dict[str, Any], key: str) -> int | None:
    value = data.get(key)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def _optional_str(data: dict[str, Any], key: str) -> str | None:
    value = data.get(key)
    return value if isinstance(value, str) else None


def _ns_to_ms(value: int | None) -> float | None:
    if value is None:
        return None
    return value / 1_000_000.0


def _log_ns_as_ms(value: int | None) -> float | None:
    milliseconds = _ns_to_ms(value)
    return None if milliseconds is None else round(milliseconds, 3)


def _elapsed_ms(started_at: float) -> float:
    return round((time.perf_counter() - started_at) * 1000.0, 3)


def _log_chat_metrics(
    *,
    outcome: str,
    model: str,
    request_duration_ms: float,
    total_duration_ns: int | None = None,
    load_duration_ns: int | None = None,
    prompt_eval_count: int | None = None,
    prompt_eval_duration_ns: int | None = None,
    eval_count: int | None = None,
    eval_duration_ns: int | None = None,
    done_reason: str | None = None,
    truncated: bool | None = None,
    failed: bool = False,
    error_type: str | None = None,
    status_code: int | None = None,
) -> None:
    metrics = {
        "event": "ollama_chat",
        "outcome": outcome,
        "model": model,
        "request_ms": request_duration_ms,
        "total_ms": _log_ns_as_ms(total_duration_ns),
        "load_ms": _log_ns_as_ms(load_duration_ns),
        "prompt_eval_count": prompt_eval_count,
        "prompt_eval_ms": _log_ns_as_ms(prompt_eval_duration_ns),
        "eval_count": eval_count,
        "eval_ms": _log_ns_as_ms(eval_duration_ns),
        "done_reason": done_reason,
        "truncated": truncated,
        "failed": failed,
        "error_type": error_type,
        "status_code": status_code,
    }
    _LOGGER.info(
        "ollama_chat %s",
        json.dumps(metrics, separators=(",", ":"), sort_keys=True),
    )


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
        started_at = time.perf_counter()

        try:
            response = self._client.post(url, json=payload, timeout=req_timeout)
        except (httpx.ConnectError, httpx.ConnectTimeout) as err:
            _log_chat_metrics(
                outcome="error",
                model=self.config.model,
                request_duration_ms=_elapsed_ms(started_at),
                failed=True,
                error_type="LlmConnectionError",
            )
            raise LlmConnectionError(self.config.base_url, str(err)) from err
        except httpx.TimeoutException as err:
            _log_chat_metrics(
                outcome="timeout",
                model=self.config.model,
                request_duration_ms=_elapsed_ms(started_at),
                failed=True,
                error_type="LlmTimeoutError",
            )
            raise LlmTimeoutError(req_timeout) from err
        except Exception as err:
            _log_chat_metrics(
                outcome="error",
                model=self.config.model,
                request_duration_ms=_elapsed_ms(started_at),
                failed=True,
                error_type="LlmConnectionError",
            )
            raise LlmConnectionError(self.config.base_url, str(err)) from err

        request_duration_ms = _elapsed_ms(started_at)

        if response.status_code == 404:
            _log_chat_metrics(
                outcome="error",
                model=self.config.model,
                request_duration_ms=request_duration_ms,
                failed=True,
                error_type="LlmModelNotFoundError",
                status_code=response.status_code,
            )
            raise LlmModelNotFoundError(self.config.model)

        if response.status_code != 200:
            _log_chat_metrics(
                outcome="error",
                model=self.config.model,
                request_duration_ms=request_duration_ms,
                failed=True,
                error_type="LlmResponseError",
                status_code=response.status_code,
            )
            raise LlmResponseError(
                f"Ollama chat error (HTTP {response.status_code}): {response.text}",
                status_code=response.status_code,
            )

        try:
            data = response.json()
            message_data = data.get("message", {})
            content = message_data.get("content", "")
            total_duration_ns = _optional_int(data, "total_duration")
            load_duration_ns = _optional_int(data, "load_duration")
            prompt_eval_count = _optional_int(data, "prompt_eval_count")
            prompt_eval_duration_ns = _optional_int(data, "prompt_eval_duration")
            eval_count = _optional_int(data, "eval_count")
            eval_duration_ns = _optional_int(data, "eval_duration")
            done_reason = _optional_str(data, "done_reason")
            truncated = bool(
                done_reason is not None
                and done_reason.strip().lower() == "length"
            )
            duration_ms = _ns_to_ms(total_duration_ns)

            result = LLMResponse(
                content=content,
                model=data.get("model", self.config.model),
                duration_ms=duration_ms,
                request_duration_ms=request_duration_ms,
                total_duration_ns=total_duration_ns,
                load_duration_ns=load_duration_ns,
                prompt_eval_count=prompt_eval_count,
                prompt_eval_duration_ns=prompt_eval_duration_ns,
                eval_count=eval_count,
                eval_duration_ns=eval_duration_ns,
                done_reason=done_reason,
                truncated=truncated,
            )
        except Exception as err:
            _log_chat_metrics(
                outcome="error",
                model=self.config.model,
                request_duration_ms=request_duration_ms,
                failed=True,
                error_type="LlmResponseError",
                status_code=response.status_code,
            )
            raise LlmResponseError(f"Failed to parse Ollama chat response: {err}") from err

        _log_chat_metrics(
            outcome="truncated" if truncated else "completed",
            model=result.model or self.config.model,
            request_duration_ms=request_duration_ms,
            total_duration_ns=total_duration_ns,
            load_duration_ns=load_duration_ns,
            prompt_eval_count=prompt_eval_count,
            prompt_eval_duration_ns=prompt_eval_duration_ns,
            eval_count=eval_count,
            eval_duration_ns=eval_duration_ns,
            done_reason=done_reason,
            truncated=truncated,
            status_code=response.status_code,
        )
        return result
