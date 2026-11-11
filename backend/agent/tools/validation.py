"""Validate tool arguments against a deliberately small JSON Schema subset.

Supported keywords
------------------
* ``type`` with the basic JSON types ``string``, ``integer``, ``number``,
  ``boolean``, ``array``, ``object``, and ``null``.
* ``properties`` for top-level object properties.
* ``required`` for top-level required property names.
* ``additionalProperties`` as a boolean. ``false`` rejects undeclared
  properties; ``true`` (or omission) allows them.
* ``enum`` on top-level property schemas.

Unsupported JSON Schema features are intentionally not implemented. Keywords
such as ``items``, ``minLength``, ``pattern``, ``format``, ``minimum``,
``maximum``, ``oneOf``, ``anyOf``, ``allOf``, ``$ref``, and nested object
schemas are ignored or rejected rather than treated as fully enforced. This
module does not claim full JSON Schema support.
"""

from __future__ import annotations

import json
import math
from typing import Any, Mapping

from pydantic import (
    BaseModel,
    ConfigDict,
    JsonValue,
    TypeAdapter,
    ValidationError,
)

from backend.agent.tools.errors import InvalidToolSchemaError

_MISSING = object()

_JSON_TYPES = frozenset(
    {
        "array",
        "boolean",
        "integer",
        "null",
        "number",
        "object",
        "string",
    }
)

_NESTED_SCHEMA_KEYWORDS = frozenset(
    {"additionalProperties", "properties", "required"}
)

_JSON_VALUE_ADAPTER = TypeAdapter(JsonValue)


class ToolArgumentIssue(BaseModel):
    """Describe one argument-validation failure without exposing its value."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str
    message: str
    keyword: str = "validation"


def validate_arguments(
    arguments: Mapping[str, Any],
    schema: Mapping[str, Any],
) -> list[ToolArgumentIssue]:
    """Return argument issues for ``arguments`` against ``schema``.

    An empty list means the arguments are valid. A malformed schema raises
    :class:`InvalidToolSchemaError`; it is never treated as an unrestricted
    schema. Issue messages contain property names and constraint keywords, but
    never argument values.
    """

    _validate_schema(schema)

    if not isinstance(arguments, Mapping):
        raise TypeError("arguments must be a mapping")

    properties = schema.get("properties", _MISSING)
    if properties is _MISSING:
        properties = {}
    required = schema.get("required", _MISSING)
    if required is _MISSING:
        required = []

    issues: list[ToolArgumentIssue] = []

    for name in required:
        if name not in arguments:
            issues.append(
                ToolArgumentIssue(
                    path=name,
                    keyword="required",
                    message=f"missing required argument: {name}",
                )
            )

    for name, property_schema in properties.items():
        if name not in arguments:
            continue

        value = arguments[name]
        expected_type = property_schema.get("type", _MISSING)
        if expected_type is not _MISSING and not _matches_type(
            value, expected_type
        ):
            issues.append(
                ToolArgumentIssue(
                    path=name,
                    keyword="type",
                    message=(
                        f"argument '{name}' must be of type "
                        f"'{expected_type}'"
                    ),
                )
            )
            continue

        allowed_values = property_schema.get("enum", _MISSING)
        if allowed_values is not _MISSING and not any(
            _json_equal(value, allowed) for allowed in allowed_values
        ):
            issues.append(
                ToolArgumentIssue(
                    path=name,
                    keyword="enum",
                    message=f"argument '{name}' is not an allowed value",
                )
            )

    if schema.get("additionalProperties", _MISSING) is False:
        for name in arguments:
            if name not in properties:
                issues.append(
                    ToolArgumentIssue(
                        path=str(name),
                        keyword="additionalProperties",
                        message=f"unexpected argument: {name}",
                    )
                )

    return issues


def _validate_schema(schema: Any) -> None:
    if not isinstance(schema, Mapping):
        raise InvalidToolSchemaError("input schema must be an object")

    if schema.get("type", _MISSING) != "object":
        raise InvalidToolSchemaError(
            "input schema must declare type='object'"
        )

    properties = schema.get("properties", _MISSING)
    if properties is not _MISSING:
        if not isinstance(properties, Mapping):
            raise InvalidToolSchemaError(
                "input schema properties must be an object"
            )
        for name, property_schema in properties.items():
            if not isinstance(name, str):
                raise InvalidToolSchemaError(
                    "input schema property names must be strings"
                )
            if not isinstance(property_schema, Mapping):
                raise InvalidToolSchemaError(
                    "input schema property definitions must be objects"
                )
            _validate_property_schema(name, property_schema)

    required = schema.get("required", _MISSING)
    if required is not _MISSING:
        if not isinstance(required, list):
            raise InvalidToolSchemaError(
                "input schema required must be a list"
            )

        seen: set[str] = set()
        for name in required:
            if not isinstance(name, str) or not name.strip():
                raise InvalidToolSchemaError(
                    "input schema required entries must be nonblank strings"
                )
            if name in seen:
                raise InvalidToolSchemaError(
                    "input schema required entries must be unique"
                )
            seen.add(name)

        if seen:
            if properties is _MISSING:
                raise InvalidToolSchemaError(
                    "input schema required requires properties"
                )
            if not seen.issubset(properties.keys()):
                raise InvalidToolSchemaError(
                    "input schema required entries must exist in properties"
                )

    additional = schema.get("additionalProperties", _MISSING)
    if additional is not _MISSING and not isinstance(additional, bool):
        raise InvalidToolSchemaError(
            "input schema additionalProperties must be a boolean"
        )


def _validate_property_schema(name: str, schema: Mapping[str, Any]) -> None:
    if any(keyword in schema for keyword in _NESTED_SCHEMA_KEYWORDS):
        raise InvalidToolSchemaError(
            f"nested object schemas are not supported for property '{name}'"
        )

    expected_type = schema.get("type", _MISSING)
    if expected_type is not _MISSING:
        if (
            not isinstance(expected_type, str)
            or expected_type not in _JSON_TYPES
        ):
            raise InvalidToolSchemaError(
                f"property '{name}' has an unsupported type"
            )

    allowed_values = schema.get("enum", _MISSING)
    if allowed_values is not _MISSING:
        if not isinstance(allowed_values, list):
            raise InvalidToolSchemaError(
                f"property '{name}' enum must be a list"
            )
        for allowed in allowed_values:
            if not _is_json_compatible(allowed):
                raise InvalidToolSchemaError(
                    f"property '{name}' enum contains a non-JSON value"
                )


def _matches_type(value: Any, expected_type: str) -> bool:
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "number":
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
        )
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "null":
        return value is None
    return False


def _is_json_compatible(value: Any) -> bool:
    try:
        _JSON_VALUE_ADAPTER.validate_python(value, strict=True)
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError, ValidationError):
        return False
    return True


def _json_equal(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return (
            isinstance(left, bool)
            and isinstance(right, bool)
            and left == right
        )

    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return left == right

    if type(left) is not type(right):
        return False

    if isinstance(left, list):
        return len(left) == len(right) and all(
            _json_equal(left_item, right_item)
            for left_item, right_item in zip(left, right)
        )

    if isinstance(left, dict):
        return left.keys() == right.keys() and all(
            _json_equal(left[key], right[key]) for key in left
        )

    return left == right


__all__ = [
    "ToolArgumentIssue",
    "validate_arguments",
]
