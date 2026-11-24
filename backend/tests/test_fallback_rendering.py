"""Regression tests for human-readable fallback rendering.

Verifies that the deterministic fallback answer renders product, inventory,
and warehouse results as readable tables instead of raw JSON, while leaving
analytics rendering unchanged and never inventing missing inventory data.
"""

from __future__ import annotations

import unittest

from backend.agent.orchestration.models import ToolCallSummary
from backend.agent.orchestration.orchestrator import AgentOrchestrator
from backend.agent.tools.contracts import ToolExecutionStatus


class TestFallbackRendering(unittest.TestCase):
    """Human-readable fallback table rendering regressions."""

    def _fallback(
        self,
        outputs: list[tuple[str, object]],
        summaries: list[ToolCallSummary] | None = None,
        *,
        intro: str = "Retrieved data:",
    ) -> str:
        return AgentOrchestrator._fallback_answer(
            summaries or [], outputs, intro=intro
        )

    # ------------------------------------------------------------------
    # Products
    # ------------------------------------------------------------------

    def test_products_rendered_as_readable_table(self) -> None:
        outputs = [
            (
                "erp.products.search",
                {
                    "items": [
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
                        {
                            "product_id": "PRD002",
                            "sku": "NUT-M10-SS304",
                            "product_name": "Hex Nut M10",
                            "category": "Nuts",
                            "material": "Stainless Steel",
                            "size": "M10",
                            "grade": "SS304",
                            "unit": "pieces",
                        },
                    ],
                    "row_count": 2,
                    "truncated": False,
                },
            )
        ]
        answer = self._fallback(outputs)

        self.assertIn("Products", answer)
        self.assertIn("Showing 2 rows.", answer)
        self.assertIn("PRD001", answer)
        self.assertIn("Hex Bolt M10", answer)
        self.assertIn("HEX-M10-SS304", answer)
        self.assertIn("Stainless Steel", answer)
        self.assertIn("pieces", answer)
        # Table header present
        self.assertIn("| Product ID |", answer)
        self.assertIn("| SKU |", answer)
        # Not raw JSON
        self.assertNotIn('"product_id": "PRD001"', answer)

    def test_products_empty_result(self) -> None:
        outputs = [
            (
                "erp.products.search",
                {"items": [], "row_count": 0, "truncated": False},
            )
        ]
        answer = self._fallback(outputs)

        self.assertIn("Products", answer)
        self.assertIn("Showing 0 rows.", answer)
        self.assertIn("No rows matched the query.", answer)

    def test_products_missing_fields_not_invented(self) -> None:
        outputs = [
            (
                "erp.products.search",
                {"items": [{"product_id": "PRD001"}], "row_count": 1},
            )
        ]
        answer = self._fallback(outputs)

        self.assertIn("PRD001", answer)
        # Missing fields render as a placeholder, not fabricated values.
        self.assertIn("—", answer)

    # ------------------------------------------------------------------
    # Inventory
    # ------------------------------------------------------------------

    def test_inventory_rendered_with_warehouse_quantities(self) -> None:
        outputs = [
            (
                "erp.inventory.get",
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
        # Real quantities, not JSON.
        self.assertIn("420", answer)
        self.assertIn("180", answer)
        self.assertNotIn('"on_hand_qty": 420', answer)

    def test_zero_stock_displayed_as_zero(self) -> None:
        outputs = [
            (
                "erp.inventory.get",
                {
                    "items": [
                        {
                            "product_id": "PRD004",
                            "product_name": "Under_score Widget",
                            "warehouse_id": "WH002",
                            "warehouse_name": "Secondary Warehouse",
                            "on_hand_qty": 0,
                            "reserved_qty": 0,
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

        self.assertIn("PRD004", answer)
        # Zero quantities remain zero.
        self.assertIn("| 0 |", answer)

    def test_missing_inventory_data_not_fabricated(self) -> None:
        # PRD006 was never looked up: it must not appear with invented stock.
        outputs = [
            (
                "erp.inventory.get",
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
                        }
                    ],
                    "row_count": 1,
                },
            )
        ]
        answer = self._fallback(outputs)

        self.assertIn("PRD001", answer)
        self.assertNotIn("PRD006", answer)

    def test_inventory_missing_fields_not_invented(self) -> None:
        outputs = [
            (
                "erp.inventory.get",
                {
                    "items": [
                        {
                            "product_id": "PRD001",
                            "product_name": "Hex Bolt M10",
                            # warehouse quantities deliberately absent
                        }
                    ],
                    "row_count": 1,
                },
            )
        ]
        answer = self._fallback(outputs)

        self.assertIn("PRD001", answer)
        # Missing numeric fields render as a placeholder, not zero.
        self.assertIn("—", answer)

    # ------------------------------------------------------------------
    # Warehouses
    # ------------------------------------------------------------------

    def test_warehouses_rendered_correctly(self) -> None:
        outputs = [
            (
                "erp.warehouses.list",
                {
                    "items": [
                        {
                            "warehouse_id": "WH001",
                            "warehouse_name": "Main Warehouse",
                            "city": "Chennai",
                        },
                        {
                            "warehouse_id": "WH002",
                            "warehouse_name": "Secondary Warehouse",
                            "city": "Coimbatore",
                        },
                    ],
                    "row_count": 2,
                },
            )
        ]
        answer = self._fallback(outputs)

        self.assertIn("Warehouses", answer)
        self.assertIn("WH001", answer)
        self.assertIn("Main Warehouse", answer)
        self.assertIn("Chennai", answer)
        self.assertIn("WH002", answer)
        self.assertIn("Secondary Warehouse", answer)
        self.assertIn("Coimbatore", answer)
        self.assertIn("| Warehouse ID |", answer)
        self.assertIn("| City |", answer)

    # ------------------------------------------------------------------
    # Low stock
    # ------------------------------------------------------------------

    def test_low_stock_rendered_as_inventory_table(self) -> None:
        outputs = [
            (
                "erp.inventory.low_stock",
                {
                    "items": [
                        {
                            "product_id": "PRD003",
                            "product_name": "100% Steel Plate",
                            "warehouse_id": "WH001",
                            "warehouse_name": "Main Warehouse",
                            "on_hand_qty": 5,
                            "reserved_qty": 0,
                            "free_stock": 5,
                            "reorder_level": 10,
                            "low_stock": True,
                        }
                    ],
                    "row_count": 1,
                },
            )
        ]
        answer = self._fallback(outputs)

        self.assertIn("Inventory", answer)
        self.assertIn("PRD003", answer)
        self.assertIn("WH001", answer)
        self.assertIn("5", answer)

    # ------------------------------------------------------------------
    # Analytics unchanged
    # ------------------------------------------------------------------

    def test_analytics_rendering_unchanged(self) -> None:
        outputs = [
            (
                "erp.finance.sales_summary",
                {
                    "group_by": "month",
                    "basis": "dispatched",
                    "rows": [
                        {"key": "2024-01", "label": "January", "orders": 10, "revenue": 1250.00}
                    ],
                    "row_count": 1,
                },
            )
        ]
        answer = self._fallback(outputs)

        # Analytics path still produces its own readable table, not raw JSON.
        self.assertIn("Sales summary by month", answer)
        self.assertIn("January", answer)
        self.assertNotIn('"key": "2024-01"', answer)

    # ------------------------------------------------------------------
    # Empty and malformed outputs
    # ------------------------------------------------------------------

    def test_empty_outputs(self) -> None:
        answer = self._fallback([])
        self.assertIn("- No tool data could be retrieved.", answer)

    def test_malformed_output_handled_safely(self) -> None:
        outputs = [
            ("erp.products.search", "not a mapping"),
            ("erp.inventory.get", None),
            ("erp.warehouses.list", {"items": "not a list"}),
        ]
        # Should not raise; falls back to generic JSON rendering safely.
        answer = self._fallback(outputs)
        self.assertIsInstance(answer, str)
        self.assertIn("Retrieved data:", answer)

    def test_unknown_tool_uses_generic_json(self) -> None:
        outputs = [
            ("erp.unknown.tool", {"foo": "bar"}),
        ]
        answer = self._fallback(outputs)
        self.assertIn("erp.unknown.tool", answer)
        self.assertIn('"foo": "bar"', answer)

    # ------------------------------------------------------------------
    # Output bounded
    # ------------------------------------------------------------------

    def test_output_remains_bounded(self) -> None:
        # Many rows to exceed the fallback char limit.
        items = [
            {
                "product_id": f"PRD{index:03d}",
                "sku": f"SKU-{index}",
                "product_name": f"Product {index}",
                "category": "Bolts",
                "material": "Steel",
                "size": "M10",
                "grade": "SS304",
                "unit": "pieces",
            }
            for index in range(200)
        ]
        outputs = [
            (
                "erp.products.search",
                {"items": items, "row_count": len(items), "truncated": False},
            )
        ]
        answer = self._fallback(outputs)

        # Bounded by the existing fallback size limit.
        self.assertIn("... (truncated)", answer)
        self.assertLessEqual(len(answer), 1500)

    # ------------------------------------------------------------------
    # Tool-call summaries preserved
    # ------------------------------------------------------------------

    def test_failure_summaries_appended(self) -> None:
        outputs = [
            (
                "erp.products.search",
                {"items": [{"product_id": "PRD001"}], "row_count": 1},
            )
        ]
        summaries = [
            ToolCallSummary(
                tool_name="erp.inventory.get",
                arguments={"product_id": "PRD999"},
                status=ToolExecutionStatus.FAILED.value,
                error="Product not found",
            )
        ]
        answer = self._fallback(outputs, summaries)

        self.assertIn("Tool calls that did not return data", answer)
        self.assertIn("erp.inventory.get", answer)


if __name__ == "__main__":
    unittest.main()
