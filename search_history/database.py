"""SQLite access for the conversation history module.

The database lives entirely inside ``search_history``.  Nothing in this module
knows about, or writes to, the ERP database under ``backend/data``.

Schema changes are additive only: :func:`initialize_database` creates missing
tables/indexes and adds the optional ``user_id`` column to an existing
``chat_sessions`` table without recreating it or touching existing rows.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

# Keep the database completely inside search_history
BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "history.db"


def get_connection(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Create a SQLite connection with foreign keys enabled.

    ``db_path`` defaults to :data:`DATABASE_PATH`.  Tests pass a temporary path
    so they never read or write the real history database.
    """
    path = Path(db_path) if db_path is not None else DATABASE_PATH
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


@contextmanager
def connection_scope(
    db_path: str | Path | None = None,
) -> Iterator[sqlite3.Connection]:
    """Yield a connection inside a transaction and always close it.

    The ``with connection`` block commits on success and rolls back on any
    exception, which gives the repository atomic write operations.
    """
    connection = get_connection(db_path)
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def _table_columns(
    connection: sqlite3.Connection, table: str
) -> set[str]:
    # ``table`` is always a module constant, never user input.
    return {
        row["name"] for row in connection.execute(f"PRAGMA table_info({table})")
    }


def initialize_database(db_path: str | Path | None = None) -> Path:
    """Create the conversation tables/indexes if they do not exist.

    Safe to call repeatedly.  Existing tables and rows are preserved; the only
    structural change is adding ``user_id`` when an older database is missing
    it (an additive ``ALTER TABLE``, never a table rebuild).
    """
    path = Path(db_path) if db_path is not None else DATABASE_PATH

    with connection_scope(path) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS chat_sessions (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (session_id)
                    REFERENCES chat_sessions(id)
                    ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_chat_sessions_updated
                ON chat_sessions(updated_at);

            CREATE INDEX IF NOT EXISTS idx_chat_messages_session
                ON chat_messages(session_id, id);
            """
        )

        if "user_id" not in _table_columns(connection, "chat_sessions"):
            connection.execute(
                "ALTER TABLE chat_sessions ADD COLUMN user_id TEXT"
            )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_chat_sessions_user
                ON chat_sessions(user_id)
            """
        )

    return path


if __name__ == "__main__":
    database_path = initialize_database()
    print(f"History database initialized: {database_path}")
