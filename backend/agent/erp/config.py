from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path

from backend.agent.erp.errors import ErpConfigurationError
from backend.agent.persistence.config import (
    DEFAULT_AGENT_DB_PATH,
    get_agent_database_url,
    get_sqlite_database_path,
)

ERP_DATABASE_PATH_ENV = "ERP_DATABASE_PATH"
ERP_QUERY_TIMEOUT_SECONDS_ENV = "ERP_QUERY_TIMEOUT_SECONDS"
DEFAULT_ERP_QUERY_TIMEOUT_SECONDS = 5.0
DEFAULT_ERP_DATABASE_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "ifive_erp.db"
)


def _normalize_timeout(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ErpConfigurationError(
            "ERP query timeout must be a positive number"
        )

    timeout = float(value)
    if not math.isfinite(timeout) or timeout <= 0:
        raise ErpConfigurationError(
            "ERP query timeout must be a positive number"
        )
    return timeout


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(os.path.abspath(str(left))) == os.path.normcase(
        os.path.abspath(str(right))
    )


def _agent_database_paths() -> tuple[Path, ...]:
    paths = [DEFAULT_AGENT_DB_PATH.resolve()]
    try:
        configured = get_sqlite_database_path(get_agent_database_url())
    except Exception:
        configured = None
    if configured is not None:
        paths.append(configured.expanduser().resolve())
    return tuple(paths)


def validate_erp_database_path(path: str | Path) -> Path:
    if isinstance(path, Path):
        raw = str(path).strip()
    elif isinstance(path, str):
        raw = path.strip()
    else:
        raise ErpConfigurationError("ERP database path must be a string")

    if not raw:
        raise ErpConfigurationError("ERP database path must not be empty")

    try:
        resolved = Path(raw).expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        raise ErpConfigurationError("ERP database path is invalid") from None

    if not resolved.exists():
        raise ErpConfigurationError("ERP database path does not exist")
    if not resolved.is_file():
        raise ErpConfigurationError(
            "ERP database path must be a regular file"
        )

    for agent_path in _agent_database_paths():
        if _same_path(resolved, agent_path):
            raise ErpConfigurationError(
                "ERP database path must not be the agent database"
            )

    return resolved


def get_erp_database_path() -> Path:
    if ERP_DATABASE_PATH_ENV not in os.environ:
        return validate_erp_database_path(DEFAULT_ERP_DATABASE_PATH)

    configured = os.environ[ERP_DATABASE_PATH_ENV]
    return validate_erp_database_path(configured)


def get_erp_query_timeout_seconds() -> float:
    raw = os.environ.get(ERP_QUERY_TIMEOUT_SECONDS_ENV)
    if raw is None:
        return DEFAULT_ERP_QUERY_TIMEOUT_SECONDS
    if not raw.strip():
        raise ErpConfigurationError(
            "ERP query timeout must be a positive number"
        )

    try:
        value = float(raw)
    except ValueError:
        raise ErpConfigurationError(
            "ERP query timeout must be a positive number"
        ) from None
    return _normalize_timeout(value)


@dataclass(frozen=True)
class ErpDatabaseConfig:
    database_path: Path
    query_timeout_seconds: float = DEFAULT_ERP_QUERY_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "database_path",
            validate_erp_database_path(self.database_path),
        )
        object.__setattr__(
            self,
            "query_timeout_seconds",
            _normalize_timeout(self.query_timeout_seconds),
        )

    @classmethod
    def from_path(
        cls,
        path: str | Path,
        *,
        query_timeout_seconds: float = DEFAULT_ERP_QUERY_TIMEOUT_SECONDS,
    ) -> ErpDatabaseConfig:
        return cls(
            database_path=validate_erp_database_path(path),
            query_timeout_seconds=query_timeout_seconds,
        )

    @classmethod
    def from_env(cls) -> ErpDatabaseConfig:
        return cls(
            database_path=get_erp_database_path(),
            query_timeout_seconds=get_erp_query_timeout_seconds(),
        )


__all__ = [
    "DEFAULT_ERP_DATABASE_PATH",
    "DEFAULT_ERP_QUERY_TIMEOUT_SECONDS",
    "ERP_DATABASE_PATH_ENV",
    "ERP_QUERY_TIMEOUT_SECONDS_ENV",
    "ErpDatabaseConfig",
    "get_erp_database_path",
    "get_erp_query_timeout_seconds",
    "validate_erp_database_path",
]
