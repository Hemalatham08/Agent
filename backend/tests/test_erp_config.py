from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.agent.erp.config import (
    DEFAULT_ERP_DATABASE_PATH,
    DEFAULT_ERP_QUERY_TIMEOUT_SECONDS,
    ERP_DATABASE_PATH_ENV,
    ERP_QUERY_TIMEOUT_SECONDS_ENV,
    ErpDatabaseConfig,
    get_erp_database_path,
    get_erp_query_timeout_seconds,
    validate_erp_database_path,
)
from backend.agent.erp.errors import ErpConfigurationError


class ErpConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self._temp_dir.name)
        self.database_path = self.root / "erp.db"
        self.database_path.write_bytes(b"fixture")

    def tearDown(self) -> None:
        self._temp_dir.cleanup()

    def test_default_path_points_at_backend_data(self) -> None:
        self.assertEqual(DEFAULT_ERP_DATABASE_PATH.name, "ifive_erp.db")
        self.assertEqual(DEFAULT_ERP_DATABASE_PATH.parent.name, "data")

    def test_valid_path_is_resolved(self) -> None:
        resolved = validate_erp_database_path(self.database_path)
        self.assertTrue(resolved.is_absolute())
        self.assertEqual(resolved, self.database_path.resolve())

    def test_missing_path_is_rejected(self) -> None:
        with self.assertRaises(ErpConfigurationError):
            validate_erp_database_path(self.root / "missing.db")

    def test_directory_path_is_rejected(self) -> None:
        with self.assertRaises(ErpConfigurationError):
            validate_erp_database_path(self.root)

    def test_empty_path_is_rejected(self) -> None:
        with self.assertRaises(ErpConfigurationError):
            validate_erp_database_path("")

    def test_empty_configured_environment_path_is_rejected(self) -> None:
        with patch.dict(
            os.environ,
            {ERP_DATABASE_PATH_ENV: ""},
            clear=False,
        ):
            with self.assertRaises(ErpConfigurationError):
                get_erp_database_path()

    def test_blank_configured_environment_path_is_rejected(self) -> None:
        with patch.dict(
            os.environ,
            {ERP_DATABASE_PATH_ENV: "   "},
            clear=False,
        ):
            with self.assertRaises(ErpConfigurationError):
                get_erp_database_path()

    def test_configured_environment_path_is_used(self) -> None:
        with patch.dict(
            os.environ,
            {ERP_DATABASE_PATH_ENV: str(self.database_path)},
            clear=False,
        ):
            self.assertEqual(
                get_erp_database_path(),
                self.database_path.resolve(),
            )

    def test_agent_database_path_is_rejected(self) -> None:
        agent_path = self.root / "agent.db"
        agent_path.write_bytes(b"agent")
        agent_url = f"sqlite:///{agent_path.as_posix()}"

        with patch.dict(
            os.environ,
            {"AGENT_DATABASE_URL": agent_url},
            clear=False,
        ):
            with self.assertRaises(ErpConfigurationError):
                validate_erp_database_path(agent_path)

    def test_query_timeout_defaults(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(ERP_QUERY_TIMEOUT_SECONDS_ENV, None)
            self.assertEqual(
                get_erp_query_timeout_seconds(),
                DEFAULT_ERP_QUERY_TIMEOUT_SECONDS,
            )

    def test_query_timeout_environment_value_is_used(self) -> None:
        with patch.dict(
            os.environ,
            {ERP_QUERY_TIMEOUT_SECONDS_ENV: "1.5"},
            clear=False,
        ):
            self.assertEqual(get_erp_query_timeout_seconds(), 1.5)

    def test_invalid_query_timeout_environment_value_is_rejected(self) -> None:
        for value in ("", " ", "0", "-1", "nan", "inf", "not-a-number"):
            with self.subTest(value=value):
                with patch.dict(
                    os.environ,
                    {ERP_QUERY_TIMEOUT_SECONDS_ENV: value},
                    clear=False,
                ):
                    with self.assertRaises(ErpConfigurationError):
                        get_erp_query_timeout_seconds()

    def test_config_from_path_validates_and_normalizes(self) -> None:
        config = ErpDatabaseConfig.from_path(
            self.database_path,
            query_timeout_seconds=2,
        )

        self.assertEqual(config.database_path, self.database_path.resolve())
        self.assertEqual(config.query_timeout_seconds, 2.0)

    def test_config_rejects_invalid_timeout(self) -> None:
        for value in (0, -1, float("nan"), float("inf"), True):
            with self.subTest(value=value):
                with self.assertRaises(ErpConfigurationError):
                    ErpDatabaseConfig.from_path(
                        self.database_path,
                        query_timeout_seconds=value,
                    )


if __name__ == "__main__":
    unittest.main()
