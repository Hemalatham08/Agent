"""Tests for database initialization and schema."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from search_history import database


def test_default_database_path_is_inside_search_history():
    """The default database must live in the search_history folder."""
    assert database.DATABASE_PATH.name == "history.db"
    assert database.DATABASE_PATH.parent.name == "search_history"
    assert "backend" not in database.DATABASE_PATH.parts


def test_initialize_creates_expected_schema(temp_db_path: Path):
    """initialize_database creates tables, indexes, and user_id column."""
    database.initialize_database(temp_db_path)

    conn = sqlite3.connect(temp_db_path)
    conn.row_factory = sqlite3.Row

    # Tables exist
    tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "chat_sessions" in tables
    assert "chat_messages" in tables

    # chat_sessions columns
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(chat_sessions)")}
    expected_cols = {"id", "title", "created_at", "updated_at", "user_id"}
    assert expected_cols.issubset(cols)

    # chat_messages columns
    mcols = {row["name"] for row in conn.execute("PRAGMA table_info(chat_messages)")}
    expected_mcols = {"id", "session_id", "role", "payload_json", "created_at"}
    assert expected_mcols.issubset(mcols)

    # Indexes exist
    indexes = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert "idx_chat_sessions_updated" in indexes
    assert "idx_chat_messages_session" in indexes
    assert "idx_chat_sessions_user" in indexes

    # Foreign keys are enabled on our connections
    conn2 = database.get_connection(temp_db_path)
    fk = conn2.execute("PRAGMA foreign_keys").fetchone()[0]
    assert fk == 1
    conn2.close()

    conn.close()


def test_initialize_is_idempotent_and_preserves_data(temp_db_path: Path, repo):
    """Repeated initialization must not destroy existing data."""
    from search_history.repository import ConversationRepository

    # Create a session and message
    repo.initialize()
    session_id = "550e8400-e29b-41d4-a716-446655440000"
    repo.create_session(session_id, "Test Session", user_id="user1")
    repo.add_message(session_id, "user", {"text": "Hello"})

    # Re-initialize
    database.initialize_database(temp_db_path)

    # Data should still be there
    session = repo.get_session(session_id, user_id="user1")
    assert session is not None
    assert session["title"] == "Test Session"

    messages = repo.get_messages(session_id, user_id="user1")
    assert len(messages) == 1
    assert messages[0]["payload"]["text"] == "Hello"


def test_connection_scope_commits_on_success(temp_db_path: Path):
    """Successful operations inside connection_scope are committed."""
    database.initialize_database(temp_db_path)
    with database.connection_scope(temp_db_path) as conn:
        conn.execute(
            "INSERT INTO chat_sessions (id, title) VALUES (?, ?)",
            ("test-id", "Test"),
        )

    # Verify committed
    conn2 = sqlite3.connect(temp_db_path)
    conn2.row_factory = sqlite3.Row
    row = conn2.execute("SELECT title FROM chat_sessions WHERE id = ?", ("test-id",)).fetchone()
    conn2.close()
    assert row is not None
    assert row["title"] == "Test"


def test_connection_scope_rolls_back_on_exception(temp_db_path: Path):
    """Exceptions inside connection_scope trigger a rollback."""
    database.initialize_database(temp_db_path)
    with pytest.raises(ValueError):
        with database.connection_scope(temp_db_path) as conn:
            conn.execute(
                "INSERT INTO chat_sessions (id, title) VALUES (?, ?)",
                ("test-id-2", "Test"),
            )
            raise ValueError("intentional error")

    # Verify rolled back
    conn2 = sqlite3.connect(temp_db_path)
    conn2.row_factory = sqlite3.Row
    row = conn2.execute("SELECT title FROM chat_sessions WHERE id = ?", ("test-id-2",)).fetchone()
    conn2.close()
    assert row is None


def test_foreign_key_cascade_delete(temp_db_path: Path, repo):
    """Deleting a session cascades to its messages via FK."""
    repo.initialize()
    session_id = "550e8400-e29b-41d4-a716-446655440000"
    repo.create_session(session_id, "Test", user_id="user1")
    repo.add_message(session_id, "user", {"text": "Hello"})
    repo.add_message(session_id, "assistant", {"answer": "Hi there"})

    # Delete the session
    repo.delete_session(session_id, user_id="user1")

    # Messages should be gone
    conn = sqlite3.connect(temp_db_path)
    count = conn.execute("SELECT COUNT(*) FROM chat_messages WHERE session_id = ?", (session_id,)).fetchone()[0]
    conn.close()
    assert count == 0


def test_user_id_column_added_to_existing_database(temp_db_path: Path):
    """user_id column is added if missing (additive migration)."""
    # Create old schema without user_id
    conn = sqlite3.connect(temp_db_path)
    conn.execute("""
        CREATE TABLE chat_sessions (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE
        )
    """)
    conn.commit()
    conn.close()

    # Initialize should add user_id column
    database.initialize_database(temp_db_path)

    conn = sqlite3.connect(temp_db_path)
    conn.row_factory = sqlite3.Row
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(chat_sessions)")}
    conn.close()
    assert "user_id" in cols