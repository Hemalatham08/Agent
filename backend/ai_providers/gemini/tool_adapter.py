"""Tool adapter for translating between ERP tool definitions and Gemini function declarations.

This module provides bidirectional conversion between the project's existing
``ToolDefinition`` contracts (defined in ``backend/agent/tools/contracts.py``
and populated by ``backend/agent/erp/definitions.py``) and the Google Gen AI
SDK's ``FunctionDeclaration`` / ``FunctionCall`` / ``FunctionResponse`` types.

The adapter never executes tools, never constructs database queries, and never
bypasses existing authorization or validation. It only translates data
structures so that Phase 4 (orchestrator integration) can feed Gemini function
calls into the existing ``ErpToolRunner`` execution layer.

No Ollama code is imported from this module. Importing this module is safe
even when ``google-genai`` is not installed; the SDK types are resolved
lazily.
"""

from __future__ import annotations

from typing import Any

try:
    from google.genai import types

    _GEN_AI_TYPES_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised when google-genai absent
    types = None
    _GEN_AI_TYPES_AVAILABLE = False

from backend.agent.erp.definitions import ERP_TOOL_DEFINITIONS_BY_NAME
from backend.agent.models import ErrorCategory, utc_now
from backend.agent.tools.contracts import (
    ToolDefinition,
    ToolExecutionRequest,
    ToolExecutionResult,
    ToolExecutionStatus,
    ToolName,
)
from backend.agent.tools.errors import InvalidToolSchemaError
from backend.agent.tools.validation import ToolArgumentIssue, validate_arguments

from backend.ai_providers.gemini.errors import GeminiResponseError

_JSON_TYPE_TO_GEMINI: dict[str | None, str | None] = {
    None: None,
    "string": "string",
    "integer": "integer",
    "number": "number",
    "boolean": "boolean",
    "array": "array",
    "object": "object",
    "null": "null",
}


def _safe_get_attr(obj: Any, name: str, default: Any = None) -> Any:
    """Safely read an attribute from a possibly malformed SDK object.

    Returns ``default`` if the attribute is absent or accessing it raises.
    """
    try:
        value = getattr(obj, name, default)
    except Exception:
        return default
    return value


def _map_json_type(json_type: str | None) -> str | None:
    """Map a JSON Schema type string to a Gemini-compatible type string."""
    return _JSON_TYPE_TO_GEMINI.get(json_type, json_type)


def to_function_declaration(tool_definition: ToolDefinition) -> types.FunctionDeclaration:
    """Convert one ``ToolDefinition`` into a Gemini ``FunctionDeclaration``.

    The tool's ``input_schema`` (a JSON Schema subset) is mapped to Gemini's
    ``parameters`` field. Unsupported schema keywords are silently dropped
    rather than causing failures, because Gemini's function declaration schema
    is a subset of JSON Schema.
    """
    schema = tool_definition.input_schema
    properties = schema.get("properties", {}) or {}
    required = schema.get("required", []) or []

    gemini_properties: dict[str, Any] = {}
    for prop_name, prop_schema in properties.items():
        if not isinstance(prop_schema, dict):
            continue
        gemini_prop: dict[str, Any] = {
            "type": _map_json_type(prop_schema.get("type")),
        }
        if prop_schema.get("description"):
            gemini_prop["description"] = prop_schema["description"]
        if "enum" in prop_schema:
            gemini_prop["enum"] = prop_schema["enum"]
        gemini_properties[prop_name] = gemini_prop

    parameters: dict[str, Any] = {
        "type": "object",
        "properties": gemini_properties,
    }
    if required:
        parameters["required"] = list(required)
    # Gemini API does not support additionalProperties in function declaration parameters.
    # Omit it to avoid INVALID_ARGUMENT errors.

    return types.FunctionDeclaration(
        name=tool_definition.name,
        description=tool_definition.description,
        parameters=parameters,
    )


def to_function_declarations(
    tool_definitions: list[ToolDefinition],
) -> list[types.FunctionDeclaration]:
    """Convert multiple ``ToolDefinition`` objects into Gemini declarations."""
    return [to_function_declaration(td) for td in tool_definitions]


def to_gemini_tools(
    tool_definitions: list[ToolDefinition],
) -> list[types.Tool]:
    """Wrap function declarations into Gemini ``Tool`` objects suitable for
    ``GenerateContentConfig(tools=...)``.

    All declarations are placed in a single ``Tool`` with
    ``function_declarations``.
    """
    declarations = to_function_declarations(tool_definitions)
    return [types.Tool(function_declarations=declarations)]


def validate_function_call(
    function_name: str,
    arguments: dict[str, Any],
    tool_definitions_by_name: dict[str, ToolDefinition],
) -> list[ToolArgumentIssue]:
    """Validate a function call's name and arguments against the ERP tool catalog.

    Returns a list of ``ToolArgumentIssue`` objects. An empty list means the
    call is valid. This function does not execute anything.

    Validation checks:
    * The function name exists in the registered tool catalog.
    * The arguments satisfy the tool's ``input_schema`` (via
      ``validate_arguments``).
    """
    if function_name not in tool_definitions_by_name:
        return [
            ToolArgumentIssue(
                path=function_name,
                message=f"Unknown tool: {function_name}",
                keyword="unknown_tool",
            )
        ]

    definition = tool_definitions_by_name[function_name]
    return validate_arguments(arguments, definition.input_schema)


def to_tool_execution_request(
    function_call: types.FunctionCall,
    tool_definitions_by_name: dict[str, ToolDefinition],
) -> ToolExecutionRequest | None:
    """Convert a Gemini ``FunctionCall`` into a ``ToolExecutionRequest``.

    Returns ``None`` if the function name is unknown or the arguments fail
    validation. No execution occurs here; the returned request is intended to
    be passed to ``ErpToolRunner.execute()`` by Phase 4.

    Validation rules:
    * The function name must be a non-blank string.
    * The arguments must be a dictionary (non-dict arguments are rejected,
      never silently coerced).
    * The arguments must satisfy the tool's ``input_schema``.
    """
    # Validate function name is a non-empty string before lookup.
    fname = _safe_get_attr(function_call, "name", None)
    if not isinstance(fname, str) or not fname.strip():
        return None

    # Reject non-dictionary arguments explicitly; never silently coerce to {}.
    args = _safe_get_attr(function_call, "args", None)
    if not isinstance(args, dict):
        return None

    issues = validate_function_call(
        fname,
        args,
        tool_definitions_by_name,
    )
    if issues:
        return None

    definition = tool_definitions_by_name[fname]
    return ToolExecutionRequest(
        tool_name=ToolName(fname),
        arguments=dict(args),
    )


def to_function_response(
    function_call_id: str,
    tool_name: str,
    result: ToolExecutionResult,
) -> types.FunctionResponse:
    """Convert a ``ToolExecutionResult`` into a Gemini ``FunctionResponse``.

    The response uses the Gemini API format with "output" for success
    and "error" for failure.
    """
    if result.status is ToolExecutionStatus.SUCCEEDED:
        response_payload: dict[str, Any] = {
            "output": result.output,
        }
    else:
        error = result.error
        response_payload = {
            "error": {
                "code": error.code if error else "tool_error",
                "message": error.message if error else "Tool execution failed",
                "category": (
                    error.category.value if error else ErrorCategory.INTERNAL.value
                ),
                "recoverable": error.recoverable if error else False,
                "retryable": error.retryable if error else False,
                "details": error.details if error else {},
            },
        }

    return types.FunctionResponse(
        id=function_call_id,
        name=tool_name,
        response=response_payload,
    )


def adapt_all_erp_tools() -> list[types.Tool]:
    """Convert all registered ERP tool definitions into Gemini ``Tool`` objects.

    This is a convenience function that reads from
    ``ERP_TOOL_DEFINITIONS`` (the authoritative ERP tool catalog) and returns
    Gemini-compatible tool declarations. No ERP files are modified.
    """
    from backend.agent.erp.definitions import ERP_TOOL_DEFINITIONS

    return to_gemini_tools(list(ERP_TOOL_DEFINITIONS))


__all__ = [
    "ToolArgumentIssue",
    "adapt_all_erp_tools",
    "to_function_declaration",
    "to_function_declarations",
    "to_function_response",
    "to_gemini_tools",
    "to_tool_execution_request",
    "validate_function_call",
]
