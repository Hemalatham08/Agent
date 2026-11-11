from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy.engine import make_url

AGENT_DATABASE_URL_ENV = "AGENT_DATABASE_URL"

DEFAULT_AGENT_DB_PATH = (
    Path(__file__).resolve().parents[2] / "agent_data" / "agent.db"
)


def default_agent_database_url() -> str:
    return f"sqlite:///{DEFAULT_AGENT_DB_PATH.as_posix()}"


def get_agent_database_url() -> str:
    configured = os.getenv(AGENT_DATABASE_URL_ENV, "").strip()
    return configured or default_agent_database_url()


def get_sqlite_database_path(database_url: str) -> Path | None:
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite":
        return None

    database = url.database
    if not database or database == ":memory:":
        return None

    return Path(database).expanduser()
