"""Adapter that exposes the Gemini provider through the application's LlmClient contract.

``GeminiClient`` speaks Gemini's native function-calling protocol: it accepts
``GeminiChatMessage`` objects and returns ``GeminiResponse`` objects containing
native ``function_calls``. The ERP agent's orchestrator instead speaks the
provider-neutral ``LlmClient`` protocol: it sends ``ChatMessage`` objects and
expects a JSON ``ToolSelectionDecision`` in ``LLMResponse.content``.

This module bridges the two without changing the Gemini SDK implementation or
the orchestrator's Ollama/Qwen3 behavior. Native Gemini function calls are
represented to the orchestrator as a ``call_tools`` decision. The orchestrator
executes them through the existing ERP tool runner and feeds the results back;
this adapter then reconstructs proper Gemini function-call/function-response
turns for the next generation request.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from typing import Any

from backend.agent.llm.errors import (
    LlmConnectionError,
    LlmError,
    LlmModelNotFoundError,
    LlmResponseError,
    LlmTimeoutError,
)
from backend.agent.llm.models import ChatMessage, ChatRole, LLMResponse
from backend.agent.tools.registry import ToolRegistry
from backend.ai_providers.gemini.client import GeminiClient
from backend.ai_providers.gemini.config import GeminiConfig
from backend.ai_providers.gemini.errors import (
    GeminiConnectionError,
    GeminiError,
    GeminiModelNotFoundError,
    GeminiTimeoutError,
)
from backend.ai_providers.gemini.models import (
    GeminiChatMessage,
    GeminiChatRole,
)
from backend.ai_providers.gemini.tool_adapter import to_gemini_tools

_NATIVE_TOOL_INSTRUCTION = """

### GEMINI NATIVE TOOL MODE:
Use the provided function tools directly whenever ERP data is required.
When you need data, call the appropriate function instead of writing a JSON
tool request. When you have enough information, reply with the final
natural-language answer for the user.
"""


def _encode_thought_signature(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return base64.b64encode(value).decode("ascii")
    if isinstance(value, str):
        return value
    return None


def _decode_thought_signature(value: Any) -> bytes | None:
    if isinstance(value, bytes):
        return value
    if not isinstance(value, str) or not value:
        return None
    try:
        return base64.b64decode(value.encode("ascii"), validate=True)
    except (ValueError, TypeError):
        return None


def _strip_code_fences(text: str) -> str:
    cleaned = text.strip()
    if not cleaned.startswith("```"):
        return cleaned
    first_newline = cleaned.find("\n")
    if first_newline != -1:
        cleaned = cleaned[first_newline + 1 :]
    else:
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    return cleaned.strip()


def _parse_json_object(text: str) -> dict[str, Any] | None:
    cleaned = _strip_code_fences(text)
    try:
        data = json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def _normalized_calls(function_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for index, call in enumerate(function_calls):
        if not isinstance(call, Mapping):
            continue
        name = call.get("name")
        if not isinstance(name, str) or not name.strip():
            # Decisions produced by this adapter store the name as tool_name.
            name = call.get("tool_name")
        if not isinstance(name, str) or not name.strip():
            continue
        arguments = call.get("arguments")
        calls.append(
            {
                "id": str(call.get("id") or f"gemini-call-{index + 1}"),
                "tool_name": name.strip(),
                "arguments": (
                    dict(arguments) if isinstance(arguments, Mapping) else {}
                ),
                "thought_signature": _encode_thought_signature(
                    call.get("thought_signature")
                ),
            }
        )
    return calls


def _calls_decision(
    calls: list[dict[str, Any]],
    thought: str = "",
) -> str:
    return json.dumps(
        {
            "thought": thought,
            "action": "call_tools",
            "tool_calls": calls,
            "tool_name": None,
            "arguments": None,
            "final_answer": None,
        },
        ensure_ascii=False,
    )


def _final_decision(answer: str) -> str:
    return json.dumps(
        {
            "thought": "",
            "action": "final_answer",
            "tool_calls": [],
            "tool_name": None,
            "arguments": None,
            "final_answer": answer,
        },
        ensure_ascii=False,
    )


def _decision_from_text(text: str) -> str:
    """Normalize a plain or JSON-shaped Gemini text response."""

    data = _parse_json_object(text)
    if data is not None:
        action = data.get("action")
        if action == "call_tools":
            calls = _normalized_calls(data.get("tool_calls") or [])
            if calls:
                return _calls_decision(calls, str(data.get("thought") or ""))
        if action == "call_tool":
            name = data.get("tool_name")
            if isinstance(name, str) and name.strip():
                arguments = data.get("arguments")
                return _calls_decision(
                    [
                        {
                            "id": "gemini-text-call-1",
                            "tool_name": name.strip(),
                            "arguments": (
                                dict(arguments)
                                if isinstance(arguments, Mapping)
                                else {}
                            ),
                            "thought_signature": None,
                        }
                    ],
                    str(data.get("thought") or ""),
                )
        if action == "final_answer":
            answer = data.get("final_answer")
            if isinstance(answer, str) and answer.strip():
                return _final_decision(answer.strip())

    return _final_decision(text.strip())


def _tool_feedback_payload(tool_name: str, content: str) -> dict[str, Any]:
    output_prefix = f"Tool `{tool_name}` output:\n"
    if content.startswith(output_prefix):
        raw = content[len(output_prefix) :]
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            parsed = {"message": raw}
        return {"output": parsed}

    if "cancelled or timed out" in content:
        return {
            "error": {
                "code": "cancelled",
                "message": content,
            }
        }

    if "failed" in content or "not recognized" in content:
        return {
            "error": {
                "code": "tool_error",
                "message": content,
            }
        }

    return {"output": {"message": content}}


def _to_gemini_message_role(role: ChatRole) -> GeminiChatRole:
    if role is ChatRole.SYSTEM:
        return GeminiChatRole.SYSTEM
    if role is ChatRole.ASSISTANT:
        return GeminiChatRole.MODEL
    if role is ChatRole.TOOL:
        return GeminiChatRole.TOOL
    return GeminiChatRole.USER


def _translate_error(
    error: Exception,
    *,
    model_name: str | None = None,
    timeout_seconds: float | None = None,
) -> LlmError | Exception:
    if isinstance(error, LlmError):
        return error
    if isinstance(error, GeminiModelNotFoundError):
        return LlmModelNotFoundError(
            model_name or "gemini",
            service_name="Gemini",
            remedy="Check GEMINI_MODEL or select a model available to this API key.",
        )
    if isinstance(error, GeminiTimeoutError):
        return LlmTimeoutError(
            timeout_seconds if timeout_seconds is not None else 0.0,
            service_name="Gemini",
        )
    if isinstance(error, GeminiConnectionError):
        return LlmConnectionError(
            "",
            str(error),
            service_name="Gemini",
            hint=(
                "Please check network connectivity, GEMINI_BASE_URL, and "
                "GEMINI_API_KEY."
            ),
        )
    if isinstance(error, GeminiError):
        return LlmResponseError(str(error))
    return error


class GeminiLlmClientAdapter:
    """Adapt ``GeminiClient`` to the provider-neutral ``LlmClient`` protocol."""

    provider_label = "Gemini"
    unavailable_error_code = "gemini_unavailable"
    connection_hint = (
        "Please ensure GEMINI_API_KEY is configured and the Gemini service "
        "is reachable."
    )

    def __init__(
        self,
        config: GeminiConfig,
        *,
        client: GeminiClient | None = None,
        tool_registry: ToolRegistry | None = None,
    ) -> None:
        self.config = config
        self._client = client or GeminiClient(config)
        self._tool_registry = tool_registry

    def _gemini_tools(self) -> list[Any] | None:
        if self._tool_registry is None:
            return None
        definitions = self._tool_registry.list_tools()
        if not definitions:
            return None
        return to_gemini_tools(definitions)

    def _to_gemini_messages(
        self,
        messages: list[ChatMessage],
    ) -> list[GeminiChatMessage]:
        system_parts: list[str] = []
        converted: list[GeminiChatMessage] = []

        index = 0
        while index < len(messages):
            message = messages[index]
            if message.role is ChatRole.SYSTEM:
                system_parts.append(message.content)
                index += 1
                continue

            if message.role is ChatRole.ASSISTANT:
                data = _parse_json_object(message.content)
                if data is not None and data.get("action") == "call_tools":
                    calls = _normalized_calls(data.get("tool_calls") or [])
                    if calls:
                        function_calls = [
                            {
                                "id": call["id"],
                                "name": call["tool_name"],
                                "arguments": call["arguments"],
                                "thought_signature": _decode_thought_signature(
                                    call.get("thought_signature")
                                ),
                            }
                            for call in calls
                        ]
                        converted.append(
                            GeminiChatMessage(
                                role=GeminiChatRole.MODEL,
                                content=str(data.get("thought") or ""),
                                function_calls=function_calls,
                            )
                        )

                        feedback_index = index + 1
                        for call in calls:
                            if feedback_index >= len(messages):
                                break
                            feedback = messages[feedback_index]
                            if feedback.role is not ChatRole.USER:
                                break
                            converted.append(
                                GeminiChatMessage(
                                    role=GeminiChatRole.TOOL,
                                    content=json.dumps(
                                        _tool_feedback_payload(
                                            call["tool_name"],
                                            feedback.content,
                                        ),
                                        ensure_ascii=False,
                                    ),
                                    call_id=call["id"],
                                    tool_name=call["tool_name"],
                                )
                            )
                            feedback_index += 1
                        index = feedback_index
                        continue

                converted.append(
                    GeminiChatMessage(
                        role=GeminiChatRole.MODEL,
                        content=message.content,
                    )
                )
                index += 1
                continue

            converted.append(
                GeminiChatMessage(
                    role=_to_gemini_message_role(message.role),
                    content=message.content,
                )
            )
            index += 1

        if system_parts:
            system_text = "\n".join(system_parts)
            if "GEMINI NATIVE TOOL MODE" not in system_text:
                system_text += _NATIVE_TOOL_INSTRUCTION
            converted.insert(
                0,
                GeminiChatMessage(
                    role=GeminiChatRole.SYSTEM,
                    content=system_text,
                ),
            )

        return converted

    def chat(
        self,
        messages: list[ChatMessage],
        *,
        format: str | None = None,
        temperature: float = 0.0,
        timeout: float | None = None,
    ) -> LLMResponse:
        gemini_messages = self._to_gemini_messages(messages)
        try:
            response = self._client.chat(
                gemini_messages,
                temperature=temperature,
                timeout=timeout,
                tools=self._gemini_tools(),
            )
        except Exception as error:
            raise _translate_error(
                error,
                model_name=self.config.model,
                timeout_seconds=timeout or self.config.timeout_seconds,
            ) from error

        calls = _normalized_calls(response.function_calls)
        if calls:
            thought = response.content.strip() if response.content else ""
            content = _calls_decision(calls, thought)
        else:
            content = _decision_from_text(response.content or "")

        return LLMResponse(
            content=content,
            model=response.model,
            duration_ms=response.duration_ms,
            request_duration_ms=response.request_duration_ms,
            done_reason=response.finish_reason,
            truncated=response.truncated,
        )

    def validate_availability(self) -> None:
        try:
            self._client.validate_availability()
        except Exception as error:
            raise _translate_error(
                error,
                model_name=self.config.model,
                timeout_seconds=self.config.timeout_seconds,
            ) from error

    def close(self) -> None:
        self._client.close()


__all__ = ["GeminiLlmClientAdapter"]
