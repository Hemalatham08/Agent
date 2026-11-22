from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from backend.agent.erp.handlers import ErpToolHandlers
from backend.agent.erp.service import ErpReadService
from backend.agent.erp.sqlite_adapter import SqliteErpReadAdapter
from backend.agent.models import utc_now
from backend.agent.tools.contracts import (
    ToolExecutionContext,
    ToolExecutionRequest,
    ToolExecutionStatus,
)
from backend.agent.tools.executor import ToolExecutor
from backend.agent.tools.registry import ToolRegistry
from backend.agent.erp.registration import register_erp_tools
from backend.tests.analytics_support import create_analytics_fixture_db


def make_context(tool_name: str) -> ToolExecutionContext:
    return ToolExecutionContext(
        execution_id="exec-financial",
        tool_name=tool_name,
        started_at=utc_now(),
    )


class FinancialHandlerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp_dir.cleanup)
        database_path = create_analytics_fixture_db(
            Path(self._temp_dir.name) / "erp.db"
        )
        self.service = ErpReadService(SqliteErpReadAdapter(database_path))
        self.handlers = ErpToolHandlers(self.service).as_mapping()

    def _invoke(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.handlers[tool_name](arguments, make_context(tool_name))

    def _assert_error(self, envelope: dict[str, Any], code: str) -> None:
        self.assertIs(envelope["ok"], False)
        self.assertEqual(envelope["error"]["code"], code)
        json.dumps(envelope, allow_nan=False)

    def test_sales_summary_default_envelope(self) -> None:
        envelope = self._invoke("erp.finance.sales_summary", {})

        self.assertIs(envelope["ok"], True)
        data = envelope["data"]
        self.assertEqual(data["group_by"], "month")
        self.assertEqual(data["basis"], "dispatched")
        self.assertEqual(data["currency"], "INR")
        self.assertEqual(data["rows"][0]["key"], "2026-10")
        self.assertAlmostEqual(data["totals"]["revenue"], 5200.0)
        self.assertAlmostEqual(data["totals"]["gross_profit"], 2020.0)

    def test_sales_summary_product_booked_with_limit(self) -> None:
        envelope = self._invoke(
            "erp.finance.sales_summary",
            {"group_by": "product", "basis": "booked", "limit": 2},
        )

        self.assertIs(envelope["ok"], True)
        data = envelope["data"]
        self.assertEqual(data["row_count"], 2)
        self.assertIs(data["truncated"], True)
        self.assertAlmostEqual(data["totals"]["revenue"], 14150.0)
        self.assertAlmostEqual(data["totals"]["cost"], 8910.0)
        self.assertEqual(
            [row["key"] for row in data["rows"]],
            ["PRD005", "PRD006"],
        )

    def test_invoiced_product_basis_is_rejected(self) -> None:
        envelope = self._invoke(
            "erp.finance.sales_summary",
            {"group_by": "product", "basis": "invoiced"},
        )
        self._assert_error(envelope, "erp_invalid_arguments")

    def test_purchase_summary_default_and_supplier(self) -> None:
        default_envelope = self._invoke(
            "erp.finance.purchase_summary",
            {},
        )
        self.assertIs(default_envelope["ok"], True)
        self.assertEqual(default_envelope["data"]["group_by"], "month")
        self.assertEqual(default_envelope["data"]["basis"], "received")
        self.assertAlmostEqual(
            default_envelope["data"]["totals"]["received_value"],
            6800.0,
        )

        supplier_envelope = self._invoke(
            "erp.finance.purchase_summary",
            {"group_by": "supplier", "basis": "ordered"},
        )
        self.assertIs(supplier_envelope["ok"], True)
        self.assertEqual(
            [row["key"] for row in supplier_envelope["data"]["rows"]],
            ["SUP003", "SUP004", "SUP001", "SUP002"],
        )
        self.assertAlmostEqual(
            supplier_envelope["data"]["totals"]["open_value"],
            15300.0,
        )

    def test_movement_summary_defaults_to_warehouse(self) -> None:
        envelope = self._invoke("erp.warehouse.movement_summary", {})

        self.assertIs(envelope["ok"], True)
        data = envelope["data"]
        self.assertEqual(data["group_by"], "warehouse")
        self.assertEqual(
            [row["key"] for row in data["rows"]],
            ["WH001", "WH002"],
        )
        self.assertEqual(data["rows"][1]["receipts_net_qty"], 738)
        self.assertEqual(data["rows"][1]["net_change"], 1008)
        self.assertEqual(data["totals"]["receipts_net_qty"], 1252)
        self.assertEqual(data["totals"]["net_change"], 2242)

    def test_fulfillment_summary_defaults_to_carrier(self) -> None:
        envelope = self._invoke("erp.fulfillment.summary", {})

        self.assertIs(envelope["ok"], True)
        data = envelope["data"]
        self.assertEqual(data["group_by"], "carrier")
        self.assertEqual(data["totals"]["picked_qty"], 770)
        self.assertEqual(data["totals"]["dispatched_qty"], 750)
        self.assertAlmostEqual(data["totals"]["pick_fill_pct"], 97.4)
        self.assertAlmostEqual(data["totals"]["order_fill_pct"], 97.4)
        self.assertAlmostEqual(
            data["totals"]["dispatched_order_fill_pct"],
            97.4,
        )

    def test_fulfillment_product_all_order_fill(self) -> None:
        envelope = self._invoke(
            "erp.fulfillment.summary",
            {"group_by": "product"},
        )

        self.assertIs(envelope["ok"], True)
        data = envelope["data"]
        self.assertEqual(data["totals"]["ordered_qty"], 1600)
        self.assertAlmostEqual(data["totals"]["order_fill_pct"], 46.88)
        values = {row["key"]: row for row in data["rows"]}
        self.assertEqual(values["PRD002"]["ordered_qty"], 350)
        self.assertEqual(values["PRD002"]["dispatched_qty"], 80)
        self.assertAlmostEqual(values["PRD002"]["order_fill_pct"], 22.86)
        self.assertIsNone(values["PRD005"]["pick_fill_pct"])

    def test_invalid_arguments_are_rejected(self) -> None:
        cases = (
            ("erp.finance.sales_summary", {"group_by": "region"}),
            ("erp.finance.sales_summary", {"basis": "cash"}),
            ("erp.finance.sales_summary", {"date_from": "2026/10/01"}),
            ("erp.finance.sales_summary", {"limit": 0}),
            ("erp.finance.sales_summary", {"limit": 51}),
            ("erp.finance.purchase_summary", {"group_by": "customer"}),
            ("erp.warehouse.movement_summary", {"group_by": "supplier"}),
            ("erp.fulfillment.summary", {"group_by": "warehouse"}),
            ("erp.fulfillment.summary", {"date_to": "not-a-date"}),
        )
        for tool_name, arguments in cases:
            with self.subTest(tool=tool_name, arguments=arguments):
                envelope = self._invoke(tool_name, arguments)
                self._assert_error(envelope, "erp_invalid_arguments")

    def test_unknown_arguments_are_rejected(self) -> None:
        envelope = self._invoke(
            "erp.finance.sales_summary",
            {"sql": "SELECT * FROM invoices"},
        )
        self._assert_error(envelope, "erp_invalid_arguments")

    def test_outputs_exclude_sensitive_fields(self) -> None:
        sensitive = {
            "purchase_price",
            "selling_price",
            "unit_price",
            "unit_cost",
            "phone",
            "contact_email",
            "payment_id",
            "amount",
        }

        def walk(value: Any) -> None:
            if isinstance(value, dict):
                self.assertFalse(sensitive.intersection(value.keys()))
                for child in value.values():
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)

        for tool_name, arguments in (
            ("erp.finance.sales_summary", {"group_by": "product"}),
            ("erp.finance.purchase_summary", {"group_by": "supplier"}),
            ("erp.warehouse.movement_summary", {"group_by": "warehouse"}),
            ("erp.fulfillment.summary", {"group_by": "customer"}),
        ):
            with self.subTest(tool=tool_name):
                envelope = self._invoke(tool_name, arguments)
                self.assertIs(envelope["ok"], True)
                walk(envelope["data"])
                json.dumps(envelope, allow_nan=False)


class FinancialRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp_dir.cleanup)
        database_path = create_analytics_fixture_db(
            Path(self._temp_dir.name) / "erp.db"
        )
        self.service = ErpReadService(SqliteErpReadAdapter(database_path))
        self.registry = ToolRegistry()
        self.executor = ToolExecutor(self.registry)
        self.addCleanup(self.executor.shutdown)
        self.registration = register_erp_tools(
            self.registry,
            self.executor,
            self.service,
        )
        self.addCleanup(self.registration.unregister)

    def test_all_financial_tools_execute_through_runner(self) -> None:
        from backend.agent.erp.runner import ErpToolRunner

        runner = ErpToolRunner(self.executor)

        cases = (
            ("erp.finance.sales_summary", {"group_by": "category"}),
            ("erp.finance.purchase_summary", {"group_by": "product"}),
            ("erp.warehouse.movement_summary", {"group_by": "movement_type"}),
            ("erp.fulfillment.summary", {"group_by": "status"}),
        )
        for tool_name, arguments in cases:
            with self.subTest(tool=tool_name):
                result = runner.execute(
                    ToolExecutionRequest(
                        tool_name=tool_name,
                        arguments=arguments,
                    )
                )
                self.assertEqual(result.status, ToolExecutionStatus.SUCCEEDED)
                self.assertIsNone(result.error)
                self.assertIsInstance(result.output, dict)


if __name__ == "__main__":
    unittest.main()
