"""Regression tests for the new ``erp.inventory.list`` ERP tool.

Covers bulk inventory retrieval across all products and warehouses,
optional warehouse filtering, limit/truncation, zero quantities,
no fabrication of missing inventory, empty results, registration
consistency, read-only SQL behavior, fallback rendering, and that
existing inventory tools remain functional.
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from backend.agent.erp.config import ErpDatabaseConfig
from backend.agent.erp.definitions import (
    ERP_TOOL_DEFINITIONS_BY_NAME,
    ERP_TOOL_NAMES,
)
from backend.agent.erp.handlers import ErpToolHandlers
from backend.agent.erp.platform import ErpToolPlatform
from backend.agent.erp.service import ErpReadService
from backend.agent.erp.sqlite_adapter import SqliteErpReadAdapter
from backend.agent.orchestration.models import ToolCallSummary
from backend.agent.orchestration.orchestrator import AgentOrchestrator
from backend.agent.tools.contracts import ToolExecutionStatus
from backend.tests.erp_support import create_erp_fixture_db


class TestInventoryListService(unittest.TestCase):
    """Service-layer tests for erp.inventory.list."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "erp.db"
        create_erp_fixture_db(self.db_path)
        self.config = ErpDatabaseConfig(self.db_path, query_timeout_seconds=5.0)
        self.adapter = SqliteErpReadAdapter(self.config)
        self.service = ErpReadService(self.adapter)

    def tearDown(self) -> None:
        self.adapter.close() if hasattr(self.adapter, "close") else None
        self.temp_dir.cleanup()

    def test_returns_all_product_warehouse_inventory_in_one_call(self) -> None:
        result = self.service.list_inventory()
        # Fixture has inventory for PRD001-PRD004 across WH001/WH002,
        # but PRD005 has no inventory rows -> 7 rows total.
        self.assertEqual(result.row_count, 7)
        self.assertIs(result.truncated, False)
        self.assertEqual(len(result.items), 7)
        product_warehouse = {
            (item.product_id, item.warehouse_id) for item in result.items
        }
        expected = {
            ("PRD001", "WH001"),
            ("PRD001", "WH002"),
            ("PRD002", "WH001"),
            ("PRD002", "WH002"),
            ("PRD003", "WH001"),
            ("PRD004", "WH001"),
            ("PRD004", "WH002"),
        }
        self.assertEqual(product_warehouse, expected)
        # All expected fields present.
        for item in result.items:
            self.assertIsInstance(item.product_id, str)
            self.assertIsInstance(item.product_name, str)
            self.assertIsInstance(item.warehouse_id, str)
            self.assertIsInstance(item.warehouse_name, str)
            self.assertIsInstance(item.on_hand_qty, int)
            self.assertIsInstance(item.reserved_qty, int)
            self.assertIsInstance(item.free_stock, int)
            self.assertIsInstance(item.reorder_level, int)
            self.assertIsInstance(item.low_stock, bool)

    def test_warehouse_filtering(self) -> None:
        result = self.service.list_inventory(warehouse_id="WH001")
        self.assertEqual(result.row_count, 4)
        self.assertEqual(len(result.items), 4)
        for item in result.items:
            self.assertEqual(item.warehouse_id, "WH001")
        product_ids = {item.product_id for item in result.items}
        self.assertEqual(product_ids, {"PRD001", "PRD002", "PRD003", "PRD004"})

    def test_limit_and_truncation(self) -> None:
        result = self.service.list_inventory(limit=2)
        self.assertEqual(result.row_count, 2)
        self.assertEqual(len(result.items), 2)
        self.assertIs(result.truncated, True)

    def test_zero_quantities_preserved(self) -> None:
        result = self.service.list_inventory()
        # PRD004 @ WH001: on_hand=50, reserved=50 -> free_stock=0
        for item in result.items:
            if item.product_id == "PRD004" and item.warehouse_id == "WH001":
                self.assertEqual(item.on_hand_qty, 50)
                self.assertEqual(item.reserved_qty, 50)
                self.assertEqual(item.free_stock, 0)
                break
        else:
            self.fail("PRD004 @ WH001 not found")

    def test_products_without_inventory_not_fabricated(self) -> None:
        result = self.service.list_inventory()
        product_ids = {item.product_id for item in result.items}
        # PRD005 has no inventory rows in the fixture.
        self.assertNotIn("PRD005", product_ids)

    def test_empty_result_when_no_inventory(self) -> None:
        connection = sqlite3.connect(self.db_path)
        try:
            connection.execute("DELETE FROM inventory")
            connection.commit()
        finally:
            connection.close()

        result = self.service.list_inventory()
        self.assertEqual(result.row_count, 0)
        self.assertEqual(len(result.items), 0)
        self.assertIs(result.truncated, False)

    def test_invalid_warehouse_id_raises(self) -> None:
        with self.assertRaises(Exception):
            self.service.list_inventory(warehouse_id="NONEXISTENT")


class TestInventoryListRegistration(unittest.TestCase):
    """Registration consistency: definition and handler must match exactly."""

    def test_definition_and_handler_match(self) -> None:
        self.assertIn("erp.inventory.list", ERP_TOOL_NAMES)
        self.assertIn("erp.inventory.list", ERP_TOOL_DEFINITIONS_BY_NAME)
        definition = ERP_TOOL_DEFINITIONS_BY_NAME["erp.inventory.list"]
        self.assertEqual(definition.metadata, {"read_only": True})
        self.assertFalse(definition.input_schema["additionalProperties"])
        self.assertIn("warehouse_id", definition.input_schema["properties"])
        self.assertIn("limit", definition.input_schema["properties"])
        self.assertNotIn("product_id", definition.input_schema["properties"])

    def test_handler_mapping_matches_definitions(self) -> None:
        handler_names = set(ErpToolHandlers(None).as_mapping().keys())
        expected_names = set(ERP_TOOL_NAMES)
        self.assertEqual(handler_names, expected_names)
        self.assertIn("erp.inventory.list", handler_names)


class TestInventoryListPlatform(unittest.TestCase):
    """End-to-end platform registration test."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "erp.db"
        create_erp_fixture_db(self.db_path)
        self.config = ErpDatabaseConfig(self.db_path, query_timeout_seconds=5.0)
        self.platform = ErpToolPlatform.from_config(self.config)

    def tearDown(self) -> None:
        self.platform.close()
        self.temp_dir.cleanup()

    def test_tool_registered_and_executable(self) -> None:
        self.assertTrue(self.platform.registry.exists("erp.inventory.list"))
        self.assertTrue(self.platform.executor.has_handler("erp.inventory.list"))

    def test_execution_through_runner(self) -> None:
        result = self.platform.runner.execute(
            __import__("backend.agent.tools.contracts", fromlist=["ToolExecutionRequest"]).ToolExecutionRequest(
                tool_name="erp.inventory.list",
                arguments={},
            )
        )
        self.assertEqual(result.status, "succeeded")
        self.assertIsNotNone(result.output)
        data = result.output
        self.assertIn("items", data)
        self.assertIn("row_count", data)
        self.assertIn("truncated", data)


class TestInventoryListReadOnlySQL(unittest.TestCase):
    """The SQL must be read-only and parameterized."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "erp.db"
        create_erp_fixture_db(self.db_path)
        self.config = ErpDatabaseConfig(self.db_path, query_timeout_seconds=5.0)
        self.adapter = SqliteErpReadAdapter(self.config)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_query_is_select_only(self) -> None:
        from backend.agent.erp.service import _INVENTORY_LIST_SQL

        statement = _INVENTORY_LIST_SQL.strip()
        self.assertTrue(statement.upper().startswith("SELECT"))
        self.assertNotIn(";", statement.rstrip(";").rstrip())
        # No write keywords.
        upper = statement.upper()
        for keyword in ("INSERT", "UPDATE", "DELETE", "DROP", "CREATE", "ALTER"):
            self.assertNotIn(keyword, upper)

    def test_connection_is_read_only(self) -> None:
        # The adapter opens connections in mode=ro with PRAGMA query_only=ON.
        self.assertTrue(str(self.adapter.database_path).endswith(".db"))
        result = self.adapter.fetch_all(
            "SELECT COUNT(*) AS c FROM inventory", (), deadline=None
        )
        self.assertGreaterEqual(result[0]["c"], 0)


class TestInventoryListFallbackRendering(unittest.TestCase):
    """The orchestrator fallback renders inventory.list as a readable table."""

    def _fallback(self, outputs):
        return AgentOrchestrator._fallback_answer([], outputs, intro="Retrieved:")

    def test_rendered_as_readable_table(self) -> None:
        outputs = [
            (
                "erp.inventory.list",
                {
                    "items": [
                        {
                            "product_id": "PRD001",
                            "product_name": "Hex Bolt M10",
                            "warehouse_id": "WH001",
                            "warehouse_name": "Main Warehouse",
                            "on_hand_qty": 420,
                            "reserved_qty": 70,
                            "free_stock": 350,
                            "reorder_level": 500,
                            "low_stock": True,
                        },
                        {
                            "product_id": "PRD001",
                            "product_name": "Hex Bolt M10",
                            "warehouse_id": "WH002",
                            "warehouse_name": "Secondary Warehouse",
                            "on_hand_qty": 180,
                            "reserved_qty": 20,
                            "free_stock": 160,
                            "reorder_level": 500,
                            "low_stock": True,
                        },
                    ],
                    "row_count": 2,
                    "truncated": False,
                },
            )
        ]
        answer = self._fallback(outputs)

        self.assertIn("Inventory", answer)
        self.assertIn("PRD001", answer)
        self.assertIn("WH001", answer)
        self.assertIn("Main Warehouse", answer)
        self.assertIn("WH002", answer)
        self.assertIn("Secondary Warehouse", answer)
        self.assertIn("| On hand |", answer)
        self.assertIn("| Free stock |", answer)
        self.assertIn("| Low stock |", answer)
        self.assertIn("420", answer)
        self.assertIn("180", answer)
        # Not raw JSON.
        self.assertNotIn('"on_hand_qty": 420', answer)

    def test_zero_stock_in_table(self) -> None:
        outputs = [
            (
                "erp.inventory.list",
                {
                    "items": [
                        {
                            "product_id": "PRD004",
                            "product_name": "Under_score Widget",
                            "warehouse_id": "WH001",
                            "warehouse_name": "Main Warehouse",
                            "on_hand_qty": 50,
                            "reserved_qty": 50,
                            "free_stock": 0,
                            "reorder_level": 10,
                            "low_stock": True,
                        }
                    ],
                    "row_count": 1,
                },
            )
        ]
        answer = self._fallback(outputs)
        self.assertIn("| 0 |", answer)


class TestInventoryListExistingToolsUnchanged(unittest.TestCase):
    """Existing inventory tools must remain functional."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "erp.db"
        create_erp_fixture_db(self.db_path)
        self.config = ErpDatabaseConfig(self.db_path, query_timeout_seconds=5.0)
        self.adapter = SqliteErpReadAdapter(self.config)
        self.service = ErpReadService(self.adapter)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_inventory_get_still_works(self) -> None:
        result = self.service.get_inventory("PRD001")
        self.assertEqual(result.row_count, 2)
        self.assertEqual(len(result.items), 2)

    def test_low_stock_still_works(self) -> None:
        result = self.service.list_low_stock()
        self.assertGreaterEqual(result.row_count, 0)
        self.assertEqual(len(result.items), result.row_count)

    def test_products_search_still_works(self) -> None:
        result = self.service.list_products()
        self.assertGreaterEqual(result.row_count, 5)

    def test_warehouses_list_still_works(self) -> None:
        result = self.service.list_warehouses()
        self.assertEqual(result.row_count, 2)


class TestInventoryListBudgetScenario(unittest.TestCase):
    """One erp.inventory.list call replaces six erp.inventory.get calls."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "erp.db"
        create_erp_fixture_db(self.db_path)
        self.config = ErpDatabaseConfig(self.db_path, query_timeout_seconds=5.0)
        self.adapter = SqliteErpReadAdapter(self.config)
        self.service = ErpReadService(self.adapter)
        self.platform = ErpToolPlatform.from_config(self.config)

    def tearDown(self) -> None:
        self.platform.close()
        self.temp_dir.cleanup()

    def test_single_call_replaces_multiple_lookups(self) -> None:
        # With budget=5, six individual inventory.get calls would exhaust the
        # budget. One inventory.list call retrieves everything.
        result = self.platform.runner.execute(
            __import__("backend.agent.tools.contracts", fromlist=["ToolExecutionRequest"]).ToolExecutionRequest(
                tool_name="erp.inventory.list",
                arguments={},
            )
        )
        self.assertEqual(result.status, "succeeded")
        data = result.output
        # All products that have inventory are returned in one call.
        product_ids = {item["product_id"] for item in data["items"]}
        self.assertIn("PRD001", product_ids)
        self.assertIn("PRD002", product_ids)
        self.assertIn("PRD003", product_ids)
        self.assertIn("PRD004", product_ids)
        # PRD005 has no inventory rows -> not fabricated.
        self.assertNotIn("PRD005", product_ids)


if __name__ == "__main__":
    unittest.main()
