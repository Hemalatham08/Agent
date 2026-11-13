from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from backend.agent.erp.definitions import (
    ERP_TOOL_DEFINITIONS,
    ERP_TOOL_DEFINITIONS_BY_NAME,
    ERP_TOOL_NAMES,
)
from backend.agent.erp.errors import ErpDatabaseError
from backend.agent.erp.handlers import ErpToolHandlers
from backend.agent.erp.registration import register_erp_tools
from backend.agent.erp.service import ErpReadService
from backend.agent.erp.sqlite_adapter import SqliteErpReadAdapter
from backend.agent.models import utc_now
from backend.agent.tools.contracts import ToolExecutionContext
from backend.agent.tools.errors import DuplicateHandlerError, DuplicateToolError
from backend.agent.tools.executor import ToolExecutor
from backend.agent.tools.registry import ToolRegistry
from backend.tests.erp_support import create_erp_fixture_db

_EXPECTED_TOOL_NAMES = (
    "erp.products.search",
    "erp.products.get",
    "erp.products.count",
    "erp.inventory.get",
    "erp.warehouses.list",
    "erp.inventory.low_stock",
    "erp.sales_orders.get",
    "erp.dispatches.get",
    "erp.dispatches.list",
    "erp.dispatches.by_sales_order",
)

_ALLOWED_SCHEMA_KEYS = {
    "type",
    "properties",
    "required",
    "additionalProperties",
}
_ALLOWED_PROPERTY_KEYS = {"type", "enum"}


def make_context(
    tool_name: str,
    *,
    timeout_seconds: float | None = None,
) -> ToolExecutionContext:
    return ToolExecutionContext(
        execution_id="exec-1",
        tool_name=tool_name,
        started_at=utc_now(),
        timeout_seconds=timeout_seconds,
    )


class ErpToolDefinitionTests(unittest.TestCase):
    def test_catalog_contains_exact_mvp_tools(self) -> None:
        self.assertEqual(ERP_TOOL_NAMES, _EXPECTED_TOOL_NAMES)
        self.assertEqual(
            set(ERP_TOOL_DEFINITIONS_BY_NAME),
            set(_EXPECTED_TOOL_NAMES),
        )
        self.assertEqual(
            len(ERP_TOOL_NAMES),
            len(set(ERP_TOOL_NAMES)),
        )

    def test_definitions_are_read_only_and_versioned(self) -> None:
        for definition in ERP_TOOL_DEFINITIONS:
            with self.subTest(tool=definition.name):
                self.assertEqual(definition.version, "1.0.0")
                self.assertEqual(definition.metadata, {"read_only": True})
                self.assertTrue(definition.description.strip())

    def test_schemas_are_strict_objects(self) -> None:
        expected_required = {
            "erp.products.search": set(),
            "erp.products.get": {"product_id"},
            "erp.products.count": set(),
            "erp.inventory.get": {"product_id"},
            "erp.warehouses.list": set(),
            "erp.inventory.low_stock": set(),
            "erp.sales_orders.get": {"so_id"},
            "erp.dispatches.get": {"dispatch_id"},
            "erp.dispatches.list": set(),
            "erp.dispatches.by_sales_order": {"so_id"},
        }
        for definition in ERP_TOOL_DEFINITIONS:
            with self.subTest(tool=definition.name):
                schema = definition.input_schema
                self.assertEqual(schema["type"], "object")
                self.assertIs(schema["additionalProperties"], False)
                self.assertEqual(
                    set(schema.get("required", [])),
                    expected_required[definition.name],
                )

    def test_schemas_use_only_supported_subset(self) -> None:
        for definition in ERP_TOOL_DEFINITIONS:
            with self.subTest(tool=definition.name):
                schema = definition.input_schema
                self.assertLessEqual(set(schema), _ALLOWED_SCHEMA_KEYS)
                for name, property_schema in schema.get(
                    "properties", {}
                ).items():
                    self.assertIsInstance(name, str)
                    self.assertIsInstance(property_schema, dict)
                    self.assertLessEqual(
                        set(property_schema),
                        _ALLOWED_PROPERTY_KEYS,
                    )


class ErpToolRegistrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp_dir.cleanup)
        database_path = create_erp_fixture_db(
            Path(self._temp_dir.name) / "erp.db"
        )
        self.service = ErpReadService(SqliteErpReadAdapter(database_path))
        self.registry = ToolRegistry()
        self.executor = ToolExecutor(self.registry)
        self.addCleanup(self.executor.shutdown)

    def test_registers_every_definition_and_handler(self) -> None:
        registration = register_erp_tools(
            self.registry,
            self.executor,
            self.service,
        )

        self.assertEqual(
            [definition.name for definition in self.registry.list_tools()],
            sorted(_EXPECTED_TOOL_NAMES),
        )
        for name in _EXPECTED_TOOL_NAMES:
            self.assertTrue(self.executor.has_handler(name))

        registration.unregister()
        self.assertEqual(self.registry.list_tools(), [])
        for name in _EXPECTED_TOOL_NAMES:
            self.assertFalse(self.executor.has_handler(name))

    def test_duplicate_registration_does_not_overwrite(self) -> None:
        register_erp_tools(self.registry, self.executor, self.service)

        with self.assertRaises(DuplicateToolError):
            register_erp_tools(self.registry, self.executor, self.service)

        self.assertEqual(len(self.registry.list_tools()), len(_EXPECTED_TOOL_NAMES))
        for name in _EXPECTED_TOOL_NAMES:
            self.assertTrue(self.executor.has_handler(name))

    def test_duplicate_handler_rejects_without_partial_registration(self) -> None:
        def handler(arguments: dict, context: ToolExecutionContext) -> dict:
            return {"ok": True, "data": {}}

        self.executor.register_handler("erp.products.search", handler)

        with self.assertRaises(DuplicateHandlerError):
            register_erp_tools(self.registry, self.executor, self.service)

        self.assertEqual(self.registry.list_tools(), [])
        self.assertFalse(self.executor.has_handler("erp.products.get"))

    def test_duplicate_definition_rejects_without_handlers(self) -> None:
        self.registry.register(ERP_TOOL_DEFINITIONS[0])

        with self.assertRaises(DuplicateToolError):
            register_erp_tools(self.registry, self.executor, self.service)

        for name in _EXPECTED_TOOL_NAMES:
            self.assertFalse(self.executor.has_handler(name))

    def test_unregister_is_idempotent_and_context_manager_cleans_up(self) -> None:
        registration = register_erp_tools(
            self.registry,
            self.executor,
            self.service,
        )
        registration.unregister()
        registration.unregister()
        self.assertEqual(self.registry.list_tools(), [])

        with register_erp_tools(
            self.registry,
            self.executor,
            self.service,
        ):
            self.assertEqual(
                len(self.registry.list_tools()),
                len(_EXPECTED_TOOL_NAMES),
            )

        self.assertEqual(self.registry.list_tools(), [])
        self.assertFalse(self.executor.has_handler("erp.products.search"))


class ErpToolHandlerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp_dir.cleanup)
        database_path = create_erp_fixture_db(
            Path(self._temp_dir.name) / "erp.db"
        )
        self.service = ErpReadService(SqliteErpReadAdapter(database_path))
        self.handlers = ErpToolHandlers(self.service).as_mapping()

    def _invoke(
        self,
        tool_name: str,
        arguments: dict,
    ) -> dict:
        return self.handlers[tool_name](
            arguments,
            make_context(tool_name),
        )

    def _assert_error(self, envelope: dict, code: str) -> None:
        self.assertIs(envelope["ok"], False)
        self.assertEqual(envelope["error"]["code"], code)
        json.dumps(envelope, allow_nan=False)

    def test_search_products_success_envelope(self) -> None:
        envelope = self._invoke(
            "erp.products.search",
            {"query": "M10"},
        )

        self.assertIs(envelope["ok"], True)
        self.assertEqual(
            [item["product_id"] for item in envelope["data"]["items"]],
            ["PRD001", "PRD002"],
        )
        self.assertEqual(envelope["data"]["row_count"], 2)
        self.assertNotIn("purchase_price", envelope["data"]["items"][0])
        self.assertNotIn("selling_price", envelope["data"]["items"][0])

    def test_search_without_query_lists_all_products(self) -> None:
        envelope = self._invoke("erp.products.search", {})

        self.assertIs(envelope["ok"], True)
        self.assertEqual(
            [item["product_id"] for item in envelope["data"]["items"]],
            ["PRD003", "PRD005", "PRD001", "PRD002", "PRD004"],
        )
        self.assertEqual(envelope["data"]["row_count"], 5)
        self.assertIs(envelope["data"]["truncated"], False)

    def test_search_blank_query_lists_all_products(self) -> None:
        envelope = self._invoke("erp.products.search", {"query": "   "})

        self.assertIs(envelope["ok"], True)
        self.assertEqual(envelope["data"]["row_count"], 5)
        self.assertIs(envelope["data"]["truncated"], False)

    def test_search_without_query_applies_limit(self) -> None:
        envelope = self._invoke("erp.products.search", {"limit": 2})

        self.assertIs(envelope["ok"], True)
        self.assertEqual(envelope["data"]["row_count"], 2)
        self.assertIs(envelope["data"]["truncated"], True)

    def test_product_detail_success_envelope(self) -> None:
        envelope = self._invoke(
            "erp.products.get",
            {"product_id": "PRD001"},
        )

        self.assertIs(envelope["ok"], True)
        self.assertEqual(envelope["data"]["product_id"], "PRD001")
        self.assertEqual(envelope["data"]["reorder_level"], 500)

    def test_product_count_success_envelope(self) -> None:
        envelope = self._invoke("erp.products.count", {})

        self.assertIs(envelope["ok"], True)
        self.assertEqual(envelope["data"], {"product_count": 5})

    def test_inventory_success_envelope(self) -> None:
        envelope = self._invoke(
            "erp.inventory.get",
            {"product_id": "PRD001"},
        )

        self.assertIs(envelope["ok"], True)
        self.assertEqual(envelope["data"]["row_count"], 2)
        self.assertEqual(
            [item["warehouse_id"] for item in envelope["data"]["items"]],
            ["WH001", "WH002"],
        )
        self.assertIn("free_stock", envelope["data"]["items"][0])

    def test_warehouse_list_success_envelope(self) -> None:
        envelope = self._invoke("erp.warehouses.list", {})

        self.assertIs(envelope["ok"], True)
        self.assertEqual(envelope["data"]["row_count"], 2)
        self.assertEqual(
            [item["warehouse_id"] for item in envelope["data"]["items"]],
            ["WH001", "WH002"],
        )

    def test_low_stock_success_envelope(self) -> None:
        envelope = self._invoke(
            "erp.inventory.low_stock",
            {"limit": 10},
        )

        self.assertIs(envelope["ok"], True)
        self.assertGreater(envelope["data"]["row_count"], 0)
        for item in envelope["data"]["items"]:
            self.assertTrue(item["low_stock"])
            self.assertIn("free_stock", item)
            self.assertIn("reorder_level", item)

    def test_sales_order_success_envelope_excludes_financial_fields(self) -> None:
        envelope = self._invoke(
            "erp.sales_orders.get",
            {"so_id": "SO001"},
        )

        self.assertIs(envelope["ok"], True)
        self.assertEqual(envelope["data"]["order"]["so_id"], "SO001")
        self.assertEqual(envelope["data"]["items_row_count"], 2)
        for item in envelope["data"]["items"]:
            self.assertNotIn("unit_price", item)
            self.assertNotIn("line_total", item)

    def test_dispatch_detail_success_envelope(self) -> None:
        envelope = self._invoke(
            "erp.dispatches.get",
            {"dispatch_id": "DSP001"},
        )

        self.assertIs(envelope["ok"], True)
        self.assertEqual(envelope["data"]["dispatch_id"], "DSP001")
        self.assertEqual(envelope["data"]["so_id"], "SO001")
        self.assertEqual(envelope["data"]["status"], "Partially Dispatched")
        self.assertEqual(envelope["data"]["carrier"], "BlueDart")
        self.assertEqual(envelope["data"]["tracking_number"], "BD10001")
        self.assertEqual(envelope["data"]["items_row_count"], 2)
        for item in envelope["data"]["items"]:
            self.assertIn("dispatched_qty", item)
            self.assertIn("picked_qty", item)
            self.assertNotIn("unit_price", item)
            self.assertNotIn("selling_price", item)

    def test_dispatch_list_success_envelope_with_filters(self) -> None:
        envelope = self._invoke(
            "erp.dispatches.list",
            {"status": "Dispatched", "limit": 20},
        )

        self.assertIs(envelope["ok"], True)
        self.assertEqual(envelope["data"]["row_count"], 1)
        self.assertEqual(envelope["data"]["items"][0]["dispatch_id"], "DSP002")
        self.assertNotIn("items", envelope["data"]["items"][0])

    def test_dispatch_list_default_limit_and_ordering(self) -> None:
        envelope = self._invoke("erp.dispatches.list", {})

        self.assertIs(envelope["ok"], True)
        self.assertEqual(envelope["data"]["row_count"], 2)
        self.assertEqual(
            [item["dispatch_id"] for item in envelope["data"]["items"]],
            ["DSP002", "DSP001"],
        )

    def test_dispatches_by_sales_order_success_envelope(self) -> None:
        envelope = self._invoke(
            "erp.dispatches.by_sales_order",
            {"so_id": "SO001"},
        )

        self.assertIs(envelope["ok"], True)
        self.assertEqual(envelope["data"]["so_id"], "SO001")
        self.assertEqual(envelope["data"]["dispatches_row_count"], 1)
        dispatch = envelope["data"]["dispatches"][0]
        self.assertEqual(dispatch["dispatch_id"], "DSP001")
        self.assertEqual(dispatch["items_row_count"], 2)
        quantities = {
            item["dispatch_item_id"]: item["dispatched_qty"]
            for item in dispatch["items"]
        }
        self.assertEqual(quantities["DI001"], 100)
        self.assertEqual(quantities["DI002"], 40)

    def test_empty_search_is_successful(self) -> None:
        envelope = self._invoke(
            "erp.products.search",
            {"query": "no-such-product"},
        )

        self.assertIs(envelope["ok"], True)
        self.assertEqual(envelope["data"]["items"], [])
        self.assertEqual(envelope["data"]["row_count"], 0)

    def test_missing_product_is_typed_not_found(self) -> None:
        for tool_name, arguments in (
            ("erp.products.get", {"product_id": "UNKNOWN"}),
            ("erp.inventory.get", {"product_id": "UNKNOWN"}),
        ):
            with self.subTest(tool=tool_name):
                envelope = self._invoke(tool_name, arguments)
                self._assert_error(envelope, "erp_not_found")
                self.assertEqual(
                    envelope["error"]["category"],
                    "not_found",
                )

    def test_missing_sales_order_is_typed_not_found(self) -> None:
        envelope = self._invoke(
            "erp.sales_orders.get",
            {"so_id": "UNKNOWN"},
        )
        self._assert_error(envelope, "erp_not_found")

    def test_missing_dispatch_is_typed_not_found(self) -> None:
        envelope = self._invoke(
            "erp.dispatches.get",
            {"dispatch_id": "DSP999"},
        )
        self._assert_error(envelope, "erp_not_found")
        self.assertEqual(
            envelope["error"]["details"]["resource"],
            "dispatch",
        )

    def test_dispatches_by_sales_order_missing_order_is_typed_not_found(self) -> None:
        envelope = self._invoke(
            "erp.dispatches.by_sales_order",
            {"so_id": "UNKNOWN"},
        )
        self._assert_error(envelope, "erp_not_found")
        self.assertEqual(
            envelope["error"]["details"]["resource"],
            "sales_order",
        )

    def test_missing_warehouse_is_typed_not_found(self) -> None:
        for tool_name, arguments in (
            (
                "erp.inventory.get",
                {"product_id": "PRD001", "warehouse_id": "UNKNOWN"},
            ),
            (
                "erp.inventory.low_stock",
                {"warehouse_id": "UNKNOWN"},
            ),
        ):
            with self.subTest(tool=tool_name):
                envelope = self._invoke(tool_name, arguments)
                self._assert_error(envelope, "erp_not_found")
                self.assertEqual(
                    envelope["error"]["details"]["resource"],
                    "warehouse",
                )

    def test_invalid_arguments_are_rejected(self) -> None:
        cases = (
            ("erp.products.search", {"query": 123}),
            ("erp.products.search", {"limit": 0}),
            ("erp.products.search", {"limit": 51}),
            ("erp.products.search", {"limit": True}),
            ("erp.products.get", {"product_id": ""}),
            ("erp.inventory.get", {"product_id": "PRD001", "limit": 1}),
            ("erp.warehouses.list", {"limit": 1}),
            ("erp.inventory.low_stock", {"limit": 51}),
            ("erp.sales_orders.get", {"so_id": " "}),
            ("erp.dispatches.get", {"dispatch_id": "  "}),
            ("erp.dispatches.get", {}),
            ("erp.dispatches.list", {"limit": 0}),
            ("erp.dispatches.list", {"limit": 51}),
            ("erp.dispatches.list", {"limit": True}),
            ("erp.dispatches.list", {"status": " "}),
            ("erp.dispatches.list", {"so_id": ""}),
            ("erp.dispatches.list", {"carrier": "   "}),
            ("erp.dispatches.by_sales_order", {"so_id": ""}),
            ("erp.dispatches.by_sales_order", {}),
        )
        for tool_name, arguments in cases:
            with self.subTest(tool=tool_name, arguments=arguments):
                envelope = self._invoke(tool_name, arguments)
                self._assert_error(envelope, "erp_invalid_arguments")

    def test_unknown_dispatch_filter_is_rejected(self) -> None:
        envelope = self._invoke(
            "erp.dispatches.list",
            {"dispatch_date": "2026-10-04"},
        )
        self._assert_error(envelope, "erp_invalid_arguments")

    def test_sql_input_is_rejected_as_unknown_argument(self) -> None:
        envelope = self._invoke(
            "erp.products.search",
            {
                "query": "M10",
                "sql": "SELECT * FROM products",
            },
        )
        self._assert_error(envelope, "erp_invalid_arguments")

    def test_sql_text_in_dispatch_filter_is_treated_as_literal(self) -> None:
        envelope = self._invoke(
            "erp.dispatches.list",
            {"status": "' OR 1=1 --"},
        )

        self.assertIs(envelope["ok"], True)
        self.assertEqual(envelope["data"]["row_count"], 0)

    def test_sql_injection_text_is_treated_as_literal_search(self) -> None:
        envelope = self._invoke(
            "erp.products.search",
            {"query": "' OR 1=1 --"},
        )

        self.assertIs(envelope["ok"], True)
        self.assertEqual(envelope["data"]["items"], [])

    def test_handler_output_is_json_serializable(self) -> None:
        for tool_name, arguments in (
            ("erp.products.search", {"query": "M10"}),
            ("erp.products.get", {"product_id": "PRD001"}),
            ("erp.products.count", {}),
            ("erp.inventory.get", {"product_id": "PRD001"}),
            ("erp.warehouses.list", {}),
            ("erp.inventory.low_stock", {}),
            ("erp.sales_orders.get", {"so_id": "SO001"}),
            ("erp.dispatches.get", {"dispatch_id": "DSP001"}),
            ("erp.dispatches.list", {}),
            ("erp.dispatches.by_sales_order", {"so_id": "SO001"}),
        ):
            with self.subTest(tool=tool_name):
                envelope = self._invoke(tool_name, arguments)
                json.dumps(envelope, allow_nan=False)

    def test_unexpected_service_failure_is_sanitized(self) -> None:
        class ExplodingService:
            def get_product(self, *_args: object, **_kwargs: object) -> None:
                raise RuntimeError("secret /tmp/erp.db")

        handlers = ErpToolHandlers(ExplodingService())  # type: ignore[arg-type]
        envelope = handlers.get_product(
            {"product_id": "PRD001"},
            make_context("erp.products.get"),
        )

        self._assert_error(envelope, "erp_internal_error")
        self.assertNotIn("secret", json.dumps(envelope))

    def test_dispatch_unexpected_service_failure_is_sanitized(self) -> None:
        class ExplodingService:
            def get_dispatch(self, *_args: object, **_kwargs: object) -> None:
                raise RuntimeError("secret /tmp/erp.db")

        handlers = ErpToolHandlers(ExplodingService())  # type: ignore[arg-type]
        envelope = handlers.get_dispatch(
            {"dispatch_id": "DSP001"},
            make_context("erp.dispatches.get"),
        )

        self._assert_error(envelope, "erp_internal_error")
        self.assertNotIn("secret", json.dumps(envelope))

    def test_database_error_envelope_preserves_sanitized_category(self) -> None:
        class DatabaseFailureService:
            def get_product(self, *_args: object, **_kwargs: object) -> None:
                raise ErpDatabaseError()

        handlers = ErpToolHandlers(
            DatabaseFailureService()  # type: ignore[arg-type]
        )
        envelope = handlers.get_product(
            {"product_id": "PRD001"},
            make_context("erp.products.get"),
        )

        self._assert_error(envelope, "erp_database_error")
        self.assertEqual(envelope["error"]["category"], "internal")
        self.assertFalse(envelope["error"]["recoverable"])
        self.assertTrue(envelope["error"]["retryable"])

    def test_handler_passes_context_timeout_to_service(self) -> None:
        class RecordingService:
            def __init__(self) -> None:
                self.timeout_seconds: float | None = None

            def list_warehouses(
                self,
                *,
                timeout_seconds: float | None = None,
            ) -> object:
                self.timeout_seconds = timeout_seconds
                from backend.agent.erp.models import WarehouseListResult

                return WarehouseListResult(
                    items=[],
                    row_count=0,
                    truncated=False,
                )

        service = RecordingService()
        handlers = ErpToolHandlers(service)  # type: ignore[arg-type]
        envelope = handlers.list_warehouses(
            {},
            make_context("erp.warehouses.list", timeout_seconds=1.5),
        )

        self.assertIs(envelope["ok"], True)
        self.assertEqual(service.timeout_seconds, 1.5)


if __name__ == "__main__":
    unittest.main()
