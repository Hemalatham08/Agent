"""Response parser for Gemini ``GenerateContentResponse`` objects.

Parses Gemini's non-streaming generate-content response into a normalized
structure containing plain text and any requested function calls. The parser
never executes functions, never constructs database queries, and never
bypasses validation. It only extracts and normalizes data from the SDK
response so that Phase 4 (orchestrator integration) can decide how to handle
each function call.

No Ollama code is imported from this module. Importing this module is safe
even when ``google-genai`` is not installed; the SDK types are resolved
lazily.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

try:
    from google.genai import types

    _GEN_AI_TYPES_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised when google-genai absent
    types = None
    _GEN_AI_TYPES_AVAILABLE = False


@dataclass
class ParsedGeminiResponse:
    """Normalized result parsed from a Gemini ``GenerateContentResponse``.

    Attributes:
        text: Concatenated plain-text content from the response parts.
        function_calls: Function call requests found in the response, in
            declaration order. May be empty for text-only responses.
        finish_reason: The SDK-reported finish reason, if any.
        truncated: True if the response was truncated due to length limits.
    """

    text: str = ""
    function_calls: list[types.FunctionCall] = field(default_factory=list)
    finish_reason: str | None = None
    truncated: bool = False


def _safe_get_attr(obj: Any, name: str, default: Any = None) -> Any:
    """Safely read an attribute from a possibly malformed SDK object.

    Returns ``default`` if the attribute is absent or accessing it raises.
    """
    try:
        value = getattr(obj, name, default)
    except Exception:
        return default
    return value


def parse_generate_content_response(
    response: types.GenerateContentResponse,
) -> ParsedGeminiResponse:
    """Parse a Gemini ``GenerateContentResponse`` into text and function calls.

    The function never raises. Malformed responses, missing candidates, empty
    parts, and unexpected structures are all handled gracefully and produce
    an empty (or partial) ``ParsedGeminiResponse``.

    Extraction rules:
    * Text is collected from every part that has a non-empty ``text`` field.
    * Function calls are collected from every part that has a
      ``function_call`` field with a non-empty ``name``.
    * ``finish_reason`` and ``truncated`` are taken from the first candidate.
    """
    text_parts: list[str] = []
    function_calls: list[types.FunctionCall] = []
    finish_reason: str | None = None
    truncated = False

    candidates = _safe_get_attr(response, "candidates", None)
    if not isinstance(candidates, list) or not candidates:
        return ParsedGeminiResponse(
            text="",
            function_calls=[],
            finish_reason=None,
            truncated=False,
        )

    first = candidates[0]
    finish_reason_raw = _safe_get_attr(first, "finish_reason", None)
    if finish_reason_raw is not None:
        # Handle both plain strings and SDK enum values (e.g. FinishReason.MAX_TOKENS).
        # SDK enums expose .value; plain strings do not have .value.
        finish_reason_value = getattr(finish_reason_raw, "value", finish_reason_raw)
        finish_reason = str(finish_reason_value).strip()
        truncated = finish_reason.lower() in {
            "length",
            "max_tokens",
        }

    content = _safe_get_attr(first, "content", None)
    if content is None:
        return ParsedGeminiResponse(
            text="".join(text_parts),
            function_calls=function_calls,
            finish_reason=finish_reason,
            truncated=truncated,
        )

    parts = _safe_get_attr(content, "parts", None)
    if not isinstance(parts, list):
        return ParsedGeminiResponse(
            text="".join(text_parts),
            function_calls=function_calls,
            finish_reason=finish_reason,
            truncated=truncated,
        )

    for part in parts:
        text = _safe_get_attr(part, "text", None)
        if isinstance(text, str) and text:
            text_parts.append(text)

        func_call = _safe_get_attr(part, "function_call", None)
        if func_call is None:
            continue

        fname = _safe_get_attr(func_call, "name", None)
        if not isinstance(fname, str) or not fname.strip():
            continue

        function_calls.append(func_call)

    return ParsedGeminiResponse(
        text="".join(text_parts),
        function_calls=function_calls,
        finish_reason=finish_reason,
        truncated=truncated,
    )


def extract_function_call_arguments(
    function_call: types.FunctionCall,
) -> dict[str, Any]:
    """Safely extract the arguments dict from a Gemini ``FunctionCall``.

    Returns an empty dict if ``args`` is absent, not a dict, or otherwise
    unusable. The caller is responsible for validating arguments against the
    tool schema (see ``tool_adapter.validate_function_call``).
    """
    args = _safe_get_attr(function_call, "args", None)
    if isinstance(args, dict):
        return dict(args)
    return {}


def extract_function_call_name(function_call: types.FunctionCall) -> str | None:
    """Safely extract the function name from a Gemini ``FunctionCall``.

    Returns ``None`` if the name is absent or not a non-blank string.
    """
    name = _safe_get_attr(function_call, "name", None)
    if isinstance(name, str) and name.strip():
        return name
    return None


__all__ = [
    "ParsedGeminiResponse",
    "extract_function_call_arguments",
    "extract_function_call_name",
    "parse_generate_content_response",
]
