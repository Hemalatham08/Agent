from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from backend.agent.erp.errors import ErpInvalidArgumentsError
from backend.agent.erp.service import ErpReadService
from backend.agent.erp.sqlite_adapter import SqliteErpReadAdapter
from backend.tests.analytics_support import (
    create_analytics_fixture_db,
    create_multi_period_fixture_db,
)


class AnalyticsServiceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp_dir.cleanup)
        database_path = create_analytics_fixture_db(
            Path(self._temp_dir.name) / "erp.db"
        )
        self.service = ErpReadService(SqliteErpReadAdapter(database_path))

    def _multi_period_service(self) -> ErpReadService:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        database_path = create_multi_period_fixture_db(
            Path(temp_dir.name) / "erp.db"
        )
        return ErpReadService(SqliteErpReadAdapter(database_path))

    def test_booked_sales_totals_match_live_reconciliation(self) -> None:
        result = self.service.sales_summary(group_by="product", basis="booked")

        self.assertEqual(result.basis, "booked")
        self.assertEqual(result.currency, "INR")
        self.assertEqual(result.totals.orders, 6)
        self.assertEqual(result.totals.units, 1600)
        self.assertAlmostEqual(result.totals.revenue, 14150.0)
        self.assertAlmostEqual(result.totals.cost or 0, 8910.0)
        self.assertAlmostEqual(result.totals.gross_profit or 0, 5240.0)
        self.assertAlmostEqual(result.totals.gross_margin_pct or 0, 37.03)
        self.assertEqual(result.row_count, 6)
        self.assertIs(result.truncated, False)

    def test_booked_sales_rows_by_product(self) -> None:
        result = self.service.sales_summary(group_by="product", basis="booked")

        values = {
            row.key: (row.revenue, row.cost, row.gross_profit)
            for row in result.rows
        }
        self.assertEqual(
            values,
            {
                "PRD001": (2640.0, 1760.0, 880.0),
                "PRD002": (2450.0, 1400.0, 1050.0),
                "PRD003": (2500.0, 1500.0, 1000.0),
                "PRD004": (1000.0, 500.0, 500.0),
                "PRD005": (2860.0, 1950.0, 910.0),
                "PRD006": (2700.0, 1800.0, 900.0),
            },
        )

    def test_booked_sales_by_customer_and_category(self) -> None:
        by_customer = self.service.sales_summary(
            group_by="customer",
            basis="booked",
        )
        self.assertEqual(
            [(row.key, row.revenue) for row in by_customer.rows],
            [
                ("CUS001", 4620.0),
                ("CUS005", 3250.0),
                ("CUS003", 2840.0),
                ("CUS004", 1840.0),
                ("CUS002", 1600.0),
            ],
        )

        by_category = self.service.sales_summary(
            group_by="category",
            basis="booked",
        )
        self.assertEqual(
            [(row.key, row.revenue) for row in by_category.rows],
            [
                ("Bolts", 8200.0),
                ("Screws", 2500.0),
                ("Nuts", 2450.0),
                ("Washers", 1000.0),
            ],
        )

    def test_dispatched_sales_totals_and_fan_out_regression(self) -> None:
        result = self.service.sales_summary(
            group_by="product",
            basis="dispatched",
        )

        self.assertEqual(result.totals.orders, 3)
        self.assertEqual(result.totals.units, 750)
        self.assertAlmostEqual(result.totals.revenue, 5200.0)
        self.assertAlmostEqual(result.totals.cost or 0, 3180.0)
        self.assertAlmostEqual(result.totals.gross_profit or 0, 2020.0)
        self.assertAlmostEqual(result.totals.gross_margin_pct or 0, 38.85)

        by_product = {
            row.key: (row.units, row.revenue) for row in result.rows
        }
        # A naive sales-order/dispatch join fans PRD001 out to 440 units.
        self.assertEqual(by_product["PRD001"], (220, 2640.0))
        self.assertEqual(by_product["PRD002"], (80, 560.0))
        self.assertEqual(by_product["PRD003"], (200, 1000.0))
        self.assertEqual(by_product["PRD004"], (250, 1000.0))

    def test_dispatched_sales_by_customer(self) -> None:
        result = self.service.sales_summary(
            group_by="customer",
            basis="dispatched",
        )

        self.assertEqual(
            [(row.key, row.revenue) for row in result.rows],
            [
                ("CUS004", 1840.0),
                ("CUS001", 1760.0),
                ("CUS002", 1600.0),
            ],
        )
        self.assertEqual(result.totals.units, 750)

    def test_invoiced_basis_reconciles_and_has_no_cost(self) -> None:
        result = self.service.sales_summary(
            group_by="month",
            basis="invoiced",
        )

        self.assertEqual(result.totals.orders, 3)
        self.assertAlmostEqual(result.totals.revenue, 5200.0)
        self.assertIsNone(result.totals.units)
        self.assertIsNone(result.totals.cost)
        self.assertIsNone(result.totals.gross_profit)
        self.assertIsNone(result.totals.gross_margin_pct)

    def test_invoiced_basis_rejects_product_and_category(self) -> None:
        for group_by in ("product", "category"):
            with self.subTest(group_by=group_by):
                with self.assertRaises(ErpInvalidArgumentsError):
                    self.service.sales_summary(
                        group_by=group_by,
                        basis="invoiced",
                    )

    def test_sales_limit_preserves_pre_truncation_totals(self) -> None:
        result = self.service.sales_summary(
            group_by="product",
            basis="booked",
            limit=1,
        )

        self.assertEqual(result.row_count, 1)
        self.assertIs(result.truncated, True)
        self.assertAlmostEqual(result.totals.revenue, 14150.0)
        self.assertAlmostEqual(result.totals.gross_profit or 0, 5240.0)

    def test_purchase_totals_and_supplier_grouping(self) -> None:
        result = self.service.purchase_summary(group_by="supplier")

        self.assertEqual(result.basis, "received")
        self.assertEqual(result.totals.orders, 4)
        self.assertEqual(result.totals.units_ordered, 3150)
        self.assertEqual(result.totals.units_received, 1800)
        self.assertAlmostEqual(result.totals.ordered_value, 22100.0)
        self.assertAlmostEqual(result.totals.received_value, 6800.0)
        self.assertAlmostEqual(result.totals.open_value, 15300.0)

        values = {
            row.key: (row.ordered_value, row.received_value, row.open_value)
            for row in result.rows
        }
        self.assertEqual(
            values["SUP001"],
            (5600.0, 4000.0, 1600.0),
        )
        self.assertEqual(values["SUP002"], (2800.0, 2800.0, 0.0))
        self.assertEqual(values["SUP003"], (7500.0, 0.0, 7500.0))
        self.assertEqual(values["SUP004"], (6200.0, 0.0, 6200.0))

    def test_purchase_product_grouping_and_ordered_basis(self) -> None:
        result = self.service.purchase_summary(
            group_by="product",
            basis="ordered",
        )

        values = {
            row.key: (row.ordered_value, row.received_value)
            for row in result.rows
        }
        self.assertEqual(values["PRD001"], (7200.0, 2400.0))
        self.assertEqual(values["PRD002"], (1600.0, 1600.0))
        self.assertEqual(values["PRD003"], (1800.0, 1800.0))
        self.assertEqual(values["PRD004"], (1000.0, 1000.0))
        self.assertEqual(values["PRD005"], (7500.0, 0.0))
        self.assertEqual(values["PRD006"], (3000.0, 0.0))
        # Ordered basis sorts by procurement commitment.
        self.assertEqual(result.rows[0].key, "PRD005")

    def test_movement_totals_and_warehouse_rows(self) -> None:
        result = self.service.movement_summary(group_by="warehouse")

        self.assertEqual(result.totals.movement_count, 12)
        self.assertEqual(result.totals.opening_qty, 990)
        self.assertEqual(result.totals.receipts_qty, 1782)
        self.assertEqual(result.totals.dispatch_qty, 530)
        self.assertEqual(result.totals.inbound_qty, 2772)
        self.assertEqual(result.totals.outbound_qty, 530)
        self.assertEqual(result.totals.receipts_net_qty, 1252)
        self.assertEqual(result.totals.net_change, 2242)

        rows = {row.key: row for row in result.rows}
        wh001 = rows["WH001"]
        self.assertEqual(
            (
                wh001.opening_qty,
                wh001.receipts_qty,
                wh001.inbound_qty,
                wh001.outbound_qty,
                wh001.receipts_net_qty,
                wh001.net_change,
            ),
            (720, 694, 1414, 180, 514, 1234),
        )
        wh002 = rows["WH002"]
        self.assertEqual(
            (
                wh002.opening_qty,
                wh002.receipts_qty,
                wh002.inbound_qty,
                wh002.outbound_qty,
                wh002.receipts_net_qty,
                wh002.net_change,
            ),
            (270, 1088, 1358, 350, 738, 1008),
        )

    def test_movement_by_type(self) -> None:
        result = self.service.movement_summary(group_by="movement_type")

        values = {
            row.key: (row.inbound_qty, row.outbound_qty, row.net_change)
            for row in result.rows
        }
        self.assertEqual(values["Opening Balance"], (990, 0, 990))
        self.assertEqual(values["Purchase Receipt"], (1782, 0, 1782))
        self.assertEqual(values["Sales Dispatch"], (0, 530, -530))

    def test_fulfillment_totals(self) -> None:
        result = self.service.fulfillment_summary(group_by="product")

        self.assertEqual(result.totals.dispatches, 3)
        self.assertEqual(result.totals.ordered_qty, 1600)
        self.assertEqual(result.totals.picked_qty, 770)
        self.assertEqual(result.totals.dispatched_qty, 750)
        self.assertEqual(result.totals.open_qty, 850)
        self.assertAlmostEqual(result.totals.pick_fill_pct or 0, 97.4)
        self.assertAlmostEqual(result.totals.order_fill_pct or 0, 46.88)
        self.assertEqual(result.totals.ordered_on_dispatched_orders, 770)
        self.assertAlmostEqual(
            result.totals.dispatched_order_fill_pct or 0,
            97.4,
        )

    def test_fulfillment_product_rows_without_join_fan_out(self) -> None:
        result = self.service.fulfillment_summary(group_by="product")

        values = {
            row.key: (
                row.ordered_qty,
                row.picked_qty,
                row.dispatched_qty,
                row.open_qty,
                row.order_fill_pct,
                row.pick_fill_pct,
            )
            for row in result.rows
        }
        self.assertEqual(values["PRD001"], (220, 220, 220, 0, 100.0, 100.0))
        self.assertEqual(values["PRD002"], (350, 100, 80, 270, 22.86, 80.0))
        self.assertEqual(values["PRD003"], (500, 200, 200, 300, 40.0, 100.0))
        self.assertEqual(values["PRD004"], (250, 250, 250, 0, 100.0, 100.0))
        self.assertEqual(values["PRD005"], (130, 0, 0, 130, 0.0, None))
        self.assertEqual(values["PRD006"], (150, 0, 0, 150, 0.0, None))

    def test_fulfillment_customer_carrier_and_status(self) -> None:
        by_customer = self.service.fulfillment_summary(group_by="customer")
        self.assertEqual(by_customer.totals.ordered_qty, 1600)
        customer_values = {
            row.key: (row.ordered_qty, row.dispatched_qty)
            for row in by_customer.rows
        }
        self.assertEqual(customer_values["CUS001"], (340, 180))
        self.assertEqual(customer_values["CUS003"], (140, 0))
        self.assertEqual(customer_values["CUS005"], (550, 0))

        by_carrier = self.service.fulfillment_summary(group_by="carrier")
        carrier_values = {
            row.key: (
                row.ordered_qty,
                row.picked_qty,
                row.dispatched_qty,
                row.order_fill_pct,
            )
            for row in by_carrier.rows
        }
        self.assertEqual(carrier_values["BlueDart"], (420, 420, 400, 95.24))
        self.assertEqual(carrier_values["DTDC"], (350, 350, 350, 100.0))
        self.assertEqual(by_carrier.totals.ordered_qty, 770)

        by_status = self.service.fulfillment_summary(group_by="status")
        status_values = {
            row.key: (row.ordered_qty, row.dispatched_qty)
            for row in by_status.rows
        }
        self.assertEqual(status_values["Dispatched"], (570, 570))
        self.assertEqual(status_values["Partially Dispatched"], (200, 180))

    def test_date_filters_are_inclusive_and_empty_ranges_are_safe(self) -> None:
        filtered = self.service.sales_summary(
            group_by="customer",
            basis="booked",
            date_from="2026-10-02",
            date_to="2026-10-02",
        )
        self.assertAlmostEqual(filtered.totals.revenue, 1900.0)
        self.assertEqual(filtered.totals.units, 200)

        empty = self.service.sales_summary(
            group_by="product",
            basis="booked",
            date_from="2020-01-01",
            date_to="2020-12-31",
        )
        self.assertEqual(empty.rows, [])
        self.assertEqual(empty.totals.orders, 0)
        self.assertAlmostEqual(empty.totals.revenue, 0.0)

        empty_fulfillment = self.service.fulfillment_summary(
            group_by="product",
            date_from="2020-01-01",
            date_to="2020-12-31",
        )
        self.assertIsNone(empty_fulfillment.totals.pick_fill_pct)
        self.assertEqual(empty_fulfillment.totals.order_fill_pct, 0.0)
        self.assertIsNone(
            empty_fulfillment.totals.dispatched_order_fill_pct
        )

    def test_invalid_arguments_are_rejected(self) -> None:
        cases = (
            ("sales group_by", lambda: self.service.sales_summary(group_by="region")),
            ("sales basis", lambda: self.service.sales_summary(basis="cash")),
            ("sales limit low", lambda: self.service.sales_summary(limit=0)),
            ("sales limit high", lambda: self.service.sales_summary(limit=51)),
            (
                "sales date format",
                lambda: self.service.sales_summary(date_from="2026/10/01"),
            ),
            (
                "sales date order",
                lambda: self.service.sales_summary(
                    date_from="2026-10-10",
                    date_to="2026-10-01",
                ),
            ),
            (
                "purchase group_by",
                lambda: self.service.purchase_summary(group_by="customer"),
            ),
            (
                "purchase basis",
                lambda: self.service.purchase_summary(basis="paid"),
            ),
            (
                "movement group_by",
                lambda: self.service.movement_summary(group_by="supplier"),
            ),
            (
                "fulfillment group_by",
                lambda: self.service.fulfillment_summary(group_by="warehouse"),
            ),
        )
        for label, call in cases:
            with self.subTest(label=label):
                with self.assertRaises(ErpInvalidArgumentsError):
                    call()

    def test_results_are_json_serializable(self) -> None:
        results = (
            self.service.sales_summary(group_by="product"),
            self.service.purchase_summary(group_by="supplier"),
            self.service.movement_summary(group_by="warehouse"),
            self.service.fulfillment_summary(group_by="carrier"),
        )
        for result in results:
            with self.subTest(result=type(result).__name__):
                json.dumps(result.model_dump(mode="json"), allow_nan=False)


class MultiPeriodAnalyticsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp_dir.cleanup)
        database_path = create_multi_period_fixture_db(
            Path(self._temp_dir.name) / "erp.db"
        )
        self.service = ErpReadService(SqliteErpReadAdapter(database_path))

    def test_monthly_sales_are_chronological(self) -> None:
        result = self.service.sales_summary(group_by="month", basis="booked")
        self.assertEqual(
            [(row.key, row.revenue) for row in result.rows],
            [
                ("2026-08", 120.0),
                ("2026-09", 290.0),
                ("2026-10", 14150.0),
            ],
        )

    def test_quarterly_sales(self) -> None:
        result = self.service.sales_summary(
            group_by="quarter",
            basis="booked",
        )
        self.assertEqual(
            [(row.key, row.revenue) for row in result.rows],
            [
                ("2026-Q3", 410.0),
                ("2026-Q4", 14150.0),
            ],
        )

    def test_dispatched_monthly_and_purchase_monthly(self) -> None:
        dispatched = self.service.sales_summary(
            group_by="month",
            basis="dispatched",
        )
        self.assertEqual(
            [(row.key, row.revenue) for row in dispatched.rows],
            [
                ("2026-08", 120.0),
                ("2026-09", 140.0),
                ("2026-10", 5200.0),
            ],
        )

        purchases = self.service.purchase_summary(group_by="month")
        self.assertEqual(
            [(row.key, row.received_value) for row in purchases.rows],
            [
                ("2026-08", 80.0),
                ("2026-09", 80.0),
                ("2026-10", 6800.0),
            ],
        )

    def test_monthly_movements(self) -> None:
        result = self.service.movement_summary(group_by="month")
        self.assertEqual(
            [(row.key, row.inbound_qty) for row in result.rows],
            [
                ("2026-08", 60),
                ("2026-09", 50),
                ("2026-10", 2772),
            ],
        )


if __name__ == "__main__":
    unittest.main()
