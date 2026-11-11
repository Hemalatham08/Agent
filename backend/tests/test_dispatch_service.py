"""Phase 3F — ErpReadService dispatch method tests."""
from __future__ import annotations

import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.agent.erp.errors import (
    ErpInvalidArgumentsError,
    ErpNotFoundError,
    ErpPermissionDeniedError,
)
from backend.agent.erp.models import DispatchDetail, DispatchSummary
from backend.agent.erp.service import ErpReadService
from backend.agent.erp.sqlite_adapter import SqliteErpReadAdapter
from backend.tests.erp_support import create_erp_fixture_db


def _make_service(root: Path) -> ErpReadService:
    db = create_erp_fixture_db(root / "erp.db")
    adapter = SqliteErpReadAdapter(db)
    return ErpReadService(adapter)


class TestGetDispatch(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.service = _make_service(Path(self._tmp.name))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_get_dispatch_success_dsp001(self) -> None:
        result = self.service.get_dispatch("DSP001")
        self.assertIsInstance(result, DispatchDetail)
        self.assertEqual(result.dispatch_id, "DSP001")
        self.assertEqual(result.so_id, "SO001")
        self.assertEqual(result.carrier, "BlueDart")
        self.assertEqual(result.tracking_number, "BD10001")
        self.assertEqual(result.status, "Partially Dispatched")
        self.assertEqual(result.dispatch_date, "2026-10-04")

    def test_get_dispatch_items_count(self) -> None:
        result = self.service.get_dispatch("DSP001")
        # DSP001 has DI001 and DI002
        self.assertEqual(result.items_row_count, 2)
        self.assertEqual(len(result.items), 2)
        self.assertFalse(result.items_truncated)

    def test_get_dispatch_item_fields(self) -> None:
        result = self.service.get_dispatch("DSP001")
        items_by_id = {item.dispatch_item_id: item for item in result.items}
        di001 = items_by_id["DI001"]
        self.assertEqual(di001.product_id, "PRD001")
        self.assertEqual(di001.product_name, "Hex Bolt M10")
        self.assertEqual(di001.picked_qty, 100)
        self.assertEqual(di001.dispatched_qty, 100)

    def test_get_dispatch_barcode_verified_bool_conversion(self) -> None:
        # DI001: barcode_verified stored as INTEGER 1 — must surface as bool True
        result = self.service.get_dispatch("DSP001")
        items_by_id = {item.dispatch_item_id: item for item in result.items}
        di001 = items_by_id["DI001"]
        self.assertIsInstance(di001.barcode_verified, bool)
        self.assertTrue(di001.barcode_verified)

    def test_get_dispatch_partial_dispatched_qty(self) -> None:
        # DI002: picked=50, dispatched=40 (partial)
        result = self.service.get_dispatch("DSP001")
        items_by_id = {item.dispatch_item_id: item for item in result.items}
        di002 = items_by_id["DI002"]
        self.assertEqual(di002.picked_qty, 50)
        self.assertEqual(di002.dispatched_qty, 40)

    def test_get_dispatch_success_dsp002(self) -> None:
        result = self.service.get_dispatch("DSP002")
        self.assertEqual(result.dispatch_id, "DSP002")
        self.assertEqual(result.so_id, "SO002")
        self.assertEqual(result.carrier, "DTDC")
        self.assertEqual(result.tracking_number, "DT20002")
        self.assertEqual(result.status, "Dispatched")
        self.assertEqual(len(result.items), 1)

    def test_get_dispatch_not_found(self) -> None:
        with self.assertRaises(ErpNotFoundError) as ctx:
            self.service.get_dispatch("DSP999")
        self.assertIn("dispatch", str(ctx.exception).lower())

    def test_get_dispatch_blank_id_raises(self) -> None:
        with self.assertRaises(ErpInvalidArgumentsError):
            self.service.get_dispatch("")

    def test_get_dispatch_whitespace_id_raises(self) -> None:
        with self.assertRaises(ErpInvalidArgumentsError):
            self.service.get_dispatch("   ")


class TestListDispatches(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.service = _make_service(Path(self._tmp.name))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_list_dispatches_no_filters(self) -> None:
        result = self.service.list_dispatches()
        # Fixture has 2 dispatch records
        self.assertEqual(result.row_count, 2)
        self.assertEqual(len(result.items), 2)
        self.assertFalse(result.truncated)

    def test_list_dispatches_default_limit_is_20(self) -> None:
        # limit omitted entirely uses the documented default of 20
        result = self.service.list_dispatches()
        self.assertLessEqual(result.row_count, 20)

    def test_list_dispatches_contains_expected_ids(self) -> None:
        result = self.service.list_dispatches()
        ids = {d.dispatch_id for d in result.items}
        self.assertIn("DSP001", ids)
        self.assertIn("DSP002", ids)

    def test_list_dispatches_filter_by_so_id(self) -> None:
        result = self.service.list_dispatches(so_id="SO001")
        self.assertEqual(result.row_count, 1)
        self.assertEqual(result.items[0].dispatch_id, "DSP001")

    def test_list_dispatches_filter_by_so_id_no_match(self) -> None:
        result = self.service.list_dispatches(so_id="SO999")
        self.assertEqual(result.row_count, 0)
        self.assertFalse(result.truncated)

    def test_list_dispatches_filter_by_status_dispatched(self) -> None:
        result = self.service.list_dispatches(status="Dispatched")
        self.assertEqual(result.row_count, 1)
        self.assertEqual(result.items[0].dispatch_id, "DSP002")

    def test_list_dispatches_filter_by_status_partially_dispatched(self) -> None:
        result = self.service.list_dispatches(status="Partially Dispatched")
        self.assertEqual(result.row_count, 1)
        self.assertEqual(result.items[0].dispatch_id, "DSP001")

    def test_list_dispatches_filter_by_carrier_bluedart(self) -> None:
        result = self.service.list_dispatches(carrier="BlueDart")
        self.assertEqual(result.row_count, 1)
        self.assertEqual(result.items[0].dispatch_id, "DSP001")

    def test_list_dispatches_filter_by_carrier_dtdc(self) -> None:
        result = self.service.list_dispatches(carrier="DTDC")
        self.assertEqual(result.row_count, 1)
        self.assertEqual(result.items[0].dispatch_id, "DSP002")

    def test_list_dispatches_filter_carrier_no_match(self) -> None:
        result = self.service.list_dispatches(carrier="FedEx")
        self.assertEqual(result.row_count, 0)

    def test_list_dispatches_combined_filters(self) -> None:
        result = self.service.list_dispatches(
            so_id="SO001",
            status="Partially Dispatched",
        )
        self.assertEqual(result.row_count, 1)
        self.assertEqual(result.items[0].dispatch_id, "DSP001")

    def test_list_dispatches_combined_filters_no_match(self) -> None:
        # SO002's dispatch has status=Dispatched, not Partially Dispatched
        result = self.service.list_dispatches(
            so_id="SO002",
            status="Partially Dispatched",
        )
        self.assertEqual(result.row_count, 0)

    def test_list_dispatches_deterministic_ordering(self) -> None:
        # Run twice — order must be identical (date DESC, id ASC)
        r1 = self.service.list_dispatches()
        r2 = self.service.list_dispatches()
        ids1 = [d.dispatch_id for d in r1.items]
        ids2 = [d.dispatch_id for d in r2.items]
        self.assertEqual(ids1, ids2)
        # DSP002 (2026-10-06) is newer than DSP001 (2026-10-04)
        self.assertEqual(ids1, ["DSP002", "DSP001"])

    def test_list_dispatches_summary_has_no_items(self) -> None:
        # list_dispatches returns DispatchSummary, not full item details
        result = self.service.list_dispatches()
        for dispatch in result.items:
            self.assertIsInstance(dispatch, DispatchSummary)
            self.assertNotIsInstance(dispatch, DispatchDetail)
            self.assertFalse(hasattr(dispatch, "items"))

    def test_list_dispatches_limit_1_truncated(self) -> None:
        result = self.service.list_dispatches(limit=1)
        self.assertEqual(result.row_count, 1)
        self.assertTrue(result.truncated)

    def test_list_dispatches_limit_equal_count_not_truncated(self) -> None:
        result = self.service.list_dispatches(limit=2)
        self.assertEqual(result.row_count, 2)
        self.assertFalse(result.truncated)

    def test_list_dispatches_max_limit_accepted(self) -> None:
        result = self.service.list_dispatches(limit=50)
        self.assertEqual(result.row_count, 2)
        self.assertFalse(result.truncated)

    def test_list_dispatches_zero_limit_raises(self) -> None:
        with self.assertRaises(ErpInvalidArgumentsError):
            self.service.list_dispatches(limit=0)

    def test_list_dispatches_negative_limit_raises(self) -> None:
        with self.assertRaises(ErpInvalidArgumentsError):
            self.service.list_dispatches(limit=-1)

    def test_list_dispatches_over_max_limit_raises(self) -> None:
        with self.assertRaises(ErpInvalidArgumentsError):
            self.service.list_dispatches(limit=51)

    def test_list_dispatches_boolean_limit_raises(self) -> None:
        with self.assertRaises(ErpInvalidArgumentsError):
            self.service.list_dispatches(limit=True)

    def test_list_dispatches_blank_filter_raises(self) -> None:
        for kwargs in (
            {"so_id": "  "},
            {"status": ""},
            {"carrier": " "},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ErpInvalidArgumentsError):
                    self.service.list_dispatches(**kwargs)

    def test_list_dispatches_overlong_filter_raises(self) -> None:
        with self.assertRaises(ErpInvalidArgumentsError):
            self.service.list_dispatches(so_id="S" * 65)


class TestGetDispatchesBySalesOrder(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.database_path = create_erp_fixture_db(self.root / "erp.db")
        self.service = ErpReadService(
            SqliteErpReadAdapter(self.database_path)
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _execute(self, sql: str, parameters: tuple[object, ...] = ()) -> None:
        connection = sqlite3.connect(self.database_path)
        try:
            connection.execute(sql, parameters)
            connection.commit()
        finally:
            connection.close()

    def test_by_sales_order_success(self) -> None:
        result = self.service.get_dispatches_by_sales_order("SO001")
        self.assertEqual(result.so_id, "SO001")
        self.assertEqual(result.dispatches_row_count, 1)
        self.assertFalse(result.dispatches_truncated)
        self.assertEqual(result.dispatches[0].dispatch_id, "DSP001")

    def test_by_sales_order_items_included(self) -> None:
        result = self.service.get_dispatches_by_sales_order("SO001")
        dispatch = result.dispatches[0]
        self.assertIsInstance(dispatch, DispatchDetail)
        self.assertEqual(dispatch.items_row_count, 2)
        self.assertFalse(dispatch.items_truncated)

    def test_by_sales_order_item_fields(self) -> None:
        result = self.service.get_dispatches_by_sales_order("SO001")
        dispatch = result.dispatches[0]
        item_ids = {item.dispatch_item_id for item in dispatch.items}
        self.assertIn("DI001", item_ids)
        self.assertIn("DI002", item_ids)
        products = {item.product_id for item in dispatch.items}
        self.assertEqual(products, {"PRD001", "PRD002"})

    def test_by_sales_order_item_quantities(self) -> None:
        result = self.service.get_dispatches_by_sales_order("SO001")
        items_by_id = {
            item.dispatch_item_id: item
            for item in result.dispatches[0].items
        }
        self.assertEqual(items_by_id["DI001"].dispatched_qty, 100)
        self.assertEqual(items_by_id["DI002"].dispatched_qty, 40)

    def test_by_sales_order_so002(self) -> None:
        result = self.service.get_dispatches_by_sales_order("SO002")
        self.assertEqual(result.so_id, "SO002")
        self.assertEqual(result.dispatches_row_count, 1)
        dispatch = result.dispatches[0]
        self.assertEqual(dispatch.dispatch_id, "DSP002")
        self.assertEqual(dispatch.items_row_count, 1)

    def test_by_sales_order_order_without_dispatches_returns_empty(self) -> None:
        self._execute(
            "INSERT INTO sales_orders VALUES (?, ?, ?, ?, ?)",
            ("SO003", "CUS001", "2026-10-07", "2026-10-08", "Pending"),
        )

        result = self.service.get_dispatches_by_sales_order("SO003")

        self.assertEqual(result.so_id, "SO003")
        self.assertEqual(result.dispatches, [])
        self.assertEqual(result.dispatches_row_count, 0)
        self.assertFalse(result.dispatches_truncated)

    def test_by_sales_order_not_found_raises(self) -> None:
        with self.assertRaises(ErpNotFoundError) as ctx:
            self.service.get_dispatches_by_sales_order("SO999")
        self.assertEqual(ctx.exception.details["resource"], "sales_order")

    def test_by_sales_order_blank_id_raises(self) -> None:
        with self.assertRaises(ErpInvalidArgumentsError):
            self.service.get_dispatches_by_sales_order("")

    def test_by_sales_order_barcode_verified_is_bool(self) -> None:
        result = self.service.get_dispatches_by_sales_order("SO001")
        for dispatch in result.dispatches:
            for item in dispatch.items:
                self.assertIsInstance(item.barcode_verified, bool)


class TestDispatchOutputSafety(unittest.TestCase):
    """Dispatch outputs must not leak financial or unapproved fields."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.service = _make_service(Path(self._tmp.name))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_dispatch_detail_dump_excludes_unapproved_fields(self) -> None:
        result = self.service.get_dispatch("DSP001").model_dump()
        allowed = {
            "dispatch_id",
            "so_id",
            "dispatch_date",
            "status",
            "carrier",
            "tracking_number",
            "items",
            "items_row_count",
            "items_truncated",
        }
        self.assertEqual(set(result), allowed)
        for item in result["items"]:
            self.assertEqual(
                set(item),
                {
                    "dispatch_item_id",
                    "product_id",
                    "product_name",
                    "picked_qty",
                    "dispatched_qty",
                    "barcode_verified",
                },
            )

    def test_dispatch_list_dump_excludes_unapproved_fields(self) -> None:
        result = self.service.list_dispatches().model_dump()
        self.assertEqual(set(result), {"items", "row_count", "truncated"})
        for summary in result["items"]:
            self.assertEqual(
                set(summary),
                {
                    "dispatch_id",
                    "so_id",
                    "dispatch_date",
                    "status",
                    "carrier",
                    "tracking_number",
                },
            )

    def test_by_sales_order_dump_excludes_unapproved_fields(self) -> None:
        result = self.service.get_dispatches_by_sales_order("SO001").model_dump()
        self.assertEqual(
            set(result),
            {"so_id", "dispatches", "dispatches_row_count", "dispatches_truncated"},
        )


class TestDispatchReadOnlySafety(unittest.TestCase):
    """Dispatch reads must stay read-only and must not mutate the database."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.database_path = create_erp_fixture_db(self.root / "erp.db")
        self.adapter = SqliteErpReadAdapter(self.database_path)
        self.service = ErpReadService(self.adapter)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_write_statements_are_rejected(self) -> None:
        for statement in (
            "INSERT INTO dispatches (dispatch_id) VALUES ('X')",
            "UPDATE dispatch_items SET dispatched_qty = 0",
            "DELETE FROM dispatches",
            "DROP TABLE dispatches",
        ):
            with self.subTest(statement=statement):
                with self.assertRaises(ErpPermissionDeniedError):
                    self.adapter.fetch_all(statement)

    def test_multiple_statements_are_rejected(self) -> None:
        with self.assertRaises(ErpPermissionDeniedError):
            self.adapter.fetch_all(
                "SELECT dispatch_id FROM dispatches; DELETE FROM dispatches"
            )

    def test_database_bytes_unchanged_after_dispatch_reads(self) -> None:
        before = hashlib.sha256(self.database_path.read_bytes()).hexdigest()
        self.service.list_dispatches(limit=50)
        self.service.get_dispatch("DSP001")
        self.service.get_dispatches_by_sales_order("SO001")
        after = hashlib.sha256(self.database_path.read_bytes()).hexdigest()
        self.assertEqual(before, after)

    def test_direct_sqlite_write_to_dispatches_fails(self) -> None:
        connection = sqlite3.connect(
            f"file:{self.database_path}?mode=ro", uri=True
        )
        try:
            with self.assertRaises(sqlite3.Error):
                connection.execute(
                    "INSERT INTO dispatches (dispatch_id) VALUES ('X')"
                )
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
