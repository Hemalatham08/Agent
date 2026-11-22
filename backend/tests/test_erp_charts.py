from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from backend.agent.charts.builders import build_chart
from backend.agent.charts.service import ChartService
from backend.agent.erp.service import ErpReadService
from backend.agent.erp.sqlite_adapter import SqliteErpReadAdapter
from backend.tests.analytics_support import (
    create_analytics_fixture_db,
    create_multi_period_fixture_db,
)


class ChartBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp_dir.cleanup)
        database_path = create_analytics_fixture_db(
            Path(self._temp_dir.name) / "erp.db"
        )
        self.service = ErpReadService(SqliteErpReadAdapter(database_path))

    def test_sales_bar_chart_for_product_grouping(self) -> None:
        output = self.service.sales_summary(
            group_by="product", basis="booked"
        ).model_dump()
        spec = build_chart("erp.finance.sales_summary", output)

        self.assertIsNotNone(spec)
        self.assertEqual(spec.chart_type, "bar")
        self.assertEqual(spec.title, "Sales revenue by product (booked)")
        self.assertEqual(spec.x_field, "key")
        self.assertEqual(spec.y_fields, ["revenue"])
        self.assertEqual(len(spec.data), 6)
        self.assertEqual(spec.data[0]["x"], "PRD005")
        self.assertEqual(spec.data[0]["revenue"], 2860.0)
        json.dumps(spec.model_dump(), allow_nan=False)

    def test_sales_line_chart_for_month_grouping(self) -> None:
        # The base fixture is October 2026 only, so month grouping yields a
        # single row: below the meaningful-data threshold, no chart is emitted.
        output = self.service.sales_summary(
            group_by="month", basis="booked"
        ).model_dump()
        self.assertEqual(len(output["rows"]), 1)
        spec = build_chart("erp.finance.sales_summary", output)
        self.assertIsNone(spec)

    def test_line_chart_type_for_multi_period_months(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database_path = create_multi_period_fixture_db(Path(tmp) / "erp.db")
            multi_service = ErpReadService(SqliteErpReadAdapter(database_path))
            output = multi_service.sales_summary(
                group_by="month", basis="booked"
            ).model_dump()
            spec = build_chart("erp.finance.sales_summary", output)

            self.assertIsNotNone(spec)
            self.assertEqual(spec.chart_type, "line")
            self.assertEqual(spec.title, "Sales revenue by month (booked)")
            self.assertEqual(spec.x_field, "key")
            self.assertEqual(spec.y_fields, ["revenue"])
            self.assertEqual(len(spec.data), 3)

    def test_purchase_chart_uses_received_value_by_default(self) -> None:
        output = self.service.purchase_summary(
            group_by="supplier"
        ).model_dump()
        spec = build_chart("erp.finance.purchase_summary", output)

        self.assertIsNotNone(spec)
        self.assertEqual(spec.chart_type, "bar")
        self.assertEqual(spec.title, "Purchase received value by supplier")
        self.assertEqual(spec.y_fields, ["received_value"])

    def test_movement_chart(self) -> None:
        output = self.service.movement_summary(
            group_by="warehouse"
        ).model_dump()
        spec = build_chart("erp.warehouse.movement_summary", output)

        self.assertIsNotNone(spec)
        self.assertEqual(spec.chart_type, "bar")
        self.assertEqual(spec.title, "Stock movement net change by warehouse")
        self.assertEqual(spec.y_fields, ["net_change"])
        values = {row["x"]: row["net_change"] for row in spec.data}
        self.assertEqual(values["WH001"], 1234)
        self.assertEqual(values["WH002"], 1008)

    def test_fulfillment_chart(self) -> None:
        output = self.service.fulfillment_summary(
            group_by="product"
        ).model_dump()
        spec = build_chart("erp.fulfillment.summary", output)

        self.assertIsNotNone(spec)
        self.assertEqual(spec.chart_type, "bar")
        self.assertEqual(spec.title, "Order fill rate by product")
        self.assertEqual(spec.y_fields, ["order_fill_pct"])

    def test_unknown_tool_returns_none(self) -> None:
        self.assertIsNone(
            build_chart("erp.products.search", {"rows": []})
        )
        self.assertIsNone(build_chart("erp.finance.sales_summary", {}))

    def test_truncated_or_empty_result_returns_none(self) -> None:
        empty = self.service.sales_summary(
            group_by="product",
            basis="booked",
            date_from="2020-01-01",
            date_to="2020-12-31",
        ).model_dump()
        self.assertIsNone(build_chart("erp.finance.sales_summary", empty))


class ChartServiceTests(unittest.TestCase):
    def test_build_charts_respects_max_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database_path = create_analytics_fixture_db(Path(tmp) / "erp.db")
            service = ErpReadService(SqliteErpReadAdapter(database_path))

            outputs = [
                ("erp.finance.sales_summary", service.sales_summary().model_dump()),
                (
                    "erp.finance.purchase_summary",
                    service.purchase_summary().model_dump(),
                ),
                (
                    "erp.warehouse.movement_summary",
                    service.movement_summary().model_dump(),
                ),
                (
                    "erp.fulfillment.summary",
                    service.fulfillment_summary().model_dump(),
                ),
            ]

            service_chart = ChartService()
            charts = service_chart.build_charts(outputs)

            self.assertEqual(len(charts), 2)
            self.assertEqual(charts[0].chart_type, "bar")
            self.assertEqual(charts[1].chart_type, "bar")


if __name__ == "__main__":
    unittest.main()
