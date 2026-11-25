"""Tests for the ConversationService."""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import MagicMock

import pytest

from search_history.errors import (
    AssistantPayloadError,
    HistoryValidationError,
    SessionNotFoundError,
)
from search_history.service import (
    AnswerGenerator,
    ConversationService,
    MockAnswerGenerator,
)
from search_history.validation import build_title


class TestMockAnswerGenerator:
    def test_generates_structured_payload(self):
        gen = MockAnswerGenerator()
        payload = gen.generate(question="Hello", history=[])

        assert isinstance(payload, dict)
        assert "summary" in payload
        assert "answer" in payload
        assert "table" in payload
        assert "charts" in payload
        assert "sql" in payload
        assert "tools" in payload
        assert "metadata" in payload
        assert payload["metadata"]["generator"] == "mock"

    def test_includes_history_length_in_metadata(self):
        gen = MockAnswerGenerator()
        payload = gen.generate(question="Test", history=[{}, {}, {}])
        assert payload["metadata"]["history_messages"] == 3


class TestTitleGeneration:
    def test_title_from_first_question(self):
        title = build_title("What is the stock level for SKU-123?")
        assert title == "What is the stock level for SKU-123?"

    def test_title_truncation_at_40_chars(self):
        long_question = "What is the current inventory status for all products in the warehouse?"
        title = build_title(long_question)
        assert len(title) <= 40
        assert title.endswith("…")

    def test_title_collapses_whitespace(self):
        title = build_title("  What    is    the    stock?  ")
        assert title == "What is the stock?"

    def test_title_short_question_unchanged(self):
        title = build_title("Hi")
        assert title == "Hi"


class TestChat:
    def test_chat_creates_new_conversation(self, service):
        result = service.chat("What is the stock?", user_id="user1")

        assert "session" in result
        assert "user_message" in result
        assert "assistant_message" in result

        session = result["session"]
        assert session["title"] == "What is the stock?"
        assert session["message_count"] == 2
        assert session["user_id"] == "user1"

        user_msg = result["user_message"]
        assert user_msg["role"] == "user"
        assert user_msg["payload"]["text"] == "What is the stock?"

        asst_msg = result["assistant_message"]
        assert asst_msg["role"] == "assistant"
        assert "answer" in asst_msg["payload"]

    def test_chat_continues_existing_conversation(self, service):
        # First turn
        result1 = service.chat("First question", user_id="user1")
        session_id = result1["session"]["id"]

        # Second turn
        result2 = service.chat("Second question", session_id=session_id, user_id="user1")

        assert result2["session"]["id"] == session_id
        assert result2["session"]["message_count"] == 4
        assert result2["session"]["title"] == "First question"  # title unchanged

    def test_chat_rejects_blank_message(self, service):
        with pytest.raises(ValueError):
            service.chat("   ")

    def test_chat_rejects_missing_session(self, service):
        fake_id = "550e8400-e29b-41d4-a716-446655440000"
        with pytest.raises(SessionNotFoundError):
            service.chat("Hello", session_id=fake_id, user_id="user1")

    def test_chat_enforces_ownership_on_continue(self, service):
        # Create as user1
        result = service.chat("Hello", user_id="user1")
        session_id = result["session"]["id"]

        # Try to continue as user2
        with pytest.raises(SessionNotFoundError):
            service.chat("Hello again", session_id=session_id, user_id="user2")

    def test_chat_generates_uuid_for_new_session(self, service):
        result = service.chat("Hello", user_id="user1")
        import uuid as uuid_module
        # Should be valid UUID
        uuid_module.UUID(result["session"]["id"])

    def test_chat_passes_history_to_generator(self, service):
        """Verify that conversation history is passed to the answer generator."""
        mock_gen = MagicMock(spec=AnswerGenerator)
        mock_gen.generate.return_value = {"answer": "Mocked"}
        svc = ConversationService(service.repository, mock_gen)

        # First turn
        result1 = svc.chat("First", user_id="user1")
        session_id = result1["session"]["id"]

        # Second turn - check history passed
        svc.chat("Second", session_id=session_id, user_id="user1")

        calls = mock_gen.generate.call_args_list
        assert len(calls) == 2
        # First call has empty history
        assert calls[0].kwargs["history"] == []
        # Second call has 2 messages (user + assistant)
        assert len(calls[1].kwargs["history"]) == 2


class TestAssistantPayloadValidation:
    def test_rejects_non_dict_from_generator(self, service):
        mock_gen = MagicMock(spec=AnswerGenerator)
        mock_gen.generate.return_value = "not a dict"
        svc = ConversationService(service.repository, mock_gen)

        with pytest.raises(AssistantPayloadError):
            svc.chat("Hello", user_id="user1")

    def test_rejects_non_serializable_from_generator(self, service):
        class NotSerializable:
            pass

        mock_gen = MagicMock(spec=AnswerGenerator)
        mock_gen.generate.return_value = {"bad": NotSerializable()}
        svc = ConversationService(service.repository, mock_gen)

        with pytest.raises(AssistantPayloadError):
            svc.chat("Hello", user_id="user1")

    def test_generator_exception_wrapped(self, service):
        mock_gen = MagicMock(spec=AnswerGenerator)
        mock_gen.generate.side_effect = RuntimeError("LLM down")
        svc = ConversationService(service.repository, mock_gen)

        with pytest.raises(AssistantPayloadError):
            svc.chat("Hello", user_id="user1")


class TestSessionManagement:
    def test_list_sessions(self, service):
        service.chat("First", user_id="user1")
        service.chat("Second", user_id="user1")

        sessions = service.list_sessions(user_id="user1")
        assert len(sessions) == 2
        # Newest first
        assert sessions[0]["title"] == "Second"
        assert sessions[1]["title"] == "First"

    def test_get_session_detail(self, service):
        result = service.chat("Hello", user_id="user1")
        session_id = result["session"]["id"]

        detail = service.get_session_detail(session_id, user_id="user1")
        assert detail["id"] == session_id
        assert len(detail["messages"]) == 2
        assert detail["messages"][0]["role"] == "user"
        assert detail["messages"][1]["role"] == "assistant"

    def test_get_session_detail_enforces_ownership(self, service):
        result = service.chat("Hello", user_id="user1")
        session_id = result["session"]["id"]

        with pytest.raises(SessionNotFoundError):
            service.get_session_detail(session_id, user_id="user2")

    def test_delete_session(self, service):
        result = service.chat("Hello", user_id="user1")
        session_id = result["session"]["id"]

        service.delete_session(session_id, user_id="user1")

        with pytest.raises(SessionNotFoundError):
            service.get_session_detail(session_id, user_id="user1")

    def test_delete_session_enforces_ownership(self, service):
        result = service.chat("Hello", user_id="user1")
        session_id = result["session"]["id"]

        with pytest.raises(SessionNotFoundError):
            service.delete_session(session_id, user_id="user2")

    def test_search(self, service):
        service.chat("Stock level for SKU-123", user_id="user1")
        service.chat("Inventory report", user_id="user1")

        results = service.search("stock", user_id="user1")
        assert len(results) == 1
        assert "Stock" in results[0]["title"]

    def test_search_by_message_content(self, service):
        service.chat("First question", user_id="user1")
        service.chat("Second question", user_id="user1")

        results = service.search("First", user_id="user1")
        assert len(results) == 1

    def test_clear_user_history(self, service):
        service.chat("User1 chat", user_id="user1")
        service.chat("User2 chat", user_id="user2")

        deleted = service.clear_user_history("user1")
        assert deleted == 1

        sessions = service.list_sessions(user_id="user1")
        assert len(sessions) == 0

        sessions2 = service.list_sessions(user_id="user2")
        assert len(sessions2) == 1

    def test_clear_user_history_rejects_empty(self, service):
        with pytest.raises(HistoryValidationError):
            service.clear_user_history("")
        with pytest.raises(HistoryValidationError):
            service.clear_user_history(None)


class TestOldSQLNotExecuted:
    """Verify that SQL stored in old conversations is never executed."""

    def test_sql_payload_stored_and_retrieved_but_not_executed(self, service):
        """SQL in assistant payload is just data, never executed."""
        # Create a conversation with SQL in the payload
        result = service.chat("Show me products", user_id="user1")
        session_id = result["session"]["id"]

        # Manually add a message with dangerous SQL (simulating old data)
        repo = service.repository
        repo.add_message(
            session_id,
            "assistant",
            {
                "answer": "Here are the products",
                "sql": "DROP TABLE chat_sessions; -- dangerous",
            },
        )

        # Retrieve the conversation - should work fine
        detail = service.get_session_detail(session_id, user_id="user1")
        assert len(detail["messages"]) == 3

        # The third message (index 2) is the manually added one with dangerous SQL
        sql_msg = detail["messages"][2]
        assert sql_msg["payload"]["sql"] == "DROP TABLE chat_sessions; -- dangerous"

        # Verify tables still exist by creating another session
        result2 = service.chat("Another question", user_id="user1")
        assert result2["session"]["id"] != session_id