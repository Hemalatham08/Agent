"""Tests for the ConversationRepository."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone

import pytest

from search_history.errors import (
    HistoryValidationError,
    InvalidMessageRoleError,
    InvalidPayloadError,
    SessionNotFoundError,
)
from search_history.repository import ConversationRepository
from search_history.validation import utc_now_iso


class TestSessionCreation:
    def test_create_session_with_all_fields(self, repo):
        session_id = str(uuid.uuid4())
        title = "My Conversation"
        user_id = "user123"
        created_at = utc_now_iso()

        session = repo.create_session(
            session_id=session_id,
            title=title,
            user_id=user_id,
            created_at=created_at,
        )

        assert session["id"] == session_id
        assert session["title"] == title
        assert session["user_id"] == user_id
        assert session["created_at"] == created_at
        assert session["updated_at"] == created_at
        assert session["message_count"] == 0

    def test_create_session_rejects_blank_title(self, repo):
        with pytest.raises(HistoryValidationError):
            repo.create_session(str(uuid.uuid4()), "   ")

    def test_create_session_rejects_long_title(self, repo):
        with pytest.raises(HistoryValidationError):
            repo.create_session(str(uuid.uuid4()), "x" * 201)

    def test_create_session_normalizes_user_id(self, repo):
        session_id = str(uuid.uuid4())
        session = repo.create_session(session_id, "Test", user_id="  user1  ")
        assert session["user_id"] == "user1"

    def test_create_session_none_user_id_stores_null(self, repo):
        session_id = str(uuid.uuid4())
        session = repo.create_session(session_id, "Test", user_id=None)
        assert session["user_id"] is None


class TestSessionRetrieval:
    def test_get_session_returns_none_for_missing(self, repo):
        assert repo.get_session("550e8400-e29b-41d4-a716-446655440000") is None

    def test_get_session_with_user_id_filters_ownership(self, repo):
        session_id = str(uuid.uuid4())
        repo.create_session(session_id, "User1 Session", user_id="user1")

        # Owner can see
        assert repo.get_session(session_id, user_id="user1") is not None
        # Different user cannot
        assert repo.get_session(session_id, user_id="user2") is None
        # No user_id (anonymous) can see all
        assert repo.get_session(session_id, user_id=None) is not None

    def test_get_session_anonymous_can_see_unowned(self, repo):
        session_id = str(uuid.uuid4())
        repo.create_session(session_id, "Unowned Session", user_id=None)
        assert repo.get_session(session_id, user_id="user1") is None  # strict ownership when user provided

    def test_get_session_include_messages(self, repo):
        session_id = str(uuid.uuid4())
        repo.create_session(session_id, "Test", user_id="user1")
        repo.add_message(session_id, "user", {"text": "Hello"})
        repo.add_message(session_id, "assistant", {"answer": "Hi"})

        session = repo.get_session(session_id, user_id="user1", include_messages=True)
        assert len(session["messages"]) == 2
        assert session["messages"][0]["role"] == "user"
        assert session["messages"][1]["role"] == "assistant"


class TestSessionListing:
    def test_list_sessions_newest_first(self, repo):
        id1 = str(uuid.uuid4())
        id2 = str(uuid.uuid4())

        # Create with explicit timestamps to control ordering
        t1 = "2024-01-01T10:00:00.000000+00:00"
        t2 = "2024-01-02T10:00:00.000000+00:00"

        repo.create_session(id1, "First", user_id="user1", created_at=t1)
        repo.add_message(id1, "user", {"text": "msg"}, created_at=t1)

        repo.create_session(id2, "Second", user_id="user1", created_at=t2)
        repo.add_message(id2, "user", {"text": "msg"}, created_at=t2)

        sessions = repo.list_sessions(user_id="user1")
        assert sessions[0]["id"] == id2  # newer first
        assert sessions[1]["id"] == id1

    def test_list_sessions_filters_by_user(self, repo):
        id1 = str(uuid.uuid4())
        id2 = str(uuid.uuid4())
        repo.create_session(id1, "User1 Session", user_id="user1")
        repo.create_session(id2, "User2 Session", user_id="user2")

        user1_sessions = repo.list_sessions(user_id="user1")
        user2_sessions = repo.list_sessions(user_id="user2")

        assert len(user1_sessions) == 1
        assert user1_sessions[0]["id"] == id1
        assert len(user2_sessions) == 1
        assert user2_sessions[0]["id"] == id2

    def test_list_sessions_pagination(self, repo):
        for i in range(5):
            repo.create_session(str(uuid.uuid4()), f"Session {i}", user_id="user1")

        page1 = repo.list_sessions(user_id="user1", limit=2, offset=0)
        page2 = repo.list_sessions(user_id="user1", limit=2, offset=2)

        assert len(page1) == 2
        assert len(page2) == 2
        assert page1[0]["id"] != page2[0]["id"]

    def test_list_sessions_validates_limit_and_offset(self, repo):
        with pytest.raises(HistoryValidationError):
            repo.list_sessions(limit=0)
        with pytest.raises(HistoryValidationError):
            repo.list_sessions(limit=201)
        with pytest.raises(HistoryValidationError):
            repo.list_sessions(offset=-1)


class TestMessageOperations:
    def test_add_user_message(self, repo):
        session_id = str(uuid.uuid4())
        repo.create_session(session_id, "Test", user_id="user1")

        msg = repo.add_message(session_id, "user", {"text": "Hello"})

        assert msg["role"] == "user"
        assert msg["payload"]["text"] == "Hello"
        assert msg["session_id"] == session_id
        assert msg["id"] > 0

    def test_add_assistant_message(self, repo):
        session_id = str(uuid.uuid4())
        repo.create_session(session_id, "Test", user_id="user1")

        payload = {
            "answer": "Hello there!",
            "summary": "Greeting",
            "table": {"columns": ["A"], "rows": [[1]]},
            "charts": [{"type": "bar"}],
            "sql": "SELECT 1",
            "tools": [{"name": "tool1"}],
            "metadata": {"key": "value"},
        }
        msg = repo.add_message(session_id, "assistant", payload)

        assert msg["role"] == "assistant"
        assert msg["payload"] == payload

    def test_structured_json_preserved_exactly(self, repo):
        session_id = str(uuid.uuid4())
        repo.create_session(session_id, "Test", user_id="user1")

        complex_payload = {
            "nested": {"deep": {"value": [1, 2, 3]}},
            "null_value": None,
            "bool_true": True,
            "bool_false": False,
            "number": 3.14159,
            "unicode": "Hello 世界 🌍",
        }
        msg = repo.add_message(session_id, "assistant", complex_payload)

        # Retrieve and verify exact preservation
        messages = repo.get_messages(session_id, user_id="user1")
        assert messages[0]["payload"] == complex_payload

    def test_add_message_rejects_invalid_role(self, repo):
        session_id = str(uuid.uuid4())
        repo.create_session(session_id, "Test", user_id="user1")

        with pytest.raises(InvalidMessageRoleError):
            repo.add_message(session_id, "system", {"text": "oops"})

    def test_add_message_rejects_non_dict_payload(self, repo):
        session_id = str(uuid.uuid4())
        repo.create_session(session_id, "Test", user_id="user1")

        with pytest.raises(InvalidPayloadError):
            repo.add_message(session_id, "user", "not a dict")

    def test_add_message_rejects_non_serializable_payload(self, repo):
        session_id = str(uuid.uuid4())
        repo.create_session(session_id, "Test", user_id="user1")

        class NotSerializable:
            pass

        with pytest.raises(InvalidPayloadError):
            repo.add_message(session_id, "user", {"obj": NotSerializable()})

    def test_add_message_updates_session_timestamp(self, repo):
        session_id = str(uuid.uuid4())
        repo.create_session(session_id, "Test", user_id="user1")

        before = repo.get_session(session_id, user_id="user1")["updated_at"]
        repo.add_message(session_id, "user", {"text": "Hello"})
        after = repo.get_session(session_id, user_id="user1")["updated_at"]

        assert after >= before

    def test_get_messages_orders_by_id_asc(self, repo):
        session_id = str(uuid.uuid4())
        repo.create_session(session_id, "Test", user_id="user1")
        repo.add_message(session_id, "user", {"text": "1"})
        repo.add_message(session_id, "assistant", {"answer": "2"})
        repo.add_message(session_id, "user", {"text": "3"})

        messages = repo.get_messages(session_id, user_id="user1")
        assert len(messages) == 3
        assert messages[0]["payload"]["text"] == "1"
        assert messages[1]["payload"]["answer"] == "2"
        assert messages[2]["payload"]["text"] == "3"

    def test_get_messages_raises_for_missing_session(self, repo):
        with pytest.raises(SessionNotFoundError):
            repo.get_messages("550e8400-e29b-41d4-a716-446655440000")

    def test_get_messages_respects_ownership(self, repo):
        session_id = str(uuid.uuid4())
        repo.create_session(session_id, "Test", user_id="user1")
        repo.add_message(session_id, "user", {"text": "Hello"})

        with pytest.raises(SessionNotFoundError):
            repo.get_messages(session_id, user_id="user2")


class TestSaveTurn:
    def test_save_turn_creates_new_session(self, repo):
        session_id = str(uuid.uuid4())
        session, user_msg, asst_msg = repo.save_turn(
            session_id=session_id,
            user_payload={"text": "Hello"},
            assistant_payload={"answer": "Hi"},
            title="New Chat",
            user_id="user1",
        )

        assert session["id"] == session_id
        assert session["title"] == "New Chat"
        assert session["message_count"] == 2
        assert user_msg["role"] == "user"
        assert user_msg["payload"]["text"] == "Hello"
        assert asst_msg["role"] == "assistant"
        assert asst_msg["payload"]["answer"] == "Hi"

    def test_save_turn_continues_existing_session(self, repo):
        session_id = str(uuid.uuid4())
        repo.create_session(session_id, "Existing", user_id="user1")
        repo.add_message(session_id, "user", {"text": "First"})
        repo.add_message(session_id, "assistant", {"answer": "Reply"})

        session, user_msg, asst_msg = repo.save_turn(
            session_id=session_id,
            user_payload={"text": "Second"},
            assistant_payload={"answer": "Reply 2"},
            user_id="user1",
        )

        assert session["message_count"] == 4
        assert user_msg["payload"]["text"] == "Second"

    def test_save_turn_rejects_missing_title_for_new_session(self, repo):
        session_id = str(uuid.uuid4())
        with pytest.raises(SessionNotFoundError):
            repo.save_turn(
                session_id=session_id,
                user_payload={"text": "Hello"},
                assistant_payload={"answer": "Hi"},
                title=None,  # missing for new session
            )

    def test_save_turn_is_atomic(self, repo):
        """If assistant payload is invalid, neither message is saved."""
        session_id = str(uuid.uuid4())

        class BadObject:
            pass

        with pytest.raises(InvalidPayloadError):
            repo.save_turn(
                session_id=session_id,
                user_payload={"text": "Hello"},
                assistant_payload={"bad": BadObject()},
                title="Test",
                user_id="user1",
            )

        # Session should not exist
        assert repo.get_session(session_id) is None


class TestSearch:
    def test_search_by_title(self, repo):
        id1 = str(uuid.uuid4())
        id2 = str(uuid.uuid4())
        repo.create_session(id1, "Project Alpha", user_id="user1")
        repo.create_session(id2, "Project Beta", user_id="user1")

        results = repo.search_sessions("Alpha", user_id="user1")
        assert len(results) == 1
        assert results[0]["id"] == id1

    def test_search_by_message_content(self, repo):
        id1 = str(uuid.uuid4())
        id2 = str(uuid.uuid4())
        repo.create_session(id1, "Session 1", user_id="user1")
        repo.create_session(id2, "Session 2", user_id="user1")
        repo.add_message(id1, "user", {"text": "Find the needle"})
        repo.add_message(id2, "user", {"text": "Haystack only"})

        results = repo.search_sessions("needle", user_id="user1")
        assert len(results) == 1
        assert results[0]["id"] == id1

    def test_search_escapes_wildcards(self, repo):
        """Percent and underscore in query are treated as literals."""
        id1 = str(uuid.uuid4())
        repo.create_session(id1, "100% Complete", user_id="user1")

        # Should find the literal "100%"
        results = repo.search_sessions("100%", user_id="user1")
        assert len(results) == 1

        # Should NOT match "100X" or similar
        results2 = repo.search_sessions("100X", user_id="user1")
        assert len(results2) == 0

    def test_search_filters_by_user(self, repo):
        id1 = str(uuid.uuid4())
        id2 = str(uuid.uuid4())
        repo.create_session(id1, "User1 Project", user_id="user1")
        repo.create_session(id2, "User2 Project", user_id="user2")

        results = repo.search_sessions("Project", user_id="user1")
        assert len(results) == 1
        assert results[0]["id"] == id1

    def test_search_rejects_blank_query(self, repo):
        with pytest.raises(HistoryValidationError):
            repo.search_sessions("")
        with pytest.raises(HistoryValidationError):
            repo.search_sessions("   ")


class TestDeletion:
    def test_delete_session_cascades_messages(self, repo):
        session_id = str(uuid.uuid4())
        repo.create_session(session_id, "Test", user_id="user1")
        repo.add_message(session_id, "user", {"text": "Hello"})
        repo.add_message(session_id, "assistant", {"answer": "Hi"})

        deleted = repo.delete_session(session_id, user_id="user1")
        assert deleted is True

        # Session gone
        assert repo.get_session(session_id, user_id="user1") is None
        # Messages gone (FK cascade)
        conn = sqlite3.connect(repo.db_path)
        count = conn.execute("SELECT COUNT(*) FROM chat_messages WHERE session_id = ?", (session_id,)).fetchone()[0]
        conn.close()
        assert count == 0

    def test_delete_session_returns_false_for_missing(self, repo):
        deleted = repo.delete_session("550e8400-e29b-41d4-a716-446655440000", user_id="user1")
        assert deleted is False

    def test_delete_session_enforces_ownership(self, repo):
        session_id = str(uuid.uuid4())
        repo.create_session(session_id, "Test", user_id="user1")

        deleted = repo.delete_session(session_id, user_id="user2")
        assert deleted is False  # cannot delete another user's session

        # Session still exists for owner
        assert repo.get_session(session_id, user_id="user1") is not None

    def test_clear_user_sessions(self, repo):
        id1 = str(uuid.uuid4())
        id2 = str(uuid.uuid4())
        id3 = str(uuid.uuid4())
        repo.create_session(id1, "User1 A", user_id="user1")
        repo.create_session(id2, "User1 B", user_id="user1")
        repo.create_session(id3, "User2 A", user_id="user2")
        repo.add_message(id1, "user", {"text": "msg"})
        repo.add_message(id3, "user", {"text": "msg"})

        deleted = repo.clear_user_sessions("user1")
        assert deleted == 2

        # User1 sessions gone
        assert repo.get_session(id1, user_id="user1") is None
        assert repo.get_session(id2, user_id="user1") is None
        # User2 session remains
        assert repo.get_session(id3, user_id="user2") is not None
        # Messages for user1 also gone
        conn = sqlite3.connect(repo.db_path)
        count = conn.execute("SELECT COUNT(*) FROM chat_messages WHERE session_id IN (?, ?)", (id1, id2)).fetchone()[0]
        conn.close()
        assert count == 0

    def test_clear_user_sessions_requires_user_id(self, repo):
        with pytest.raises(HistoryValidationError):
            repo.clear_user_sessions("")
        with pytest.raises(HistoryValidationError):
            repo.clear_user_sessions(None)


class TestValidation:
    def test_validate_session_id_accepts_valid_uuid(self):
        valid = "550e8400-e29b-41d4-a716-446655440000"
        assert ConversationRepository._validate_limit(50) == 50

    def test_validate_session_id_rejects_invalid(self):
        with pytest.raises(HistoryValidationError):
            ConversationRepository._validate_limit("not int")
        with pytest.raises(HistoryValidationError):
            ConversationRepository._validate_limit(0)