"""Non-streaming client for the Google Gemini API.

Uses the official ``google-genai`` SDK. The underlying SDK client is created
lazily on first use so that constructing this client never requires network
access or a valid API key. The API key is managed entirely by the SDK and is
never logged or included in exceptions.

This module imports no Ollama code. Importing this module is safe even when
``google-genai`` is not installed; instantiating ``GeminiClient`` or calling
its methods raises a clear :class:`GeminiConfigurationError` in that case.
"""

from __future__ import annotations

import logging
import time
import json
from typing import Any, Optional

try:
    from google import genai
    from google.genai import errors as genai_errors
    from google.genai import types

    _GEN_AI_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised when google-genai absent
    genai = None
    genai_errors = None
    types = None
    _GEN_AI_AVAILABLE = False

from backend.ai_providers.gemini.config import GeminiConfig
from backend.ai_providers.gemini.errors import (
    GeminiAuthError,
    GeminiConfigurationError,
    GeminiConnectionError,
    GeminiError,
    GeminiInvalidRequestError,
    GeminiModelNotFoundError,
    GeminiPermissionError,
    GeminiQuotaError,
    GeminiResponseError,
    GeminiTimeoutError,
)
from backend.ai_providers.gemini.models import (
    GeminiChatMessage,
    GeminiChatRole,
    GeminiModelInfo,
    GeminiResponse,
)

_LOGGER = logging.getLogger(__name__)

# Gemini API status codes mapped to provider exceptions.
_GEMINI_STATUS_UNAUTHORIZED = 401
_GEMINI_STATUS_NOT_FOUND = 404
_GEMINI_STATUS_BAD_REQUEST = 400
_GEMINI_STATUS_FORBIDDEN = 403
_GEMINI_STATUS_QUOTA_EXCEEDED = 429

# Persistent client timeout for metadata operations (list_models, validate_availability).
# These calls use the persistent client which is created once. Use a generous
# fixed timeout (120 seconds) independent of the per-call generation timeout.
_PERSISTENT_CLIENT_TIMEOUT_MS = 120_000


def _normalize_model_name(name: str) -> str:
    """Normalize model name by removing 'models/' prefix for comparison."""
    return name.removeprefix("models/")


def _elapsed_ms(started_at: float) -> float:
    return round((time.perf_counter() - started_at) * 1000.0, 3)


def _safe_get_attr(obj: Any, name: str, default: Any = None) -> Any:
    """Safely read an attribute from a possibly malformed SDK object."""
    try:
        value = getattr(obj, name, default)
    except Exception:
        return default
    return value


def _map_sdk_error(err: Exception) -> GeminiError:
    """Convert an SDK or transport error into a sanitized GeminiError.

    The API key and raw SDK error details are never included in the resulting
    message. Only generic, provider-owned wording is used.
    """
    # SDK-level API errors carry an HTTP status code. The raw SDK message is
    # intentionally ignored; only the status code informs the exception type.
    if genai_errors is not None and isinstance(err, genai_errors.APIError):
        code = getattr(err, "code", None)
        if code == _GEMINI_STATUS_UNAUTHORIZED:
            return GeminiAuthError(
                "Gemini authentication failed. Verify that GEMINI_API_KEY is "
                "set and valid."
            )
        if code == _GEMINI_STATUS_NOT_FOUND:
            return GeminiModelNotFoundError(
                "The requested Gemini model or resource was not found."
            )
        if code == _GEMINI_STATUS_BAD_REQUEST:
            return GeminiInvalidRequestError(
                "Gemini request was invalid. Check request format and parameters."
            )
        if code == _GEMINI_STATUS_FORBIDDEN:
            return GeminiPermissionError(
                "Gemini API access denied. The API key may lack permission for "
                "the requested model or operation."
            )
        if code == _GEMINI_STATUS_QUOTA_EXCEEDED:
            return GeminiQuotaError(
                "Gemini API quota or rate limit exceeded. Please retry later."
            )
        if isinstance(err, genai_errors.ServerError):
            return GeminiResponseError(
                "Gemini service error. Please try again later."
            )
        return GeminiResponseError(f"Gemini API error (HTTP {code}).")

    # Transport-level connectivity errors. Use only the exception type name;
    # never include the raw error string which may contain secrets or URLs.
    type_name = type(err).__name__
    if "Timeout" in type_name:
        return GeminiTimeoutError("Gemini request timed out.")
    if "Connect" in type_name or "Connection" in type_name:
        return GeminiConnectionError(
            "Cannot connect to the Gemini service. Check network connectivity."
        )

    return GeminiConnectionError(
        "Unexpected error while contacting the Gemini service."
    )


class GeminiClient:
    """Client for non-streaming Google Gemini generations."""

    def __init__(self, config: GeminiConfig) -> None:
        if not _GEN_AI_AVAILABLE:
            raise GeminiConfigurationError(
                "google-genai SDK is not installed. Install it with: "
                "pip install -r backend/requirements-gemini.txt"
            )
        self.config = config
        self._sdk_client: Optional[genai.Client] = None

    @property
    def _client(self) -> genai.Client:
        """Lazily create the SDK client on first use."""
        if self._sdk_client is None:
            http_options = types.HttpOptions(
                base_url=self.config.base_url,
                timeout=int(self.config.timeout_seconds * 1000),
            )
            self._sdk_client = genai.Client(
                api_key=self.config.api_key,
                http_options=http_options,
            )
        return self._sdk_client

    def close(self) -> None:
        """Release any held SDK client resources."""
        if self._sdk_client is not None:
            try:
                close = getattr(self._sdk_client, "close", None)
                if close is not None:
                    close()
            finally:
                self._sdk_client = None

    def __enter__(self) -> GeminiClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def is_healthy(self) -> bool:
        """Return True if the Gemini service is reachable and authenticated."""
        try:
            self._client.models.list()
            return True
        except Exception:
            return False

    def list_models(self) -> list[GeminiModelInfo]:
        """List models available to the configured API key."""
        try:
            result = self._client.models.list()
        except Exception as err:
            # Suppress the raw SDK exception chain so sensitive SDK error
            # messages cannot appear in formatted tracebacks.
            raise _map_sdk_error(err) from None

        models: list[GeminiModelInfo] = []
        for item in result or []:
            name = getattr(item, "name", "") or ""
            version = getattr(item, "version", None)
            if name:
                models.append(GeminiModelInfo(name=name, version=version))
        return models

    def is_model_available(self, model_name: str | None = None) -> bool:
        """Check whether the target model is available to the API key.

        Returns False (rather than raising) when the model list cannot be
        retrieved, so callers can degrade gracefully.
        """
        target = (model_name or self.config.model).strip()
        target_norm = _normalize_model_name(target)
        target_base = target_norm.split(":")[0]
        try:
            installed = self.list_models()
        except GeminiError:
            return False
        for item in installed:
            name = item.name
            name_norm = _normalize_model_name(name)
            name_base = name_norm.split(":")[0]
            if name_norm == target_norm or name_base == target_norm or name_norm == f"{target_norm}:latest":
                return True
            if name_base == target_base and ":" not in target_norm:
                return True
        return False

    def validate_availability(self) -> None:
        """Ensure the configured model is available, raising otherwise."""
        target = self.config.model.strip()
        target_norm = _normalize_model_name(target)
        target_base = target_norm.split(":")[0]
        try:
            installed = [m.name for m in self.list_models()]
        except GeminiError as err:
            raise err
        found = False
        for name in installed:
            nl_norm = _normalize_model_name(name)
            nl_base = nl_norm.split(":")[0]
            if nl_norm == target_norm or nl_base == target_norm or nl_norm == f"{target_norm}:latest":
                found = True
                break
            if nl_base == target_base and ":" not in target_norm:
                found = True
                break
        if not found:
            available = ", ".join(f"'{n}'" for n in installed) if installed else "none"
            raise GeminiModelNotFoundError(
                f"Configured Gemini model '{target}' is not available. "
                f"Available models: [{available}]."
            )

    def chat(
        self,
        messages: list[GeminiChatMessage],
        *,
        temperature: float = 0.0,
        timeout: float | None = None,
        tools: list[types.Tool] | None = None,
    ) -> GeminiResponse:
        """Send messages to Gemini and return a normalized response.

        Tool/FUNCTION messages are supported. A per-call ``timeout`` is honored
        only for this call and does not permanently change the client's
        configured timeout. Optional ``tools`` are passed to the SDK for native
        function calling.
        """

        # Separate system instructions (Gemini uses system_instruction) from
        # conversational contents. TOOL/FUNCTION roles are not supported by
        # this phase and are explicitly rejected.
        system_parts: list[str] = []
        contents: list[types.Content] = []
        for message in messages:
            if message.role is GeminiChatRole.SYSTEM:
                system_parts.append(message.content)
            elif message.role is GeminiChatRole.USER:
                contents.append(
                    types.Content(role="user", parts=[types.Part(text=message.content)])
                )
            elif message.role is GeminiChatRole.MODEL:
                parts: list[types.Part] = []
                if message.content:
                    parts.append(types.Part(text=message.content))
                if message.function_calls:
                    for fc in message.function_calls:
                        part_kwargs = {
                            "function_call": types.FunctionCall(
                                id=fc.get("id", ""),
                                name=fc.get("name", ""),
                                args=fc.get("arguments", {}),
                            )
                        }
                        # Use function call's own thought_signature, not message-level
                        fc_thought_sig = fc.get("thought_signature")
                        if fc_thought_sig:
                            part_kwargs["thought_signature"] = fc_thought_sig
                        parts.append(types.Part(**part_kwargs))
                contents.append(types.Content(role="model", parts=parts))
            else:  # TOOL / FUNCTION - feed function response back to Gemini
                # Parse content as JSON response envelope
                try:
                    response_data = json.loads(message.content) if message.content else {}
                except (json.JSONDecodeError, TypeError):
                    response_data = {"error": {"message": "Invalid function response content"}}
                parts = [types.Part(function_response=types.FunctionResponse(
                    id=message.call_id or "",
                    name=message.tool_name or "unknown",
                    response=response_data,
                ))]
                # Gemini API expects function responses as "user" role messages.
                contents.append(types.Content(role="user", parts=parts))

        system_instruction = "\n".join(system_parts) if system_parts else None

        config = types.GenerateContentConfig(
            temperature=temperature,
            system_instruction=system_instruction,
            tools=tools,
        )

        # Determine which SDK client to use for this call. A per-call timeout
        # is honored by using a temporary client; the persistent client is
        # never mutated by a per-call timeout. A temporary client is created
        # even when no persistent client exists yet (first-ever call). When no
        # custom timeout is requested and no persistent client exists yet, the
        # persistent client is created with a fixed metadata timeout.
        persistent_client = self._sdk_client
        temp_client: Optional[genai.Client] = None
        if timeout is not None and timeout != self.config.timeout_seconds:
            http_options = types.HttpOptions(
                base_url=self.config.base_url,
                timeout=int(timeout * 1000),
            )
            temp_client = genai.Client(
                api_key=self.config.api_key,
                http_options=http_options,
            )
        elif persistent_client is None:
            http_options = types.HttpOptions(
                base_url=self.config.base_url,
                timeout=_PERSISTENT_CLIENT_TIMEOUT_MS,
            )
            persistent_client = genai.Client(
                api_key=self.config.api_key,
                http_options=http_options,
            )
            self._sdk_client = persistent_client
        client_to_use = temp_client if temp_client is not None else persistent_client

        try:
            started_at = time.perf_counter()
            try:
                response = client_to_use.models.generate_content(
                    model=self.config.model,
                    contents=contents,
                    config=config,
                )
            except Exception as err:
                request_duration_ms = _elapsed_ms(started_at)
                _LOGGER.warning(
                    "gemini_chat error model=%s request_ms=%s error_type=%s",
                    self.config.model,
                    request_duration_ms,
                    type(err).__name__,
                )
                # Suppress the raw SDK exception chain so sensitive SDK error
                # messages cannot appear in formatted tracebacks.
                raise _map_sdk_error(err) from None

            request_duration_ms = _elapsed_ms(started_at)

            content = getattr(response, "text", None) or ""
            # If text is empty but candidates exist, extract text from parts
            if not content:
                candidates = getattr(response, "candidates", None)
                if candidates:
                    first = candidates[0]
                    content_parts = _safe_get_attr(first, "content", None)
                    if content_parts:
                        parts = _safe_get_attr(content_parts, "parts", None)
                        if parts:
                            for part in parts:
                                part_text = _safe_get_attr(part, "text", None)
                                if isinstance(part_text, str) and part_text:
                                    content = part_text
                                    break

            model_name = getattr(response, "model_version", None) or self.config.model

            finish_reason: str | None = None
            safety_ratings: list[dict[str, Any]] = []
            function_calls: list[dict[str, Any]] = []
            candidates = getattr(response, "candidates", None)
            if candidates:
                first = candidates[0]
                finish_reason = getattr(first, "finish_reason", None)
                ratings = getattr(first, "safety_ratings", None) or []
                for rating in ratings:
                    safety_ratings.append(
                        {
                            "category": getattr(rating, "category", None),
                            "probability": getattr(rating, "probability", None),
                        }
                    )
                content_parts = _safe_get_attr(first, "content", None)
                if content_parts:
                    parts = _safe_get_attr(content_parts, "parts", None)
                    if parts:
                        for part in parts:
                            fc = _safe_get_attr(part, "function_call", None)
                            if fc is not None:
                                fc_name = _safe_get_attr(fc, "name", None)
                                fc_args = _safe_get_attr(fc, "args", None)
                                fc_id = _safe_get_attr(fc, "id", None)
                                if isinstance(fc_name, str) and fc_name.strip():
                                    thought_sig = _safe_get_attr(part, "thought_signature", None)
                                    function_calls.append(
                                        {
                                            "id": fc_id or "",
                                            "name": fc_name,
                                            "arguments": fc_args
                                            if isinstance(fc_args, dict)
                                            else {},
                                            "thought_signature": thought_sig,
                                        }
                                    )

            truncated = bool(
                finish_reason is not None
                and str(finish_reason).strip().lower() in {"length", "max_tokens"}
            )

            _LOGGER.info(
                "gemini_chat completed model=%s request_ms=%s finish_reason=%s truncated=%s",
                model_name,
                request_duration_ms,
                finish_reason,
                truncated,
            )

            return GeminiResponse(
                content=content,
                model=model_name,
                duration_ms=None,
                request_duration_ms=request_duration_ms,
                finish_reason=finish_reason,
                safety_ratings=safety_ratings,
                truncated=truncated,
                function_calls=function_calls,
            )
        finally:
            # Close any temporary client created for a per-call timeout,
            # including when generation raised an exception. The persistent
            # client is never touched here.
            if temp_client is not None:
                try:
                    close = getattr(temp_client, "close", None)
                    if close is not None:
                        close()
                except Exception:
                    pass


__all__ = ["GeminiClient"]
