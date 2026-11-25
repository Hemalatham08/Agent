"""Shared pytest fixtures for conversation history tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure the project root is on sys.path for imports
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def temp_db_path(tmp_path) -> Path:
    """Provide a temporary database path for each test."""
    return tmp_path / "test_history.db"


@pytest.fixture
def repo(temp_db_path):
    """Provide a fresh ConversationRepository backed by a temporary database."""
    from search_history.repository import ConversationRepository

    repository = ConversationRepository(temp_db_path)
    repository.initialize()
    return repository


@pytest.fixture
def service(repo):
    """Provide a ConversationService with the mock answer generator."""
    from search_history.service import ConversationService, MockAnswerGenerator

    return ConversationService(repo, MockAnswerGenerator())


@pytest.fixture
def client(temp_db_path):
    """Provide a FastAPI TestClient for API tests."""
    from fastapi.testclient import TestClient
    from search_history.app import create_app

    app = create_app(db_path=temp_db_path)
    with TestClient(app) as client:
        yield client


@pytest.fixture
def sample_uuid() -> str:
    """A valid UUID string for testing."""
    return "550e8400-e29b-41d4-a716-446655440000"


@pytest.fixture
def another_uuid() -> str:
    """Another valid UUID string for testing."""
    return "6ba7b810-9dad-41d4-a716-446655440000"