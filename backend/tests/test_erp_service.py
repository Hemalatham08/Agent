from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.agent.erp.errors import (
    ErpConfigurationError,
    ErpDatabaseError,
    ErpInvalidArgumentsError,
    ErpNotFoundError,
    ErpQueryTimeoutError,
)
from backend.agent.erp.service import ErpReadService
from backend.agent.erp.sqlite_adapter import SqliteErpReadAdapter
from backend.tests.erp_support import create_erp_fixture_db


class ErpReadServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self._temp_dir.name)
        self.database_path = create_erp_fixture_db(self.root / "erp.db")
        self.adapter = SqliteErpReadAdapter(self.database_path)
        self.service = ErpReadService(self.adapter)

    def tearDown(self) -> None:
        self._temp_dir.cleanup()

    def _execute(self, sql: str, parameters: tuple[object, ...] = ()) -> None:
        connection = sqlite3.connect(self.database_path)
        try:
            connection.execute(sql, parameters)
            connection.commit()
        finally:
            connection.close()

    def test_product_search_returns_ordered_summaries(self) -> None:
        result = self.service.search_products("M10")

        self.assertEqual(
            [item.product_id for item in result.items],
            ["PRD001", "PRD002"],
        )
        self.assertEqual(result.row_count, 2)
        self.assertFalse(result.truncated)
        self.assertEqual(
            result.items[0].model_dump(),
            {
                "product_id": "PRD001",
                "sku": "HEX-M10-SS304",
                "product_name": "Hex Bolt M10",
                "category": "Bolts",
                "material": "Stainless Steel",
                "size": "M10",
                "grade": "SS304",
                "unit": "pieces",
            },
        )

    def test_product_search_is_case_insensitive(self) -> None:
        result = self.service.search_products("hex bolt")

        self.assertEqual([item.product_id for item in result.items], ["PRD001"])

    def test_product_search_matches_material_size_and_grade(self) -> None:
        for query in ("stainless", "M10", "ss304"):
            with self.subTest(query=query):
                result = self.service.search_products(query)
                self.assertEqual(
                    [item.product_id for item in result.items],
                    ["PRD001", "PRD002"],
                )

    def test_product_search_escapes_percent_wildcard(self) -> None:
        result = self.service.search_products("%")

        self.assertEqual([item.product_id for item in result.items], ["PRD003"])

    def test_product_search_escapes_underscore_wildcard(self) -> None:
        result = self.service.search_products("_")

        self.assertEqual([item.product_id for item in result.items], ["PRD004"])

    def test_product_search_escapes_backslash(self) -> None:
        result = self.service.search_products("\\")
        self.assertEqual(result.items, [])

    def test_product_search_applies_limit_and_truncation(self) -> None:
        result = self.service.search_products("M10", 1)

        self.assertEqual([item.product_id for item in result.items], ["PRD001"])
        self.assertEqual(result.row_count, 1)
        self.assertTrue(result.truncated)

    def test_product_search_empty_result_is_success(self) -> None:
        result = self.service.search_products("no-such-product")

        self.assertEqual(result.items, [])
        self.assertEqual(result.row_count, 0)
        self.assertFalse(result.truncated)

    def test_product_search_rejects_invalid_arguments(self) -> None:
        invalid_queries = ("", "   ", "x" * 201, 123, None)
        for query in invalid_queries:
            with self.subTest(query=query):
                with self.assertRaises(ErpInvalidArgumentsError):
                    self.service.search_products(query)

        invalid_limits = (0, 51, True, "20", None)
        for limit in invalid_limits:
            with self.subTest(limit=limit):
                with self.assertRaises(ErpInvalidArgumentsError):
                    self.service.search_products("M10", limit)

    def test_list_products_returns_all_ordered(self) -> None:
        result = self.service.list_products()

        self.assertEqual(
            [item.product_id for item in result.items],
            ["PRD003", "PRD005", "PRD001", "PRD002", "PRD004"],
        )
        self.assertEqual(result.row_count, 5)
        self.assertFalse(result.truncated)

    def test_list_products_returns_all_six_when_present(self) -> None:
        self._execute(
            "INSERT INTO products VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "PRD006",
                "HEX-M12-SS316",
                "Hex Bolt M12",
                "Bolts",
                "Stainless Steel",
                "M12",
                "SS316",
                "pieces",
                9.0,
                14.0,
                300,
            ),
        )

        result = self.service.list_products()

        self.assertEqual(result.row_count, 6)
        self.assertIn("PRD006", [item.product_id for item in result.items])
        self.assertFalse(result.truncated)

    def test_list_products_applies_limit_and_truncation(self) -> None:
        result = self.service.list_products(2)

        self.assertEqual(result.row_count, 2)
        self.assertTrue(result.truncated)

    def test_list_products_rejects_invalid_limits(self) -> None:
        for limit in (0, 51, True, "20", None):
            with self.subTest(limit=limit):
                with self.assertRaises(ErpInvalidArgumentsError):
                    self.service.list_products(limit)

    def test_product_detail_returns_allowed_fields_only(self) -> None:
        product = self.service.get_product("PRD001")

        self.assertEqual(
            product.model_dump(),
            {
                "product_id": "PRD001",
                "sku": "HEX-M10-SS304",
                "product_name": "Hex Bolt M10",
                "category": "Bolts",
                "material": "Stainless Steel",
                "size": "M10",
                "grade": "SS304",
                "unit": "pieces",
                "reorder_level": 500,
            },
        )
        self.assertNotIn("purchase_price", product.model_dump())
        self.assertNotIn("selling_price", product.model_dump())

    def test_product_detail_not_found(self) -> None:
        with self.assertRaises(ErpNotFoundError):
            self.service.get_product("MISSING")

    def test_product_detail_rejects_blank_id(self) -> None:
        with self.assertRaises(ErpInvalidArgumentsError):
            self.service.get_product("   ")

    def test_inventory_returns_per_warehouse_rows(self) -> None:
        result = self.service.get_inventory("PRD002")

        self.assertEqual(
            [item.warehouse_id for item in result.items],
            ["WH001", "WH002"],
        )
        self.assertEqual(result.items[0].free_stock, 900)
        self.assertFalse(result.items[0].low_stock)
        self.assertEqual(result.items[1].free_stock, 300)
        self.assertTrue(result.items[1].low_stock)
        self.assertEqual(result.row_count, 2)
        self.assertFalse(result.truncated)

    def test_inventory_can_filter_by_warehouse(self) -> None:
        result = self.service.get_inventory("PRD004", "WH002")

        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.items[0].warehouse_id, "WH002")
        self.assertEqual(result.items[0].free_stock, 100)
        self.assertFalse(result.items[0].low_stock)

    def test_inventory_existing_product_without_rows_is_empty(self) -> None:
        result = self.service.get_inventory("PRD005")

        self.assertEqual(result.items, [])
        self.assertEqual(result.row_count, 0)
        self.assertFalse(result.truncated)

    def test_inventory_unknown_product_is_not_found(self) -> None:
        with self.assertRaises(ErpNotFoundError):
            self.service.get_inventory("MISSING")

    def test_inventory_unknown_warehouse_is_not_found(self) -> None:
        with self.assertRaises(ErpNotFoundError):
            self.service.get_inventory("PRD001", "WH999")

    def test_inventory_rejects_blank_warehouse_id(self) -> None:
        with self.assertRaises(ErpInvalidArgumentsError):
            self.service.get_inventory("PRD001", "   ")

    def test_warehouse_list_is_ordered(self) -> None:
        result = self.service.list_warehouses()

        self.assertEqual(
            [item.warehouse_id for item in result.items],
            ["WH001", "WH002"],
        )
        self.assertEqual(result.items[0].city, "Chennai")
        self.assertEqual(result.row_count, 2)
        self.assertFalse(result.truncated)

    def test_low_stock_uses_per_warehouse_definition(self) -> None:
        result = self.service.list_low_stock()

        self.assertEqual(
            [
                (item.product_id, item.warehouse_id)
                for item in result.items
            ],
            [
                ("PRD001", "WH001"),
                ("PRD001", "WH002"),
                ("PRD002", "WH002"),
                ("PRD003", "WH001"),
                ("PRD004", "WH001"),
            ],
        )
        self.assertTrue(all(item.low_stock for item in result.items))
        self.assertNotIn(
            ("PRD002", "WH001"),
            [(item.product_id, item.warehouse_id) for item in result.items],
        )

    def test_low_stock_can_filter_by_warehouse(self) -> None:
        result = self.service.list_low_stock("WH002")

        self.assertEqual(
            [
                (item.product_id, item.warehouse_id)
                for item in result.items
            ],
            [("PRD001", "WH002"), ("PRD002", "WH002")],
        )

    def test_low_stock_applies_limit_and_truncation(self) -> None:
        result = self.service.list_low_stock(limit=2)

        self.assertEqual(result.row_count, 2)
        self.assertTrue(result.truncated)

    def test_low_stock_unknown_warehouse_is_not_found(self) -> None:
        with self.assertRaises(ErpNotFoundError):
            self.service.list_low_stock("WH999")

    def test_low_stock_rejects_invalid_limit(self) -> None:
        for limit in (0, 51, True, "20", None):
            with self.subTest(limit=limit):
                with self.assertRaises(ErpInvalidArgumentsError):
                    self.service.list_low_stock(limit=limit)

    def test_sales_order_returns_header_and_items_without_financials(self) -> None:
        result = self.service.get_sales_order("SO001")

        self.assertEqual(
            result.order.model_dump(),
            {
                "so_id": "SO001",
                "customer_id": "CUS001",
                "customer_name": "Sri Venkateswara Engineering",
                "order_date": "2026-10-02",
                "required_date": "2026-10-05",
                "status": "Partially Dispatched",
            },
        )
        self.assertEqual(
            [item.model_dump() for item in result.items],
            [
                {
                    "product_id": "PRD001",
                    "product_name": "Hex Bolt M10",
                    "ordered_qty": 100,
                },
                {
                    "product_id": "PRD002",
                    "product_name": "Hex Nut M10",
                    "ordered_qty": 50,
                },
            ],
        )
        self.assertEqual(result.items_row_count, 2)
        self.assertFalse(result.items_truncated)
        self.assertNotIn("phone", result.order.model_dump())
        self.assertNotIn("unit_price", result.items[0].model_dump())

    def test_sales_order_without_items_is_success(self) -> None:
        self._execute(
            "INSERT INTO sales_orders VALUES (?, ?, ?, ?, ?)",
            ("SO003", "CUS001", "2026-10-07", "2026-10-08", "Pending"),
        )

        result = self.service.get_sales_order("SO003")

        self.assertEqual(result.items, [])
        self.assertEqual(result.items_row_count, 0)
        self.assertFalse(result.items_truncated)

    def test_sales_order_not_found(self) -> None:
        with self.assertRaises(ErpNotFoundError):
            self.service.get_sales_order("MISSING")

    def test_sales_order_rejects_blank_id(self) -> None:
        with self.assertRaises(ErpInvalidArgumentsError):
            self.service.get_sales_order("   ")

    def test_outputs_are_json_compatible(self) -> None:
        outputs = (
            self.service.search_products("M10").model_dump(mode="json"),
            self.service.get_product("PRD001").model_dump(mode="json"),
            self.service.get_inventory("PRD001").model_dump(mode="json"),
            self.service.list_warehouses().model_dump(mode="json"),
            self.service.list_low_stock().model_dump(mode="json"),
            self.service.get_sales_order("SO001").model_dump(mode="json"),
        )

        for output in outputs:
            with self.subTest(output=output):
                encoded = json.dumps(output, allow_nan=False)
                self.assertIsInstance(encoded, str)

    def test_search_truncates_at_configured_maximum(self) -> None:
        rows = [
            (
                f"BULK{index:03d}",
                f"BULK-SKU-{index:03d}",
                f"Bulk Item {index:03d}",
                "Bulk",
                "Steel",
                "M8",
                "A2",
                "pieces",
                1.0,
                2.0,
                10,
            )
            for index in range(1, 52)
        ]
        connection = sqlite3.connect(self.database_path)
        try:
            connection.executemany(
                "INSERT INTO products VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            connection.commit()
        finally:
            connection.close()

        result = self.service.search_products("Bulk", 50)

        self.assertEqual(result.row_count, 50)
        self.assertTrue(result.truncated)

    def test_warehouse_and_inventory_results_truncate(self) -> None:
        warehouses = [
            (f"WHX{index:03d}", f"Extra Warehouse {index:03d}", "City")
            for index in range(1, 52)
        ]
        inventory = [
            (
                f"INVX{index:03d}",
                "PRD005",
                f"WHX{index:03d}",
                0,
                0,
            )
            for index in range(1, 52)
        ]
        connection = sqlite3.connect(self.database_path)
        try:
            connection.executemany(
                "INSERT INTO warehouses VALUES (?, ?, ?)",
                warehouses,
            )
            connection.executemany(
                "INSERT INTO inventory VALUES (?, ?, ?, ?, ?)",
                inventory,
            )
            connection.commit()
        finally:
            connection.close()

        warehouse_result = self.service.list_warehouses()
        inventory_result = self.service.get_inventory("PRD005")
        low_stock_result = self.service.list_low_stock(limit=50)

        self.assertEqual(warehouse_result.row_count, 50)
        self.assertTrue(warehouse_result.truncated)
        self.assertEqual(inventory_result.row_count, 50)
        self.assertTrue(inventory_result.truncated)
        self.assertEqual(low_stock_result.row_count, 50)
        self.assertTrue(low_stock_result.truncated)

    def test_sales_order_items_truncate(self) -> None:
        connection = sqlite3.connect(self.database_path)
        try:
            connection.execute(
                "INSERT INTO sales_orders VALUES (?, ?, ?, ?, ?)",
                ("SO003", "CUS001", "2026-10-07", "2026-10-08", "Pending"),
            )
            connection.executemany(
                "INSERT INTO sales_order_items VALUES (?, ?, ?, ?, ?)",
                [
                    (
                        f"SOI{index:04d}",
                        "SO003",
                        "PRD001",
                        1,
                        1.0,
                    )
                    for index in range(1000, 1101)
                ],
            )
            connection.commit()
        finally:
            connection.close()

        result = self.service.get_sales_order("SO003")

        self.assertEqual(result.items_row_count, 100)
        self.assertTrue(result.items_truncated)

    def test_query_timeout_arguments(self) -> None:
        with self.assertRaises(ErpQueryTimeoutError):
            self.service.search_products("M10", timeout_seconds=0)

        with self.assertRaises(ErpQueryTimeoutError):
            self.service.search_products("M10", timeout_seconds=-1)

        with self.assertRaises(ErpInvalidArgumentsError):
            self.service.search_products(
                "M10",
                timeout_seconds=float("nan"),
            )

        with self.assertRaises(ErpInvalidArgumentsError):
            self.service.search_products("M10", timeout_seconds="1")

    def test_service_rejects_invalid_configured_timeout(self) -> None:
        with self.assertRaises(ErpConfigurationError):
            ErpReadService(self.adapter, query_timeout_seconds=0)

    def test_database_errors_propagate_sanitized(self) -> None:
        self.database_path.unlink()

        with self.assertRaises(ErpDatabaseError):
            self.service.get_product("PRD001")


if __name__ == "__main__":
    unittest.main()
