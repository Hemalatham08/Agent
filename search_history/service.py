"""Conversation history service.

The service owns conversation lifecycle logic (title generation, continuing a
conversation, ownership checks) and delegates persistence to the repository.

Answer generation is isolated behind :class:`AnswerGenerator`.  The real ERP
agent is *not* imported here; a future integration can implement the protocol
and inject it into :class:`ConversationService` with explicit approval.
"""

from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID, uuid4

from .errors import (
    AssistantPayloadError,
    HistoryValidationError,
    InvalidPayloadError,
    SessionNotFoundError,
)
from .repository import ConversationRepository
from .validation import (
    build_title,
    ensure_json_object,
    normalize_user_id,
    validate_message,
    validate_session_id,
)


class AnswerGenerator(Protocol):
    """Interface for producing an assistant response payload.

    ``history`` contains previously stored messages (oldest first), each with
    ``role``, ``payload`` and ``created_at`` keys.  The returned object is
    stored verbatim as structured JSON.
    """

    def generate(
        self,
        *,
        question: str,
        history: list[dict[str, Any]],
    ) -> dict[str, Any]:  # pragma: no cover - protocol definition
        ...


class MockAnswerGenerator:
    """Deterministic stand-in used when the ERP agent is unavailable."""

    def generate(
        self,
        *,
        question: str,
        history: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "summary": build_title(question, 60),
            "answer": f"Mock response to: {question}",
            "table": {
                "columns": ["Field", "Value"],
                "rows": [["Question", question]],
            },
            "charts": [],
            "sql": "SELECT 1 AS mock_value",
            "tools": [
                {
                    "tool_name": "mock_answer",
                    "status": "success",
                    "arguments": {},
                }
            ],
            "metadata": {
                "generator": "mock",
                "structured": True,
                "history_messages": len(history),
            },
        }


class ConversationService:
    """High-level conversation history operations."""

    def __init__(
        self,
        repository: ConversationRepository,
        answer_generator: AnswerGenerator | None = None,
    ) -> None:
        self.repository = repository
        self.answer_generator = answer_generator or MockAnswerGenerator()

    # ------------------------------------------------------------------
    # Chat
    # ------------------------------------------------------------------
    def chat(
        self,
        message: str,
        session_id: str | UUID | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Create or continue a conversation and save one full turn."""
        text = validate_message(message)
        owner = normalize_user_id(user_id)

        if session_id is None:
            canonical_id = str(uuid4())
            title: str | None = build_title(text)
            history: list[dict[str, Any]] = []
        else:
            canonical_id = validate_session_id(session_id)
            session = self.repository.get_session(
                canonical_id, user_id=owner
            )
            if session is None:
                raise SessionNotFoundError(canonical_id)
            title = None
            history = self.repository.get_messages(
                canonical_id, user_id=owner
            )

        assistant_payload = self._generate_payload(text, history)

        session, user_message, assistant_message = (
            self.repository.save_turn(
                session_id=canonical_id,
                title=title,
                user_id=owner,
                user_payload={"text": text},
                assistant_payload=assistant_payload,
            )
        )

        return {
            "session": session,
            "user_message": user_message,
            "assistant_message": assistant_message,
        }

    def _generate_payload(
        self, question: str, history: list[dict[str, Any]]
    ) -> dict[str, Any]:
        try:
            payload = self.answer_generator.generate(
                question=question, history=history
            )
        except Exception as exc:  # noqa: BLE001 - surface as upstream failure
            raise AssistantPayloadError(
                "The answer generator failed to produce a response."
            ) from exc

        if not isinstance(payload, dict):
            raise AssistantPayloadError(
                "The answer generator must return a JSON object."
            )
        try:
            ensure_json_object(payload)
        except InvalidPayloadError as exc:
            raise AssistantPayloadError(str(exc)) from exc
        return payload

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------
    def list_sessions(
        self,
        user_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        return self.repository.list_sessions(
            user_id=user_id, limit=limit, offset=offset
        )

    def get_session_detail(
        self, session_id: str | UUID, user_id: str | None = None
    ) -> dict[str, Any]:
        canonical_id = validate_session_id(session_id)
        session = self.repository.get_session(
            canonical_id,
            user_id=user_id,
            include_messages=True,
        )
        if session is None:
            raise SessionNotFoundError(canonical_id)
        return session

    def delete_session(
        self, session_id: str | UUID, user_id: str | None = None
    ) -> None:
        canonical_id = validate_session_id(session_id)
        if not self.repository.delete_session(
            canonical_id, user_id=user_id
        ):
            raise SessionNotFoundError(canonical_id)

    def search(
        self,
        query: str,
        user_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        return self.repository.search_sessions(
            query=query,
            user_id=user_id,
            limit=limit,
            offset=offset,
        )

    def clear_user_history(self, user_id: str) -> int:
        owner = normalize_user_id(user_id)
        if owner is None:
            raise HistoryValidationError(
                "user_id is required to clear conversation history."
            )
        return self.repository.clear_user_sessions(owner)
