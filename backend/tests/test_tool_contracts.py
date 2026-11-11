import json
import unittest
from datetime import timedelta

from pydantic import ValidationError

from backend.agent.models import ErrorCategory, TaskError, utc_now
from backend.agent.tools import (
    TERMINAL_TOOL_EXECUTION_STATUSES,
    ToolDefinition,
    ToolExecutionError,
    ToolExecutionRequest,
    ToolExecutionResult,
    ToolExecutionStatus,
)


def make_definition(**overrides: object) -> ToolDefinition:
    data: dict[str, object] = {
        "name": "inventory_read",
        "description": "Read inventory records.",
        "input_schema": {
            "type": "object",
            "properties": {
                "sku": {"type": "string"},
            },
            "required": ["sku"],
            "additionalProperties": False,
        },
    }
    data.update(overrides)
    return ToolDefinition(**data)


def make_error(**overrides: object) -> ToolExecutionError:
    data: dict[str, object] = {
        "code": "tool_failure",
        "message": "tool failed",
    }
    data.update(overrides)
    return ToolExecutionError(**data)


def make_succeeded_result(**overrides: object) -> ToolExecutionResult:
    started = utc_now()
    data: dict[str, object] = {
        "execution_id": "exec-1",
        "tool_name": "inventory_read",
        "status": ToolExecutionStatus.SUCCEEDED,
        "output": {"rows": 1},
        "started_at": started,
        "finished_at": started + timedelta(milliseconds=5),
        "duration_ms": 5.0,
    }
    data.update(overrides)
    return ToolExecutionResult(**data)


class ToolDefinitionTests(unittest.TestCase):
    def test_valid_definition(self) -> None:
        definition = make_definition(
            version="1.0.0",
            metadata={"owner": "test"},
        )

        self.assertEqual(definition.name, "inventory_read")
        self.assertEqual(definition.version, "1.0.0")
        self.assertEqual(definition.metadata, {"owner": "test"})
        self.assertEqual(definition.input_schema["type"], "object")

    def test_valid_separator_tool_names(self) -> None:
        for name in ("inventory_read", "erp.inventory.read", "tool1"):
            with self.subTest(name=name):
                self.assertEqual(make_definition(name=name).name, name)

    def test_invalid_tool_names_are_rejected(self) -> None:
        for name in (
            "",
            "   ",
            "Inventory_read",
            "1read",
            "_read",
            "read data",
            "read-data",
            "a" * 65,
        ):
            with self.subTest(name=name):
                with self.assertRaises(ValidationError):
                    make_definition(name=name)

    def test_blank_description_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            make_definition(description="   ")

    def test_extra_field_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            make_definition(unexpected=True)

    def test_attribute_assignment_is_rejected(self) -> None:
        definition = make_definition()
        with self.assertRaises(ValidationError):
            definition.name = "other_tool"

    def test_nested_dictionaries_remain_mutable(self) -> None:
        definition = make_definition(
            metadata={"nested": {"count": 1}},
        )
        nested_metadata = definition.metadata["nested"]
        self.assertIsInstance(nested_metadata, dict)
        nested_metadata["count"] = 2
        self.assertEqual(definition.metadata["nested"]["count"], 2)

        properties = definition.input_schema["properties"]
        self.assertIsInstance(properties, dict)
        sku_schema = properties["sku"]
        self.assertIsInstance(sku_schema, dict)
        sku_schema["type"] = "integer"
        self.assertEqual(
            definition.input_schema["properties"]["sku"]["type"],
            "integer",
        )

    def test_default_metadata_is_not_shared(self) -> None:
        first = make_definition()
        second = make_definition()

        self.assertIsNot(first.metadata, second.metadata)
        first.metadata["owner"] = "first"
        self.assertEqual(second.metadata, {})

    def test_empty_schema_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            make_definition(input_schema={})

    def test_schema_type_must_be_object(self) -> None:
        for schema in (
            {"type": "array"},
            {"properties": {"sku": {"type": "string"}}},
        ):
            with self.subTest(schema=schema):
                with self.assertRaises(ValidationError):
                    make_definition(input_schema=schema)

    def test_required_without_properties_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            make_definition(
                input_schema={
                    "type": "object",
                    "required": ["sku"],
                }
            )

    def test_required_must_be_a_list(self) -> None:
        with self.assertRaises(ValidationError):
            make_definition(
                input_schema={
                    "type": "object",
                    "properties": {"sku": {"type": "string"}},
                    "required": "sku",
                }
            )

    def test_required_entries_must_be_nonblank_strings(self) -> None:
        for required in ([""], ["  "], [1], ["sku", None]):
            with self.subTest(required=required):
                with self.assertRaises(ValidationError):
                    make_definition(
                        input_schema={
                            "type": "object",
                            "properties": {"sku": {"type": "string"}},
                            "required": required,
                        }
                    )

    def test_required_entries_must_be_unique(self) -> None:
        with self.assertRaises(ValidationError):
            make_definition(
                input_schema={
                    "type": "object",
                    "properties": {"sku": {"type": "string"}},
                    "required": ["sku", "sku"],
                }
            )

    def test_required_entries_must_exist_in_properties(self) -> None:
        with self.assertRaises(ValidationError):
            make_definition(
                input_schema={
                    "type": "object",
                    "properties": {"sku": {"type": "string"}},
                    "required": ["missing"],
                }
            )

    def test_properties_must_be_an_object(self) -> None:
        with self.assertRaises(ValidationError):
            make_definition(
                input_schema={
                    "type": "object",
                    "properties": [],
                }
            )

    def test_property_schemas_must_be_objects(self) -> None:
        with self.assertRaises(ValidationError):
            make_definition(
                input_schema={
                    "type": "object",
                    "properties": {"sku": "string"},
                }
            )

    def test_additional_properties_must_be_boolean_or_object(self) -> None:
        with self.assertRaises(ValidationError):
            make_definition(
                input_schema={
                    "type": "object",
                    "properties": {"sku": {"type": "string"}},
                    "additionalProperties": [],
                }
            )

    def test_json_round_trip(self) -> None:
        definition = make_definition(
            version="1.0.0",
            metadata={"nested": {"enabled": True, "levels": [1, 2]}},
        )
        restored = ToolDefinition.model_validate_json(
            definition.model_dump_json()
        )

        self.assertEqual(restored, definition)


class ToolExecutionRequestTests(unittest.TestCase):
    def test_defaults(self) -> None:
        request = ToolExecutionRequest(tool_name="inventory_read")

        self.assertTrue(request.execution_id)
        self.assertEqual(request.arguments, {})
        self.assertEqual(request.metadata, {})

    def test_explicit_values(self) -> None:
        request = ToolExecutionRequest(
            execution_id="exec-1",
            tool_name="erp.inventory.read",
            arguments={"sku": "ABC-1"},
            metadata={"request_id": "req-1"},
        )

        self.assertEqual(request.execution_id, "exec-1")
        self.assertEqual(request.arguments, {"sku": "ABC-1"})
        self.assertEqual(request.metadata, {"request_id": "req-1"})

    def test_invalid_tool_name_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            ToolExecutionRequest(tool_name="Inventory_Read")

    def test_arguments_must_be_a_mapping(self) -> None:
        with self.assertRaises(ValidationError):
            ToolExecutionRequest(
                tool_name="inventory_read",
                arguments=["sku"],
            )

    def test_metadata_must_be_json_compatible(self) -> None:
        with self.assertRaises(ValidationError):
            ToolExecutionRequest(
                tool_name="inventory_read",
                metadata={"bad": object()},
            )

    def test_extra_field_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            ToolExecutionRequest(tool_name="inventory_read", unexpected=True)

    def test_frozen_model_has_mutable_nested_arguments(self) -> None:
        request = ToolExecutionRequest(
            tool_name="inventory_read",
            arguments={"filter": {"sku": "ABC-1"}},
        )

        with self.assertRaises(ValidationError):
            request.tool_name = "other_tool"

        nested_filter = request.arguments["filter"]
        self.assertIsInstance(nested_filter, dict)
        nested_filter["sku"] = "ABC-2"
        self.assertEqual(request.arguments["filter"]["sku"], "ABC-2")

    def test_default_containers_are_not_shared(self) -> None:
        first = ToolExecutionRequest(tool_name="inventory_read")
        second = ToolExecutionRequest(tool_name="inventory_read")

        self.assertIsNot(first.arguments, second.arguments)
        self.assertIsNot(first.metadata, second.metadata)
        first.arguments["sku"] = "ABC-1"
        self.assertEqual(second.arguments, {})

    def test_json_round_trip(self) -> None:
        request = ToolExecutionRequest(
            execution_id="exec-1",
            tool_name="inventory_read",
            arguments={"sku": "ABC-1"},
            metadata={"nested": {"attempt": 1}},
        )
        restored = ToolExecutionRequest.model_validate_json(
            request.model_dump_json()
        )

        self.assertEqual(restored, request)


class ToolExecutionErrorTests(unittest.TestCase):
    def test_defaults(self) -> None:
        error = make_error()

        self.assertIsInstance(error, TaskError)
        self.assertEqual(error.category, ErrorCategory.TOOL)
        self.assertEqual(error.details, {})
        self.assertFalse(error.recoverable)
        self.assertFalse(error.retryable)

    def test_validation_category_can_be_selected(self) -> None:
        error = make_error(
            category=ErrorCategory.VALIDATION,
            recoverable=True,
            retryable=False,
        )

        self.assertEqual(error.category, ErrorCategory.VALIDATION)
        self.assertTrue(error.recoverable)

    def test_nested_json_details_round_trip(self) -> None:
        error = make_error(
            details={
                "field": "sku",
                "nested": {"allowed": ["A", "B"], "count": 2},
            }
        )
        restored = ToolExecutionError.model_validate_json(
            error.model_dump_json()
        )

        self.assertEqual(restored, error)
        self.assertEqual(
            json.loads(error.model_dump_json())["category"],
            "tool",
        )

    def test_non_json_details_are_rejected(self) -> None:
        for details in ({"bad": object()}, {"bad": {1, 2}}):
            with self.subTest(details=details):
                with self.assertRaises(ValidationError):
                    make_error(details=details)

    def test_extra_fields_are_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            make_error(traceback="secret internal traceback")

    def test_nested_details_remain_mutable(self) -> None:
        error = make_error(details={"nested": {"count": 1}})
        nested_details = error.details["nested"]
        self.assertIsInstance(nested_details, dict)

        with self.assertRaises(ValidationError):
            error.code = "other_code"

        nested_details["count"] = 2
        self.assertEqual(error.details["nested"]["count"], 2)


class ToolExecutionStatusTests(unittest.TestCase):
    def test_status_values(self) -> None:
        self.assertEqual(
            {status.value for status in ToolExecutionStatus},
            {"pending", "running", "succeeded", "failed", "cancelled"},
        )

    def test_terminal_statuses(self) -> None:
        self.assertEqual(
            TERMINAL_TOOL_EXECUTION_STATUSES,
            {
                ToolExecutionStatus.SUCCEEDED,
                ToolExecutionStatus.FAILED,
                ToolExecutionStatus.CANCELLED,
            },
        )
        for status in TERMINAL_TOOL_EXECUTION_STATUSES:
            with self.subTest(status=status):
                self.assertTrue(status.is_terminal)

    def test_non_terminal_statuses(self) -> None:
        for status in (
            ToolExecutionStatus.PENDING,
            ToolExecutionStatus.RUNNING,
        ):
            with self.subTest(status=status):
                self.assertFalse(status.is_terminal)


class ToolExecutionResultTests(unittest.TestCase):
    def test_pending_result(self) -> None:
        result = ToolExecutionResult(
            execution_id="exec-1",
            tool_name="inventory_read",
            status=ToolExecutionStatus.PENDING,
        )

        self.assertIsNone(result.output)
        self.assertIsNone(result.error)
        self.assertIsNone(result.started_at)
        self.assertIsNone(result.finished_at)
        self.assertIsNone(result.duration_ms)

    def test_pending_result_rejects_terminal_data(self) -> None:
        now = utc_now()
        for overrides in (
            {"output": {"rows": 1}},
            {"error": make_error()},
            {"started_at": now},
            {"finished_at": now},
            {"duration_ms": 1.0},
        ):
            with self.subTest(overrides=overrides):
                with self.assertRaises(ValidationError):
                    ToolExecutionResult(
                        execution_id="exec-1",
                        tool_name="inventory_read",
                        status=ToolExecutionStatus.PENDING,
                        **overrides,
                    )

    def test_running_result(self) -> None:
        result = ToolExecutionResult(
            execution_id="exec-1",
            tool_name="inventory_read",
            status=ToolExecutionStatus.RUNNING,
            started_at=utc_now(),
        )

        self.assertIsNone(result.finished_at)
        self.assertIsNone(result.output)
        self.assertIsNone(result.error)

    def test_running_result_requires_started_at(self) -> None:
        with self.assertRaises(ValidationError):
            ToolExecutionResult(
                execution_id="exec-1",
                tool_name="inventory_read",
                status=ToolExecutionStatus.RUNNING,
            )

    def test_running_result_rejects_terminal_data(self) -> None:
        now = utc_now()
        for overrides in (
            {"output": {"rows": 1}},
            {"error": make_error()},
            {"finished_at": now},
            {"duration_ms": 1.0},
        ):
            with self.subTest(overrides=overrides):
                with self.assertRaises(ValidationError):
                    ToolExecutionResult(
                        execution_id="exec-1",
                        tool_name="inventory_read",
                        status=ToolExecutionStatus.RUNNING,
                        started_at=now,
                        **overrides,
                    )

    def test_succeeded_result(self) -> None:
        result = make_succeeded_result()

        self.assertEqual(result.status, ToolExecutionStatus.SUCCEEDED)
        self.assertEqual(result.output, {"rows": 1})
        self.assertIsNone(result.error)

    def test_succeeded_result_allows_no_output(self) -> None:
        result = make_succeeded_result(output=None)

        self.assertIsNone(result.output)

    def test_succeeded_result_requires_timestamps(self) -> None:
        for overrides in (
            {"started_at": None},
            {"finished_at": None},
        ):
            with self.subTest(overrides=overrides):
                with self.assertRaises(ValidationError):
                    make_succeeded_result(**overrides)

    def test_succeeded_result_rejects_error(self) -> None:
        with self.assertRaises(ValidationError):
            make_succeeded_result(error=make_error())

    def test_failed_result_without_started_at_is_valid(self) -> None:
        result = ToolExecutionResult(
            execution_id="exec-1",
            tool_name="inventory_read",
            status=ToolExecutionStatus.FAILED,
            error=make_error(category=ErrorCategory.VALIDATION),
            finished_at=utc_now(),
        )

        self.assertIsNone(result.started_at)
        self.assertEqual(result.error.category, ErrorCategory.VALIDATION)

    def test_failed_result_requires_error(self) -> None:
        with self.assertRaises(ValidationError):
            ToolExecutionResult(
                execution_id="exec-1",
                tool_name="inventory_read",
                status=ToolExecutionStatus.FAILED,
                finished_at=utc_now(),
            )

    def test_failed_result_requires_finished_at(self) -> None:
        with self.assertRaises(ValidationError):
            ToolExecutionResult(
                execution_id="exec-1",
                tool_name="inventory_read",
                status=ToolExecutionStatus.FAILED,
                error=make_error(),
            )

    def test_failed_result_rejects_output(self) -> None:
        with self.assertRaises(ValidationError):
            ToolExecutionResult(
                execution_id="exec-1",
                tool_name="inventory_read",
                status=ToolExecutionStatus.FAILED,
                output={"rows": 1},
                error=make_error(),
                finished_at=utc_now(),
            )

    def test_cancelled_result(self) -> None:
        result = ToolExecutionResult(
            execution_id="exec-1",
            tool_name="inventory_read",
            status=ToolExecutionStatus.CANCELLED,
            finished_at=utc_now(),
        )

        self.assertIsNone(result.started_at)
        self.assertIsNone(result.output)
        self.assertIsNone(result.error)

    def test_cancelled_result_requires_finished_at(self) -> None:
        with self.assertRaises(ValidationError):
            ToolExecutionResult(
                execution_id="exec-1",
                tool_name="inventory_read",
                status=ToolExecutionStatus.CANCELLED,
            )

    def test_cancelled_result_rejects_output_and_error(self) -> None:
        now = utc_now()
        for overrides in (
            {"output": {"rows": 1}},
            {"error": make_error()},
        ):
            with self.subTest(overrides=overrides):
                with self.assertRaises(ValidationError):
                    ToolExecutionResult(
                        execution_id="exec-1",
                        tool_name="inventory_read",
                        status=ToolExecutionStatus.CANCELLED,
                        finished_at=now,
                        **overrides,
                    )

    def test_finished_at_must_not_precede_started_at(self) -> None:
        now = utc_now()
        with self.assertRaises(ValidationError):
            make_succeeded_result(
                started_at=now,
                finished_at=now - timedelta(milliseconds=1),
            )

    def test_negative_duration_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            make_succeeded_result(duration_ms=-1)

    def test_blank_execution_id_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            make_succeeded_result(execution_id="   ")

    def test_extra_field_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            make_succeeded_result(unexpected=True)

    def test_frozen_model_has_mutable_nested_output(self) -> None:
        result = make_succeeded_result(
            output={"nested": {"rows": 1}},
        )

        with self.assertRaises(ValidationError):
            result.status = ToolExecutionStatus.FAILED

        nested_output = result.output["nested"]
        self.assertIsInstance(nested_output, dict)
        nested_output["rows"] = 2
        self.assertEqual(result.output["nested"]["rows"], 2)

    def test_succeeded_json_round_trip(self) -> None:
        result = make_succeeded_result(
            output={"nested": {"rows": 1}, "names": ["A", "B"]},
        )
        restored = ToolExecutionResult.model_validate_json(
            result.model_dump_json()
        )

        self.assertEqual(restored, result)

    def test_failed_json_round_trip(self) -> None:
        now = utc_now()
        result = ToolExecutionResult(
            execution_id="exec-1",
            tool_name="inventory_read",
            status=ToolExecutionStatus.FAILED,
            error=make_error(
                category=ErrorCategory.TIMEOUT,
                retryable=True,
                details={"nested": {"attempt": 1}},
            ),
            started_at=now,
            finished_at=now + timedelta(milliseconds=5),
            duration_ms=5.0,
        )
        restored = ToolExecutionResult.model_validate_json(
            result.model_dump_json()
        )

        self.assertEqual(restored, result)
        self.assertEqual(
            restored.error.category,
            ErrorCategory.TIMEOUT,
        )


if __name__ == "__main__":
    unittest.main()
