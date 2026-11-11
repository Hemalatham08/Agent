from __future__ import annotations

import math
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from time import monotonic
from typing import Any, Iterator, Sequence

from backend.agent.erp.config import (
    DEFAULT_ERP_QUERY_TIMEOUT_SECONDS,
    ErpDatabaseConfig,
)
from backend.agent.erp.errors import (
    ErpDatabaseError,
    ErpInvalidArgumentsError,
    ErpPermissionDeniedError,
    ErpQueryTimeoutError,
)


class SqliteErpReadAdapter:
    """SQLite adapter that opens one read-only connection per query."""

    def __init__(
        self,
        database_path: str | Path | ErpDatabaseConfig,
        *,
        query_timeout_seconds: float | None = None,
    ) -> None:
        if isinstance(database_path, ErpDatabaseConfig):
            if query_timeout_seconds is None:
                config = database_path
            else:
                config = ErpDatabaseConfig(
                    database_path=database_path.database_path,
                    query_timeout_seconds=query_timeout_seconds,
                )
        else:
            config = ErpDatabaseConfig.from_path(
                database_path,
                query_timeout_seconds=(
                    DEFAULT_ERP_QUERY_TIMEOUT_SECONDS
                    if query_timeout_seconds is None
                    else query_timeout_seconds
                ),
            )
        self._config = config

    @classmethod
    def from_env(cls) -> SqliteErpReadAdapter:
        return cls(ErpDatabaseConfig.from_env())

    @property
    def config(self) -> ErpDatabaseConfig:
        return self._config

    @property
    def database_path(self) -> Path:
        return self._config.database_path

    @property
    def query_timeout_seconds(self) -> float:
        return self._config.query_timeout_seconds

    def fetch_all(
        self,
        sql: str,
        parameters: Sequence[object] = (),
        *,
        deadline: float | None = None,
    ) -> list[dict[str, Any]]:
        self._validate_read_only_statement(sql)
        effective_deadline = self._resolve_deadline(deadline)

        try:
            with self._connect(effective_deadline) as connection:
                cursor = connection.execute(sql, tuple(parameters))
                return [dict(row) for row in cursor.fetchall()]
        except ErpQueryTimeoutError:
            raise
        except sqlite3.OperationalError as exc:
            if "interrupted" in str(exc).lower():
                raise ErpQueryTimeoutError() from None
            raise ErpDatabaseError() from None
        except sqlite3.Error:
            raise ErpDatabaseError() from None

    def fetch_one(
        self,
        sql: str,
        parameters: Sequence[object] = (),
        *,
        deadline: float | None = None,
    ) -> dict[str, Any] | None:
        rows = self.fetch_all(sql, parameters, deadline=deadline)
        return rows[0] if rows else None

    @contextmanager
    def _connect(self, deadline: float | None) -> Iterator[sqlite3.Connection]:
        uri = f"{self.database_path.as_uri()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=0.0)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only = ON")
            connection.execute("PRAGMA trusted_schema = OFF")
            connection.enable_load_extension(False)
            if deadline is not None:
                connection.set_progress_handler(
                    lambda: 1 if monotonic() >= deadline else 0,
                    1000,
                )
            yield connection
        finally:
            connection.close()

    def _resolve_deadline(self, deadline: float | None) -> float:
        if deadline is None:
            return monotonic() + self.query_timeout_seconds
        if (
            isinstance(deadline, bool)
            or not isinstance(deadline, (int, float))
            or not math.isfinite(deadline)
        ):
            raise ErpInvalidArgumentsError("deadline")
        return float(deadline)

    @staticmethod
    def _validate_read_only_statement(sql: str) -> None:
        if not isinstance(sql, str):
            raise ErpPermissionDeniedError(
                "Only fixed read-only SELECT statements are allowed"
            )

        statement = sql.strip()
        if not statement:
            raise ErpPermissionDeniedError(
                "Only fixed read-only SELECT statements are allowed"
            )
        if not statement.upper().startswith("SELECT"):
            raise ErpPermissionDeniedError(
                "Only fixed read-only SELECT statements are allowed"
            )

        without_trailing = statement.rstrip()
        while without_trailing.endswith(";"):
            without_trailing = without_trailing[:-1].rstrip()
        if ";" in without_trailing:
            raise ErpPermissionDeniedError(
                "Multiple SQL statements are not allowed"
            )


__all__ = ["SqliteErpReadAdapter"]
