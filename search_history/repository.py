"""SQL data access for conversations and messages.

Every statement uses parameter binding.  Writes run inside transactions via
:func:`search_history.database.connection_scope`.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from .database import (
    DATABASE_PATH,
    connection_scope,
    initialize_database,
)
from .errors import HistoryValidationError, SessionNotFoundError
from .validation import (
    deserialize_payload,
    ensure_json_object,
    normalize_user_id,
    serialize_payload,
    utc_now_iso,
    validate_role,
    validate_session_id,
)

_SESSION_SELECT = """
    SELECT
        s.id,
        s.title,
        s.user_id,
        s.created_at,
        s.updated_at,
        (
            SELECT COUNT(*)
            FROM chat_messages m
            WHERE m.session_id = s.id
        ) AS message_count
    FROM chat_sessions s
"""

_MESSAGE_SELECT = """
    SELECT id, session_id, role, payload_json, created_at
    FROM chat_messages
    WHERE session_id = ?
    ORDER BY id ASC
"""


def _escape_like(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


class ConversationRepository:
    """Persistence layer for conversation history."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path is not None else DATABASE_PATH

    def initialize(self) -> None:
        initialize_database(self.db_path)

    def _scope(self):
        return connection_scope(self.db_path)

    # ------------------------------------------------------------------
    # Session helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _row_to_session(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["message_count"] = int(data.get("message_count") or 0)
        return data

    @staticmethod
    def _row_to_message(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "session_id": row["session_id"],
            "role": row["role"],
            "payload": deserialize_payload(row["payload_json"]),
            "created_at": row["created_at"],
        }

    @staticmethod
    def _is_visible(row: sqlite3.Row, user_id: str | None) -> bool:
        # Anonymous access (no user_id) may read any conversation.  Once a
        # user_id is supplied, ownership must match exactly.
        return user_id is None or row["user_id"] == user_id

    @staticmethod
    def _validate_title(title: str) -> str:
        if not isinstance(title, str):
            raise HistoryValidationError("title must be a string.")
        cleaned = title.strip()
        if not cleaned:
            raise HistoryValidationError("title must not be blank.")
        if len(cleaned) > 200:
            raise HistoryValidationError(
                "title must be at most 200 characters."
            )
        return cleaned

    def _fetch_session_row(
        self, connection: sqlite3.Connection, session_id: str
    ) -> sqlite3.Row | None:
        return connection.execute(
            _SESSION_SELECT + " WHERE s.id = ?",
            (session_id,),
        ).fetchone()

    def _fetch_messages(
        self, connection: sqlite3.Connection, session_id: str
    ) -> list[dict[str, Any]]:
        return [
            self._row_to_message(row)
            for row in connection.execute(_MESSAGE_SELECT, (session_id,))
        ]

    def _insert_message(
        self,
        connection: sqlite3.Connection,
        session_id: str,
        role: str,
        payload: dict[str, Any],
        created_at: str,
    ) -> dict[str, Any]:
        role_value = validate_role(role)
        payload_json = serialize_payload(payload)
        cursor = connection.execute(
            """
            INSERT INTO chat_messages
                (session_id, role, payload_json, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (session_id, role_value, payload_json, created_at),
        )
        return {
            "id": int(cursor.lastrowid),
            "session_id": session_id,
            "role": role_value,
            "payload": payload,
            "created_at": created_at,
        }

    # ------------------------------------------------------------------
    # Session operations
    # ------------------------------------------------------------------
    def create_session(
        self,
        session_id: str,
        title: str,
        user_id: str | None = None,
        created_at: str | None = None,
    ) -> dict[str, Any]:
        canonical_id = validate_session_id(session_id)
        title_value = self._validate_title(title)
        owner = normalize_user_id(user_id)
        timestamp = created_at or utc_now_iso()

        with self._scope() as connection:
            connection.execute(
                """
                INSERT INTO chat_sessions
                    (id, title, user_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (canonical_id, title_value, owner, timestamp, timestamp),
            )
            row = self._fetch_session_row(connection, canonical_id)

        return self._row_to_session(row)

    def get_session(
        self,
        session_id: str,
        user_id: str | None = None,
        include_messages: bool = False,
    ) -> dict[str, Any] | None:
        canonical_id = validate_session_id(session_id)
        owner = normalize_user_id(user_id)

        with self._scope() as connection:
            row = self._fetch_session_row(connection, canonical_id)
            if row is None or not self._is_visible(row, owner):
                return None
            session = self._row_to_session(row)
            if include_messages:
                session["messages"] = self._fetch_messages(
                    connection, canonical_id
                )

        return session

    def list_sessions(
        self,
        user_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        owner = normalize_user_id(user_id)
        limit = self._validate_limit(limit)
        offset = self._validate_offset(offset)

        sql = _SESSION_SELECT
        params: list[Any] = []
        if owner is not None:
            sql += " WHERE s.user_id = ?"
            params.append(owner)
        sql += " ORDER BY s.updated_at DESC, s.id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with self._scope() as connection:
            return [
                self._row_to_session(row)
                for row in connection.execute(sql, params)
            ]

    def search_sessions(
        self,
        query: str,
        user_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        if not isinstance(query, str) or not query.strip():
            raise HistoryValidationError("search query must not be blank.")
        owner = normalize_user_id(user_id)
        limit = self._validate_limit(limit)
        offset = self._validate_offset(offset)

        pattern = f"%{_escape_like(query.strip())}%"
        sql = _SESSION_SELECT + """
            WHERE (
                s.title LIKE ? ESCAPE '\\'
                OR EXISTS (
                    SELECT 1
                    FROM chat_messages m
                    WHERE m.session_id = s.id
                      AND m.payload_json LIKE ? ESCAPE '\\'
                )
            )
        """
        params: list[Any] = [pattern, pattern]
        if owner is not None:
            sql += " AND s.user_id = ?"
            params.append(owner)
        sql += " ORDER BY s.updated_at DESC, s.id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with self._scope() as connection:
            return [
                self._row_to_session(row)
                for row in connection.execute(sql, params)
            ]

    def delete_session(
        self, session_id: str, user_id: str | None = None
    ) -> bool:
        canonical_id = validate_session_id(session_id)
        owner = normalize_user_id(user_id)

        with self._scope() as connection:
            row = self._fetch_session_row(connection, canonical_id)
            if row is None or not self._is_visible(row, owner):
                return False
            connection.execute(
                "DELETE FROM chat_sessions WHERE id = ?",
                (canonical_id,),
            )

        return True

    def clear_user_sessions(self, user_id: str) -> int:
        owner = normalize_user_id(user_id)
        if owner is None:
            raise HistoryValidationError(
                "user_id is required to clear conversation history."
            )

        with self._scope() as connection:
            cursor = connection.execute(
                "DELETE FROM chat_sessions WHERE user_id = ?",
                (owner,),
            )
            return int(cursor.rowcount)

    def session_exists(
        self, session_id: str, user_id: str | None = None
    ) -> bool:
        return self.get_session(session_id, user_id=user_id) is not None

    # ------------------------------------------------------------------
    # Message operations
    # ------------------------------------------------------------------
    def add_message(
        self,
        session_id: str,
        role: str,
        payload: dict[str, Any],
        created_at: str | None = None,
    ) -> dict[str, Any]:
        canonical_id = validate_session_id(session_id)
        role_value = validate_role(role)
        ensure_json_object(payload)
        timestamp = created_at or utc_now_iso()

        with self._scope() as connection:
            row = self._fetch_session_row(connection, canonical_id)
            if row is None:
                raise SessionNotFoundError(canonical_id)
            message = self._insert_message(
                connection,
                canonical_id,
                role_value,
                payload,
                timestamp,
            )
            connection.execute(
                "UPDATE chat_sessions SET updated_at = ? WHERE id = ?",
                (timestamp, canonical_id),
            )

        return message

    def get_messages(
        self, session_id: str, user_id: str | None = None
    ) -> list[dict[str, Any]]:
        canonical_id = validate_session_id(session_id)
        owner = normalize_user_id(user_id)

        with self._scope() as connection:
            row = self._fetch_session_row(connection, canonical_id)
            if row is None or not self._is_visible(row, owner):
                raise SessionNotFoundError(canonical_id)
            return self._fetch_messages(connection, canonical_id)

    def save_turn(
        self,
        *,
        session_id: str,
        user_payload: dict[str, Any],
        assistant_payload: dict[str, Any],
        title: str | None = None,
        user_id: str | None = None,
        created_at: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        """Atomically create/continue a conversation and save one full turn.

        Returns ``(session, user_message, assistant_message)``.  If the
        conversation does not exist and no ``title`` is supplied, or the
        conversation belongs to another user, ``SessionNotFoundError`` is
        raised and nothing is written.
        """
        canonical_id = validate_session_id(session_id)
        ensure_json_object(user_payload)
        ensure_json_object(assistant_payload)
        owner = normalize_user_id(user_id)
        timestamp = created_at or utc_now_iso()

        with self._scope() as connection:
            row = self._fetch_session_row(connection, canonical_id)
            if row is None:
                if title is None:
                    raise SessionNotFoundError(canonical_id)
                title_value = self._validate_title(title)
                connection.execute(
                    """
                    INSERT INTO chat_sessions
                        (id, title, user_id, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (canonical_id, title_value, owner, timestamp, timestamp),
                )
            else:
                if not self._is_visible(row, owner):
                    raise SessionNotFoundError(canonical_id)
                connection.execute(
                    "UPDATE chat_sessions SET updated_at = ? WHERE id = ?",
                    (timestamp, canonical_id),
                )

            user_message = self._insert_message(
                connection, canonical_id, "user", user_payload, timestamp
            )
            assistant_message = self._insert_message(
                connection,
                canonical_id,
                "assistant",
                assistant_payload,
                timestamp,
            )
            session_row = self._fetch_session_row(connection, canonical_id)

        return (
            self._row_to_session(session_row),
            user_message,
            assistant_message,
        )

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _validate_limit(limit: int) -> int:
        if not isinstance(limit, int) or isinstance(limit, bool):
            raise HistoryValidationError("limit must be an integer.")
        if limit < 1 or limit > 200:
            raise HistoryValidationError("limit must be between 1 and 200.")
        return limit

    @staticmethod
    def _validate_offset(offset: int) -> int:
        if not isinstance(offset, int) or isinstance(offset, bool):
            raise HistoryValidationError("offset must be an integer.")
        if offset < 0:
            raise HistoryValidationError("offset must not be negative.")
        return offset
