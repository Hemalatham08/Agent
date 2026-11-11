from __future__ import annotations

from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.agent.persistence.config import (
    get_agent_database_url,
    get_sqlite_database_path,
)


def _enable_sqlite_foreign_keys(
    dbapi_connection: Any,
    connection_record: Any,
) -> None:
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


def create_agent_engine(database_url: str | None = None) -> Engine:
    resolved_url = database_url or get_agent_database_url()
    url = make_url(resolved_url)

    if url.get_backend_name() != "sqlite":
        return create_engine(url, pool_pre_ping=True)

    database_path = get_sqlite_database_path(resolved_url)
    if database_path is not None:
        database_path.parent.mkdir(parents=True, exist_ok=True)

    engine_kwargs: dict[str, Any] = {
        "connect_args": {"check_same_thread": False},
    }
    if url.database in (None, "", ":memory:"):
        engine_kwargs["poolclass"] = StaticPool

    engine = create_engine(url, **engine_kwargs)
    event.listen(engine, "connect", _enable_sqlite_foreign_keys)
    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)
