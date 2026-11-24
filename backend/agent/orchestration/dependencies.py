"""Resolve explicit ``$steps`` argument references for the ERP agent.

The resolver is a pure orchestration-layer helper. It reads only the outputs of
successful tool executions that already happened during the current
``AgentOrchestrator.process_question`` request. It never executes tools, never
touches the database or filesystem, and never uses ``eval``, ``exec``,
``getattr``, or Python attribute traversal.

Reference syntax::

    $steps.step_1.product_id
    $steps.step_1.items[0].product_id
    $steps.step_1.order.customer_id

``step_N`` is the Nth actual tool execution attempt in the current request
(1-based). Failed and cancelled attempts occupy a number but cannot be
referenced. Pre-flight validation failures never occupy a number.

Resolved values are still passed through the normal ``normalize_tool_arguments``
and executor validation path. The resolver only rejects references that are
malformed, unavailable, not successful, missing a path, or incompatible with
the destination argument schema.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from backend.agent.tools.contracts import ToolDefinition, ToolExecutionStatus

_REFERENCE_PREFIX = "$steps."

# A path segment is either ``.key`` or ``[index]``. Keys must start with a
# letter so private/dunder-like names are rejected before any lookup happens.
_STEP_REFERENCE_PATTERN = re.compile(
    r"^\$steps\.step_(?P<step>[1-9][0-9]*)"
    r"(?P<path>(?:\.(?:[A-Za-z][A-Za-z0-9_]*)|(?:\[[0-9]{1,3}\]))+)$"
)
_INTEGER_TEXT_PATTERN = re.compile(r"^[+-]?\d+$")

_MAX_REFERENCE_LENGTH = 256
_MAX_PATH_SEGMENTS = 8
_MAX_REFERENCES_PER_CALL = 16
_MAX_NESTING_DEPTH = 4
_MAX_REPORTED_ISSUES = 8

_UNRESOLVED = object()


@dataclass(frozen=True)
class DependencyStep:
    """One actual tool execution attempt from the current request.

    ``output`` is populated only for successful executions. Failed and
    cancelled attempts keep ``output=None`` but still occupy a step number.
    """

    step_number: int
    tool_name: str
    status: str
    output: Any | None = None


@dataclass(frozen=True)
class DependencyIssue:
    """A single unresolved or invalid dependency reference."""

    reference: str
    code: str
    message: str


@dataclass
class _ResolutionState:
    steps: Sequence[DependencyStep]
    issues: list[DependencyIssue] = field(default_factory=list)
    reference_count: int = 0


def resolve_argument_dependencies(
    arguments: Mapping[str, Any],
    definition: ToolDefinition,
    steps: Sequence[DependencyStep],
) -> tuple[dict[str, Any], list[DependencyIssue]]:
    """Resolve explicit ``$steps`` references in model-supplied arguments.

    Returns ``(resolved_arguments, issues)``. When ``issues`` is non-empty the
    caller must not execute the tool. The input mapping and the previous tool
    outputs are never mutated.
    """

    if not isinstance(arguments, Mapping):
        issue = DependencyIssue(
            reference="",
            code="invalid_arguments",
            message="tool arguments must be an object",
        )
        return {}, [issue]

    state = _ResolutionState(steps=steps)
    schema = definition.input_schema
    properties = schema.get("properties") if isinstance(schema, Mapping) else None
    if not isinstance(properties, Mapping):
        properties = {}
    required = schema.get("required") if isinstance(schema, Mapping) else None
    if not isinstance(required, list):
        required = []

    resolved: dict[str, Any] = {}
    for name, value in arguments.items():
        property_schema = properties.get(name)
        if not isinstance(property_schema, Mapping):
            property_schema = None
        resolved_value = _resolve_value(
            value,
            property_schema,
            state,
            depth=0,
        )
        if resolved_value is _UNRESOLVED:
            continue
        resolved[name] = resolved_value

    # A reference that resolves to null is not useful for a required argument.
    # Type checks already reject null for string/integer arguments; this also
    # covers schemas without an explicit type.
    for name in required:
        if name not in resolved or resolved[name] is not None:
            continue
        original = arguments.get(name)
        if isinstance(original, str) and original.startswith(_REFERENCE_PREFIX):
            _add_issue(
                state,
                original,
                "null_for_required",
                f"argument '{name}' is required and the resolved value is null",
            )

    return resolved, state.issues


def format_dependency_feedback(issues: Sequence[DependencyIssue]) -> str:
    """Build concise corrective feedback for the reasoning model."""

    lines = ["Your tool arguments contain unresolved dependency references:"]
    for issue in issues:
        lines.append(f"- `{issue.reference}`: {issue.message}")
    lines.append(
        "Use a literal identifier from a successful result, or call the tool "
        "that retrieves it first. Do not guess identifiers."
    )
    return "\n".join(lines)


def _resolve_value(
    value: Any,
    property_schema: Mapping[str, Any] | None,
    state: _ResolutionState,
    *,
    depth: int,
) -> Any:
    """Recursively resolve references while preserving literal values."""

    if isinstance(value, str):
        if not value.startswith(_REFERENCE_PREFIX):
            return value
        return _resolve_reference(value, property_schema, state)

    if isinstance(value, Mapping):
        if depth >= _MAX_NESTING_DEPTH:
            return dict(value)
        child_properties = _child_properties(property_schema)
        result: dict[Any, Any] = {}
        for key, child_value in value.items():
            child_schema = None
            if isinstance(key, str) and child_properties is not None:
                candidate = child_properties.get(key)
                if isinstance(candidate, Mapping):
                    child_schema = candidate
            resolved_child = _resolve_value(
                child_value,
                child_schema,
                state,
                depth=depth + 1,
            )
            if resolved_child is _UNRESOLVED:
                continue
            result[key] = resolved_child
        return result

    if isinstance(value, (list, tuple)):
        if depth >= _MAX_NESTING_DEPTH:
            return list(value)
        item_schema = _item_schema(property_schema)
        result_list: list[Any] = []
        for item in value:
            resolved_item = _resolve_value(
                item,
                item_schema,
                state,
                depth=depth + 1,
            )
            if resolved_item is _UNRESOLVED:
                continue
            result_list.append(resolved_item)
        return result_list

    return value


def _child_properties(
    property_schema: Mapping[str, Any] | None,
) -> Mapping[str, Any] | None:
    if not isinstance(property_schema, Mapping):
        return None
    if property_schema.get("type") != "object":
        return None
    properties = property_schema.get("properties")
    return properties if isinstance(properties, Mapping) else None


def _item_schema(
    property_schema: Mapping[str, Any] | None,
) -> Mapping[str, Any] | None:
    if not isinstance(property_schema, Mapping):
        return None
    if property_schema.get("type") != "array":
        return None
    items = property_schema.get("items")
    return items if isinstance(items, Mapping) else None


def _resolve_reference(
    reference: str,
    property_schema: Mapping[str, Any] | None,
    state: _ResolutionState,
) -> Any:
    if len(reference) > _MAX_REFERENCE_LENGTH:
        return _add_issue(
            state,
            reference,
            "reference_too_long",
            f"references must be at most {_MAX_REFERENCE_LENGTH} characters",
        )

    match = _STEP_REFERENCE_PATTERN.match(reference)
    if match is None:
        return _add_issue(
            state,
            reference,
            "invalid_reference",
            "use the form '$steps.step_<N>.<path>' with safe keys and "
            "non-negative array indices",
        )

    segments = _parse_path(match.group("path"))
    if segments is None or len(segments) > _MAX_PATH_SEGMENTS:
        return _add_issue(
            state,
            reference,
            "invalid_path",
            f"paths may contain at most {_MAX_PATH_SEGMENTS} segments",
        )

    state.reference_count += 1
    if state.reference_count > _MAX_REFERENCES_PER_CALL:
        return _add_issue(
            state,
            reference,
            "too_many_references",
            f"at most {_MAX_REFERENCES_PER_CALL} references are allowed per "
            "tool call",
        )

    step_number = int(match.group("step"))
    if step_number > len(state.steps):
        return _add_issue(
            state,
            reference,
            "unknown_step",
            f"step_{step_number} has not been recorded; only "
            f"{len(state.steps)} tool execution(s) have occurred",
        )

    step = state.steps[step_number - 1]
    if (
        step.status != ToolExecutionStatus.SUCCEEDED.value
        or step.output is None
    ):
        return _add_issue(
            state,
            reference,
            "step_not_successful",
            f"step_{step_number} did not succeed and cannot be referenced",
        )

    resolved, path_error = _read_path(step.output, segments)
    if path_error is not None:
        code, message = path_error
        return _add_issue(state, reference, code, message)

    type_error = _check_resolved_type(resolved, property_schema)
    if type_error is not None:
        return _add_issue(state, reference, "type_mismatch", type_error)

    return resolved


def _parse_path(path: str) -> list[str | int] | None:
    """Parse ``.key`` and ``[index]`` segments into safe lookup operations."""

    segments: list[str | int] = []
    index = 0
    while index < len(path):
        char = path[index]
        if char == ".":
            end = index + 1
            while end < len(path) and (
                path[end].isalnum() or path[end] == "_"
            ):
                end += 1
            if end == index + 1:
                return None
            key = path[index + 1 : end]
            if not key or key.startswith("_"):
                return None
            segments.append(key)
            index = end
        elif char == "[":
            end = path.find("]", index + 1)
            if end == -1:
                return None
            digits = path[index + 1 : end]
            if not digits.isdigit() or len(digits) > 3:
                return None
            segments.append(int(digits))
            index = end + 1
        else:
            return None

    return segments or None


def _read_path(
    value: Any,
    segments: Sequence[str | int],
) -> tuple[Any, tuple[str, str] | None]:
    current = value
    for segment in segments:
        if isinstance(segment, int):
            if not isinstance(current, (list, tuple)):
                return _UNRESOLVED, (
                    "path_not_found",
                    f"cannot use index [{segment}] on a non-array value",
                )
            if segment >= len(current):
                return _UNRESOLVED, (
                    "index_out_of_range",
                    f"index [{segment}] is out of range "
                    f"(length {len(current)})",
                )
            current = current[segment]
            continue

        if not isinstance(current, Mapping):
            return _UNRESOLVED, (
                "path_not_found",
                f"cannot read key '{segment}' from a non-object value",
            )
        if segment not in current:
            return _UNRESOLVED, (
                "path_not_found",
                f"key '{segment}' is not present in the step output",
            )
        current = current[segment]

    return current, None


def _check_resolved_type(
    value: Any,
    property_schema: Mapping[str, Any] | None,
) -> str | None:
    """Check a resolved value against the destination argument schema."""

    if not isinstance(property_schema, Mapping):
        return None

    expected = property_schema.get("type")
    if expected is None:
        return None

    if expected == "string":
        if isinstance(value, str):
            return None
        if isinstance(value, int) and not isinstance(value, bool):
            return None
        return "resolved value must be a string"

    if expected == "integer":
        if isinstance(value, bool):
            return "resolved value must be an integer"
        if isinstance(value, int):
            return None
        if isinstance(value, str) and _INTEGER_TEXT_PATTERN.match(
            value.strip()
        ):
            return None
        return "resolved value must be an integer"

    if expected == "number":
        if isinstance(value, bool):
            return "resolved value must be a number"
        if isinstance(value, (int, float)):
            return None
        if isinstance(value, str):
            try:
                float(value.strip())
            except ValueError:
                return "resolved value must be a number"
            return None
        return "resolved value must be a number"

    if expected == "boolean":
        if isinstance(value, bool):
            return None
        return "resolved value must be a boolean"

    if expected == "array":
        if isinstance(value, list):
            return None
        return "resolved value must be an array"

    if expected == "object":
        if isinstance(value, Mapping):
            return None
        return "resolved value must be an object"

    if expected == "null":
        if value is None:
            return None
        return "resolved value must be null"

    return None


def _add_issue(
    state: _ResolutionState,
    reference: str,
    code: str,
    message: str,
) -> Any:
    if len(state.issues) < _MAX_REPORTED_ISSUES:
        state.issues.append(
            DependencyIssue(
                reference=reference,
                code=code,
                message=message,
            )
        )
    return _UNRESOLVED


__all__ = [
    "DependencyIssue",
    "DependencyStep",
    "format_dependency_feedback",
    "resolve_argument_dependencies",
]
