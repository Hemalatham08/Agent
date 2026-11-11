from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from time import monotonic
from unittest.mock import patch

from backend.agent.erp.config import ERP_DATABASE_PATH_ENV
from backend.agent.erp.errors import (
    ErpDatabaseError,
    ErpInvalidArgumentsError,
    ErpPermissionDeniedError,
    ErpQueryTimeoutError,
)
from backend.agent.erp.sqlite_adapter import SqliteErpReadAdapter
from backend.tests.erp_support import create_erp_fixture_db

_SLOW_SQL = """
SELECT count(*)
FROM (
    WITH RECURSIVE cnt(x) AS (
        SELECT 1
        UNION ALL
        SELECT x + 1 FROM cnt WHERE x < 1000000
    )
    SELECT x FROM cnt
)
"""


class SqliteErpReadAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self._temp_dir.name)
        self.database_path = create_erp_fixture_db(self.root / "erp.db")
        self.adapter = SqliteErpReadAdapter(self.database_path)

    def tearDown(self) -> None:
        self._temp_dir.cleanup()

    def test_fetch_all_returns_dictionaries(self) -> None:
        rows = self.adapter.fetch_all(
            "SELECT product_id, product_name FROM products "
            "ORDER BY product_id LIMIT ?",
            (2,),
        )

        self.assertEqual(
            rows,
            [
                {
                    "product_id": "PRD001",
                    "product_name": "Hex Bolt M10",
                },
                {
                    "product_id": "PRD002",
                    "product_name": "Hex Nut M10",
                },
            ],
        )
        self.assertIsInstance(rows[0], dict)

    def test_fetch_one_returns_first_row_or_none(self) -> None:
        row = self.adapter.fetch_one(
            "SELECT product_id FROM products WHERE product_id = ?",
            ("PRD001",),
        )
        missing = self.adapter.fetch_one(
            "SELECT product_id FROM products WHERE product_id = ?",
            ("MISSING",),
        )

        self.assertEqual(row, {"product_id": "PRD001"})
        self.assertIsNone(missing)

    def test_non_select_statements_are_rejected(self) -> None:
        statements = (
            "INSERT INTO products (product_id) VALUES ('X')",
            "UPDATE products SET product_name = 'X'",
            "DELETE FROM products",
            "CREATE TABLE unexpected (id TEXT)",
            "DROP TABLE products",
            "PRAGMA query_only = OFF",
        )

        for statement in statements:
            with self.subTest(statement=statement):
                with self.assertRaises(ErpPermissionDeniedError):
                    self.adapter.fetch_all(statement)

    def test_multiple_statements_are_rejected(self) -> None:
        with self.assertRaises(ErpPermissionDeniedError):
            self.adapter.fetch_all("SELECT 1; SELECT 2")

    def test_single_trailing_semicolon_is_allowed(self) -> None:
        rows = self.adapter.fetch_all("SELECT 1 AS value;")
        self.assertEqual(rows, [{"value": 1}])

    def test_connection_pragmas_and_write_denial(self) -> None:
        with self.adapter._connect(None) as connection:
            query_only = connection.execute(
                "PRAGMA query_only"
            ).fetchone()[0]
            trusted_schema = connection.execute(
                "PRAGMA trusted_schema"
            ).fetchone()[0]

            self.assertEqual(query_only, 1)
            self.assertEqual(trusted_schema, 0)
            with self.assertRaises(sqlite3.Error):
                connection.execute(
                    "INSERT INTO products (product_id) VALUES ('X')"
                )
            with self.assertRaises(sqlite3.Error):
                connection.execute("SELECT load_extension('missing')")

    def test_missing_database_after_creation_fails_closed(self) -> None:
        self.database_path.unlink()

        with self.assertRaises(ErpDatabaseError):
            self.adapter.fetch_all("SELECT 1 AS value")

        self.assertFalse(self.database_path.exists())

    def test_corrupt_database_fails_closed(self) -> None:
        corrupt_path = self.root / "corrupt.db"
        corrupt_path.write_bytes(b"not a sqlite database")
        adapter = SqliteErpReadAdapter(corrupt_path)

        with self.assertRaises(ErpDatabaseError):
            adapter.fetch_all("SELECT product_id FROM products LIMIT 1")

    def test_wall_clock_deadline_interrupts_query(self) -> None:
        with self.assertRaises(ErpQueryTimeoutError):
            self.adapter.fetch_all(
                _SLOW_SQL,
                deadline=monotonic() - 1,
            )

    def test_invalid_deadline_is_rejected(self) -> None:
        for deadline in (True, float("nan"), float("inf"), "later"):
            with self.subTest(deadline=deadline):
                with self.assertRaises(ErpInvalidArgumentsError):
                    self.adapter.fetch_all(
                        "SELECT 1 AS value",
                        deadline=deadline,
                    )

    def test_adapter_from_environment(self) -> None:
        with patch.dict(
            os.environ,
            {ERP_DATABASE_PATH_ENV: str(self.database_path)},
            clear=False,
        ):
            adapter = SqliteErpReadAdapter.from_env()

        self.assertEqual(adapter.database_path, self.database_path.resolve())
        self.assertEqual(
            adapter.fetch_all("SELECT 1 AS value"),
            [{"value": 1}],
        )

    def test_adapter_exposes_configuration(self) -> None:
        self.assertEqual(
            self.adapter.database_path,
            self.database_path.resolve(),
        )
        self.assertEqual(self.adapter.query_timeout_seconds, 5.0)
        self.assertEqual(
            self.adapter.config.database_path,
            self.database_path.resolve(),
        )


if __name__ == "__main__":
    unittest.main()
