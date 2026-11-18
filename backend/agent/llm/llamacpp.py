from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

from backend.agent.llm.errors import (
    LlmConnectionError,
    LlmModelNotFoundError,
    LlmResponseError,
    LlmTimeoutError,
)
from backend.agent.llm.models import ChatMessage, LLMResponse, ModelInfo

_LOGGER = logging.getLogger(__name__)

DEFAULT_LLAMACPP_BASE_URL = "http://127.0.0.1:11435"
DEFAULT_LLAMACPP_MODEL = "qwen3-1.7b"
DEFAULT_LLAMACPP_TIMEOUT_SECONDS = 180.0
DEFAULT_MAX_TOOL_CALLS = 5

_SERVICE_NAME = "llama.cpp"
_CONNECTION_HINT = (
    "Please ensure the llama.cpp server is running and has loaded the Qwen3 "
    "model at the configured base URL."
)


def _elapsed_ms(started_at: float) -> float:
    return round((time.perf_counter() - started_at) * 1000.0, 3)


def _optional_int(data: Mapping[str, Any], key: str) -> int | None:
    value = data.get(key)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def _optional_float(data: Mapping[str, Any], key: str) -> float | None:
    value = data.get(key)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _optional_str(data: Mapping[str, Any], key: str) -> str | None:
    value = data.get(key)
    return value if isinstance(value, str) else None


def _log_chat_metrics(
    *,
    outcome: str,
    model: str,
    request_duration_ms: float,
    prompt_eval_count: int | None = None,
    eval_count: int | None = None,
    prompt_eval_ms: float | None = None,
    eval_ms: float | None = None,
    done_reason: str | None = None,
    truncated: bool | None = None,
    failed: bool = False,
    error_type: str | None = None,
    status_code: int | None = None,
) -> None:
    metrics = {
        "event": "llamacpp_chat",
        "outcome": outcome,
        "model": model,
        "request_ms": request_duration_ms,
        "prompt_eval_count": prompt_eval_count,
        "prompt_eval_ms": prompt_eval_ms,
        "eval_count": eval_count,
        "eval_ms": eval_ms,
        "done_reason": done_reason,
        "truncated": truncated,
        "failed": failed,
        "error_type": error_type,
        "status_code": status_code,
    }
    _LOGGER.info(
        "llamacpp_chat %s",
        json.dumps(metrics, separators=(",", ":"), sort_keys=True),
    )


@dataclass(frozen=True)
class LlamaCppConfig:
    """Configuration for a local llama.cpp OpenAI-compatible server."""

    base_url: str = DEFAULT_LLAMACPP_BASE_URL
    model: str = DEFAULT_LLAMACPP_MODEL
    timeout_seconds: float = DEFAULT_LLAMACPP_TIMEOUT_SECONDS
    max_tool_calls: int = DEFAULT_MAX_TOOL_CALLS
    enable_thinking: bool = False

    def __post_init__(self) -> None:
        url = self.base_url.strip()
        if not url:
            raise ValueError("base_url must not be empty")

        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError(f"base_url scheme must be http or https, got '{parsed.scheme}'")
        if not parsed.netloc:
            raise ValueError("base_url must contain a valid host and port")

        object.__setattr__(self, "base_url", url.rstrip("/"))

        model_name = self.model.strip()
        if not model_name:
            raise ValueError("model must not be empty")
        object.__setattr__(self, "model", model_name)

        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

        if self.max_tool_calls < 1:
            raise ValueError("max_tool_calls must be at least 1")

        if not isinstance(self.enable_thinking, bool):
            raise ValueError("enable_thinking must be a boolean")

    @classmethod
    def from_env(cls) -> LlamaCppConfig:
        base_url = os.getenv("LLAMACPP_BASE_URL", DEFAULT_LLAMACPP_BASE_URL).strip()
        if not base_url:
            base_url = DEFAULT_LLAMACPP_BASE_URL

        model = os.getenv("LLAMACPP_MODEL", DEFAULT_LLAMACPP_MODEL).strip()
        if not model:
            model = DEFAULT_LLAMACPP_MODEL

        timeout_raw = os.getenv("LLAMACPP_TIMEOUT_SECONDS", "").strip()
        timeout = DEFAULT_LLAMACPP_TIMEOUT_SECONDS
        if timeout_raw:
            try:
                timeout = float(timeout_raw)
            except ValueError:
                timeout = DEFAULT_LLAMACPP_TIMEOUT_SECONDS

        max_calls_raw = os.getenv("AGENT_MAX_TOOL_CALLS", "").strip()
        max_calls = DEFAULT_MAX_TOOL_CALLS
        if max_calls_raw:
            try:
                max_calls = int(max_calls_raw)
            except ValueError:
                max_calls = DEFAULT_MAX_TOOL_CALLS

        thinking_raw = os.getenv("LLAMACPP_ENABLE_THINKING", "").strip().lower()
        enable_thinking = thinking_raw in ("1", "true", "yes", "on")

        return cls(
            base_url=base_url,
            model=model,
            timeout_seconds=timeout,
            max_tool_calls=max_calls,
            enable_thinking=enable_thinking,
        )


class LlamaCppClient:
    """Client for a local llama.cpp OpenAI-compatible chat server."""

    provider_label = _SERVICE_NAME
    unavailable_error_code = "llamacpp_unavailable"
    connection_hint = _CONNECTION_HINT

    def __init__(
        self,
        config: LlamaCppConfig,
        *,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.config = config
        self._owned_client = http_client is None
        self._client = http_client or httpx.Client(timeout=config.timeout_seconds)

    def close(self) -> None:
        if self._owned_client:
            self._client.close()

    def __enter__(self) -> LlamaCppClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _connection_error(self, err: Exception) -> LlmConnectionError:
        return LlmConnectionError(
            self.config.base_url,
            str(err),
            service_name=_SERVICE_NAME,
            hint=_CONNECTION_HINT,
        )

    def is_healthy(self) -> bool:
        """Return True if the llama.cpp server is reachable and ready."""
        try:
            response = self._client.get(f"{self.config.base_url}/health")
            if response.status_code == 200:
                return True
            if response.status_code != 404:
                return False

            # Older llama.cpp builds may not expose /health.
            models_response = self._client.get(f"{self.config.base_url}/v1/models")
            return models_response.status_code == 200
        except Exception:
            return False

    def list_models(self) -> list[ModelInfo]:
        """List models exposed by the llama.cpp OpenAI-compatible endpoint."""
        try:
            response = self._client.get(f"{self.config.base_url}/v1/models")
        except (httpx.ConnectError, httpx.ConnectTimeout) as err:
            raise self._connection_error(err) from err
        except httpx.TimeoutException as err:
            raise LlmTimeoutError(
                self.config.timeout_seconds, service_name=_SERVICE_NAME
            ) from err
        except Exception as err:
            raise self._connection_error(err) from err

        if response.status_code != 200:
            raise LlmResponseError(
                f"Failed to list llama.cpp models: HTTP {response.status_code}",
                status_code=response.status_code,
            )

        try:
            payload = response.json()
            entries = payload.get("data")
            if not isinstance(entries, list):
                entries = payload.get("models")
            if not isinstance(entries, list):
                raise ValueError("response does not contain a 'data' or 'models' list")

            models: list[ModelInfo] = []
            for entry in entries:
                if not isinstance(entry, Mapping):
                    continue
                name = entry.get("id") or entry.get("name") or entry.get("model")
                if not isinstance(name, str) or not name.strip():
                    continue
                meta = entry.get("meta")
                size = _optional_int(meta, "size") if isinstance(meta, Mapping) else None
                models.append(ModelInfo(name=name.strip(), size=size))
            return models
        except Exception as err:
            raise LlmResponseError(
                f"Malformed response when listing llama.cpp models: {err}"
            ) from err

    @staticmethod
    def _normalize_model_name(value: str) -> str:
        text = value.strip().lower().replace("\\", "/")
        text = text.rsplit("/", 1)[-1]
        if text.endswith(".gguf"):
            text = text[: -len(".gguf")]
        return text

    @classmethod
    def _model_matches(cls, target: str, candidate: str) -> bool:
        """Match tolerance for llama.cpp model ids (often full GGUF paths)."""
        target_name = cls._normalize_model_name(target)
        candidate_name = cls._normalize_model_name(candidate)
        if not target_name or not candidate_name:
            return False

        target_base = target_name.split(":", 1)[0]
        candidate_base = candidate_name.split(":", 1)[0]
        if target_name == candidate_name or target_base == candidate_base:
            return True
        if target_name == f"{candidate_base}:latest":
            return True
        if candidate_name == f"{target_base}:latest":
            return True
        return target_name in candidate_name or candidate_name in target_name

    def is_model_available(self, model_name: str | None = None) -> bool:
        """Check if the target model is exposed by the llama.cpp server."""
        target = (model_name or self.config.model).strip()
        return any(
            self._model_matches(target, item.name) for item in self.list_models()
        )

    def validate_availability(self) -> None:
        """Ensure the llama.cpp server is reachable and the model is available."""
        available_names = [model.name for model in self.list_models()]
        if not any(
            self._model_matches(self.config.model, name)
            for name in available_names
        ):
            raise LlmModelNotFoundError(
                self.config.model,
                available_names,
                service_name=_SERVICE_NAME,
                remedy=(
                    "Load this model in the llama.cpp server or set LLAMACPP_MODEL "
                    "to the model id reported by /v1/models."
                ),
            )

    def chat(
        self,
        messages: list[ChatMessage],
        *,
        format: str | None = None,
        temperature: float = 0.0,
        timeout: float | None = None,
    ) -> LLMResponse:
        """Send chat messages to llama.cpp and return the assistant response."""
        url = f"{self.config.base_url}/v1/chat/completions"
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": [{"role": m.role.value, "content": m.content} for m in messages],
            "stream": False,
            "temperature": temperature,
            # Qwen3 defaults to thinking mode, which can consume the whole
            # response before any answer content is emitted. The ERP agent
            # needs deterministic JSON decisions, so thinking is off by default.
            "chat_template_kwargs": {"enable_thinking": self.config.enable_thinking},
        }
        if format:
            payload["response_format"] = {"type": "json_object"}

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
            raise self._connection_error(err) from err
        except httpx.TimeoutException as err:
            _log_chat_metrics(
                outcome="timeout",
                model=self.config.model,
                request_duration_ms=_elapsed_ms(started_at),
                failed=True,
                error_type="LlmTimeoutError",
            )
            raise LlmTimeoutError(
                req_timeout, service_name=_SERVICE_NAME
            ) from err
        except Exception as err:
            _log_chat_metrics(
                outcome="error",
                model=self.config.model,
                request_duration_ms=_elapsed_ms(started_at),
                failed=True,
                error_type="LlmConnectionError",
            )
            raise self._connection_error(err) from err

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
            raise LlmModelNotFoundError(
                self.config.model, service_name=_SERVICE_NAME
            )

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
                f"llama.cpp chat error (HTTP {response.status_code}): {response.text}",
                status_code=response.status_code,
            )

        try:
            data = response.json()
            choices = data.get("choices")
            if not isinstance(choices, list) or not choices:
                raise ValueError("response does not contain any choices")

            first_choice = choices[0]
            if not isinstance(first_choice, Mapping):
                raise ValueError("first choice is not an object")

            message_data = first_choice.get("message")
            if not isinstance(message_data, Mapping):
                raise ValueError("first choice does not contain a message")

            content = message_data.get("content")
            if content is None:
                content = ""
            if not isinstance(content, str):
                raise ValueError("message content is not a string")

            usage = data.get("usage")
            if not isinstance(usage, Mapping):
                usage = {}
            timings = data.get("timings")
            if not isinstance(timings, Mapping):
                timings = {}

            prompt_eval_count = _optional_int(usage, "prompt_tokens")
            eval_count = _optional_int(usage, "completion_tokens")
            prompt_eval_ms = _optional_float(timings, "prompt_ms")
            eval_ms = _optional_float(timings, "predicted_ms")
            done_reason = _optional_str(first_choice, "finish_reason")
            truncated = bool(
                done_reason is not None and done_reason.strip().lower() == "length"
            )

            result = LLMResponse(
                content=content,
                model=_optional_str(data, "model") or self.config.model,
                duration_ms=request_duration_ms,
                request_duration_ms=request_duration_ms,
                prompt_eval_count=prompt_eval_count,
                eval_count=eval_count,
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
            raise LlmResponseError(
                f"Failed to parse llama.cpp chat response: {err}"
            ) from err

        _log_chat_metrics(
            outcome="truncated" if truncated else "completed",
            model=result.model or self.config.model,
            request_duration_ms=request_duration_ms,
            prompt_eval_count=prompt_eval_count,
            eval_count=eval_count,
            prompt_eval_ms=prompt_eval_ms,
            eval_ms=eval_ms,
            done_reason=done_reason,
            truncated=truncated,
            status_code=response.status_code,
        )
        return result


__all__ = [
    "DEFAULT_LLAMACPP_BASE_URL",
    "DEFAULT_LLAMACPP_MODEL",
    "DEFAULT_LLAMACPP_TIMEOUT_SECONDS",
    "LlamaCppClient",
    "LlamaCppConfig",
]
