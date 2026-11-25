"""Integration tests for the complete conversation history module."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from search_history.app import create_app
from search_history.repository import ConversationRepository
from search_history.service import ConversationService, MockAnswerGenerator
from search_history.validation import build_title


class TestFullConversationLifecycle:
    """End-to-end tests using the service layer."""

    def test_complete_conversation_flow(self, temp_db_path):
        repo = ConversationRepository(temp_db_path)
        repo.initialize()
        svc = ConversationService(repo, MockAnswerGenerator())

        # Turn 1
        r1 = svc.chat("What is the stock for SKU-001?", user_id="user1")
        assert r1["session"]["message_count"] == 2
        sid = r1["session"]["id"]

        # Turn 2
        r2 = svc.chat("And for SKU-002?", session_id=sid, user_id="user1")
        assert r2["session"]["message_count"] == 4
        assert r2["session"]["id"] == sid

        # Turn 3
        r3 = svc.chat("Show me low stock items", session_id=sid, user_id="user1")
        assert r3["session"]["message_count"] == 6

        # Retrieve full history
        detail = svc.get_session_detail(sid, user_id="user1")
        assert len(detail["messages"]) == 6
        roles = [m["role"] for m in detail["messages"]]
        assert roles == ["user", "assistant"] * 3

    def test_multiple_users_independent(self, temp_db_path):
        repo = ConversationRepository(temp_db_path)
        repo.initialize()
        svc = ConversationService(repo, MockAnswerGenerator())

        svc.chat("User1 question", user_id="user1")
        svc.chat("User2 question", user_id="user2")

        u1_sessions = svc.list_sessions(user_id="user1")
        u2_sessions = svc.list_sessions(user_id="user2")

        assert len(u1_sessions) == 1
        assert len(u2_sessions) == 1
        assert u1_sessions[0]["title"] == "User1 question"
        assert u2_sessions[0]["title"] == "User2 question"

    def test_search_across_users(self, temp_db_path):
        repo = ConversationRepository(temp_db_path)
        repo.initialize()
        svc = ConversationService(repo, MockAnswerGenerator())

        svc.chat("Stock report for Q1", user_id="user1")
        svc.chat("Financial report for Q1", user_id="user2")

        # Each user only sees their own
        assert len(svc.search("report", user_id="user1")) == 1
        assert len(svc.search("report", user_id="user2")) == 1


class TestDatabaseIsolation:
    """Verify the module is isolated from the ERP database."""

    def test_default_db_path_not_erp(self):
        from search_history import database
        assert database.DATABASE_PATH.parent.name == "search_history"
        assert "backend" not in database.DATABASE_PATH.parts
        assert "data" not in database.DATABASE_PATH.parts

    def test_temp_db_operations_dont_affect_real_db(self, temp_db_path):
        """Operations on temp DB don't touch the real history.db."""
        real_db = Path(__file__).resolve().parents[1] / "history.db"
        real_size_before = real_db.stat().st_size if real_db.exists() else 0
        real_mtime_before = real_db.stat().st_mtime if real_db.exists() else 0

        repo = ConversationRepository(temp_db_path)
        repo.initialize()
        svc = ConversationService(repo, MockAnswerGenerator())
        svc.chat("Test message", user_id="testuser")

        if real_db.exists():
            assert real_db.stat().st_size == real_size_before
            assert real_db.stat().st_mtime == real_mtime_before

    def test_no_backend_imports_in_module(self):
        """Verify no accidental imports of ERP backend modules."""
        import search_history.repository as repo_mod
        import search_history.service as svc_mod
        import search_history.router as router_mod

        for mod in (repo_mod, svc_mod, router_mod):
            source = mod.__file__
            content = Path(source).read_text()
            # Check for actual import statements, not docstring mentions
            lines = content.split('\n')
            import_lines = [l for l in lines if l.strip().startswith(('import ', 'from '))]
            for line in import_lines:
                assert "backend" not in line, f"Found backend import in {mod.__name__}: {line}"
                assert "erp" not in line.lower() or "erp" in line.lower()  # ERP might appear in comments


class TestPersistenceCorrectness:
    """Test that data persists correctly across operations."""

    def test_session_persists_after_reinit(self, temp_db_path):
        repo = ConversationRepository(temp_db_path)
        repo.initialize()
        svc = ConversationService(repo, MockAnswerGenerator())

        r = svc.chat("Persist me", user_id="user1")
        sid = r["session"]["id"]

        # Create new repository instance (simulates app restart)
        repo2 = ConversationRepository(temp_db_path)
        repo2.initialize()
        svc2 = ConversationService(repo2, MockAnswerGenerator())

        detail = svc2.get_session_detail(sid, user_id="user1")
        assert detail["title"] == "Persist me"
        assert len(detail["messages"]) == 2

    def test_message_order_preserved(self, temp_db_path):
        repo = ConversationRepository(temp_db_path)
        repo.initialize()
        svc = ConversationService(repo, MockAnswerGenerator())

        # First message creates the session
        r1 = svc.chat("Question 0", user_id="user1")
        sid = r1["session"]["id"]
        for i in range(1, 5):
            svc.chat(f"Question {i}", session_id=sid, user_id="user1")

        detail = svc.get_session_detail(sid, user_id="user1")
        assert detail["message_count"] == 10
        assert len(detail["messages"]) == 10

    def test_large_payload_stored_correctly(self, temp_db_path):
        repo = ConversationRepository(temp_db_path)
        repo.initialize()
        svc = ConversationService(repo, MockAnswerGenerator())

        # Manually add a large structured payload
        large_payload = {
            "table": {
                "columns": [f"col{i}" for i in range(50)],
                "rows": [[f"row{r}c{c}" for c in range(50)] for r in range(100)],
            },
            "charts": [{"type": "bar", "data": list(range(1000))} for _ in range(10)],
        }
        session_id = str(uuid.uuid4())
        repo.create_session(session_id, "Large Data", user_id="user1")
        repo.add_message(session_id, "assistant", large_payload)

        # Retrieve and verify
        detail = svc.get_session_detail(session_id, user_id="user1")
        msg = next(m for m in detail["messages"] if m["role"] == "assistant")
        assert msg["payload"]["table"]["columns"] == large_payload["table"]["columns"]
        assert len(msg["payload"]["charts"]) == 10


class TestConcurrencySafety:
    """Basic concurrency safety (serialized via SQLite)."""

    def test_rapid_sequential_turns(self, temp_db_path):
        repo = ConversationRepository(temp_db_path)
        repo.initialize()
        svc = ConversationService(repo, MockAnswerGenerator())

        sid = None
        for i in range(20):
            r = svc.chat(f"Question {i}", session_id=sid, user_id="user1")
            sid = r["session"]["id"]

        detail = svc.get_session_detail(sid, user_id="user1")
        assert len(detail["messages"]) == 40
        assert detail["message_count"] == 40


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_unicode_in_messages(self, temp_db_path):
        repo = ConversationRepository(temp_db_path)
        repo.initialize()
        svc = ConversationService(repo, MockAnswerGenerator())

        r = svc.chat("Stock for 产品-123 📦", user_id="user1")
        detail = svc.get_session_detail(r["session"]["id"], user_id="user1")
        assert detail["messages"][0]["payload"]["text"] == "Stock for 产品-123 📦"

    def test_very_long_message(self, temp_db_path):
        repo = ConversationRepository(temp_db_path)
        repo.initialize()
        svc = ConversationService(repo, MockAnswerGenerator())

        long_msg = "x" * 10000
        r = svc.chat(long_msg, user_id="user1")
        assert r["user_message"]["payload"]["text"] == long_msg

    def test_special_chars_in_search(self, temp_db_path):
        repo = ConversationRepository(temp_db_path)
        repo.initialize()
        svc = ConversationService(repo, MockAnswerGenerator())

        svc.chat("100% complete", user_id="user1")
        svc.chat("50% done", user_id="user1")

        # Search with literal percent
        results = svc.search("100%", user_id="user1")
        assert len(results) == 1
        assert "100%" in results[0]["title"]

    def test_underscore_in_search(self, temp_db_path):
        repo = ConversationRepository(temp_db_path)
        repo.initialize()
        svc = ConversationService(repo, MockAnswerGenerator())

        svc.chat("SKU_123 status", user_id="user1")
        results = svc.search("SKU_123", user_id="user1")
        assert len(results) == 1

    def test_newlines_in_message(self, temp_db_path):
        repo = ConversationRepository(temp_db_path)
        repo.initialize()
        svc = ConversationService(repo, MockAnswerGenerator())

        r = svc.chat("Line 1\nLine 2\nLine 3", user_id="user1")
        assert r["user_message"]["payload"]["text"] == "Line 1\nLine 2\nLine 3"


class TestValidationIntegration:
    """Integration tests for validation across layers."""

    def test_repository_rejects_bad_role_via_service(self, temp_db_path):
        repo = ConversationRepository(temp_db_path)
        repo.initialize()

        with pytest.raises(Exception):  # InvalidMessageRoleError
            repo.add_message(str(uuid.uuid4()), "system", {"text": "bad"})

    def test_service_rejects_blank_message(self, temp_db_path):
        repo = ConversationRepository(temp_db_path)
        repo.initialize()
        svc = ConversationService(repo, MockAnswerGenerator())

        with pytest.raises(Exception):  # HistoryValidationError
            svc.chat("   ")

    def test_api_rejects_blank_message(self, temp_db_path):
        app = create_app(db_path=temp_db_path)
        from fastapi.testclient import TestClient
        with TestClient(app) as client:
            resp = client.post("/chat", json={"message": "   "})
            assert resp.status_code == 422


class TestAPIContracts:
    """Verify API request/response contracts match models."""

    def test_chat_response_shape(self):
        app = create_app()
        from fastapi.testclient import TestClient
        with TestClient(app) as client:
            resp = client.post("/chat", json={"message": "Hello"})
            assert resp.status_code == 200
            data = resp.json()

            # Required fields
            assert "session" in data
            assert "user_message" in data
            assert "assistant_message" in data

            # Session shape
            session = data["session"]
            assert all(k in session for k in ("id", "title", "user_id", "created_at", "updated_at", "message_count"))

            # Message shape
            for msg in (data["user_message"], data["assistant_message"]):
                assert all(k in msg for k in ("id", "role", "payload", "created_at"))
                assert msg["role"] in ("user", "assistant")
                assert isinstance(msg["payload"], dict)

    def test_session_list_shape(self):
        app = create_app()
        from fastapi.testclient import TestClient
        with TestClient(app) as client:
            client.post("/chat", json={"message": "Test"})
            resp = client.get("/chat/sessions")
            sessions = resp.json()
            assert isinstance(sessions, list)
            if sessions:
                s = sessions[0]
                assert all(k in s for k in ("id", "title", "user_id", "created_at", "updated_at", "message_count"))

    def test_session_detail_shape(self):
        app = create_app()
        from fastapi.testclient import TestClient
        with TestClient(app) as client:
            r = client.post("/chat", json={"message": "Test"})
            sid = r.json()["session"]["id"]
            resp = client.get(f"/chat/sessions/{sid}")
            detail = resp.json()
            assert "messages" in detail
            assert isinstance(detail["messages"], list)