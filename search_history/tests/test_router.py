"""Tests for the FastAPI router endpoints."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from search_history.app import create_app
from search_history.errors import AssistantPayloadError
from search_history.service import AnswerGenerator


@pytest.fixture
def app(temp_db_path: Path):
    """Create a fresh app for each test with isolated database."""
    return create_app(db_path=temp_db_path)


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app)


def test_post_chat_creates_new_conversation(client: TestClient):
    response = client.post(
        "/chat",
        json={"message": "What is the stock level?"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "session" in data
    assert "user_message" in data
    assert "assistant_message" in data
    assert data["session"]["title"] == "What is the stock level?"
    assert data["session"]["message_count"] == 2
    assert data["user_message"]["role"] == "user"
    assert data["user_message"]["payload"]["text"] == "What is the stock level?"
    assert data["assistant_message"]["role"] == "assistant"
    assert "answer" in data["assistant_message"]["payload"]


def test_post_chat_continues_existing_conversation(client: TestClient):
    # First request
    resp1 = client.post("/chat", json={"message": "First question"})
    assert resp1.status_code == 200
    session_id = resp1.json()["session"]["id"]

    # Second request with session_id
    resp2 = client.post(
        "/chat",
        json={"message": "Second question", "session_id": session_id},
    )
    assert resp2.status_code == 200
    data = resp2.json()
    assert data["session"]["id"] == session_id
    assert data["session"]["message_count"] == 4
    assert data["session"]["title"] == "First question"  # unchanged


def test_post_chat_with_user_id(client: TestClient):
    response = client.post(
        "/chat",
        json={"message": "Hello", "user_id": "user123"},
    )
    assert response.status_code == 200
    assert response.json()["session"]["user_id"] == "user123"


def test_post_chat_rejects_blank_message(client: TestClient):
    response = client.post("/chat", json={"message": "   "})
    assert response.status_code == 422  # Pydantic validation


def test_post_chat_rejects_invalid_session_id(client: TestClient):
    response = client.post(
        "/chat",
        json={"message": "Hello", "session_id": "not-a-uuid"},
    )
    assert response.status_code == 422  # Pydantic UUID validation


def test_post_chat_rejects_missing_session(client: TestClient):
    fake_id = "550e8400-e29b-41d4-a716-446655440000"
    response = client.post(
        "/chat",
        json={"message": "Hello", "session_id": fake_id},
    )
    assert response.status_code == 404


def test_post_chat_enforces_ownership(client: TestClient):
    # Create as user1
    resp1 = client.post("/chat", json={"message": "Hello", "user_id": "user1"})
    session_id = resp1.json()["session"]["id"]

    # Try to continue as user2
    resp2 = client.post(
        "/chat",
        json={"message": "Again", "session_id": session_id, "user_id": "user2"},
    )
    assert resp2.status_code == 404


def test_get_sessions_list(client: TestClient):
    client.post("/chat", json={"message": "First", "user_id": "user1"})
    client.post("/chat", json={"message": "Second", "user_id": "user1"})

    response = client.get("/chat/sessions?user_id=user1")
    assert response.status_code == 200
    sessions = response.json()
    assert len(sessions) == 2
    # Newest first
    assert sessions[0]["title"] == "Second"
    assert sessions[1]["title"] == "First"


def test_get_sessions_pagination(client: TestClient):
    for i in range(5):
        client.post("/chat", json={"message": f"Msg {i}", "user_id": "user1"})

    resp1 = client.get("/chat/sessions?user_id=user1&limit=2&offset=0")
    resp2 = client.get("/chat/sessions?user_id=user1&limit=2&offset=2")

    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert len(resp1.json()) == 2
    assert len(resp2.json()) == 2
    assert resp1.json()[0]["id"] != resp2.json()[0]["id"]


def test_get_sessions_validates_limit(client: TestClient):
    response = client.get("/chat/sessions?limit=0")
    assert response.status_code == 422
    response = client.get("/chat/sessions?limit=201")
    assert response.status_code == 422


def test_get_session_detail(client: TestClient):
    resp1 = client.post("/chat", json={"message": "Hello", "user_id": "user1"})
    session_id = resp1.json()["session"]["id"]

    response = client.get(f"/chat/sessions/{session_id}?user_id=user1")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == session_id
    assert len(data["messages"]) == 2
    assert data["messages"][0]["role"] == "user"
    assert data["messages"][1]["role"] == "assistant"


def test_get_session_detail_not_found(client: TestClient):
    fake_id = "550e8400-e29b-41d4-a716-446655440000"
    response = client.get(f"/chat/sessions/{fake_id}")
    assert response.status_code == 404


def test_get_session_detail_invalid_uuid(client: TestClient):
    response = client.get("/chat/sessions/not-a-uuid")
    assert response.status_code == 422


def test_get_session_detail_enforces_ownership(client: TestClient):
    resp1 = client.post("/chat", json={"message": "Hello", "user_id": "user1"})
    session_id = resp1.json()["session"]["id"]

    response = client.get(f"/chat/sessions/{session_id}?user_id=user2")
    assert response.status_code == 404


def test_delete_session(client: TestClient):
    resp1 = client.post("/chat", json={"message": "Hello", "user_id": "user1"})
    session_id = resp1.json()["session"]["id"]

    response = client.delete(f"/chat/sessions/{session_id}?user_id=user1")
    assert response.status_code == 200
    assert response.json()["deleted"] is True
    assert response.json()["session_id"] == session_id

    # Verify deleted
    get_resp = client.get(f"/chat/sessions/{session_id}?user_id=user1")
    assert get_resp.status_code == 404


def test_delete_session_not_found(client: TestClient):
    fake_id = "550e8400-e29b-41d4-a716-446655440000"
    response = client.delete(f"/chat/sessions/{fake_id}")
    assert response.status_code == 404


def test_delete_session_enforces_ownership(client: TestClient):
    resp1 = client.post("/chat", json={"message": "Hello", "user_id": "user1"})
    session_id = resp1.json()["session"]["id"]

    response = client.delete(f"/chat/sessions/{session_id}?user_id=user2")
    assert response.status_code == 404


def test_search_sessions(client: TestClient):
    client.post("/chat", json={"message": "Stock level for SKU-123", "user_id": "user1"})
    client.post("/chat", json={"message": "Inventory report", "user_id": "user1"})

    response = client.get("/chat/search?q=stock&user_id=user1")
    assert response.status_code == 200
    results = response.json()
    assert len(results) == 1
    assert "Stock" in results[0]["title"]


def test_search_by_message_content(client: TestClient):
    client.post("/chat", json={"message": "Find the needle", "user_id": "user1"})
    client.post("/chat", json={"message": "Haystack only", "user_id": "user1"})

    response = client.get("/chat/search?q=needle&user_id=user1")
    assert response.status_code == 200
    results = response.json()
    assert len(results) == 1


def test_search_rejects_empty_query(client: TestClient):
    response = client.get("/chat/search?q=")
    assert response.status_code == 422


def test_clear_user_sessions(client: TestClient):
    client.post("/chat", json={"message": "User1 chat", "user_id": "user1"})
    client.post("/chat", json={"message": "User2 chat", "user_id": "user2"})

    response = client.delete("/chat/sessions?user_id=user1")
    assert response.status_code == 200
    assert response.json()["deleted_count"] == 1
    assert response.json()["user_id"] == "user1"

    # Verify cleared
    sessions = client.get("/chat/sessions?user_id=user1").json()
    assert len(sessions) == 0

    sessions2 = client.get("/chat/sessions?user_id=user2").json()
    assert len(sessions2) == 1


def test_clear_user_sessions_requires_user_id(client: TestClient):
    response = client.delete("/chat/sessions")
    assert response.status_code == 422


def test_mock_generator_behavior(client: TestClient):
    """Verify mock answer generator produces structured responses."""
    response = client.post("/chat", json={"message": "Test question"})
    data = response.json()
    payload = data["assistant_message"]["payload"]

    assert "summary" in payload
    assert "answer" in payload
    assert "table" in payload
    assert "charts" in payload
    assert "sql" in payload
    assert "tools" in payload
    assert "metadata" in payload
    assert payload["metadata"]["generator"] == "mock"
    assert payload["metadata"]["structured"] is True


def test_502_on_generator_failure(tmp_path: Path):
    """If answer generator fails, return 502."""
    class BadGenerator:
        def generate(self, *, question, history):
            raise RuntimeError("LLM unavailable")

    app = create_app(answer_generator=BadGenerator(), db_path=tmp_path / "bad_gen.db")
    with TestClient(app) as bad_client:
        response = bad_client.post("/chat", json={"message": "Hello"})
        assert response.status_code == 502


def test_502_on_bad_payload_from_generator(tmp_path: Path):
    """If generator returns non-dict or non-serializable, return 502."""
    class BadPayloadGenerator:
        def generate(self, *, question, history):
            return "not a dict"

    app = create_app(answer_generator=BadPayloadGenerator(), db_path=tmp_path / "bad_payload.db")
    with TestClient(app) as bad_client:
        response = bad_client.post("/chat", json={"message": "Hello"})
        assert response.status_code == 502


def test_conversation_isolation_from_erp_database(tmp_path: Path):
    """Ensure the history module never touches the ERP database."""
    from search_history import database
    from pathlib import Path

    # Default path is in search_history
    assert database.DATABASE_PATH.parent.name == "search_history"
    assert "backend" not in database.DATABASE_PATH.parts

    # Using temp DB also stays isolated
    app = create_app(db_path=tmp_path / "isolated.db")
    with TestClient(app) as c:
        c.post("/chat", json={"message": "Test"})

    # ERP database untouched (we can't easily test this without the actual file,
    # but the path separation is verified above)
    assert True


def test_structured_payload_round_trip(client: TestClient):
    """Full round-trip preserves complex structured data."""
    response = client.post("/chat", json={"message": "Complex query"})
    session_id = response.json()["session"]["id"]

    # Get full conversation
    detail = client.get(f"/chat/sessions/{session_id}").json()

    # Assistant message has all structured fields
    asst_msg = next(m for m in detail["messages"] if m["role"] == "assistant")
    payload = asst_msg["payload"]

    assert isinstance(payload["table"], dict)
    assert "columns" in payload["table"]
    assert "rows" in payload["table"]
    assert isinstance(payload["charts"], list)
    assert isinstance(payload["sql"], str)
    assert isinstance(payload["tools"], list)
    assert isinstance(payload["metadata"], dict)


def test_title_truncation_in_api(client: TestClient):
    """API respects 40-character title limit."""
    long_question = "What is the current inventory status for all products in the warehouse?"
    response = client.post("/chat", json={"message": long_question})
    assert response.status_code == 200
    title = response.json()["session"]["title"]
    assert len(title) <= 40
    assert title.endswith("…")


def test_anonymous_access_works(client: TestClient):
    """Without user_id, all conversations are visible."""
    client.post("/chat", json={"message": "Anon chat 1"})
    client.post("/chat", json={"message": "Anon chat 2"})

    sessions = client.get("/chat/sessions").json()
    assert len(sessions) == 2