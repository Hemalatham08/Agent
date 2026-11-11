import json
import unittest
from copy import deepcopy

from pydantic import ValidationError

from backend.agent.tools import (
    InvalidToolSchemaError,
    ToolArgumentIssue,
    validate_arguments,
)


def object_schema(
    properties: dict | None = None,
    *,
    required: list[str] | None = None,
    additional_properties: object = ...,
) -> dict:
    schema: dict[str, object] = {"type": "object"}
    if properties is not None:
        schema["properties"] = properties
    if required is not None:
        schema["required"] = required
    if additional_properties is not ...:
        schema["additionalProperties"] = additional_properties
    return schema


class ToolArgumentValidationTests(unittest.TestCase):
    def test_valid_arguments_return_no_issues(self) -> None:
        schema = object_schema(
            {"sku": {"type": "string"}},
            required=["sku"],
            additional_properties=False,
        )

        self.assertEqual(validate_arguments({"sku": "ABC-1"}, schema), [])

    def test_optional_properties_may_be_omitted(self) -> None:
        schema = object_schema(
            {
                "sku": {"type": "string"},
                "note": {"type": "string"},
            },
            required=["sku"],
            additional_properties=False,
        )

        self.assertEqual(validate_arguments({"sku": "ABC-1"}, schema), [])

    def test_missing_required_properties_are_reported(self) -> None:
        schema = object_schema(
            {
                "sku": {"type": "string"},
                "warehouse": {"type": "string"},
            },
            required=["sku", "warehouse"],
            additional_properties=False,
        )

        issues = validate_arguments({}, schema)

        self.assertEqual(
            [(issue.path, issue.keyword) for issue in issues],
            [("sku", "required"), ("warehouse", "required")],
        )

    def test_additional_properties_false_rejects_undeclared_arguments(
        self,
    ) -> None:
        schema = object_schema(
            {"sku": {"type": "string"}},
            required=["sku"],
            additional_properties=False,
        )

        issues = validate_arguments(
            {"sku": "ABC-1", "extra": 1},
            schema,
        )

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].path, "extra")
        self.assertEqual(issues[0].keyword, "additionalProperties")

    def test_additional_properties_true_or_omitted_allows_extra(
        self,
    ) -> None:
        for additional in (True, ...):
            with self.subTest(additional=additional):
                schema = object_schema(
                    {"sku": {"type": "string"}},
                    additional_properties=additional,
                )
                self.assertEqual(
                    validate_arguments(
                        {"sku": "ABC-1", "extra": 1},
                        schema,
                    ),
                    [],
                )

    def test_empty_object_schema(self) -> None:
        schema = object_schema()

        self.assertEqual(validate_arguments({}, schema), [])
        self.assertEqual(
            validate_arguments({"extra": 1}, schema),
            [],
        )

    def test_empty_object_schema_with_additional_false(self) -> None:
        schema = object_schema(additional_properties=False)

        issues = validate_arguments({"extra": 1}, schema)

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].path, "extra")

    def test_basic_json_types_accept_matching_values(self) -> None:
        cases = [
            ("string", "value"),
            ("integer", 3),
            ("number", 3),
            ("number", 3.5),
            ("boolean", True),
            ("array", [1, 2]),
            ("object", {"nested": 1}),
            ("null", None),
        ]
        for expected_type, value in cases:
            with self.subTest(expected_type=expected_type, value=value):
                schema = object_schema(
                    {"value": {"type": expected_type}},
                )
                self.assertEqual(
                    validate_arguments({"value": value}, schema),
                    [],
                )

    def test_basic_json_types_reject_mismatched_values(self) -> None:
        cases = [
            ("string", 1),
            ("integer", "1"),
            ("integer", 1.5),
            ("number", "1"),
            ("boolean", 1),
            ("array", {"0": 1}),
            ("object", [1]),
            ("null", False),
        ]
        for expected_type, value in cases:
            with self.subTest(expected_type=expected_type, value=value):
                schema = object_schema(
                    {"value": {"type": expected_type}},
                )
                issues = validate_arguments({"value": value}, schema)
                self.assertEqual(len(issues), 1)
                self.assertEqual(issues[0].keyword, "type")

    def test_integer_and_number_exclude_booleans(self) -> None:
        for expected_type in ("integer", "number"):
            with self.subTest(expected_type=expected_type):
                schema = object_schema(
                    {"value": {"type": expected_type}},
                )
                issues = validate_arguments({"value": True}, schema)
                self.assertEqual(len(issues), 1)
                self.assertEqual(issues[0].keyword, "type")

    def test_number_rejects_non_finite_values(self) -> None:
        schema = object_schema({"value": {"type": "number"}})

        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                issues = validate_arguments({"value": value}, schema)
                self.assertEqual(len(issues), 1)
                self.assertEqual(issues[0].keyword, "type")

    def test_enum_accepts_allowed_values(self) -> None:
        schema = object_schema(
            {"status": {"type": "string", "enum": ["open", "closed"]}},
        )

        self.assertEqual(
            validate_arguments({"status": "open"}, schema),
            [],
        )

    def test_enum_rejects_disallowed_values(self) -> None:
        schema = object_schema(
            {"status": {"type": "string", "enum": ["open", "closed"]}},
        )

        issues = validate_arguments({"status": "pending"}, schema)

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].keyword, "enum")

    def test_enum_distinguishes_booleans_from_integers(self) -> None:
        schema = object_schema({"value": {"enum": [True]}})

        self.assertEqual(validate_arguments({"value": True}, schema), [])
        issues = validate_arguments({"value": 1}, schema)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].keyword, "enum")

    def test_enum_supports_json_structures(self) -> None:
        schema = object_schema(
            {"value": {"enum": [{"a": [1, 2]}, ["x"]]}},
        )

        self.assertEqual(
            validate_arguments({"value": {"a": [1, 2]}}, schema),
            [],
        )
        issues = validate_arguments({"value": {"a": [2, 1]}}, schema)
        self.assertEqual(len(issues), 1)

    def test_multiple_independent_issues_are_reported(self) -> None:
        schema = object_schema(
            {
                "sku": {"type": "string"},
                "count": {"type": "integer"},
            },
            required=["sku"],
            additional_properties=False,
        )

        issues = validate_arguments(
            {"count": "many", "extra": True},
            schema,
        )

        self.assertEqual(
            {(issue.path, issue.keyword) for issue in issues},
            {
                ("sku", "required"),
                ("count", "type"),
                ("extra", "additionalProperties"),
            },
        )

    def test_issue_messages_do_not_expose_argument_values(self) -> None:
        secret = "SECRET-VALUE-123"
        schema = object_schema(
            {"count": {"type": "integer", "enum": [1, 2]}},
            required=["count"],
            additional_properties=False,
        )

        issues = validate_arguments({"count": secret, "extra": secret}, schema)

        rendered = json.dumps(
            [issue.model_dump(mode="json") for issue in issues]
        )
        self.assertNotIn(secret, rendered)
        for issue in issues:
            self.assertNotIn(secret, issue.message)
            self.assertNotIn(secret, issue.path)

    def test_unsupported_keywords_are_not_enforced(self) -> None:
        schema = {
            "type": "object",
            "description": "ignored",
            "properties": {
                "name": {
                    "type": "string",
                    "minLength": 10,
                    "pattern": "^[A-Z]+$",
                    "format": "email",
                }
            },
        }

        self.assertEqual(validate_arguments({"name": "x"}, schema), [])

    def test_arguments_and_schema_are_not_mutated(self) -> None:
        schema = object_schema(
            {"sku": {"type": "string"}},
            required=["sku"],
            additional_properties=False,
        )
        arguments = {"sku": "ABC-1", "extra": {"nested": [1]}}
        original_arguments = deepcopy(arguments)
        original_schema = deepcopy(schema)

        validate_arguments(arguments, schema)

        self.assertEqual(arguments, original_arguments)
        self.assertEqual(schema, original_schema)

    def test_issue_is_frozen_and_json_serializable(self) -> None:
        issue = ToolArgumentIssue(
            path="sku",
            keyword="required",
            message="missing required argument: sku",
        )

        with self.assertRaises(ValidationError):
            issue.message = "changed"

        payload = json.loads(issue.model_dump_json())
        self.assertEqual(
            payload,
            {
                "path": "sku",
                "keyword": "required",
                "message": "missing required argument: sku",
            },
        )

    def test_arguments_must_be_a_mapping(self) -> None:
        schema = object_schema()

        with self.assertRaises(TypeError):
            validate_arguments(["sku"], schema)


class InvalidToolSchemaTests(unittest.TestCase):
    def test_invalid_schema_structures_raise_safely(self) -> None:
        cases = [
            ("not-an-object", []),
            ("missing-type", {"properties": {}}),
            ("wrong-type", {"type": "array"}),
            (
                "properties-not-object",
                {"type": "object", "properties": []},
            ),
            (
                "property-not-object",
                {"type": "object", "properties": {"a": "string"}},
            ),
            (
                "property-name-not-string",
                {"type": "object", "properties": {1: {"type": "string"}}},
            ),
            (
                "required-not-list",
                {
                    "type": "object",
                    "properties": {"a": {}},
                    "required": "a",
                },
            ),
            (
                "required-blank",
                {
                    "type": "object",
                    "properties": {"a": {}},
                    "required": [" "],
                },
            ),
            (
                "required-non-string",
                {
                    "type": "object",
                    "properties": {"a": {}},
                    "required": [1],
                },
            ),
            (
                "required-duplicate",
                {
                    "type": "object",
                    "properties": {"a": {}},
                    "required": ["a", "a"],
                },
            ),
            (
                "required-without-properties",
                {"type": "object", "required": ["a"]},
            ),
            (
                "required-unknown",
                {
                    "type": "object",
                    "properties": {"a": {}},
                    "required": ["b"],
                },
            ),
            (
                "additional-not-boolean",
                {"type": "object", "additionalProperties": {}},
            ),
            (
                "unknown-type",
                {
                    "type": "object",
                    "properties": {"a": {"type": "date"}},
                },
            ),
            (
                "type-list",
                {
                    "type": "object",
                    "properties": {"a": {"type": ["string", "null"]}},
                },
            ),
            (
                "enum-not-list",
                {
                    "type": "object",
                    "properties": {"a": {"enum": "x"}},
                },
            ),
            (
                "enum-non-json",
                {
                    "type": "object",
                    "properties": {"a": {"enum": [object()]}},
                },
            ),
        ]

        for label, schema in cases:
            with self.subTest(label=label):
                with self.assertRaises(InvalidToolSchemaError):
                    validate_arguments({}, schema)

    def test_malformed_schema_is_not_treated_as_unrestricted(self) -> None:
        schema = {"type": "object", "properties": []}

        with self.assertRaises(InvalidToolSchemaError):
            validate_arguments({"anything": "goes"}, schema)

    def test_nested_object_schemas_are_rejected(self) -> None:
        cases = [
            {
                "type": "object",
                "properties": {
                    "nested": {
                        "type": "object",
                        "properties": {"value": {"type": "string"}},
                    }
                },
            },
            {
                "type": "object",
                "properties": {
                    "nested": {
                        "type": "object",
                        "additionalProperties": False,
                    }
                },
            },
            {
                "type": "object",
                "properties": {
                    "nested": {
                        "type": "object",
                        "required": ["value"],
                    }
                },
            },
        ]

        for schema in cases:
            with self.subTest(schema=schema):
                with self.assertRaises(InvalidToolSchemaError):
                    validate_arguments({}, schema)

    def test_schema_error_does_not_expose_arguments(self) -> None:
        secret = "SECRET-SCHEMA-VALUE"
        schema = {"type": "object", "properties": []}

        with self.assertRaises(InvalidToolSchemaError) as context:
            validate_arguments({"value": secret}, schema)

        self.assertNotIn(secret, str(context.exception))


if __name__ == "__main__":
    unittest.main()
