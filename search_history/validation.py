"""Shared validation and serialization helpers.

Keeping these helpers independent of FastAPI means the repository and service
can be reused by a future ERP integration without pulling in web concerns.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from .errors import (
    HistoryValidationError,
    InvalidMessageRoleError,
    InvalidPayloadError,
)

VALID_ROLES = frozenset({"user", "assistant"})
TITLE_MAX_LENGTH = 40
USER_ID_MAX_LENGTH = 128


def utc_now_iso() -> str:
    """Return a sortable, timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f+00:00")


def validate_session_id(session_id: str | UUID) -> str:
    """Return the canonical lowercase UUID string or raise."""
    try:
        return str(UUID(str(session_id)))
    except (AttributeError, TypeError, ValueError) as exc:
        raise HistoryValidationError(
            "session_id must be a valid UUID."
        ) from exc


def validate_message(message: str) -> str:
    """Strip a user message and reject blank values."""
    if not isinstance(message, str):
        raise ValueError("message must be a string.")
    text = message.strip()
    if not text:
        raise ValueError("message must not be blank.")
    return text


def normalize_user_id(user_id: str | None) -> str | None:
    """Trim an optional user identifier and reject unusable values."""
    if user_id is None:
        return None
    if not isinstance(user_id, str):
        raise HistoryValidationError("user_id must be a string.")
    cleaned = user_id.strip()
    if not cleaned:
        return None
    if len(cleaned) > USER_ID_MAX_LENGTH:
        raise HistoryValidationError(
            f"user_id must be at most {USER_ID_MAX_LENGTH} characters."
        )
    if any(ord(char) < 32 for char in cleaned):
        raise HistoryValidationError("user_id contains control characters.")
    return cleaned


def validate_role(role: str) -> str:
    """Normalize and validate a message role."""
    value = role.value if hasattr(role, "value") else role
    if value not in VALID_ROLES:
        raise InvalidMessageRoleError(
            f"role must be one of {sorted(VALID_ROLES)}."
        )
    return value


def build_title(text: str, max_length: int = TITLE_MAX_LENGTH) -> str:
    """Build a conversation title from the first user question.

    Whitespace is collapsed and the result is truncated to approximately
    ``max_length`` characters (an ellipsis counts toward the limit).
    """
    normalized = " ".join(text.split())
    if len(normalized) <= max_length:
        return normalized
    return normalized[: max_length - 1].rstrip() + "\u2026"


def ensure_json_object(payload: Any) -> dict[str, Any]:
    """Validate that ``payload`` is a JSON-serializable object."""
    if not isinstance(payload, dict):
        raise InvalidPayloadError("payload must be a JSON object.")
    try:
        json.dumps(payload, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise InvalidPayloadError(
            "payload must contain only JSON-serializable values."
        ) from exc
    return payload


def serialize_payload(payload: dict[str, Any]) -> str:
    """Serialize a validated payload for storage."""
    ensure_json_object(payload)
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def deserialize_payload(payload_json: str) -> dict[str, Any]:
    """Parse a stored payload, guaranteeing an object is returned."""
    try:
        payload = json.loads(payload_json)
    except (TypeError, ValueError) as exc:
        raise InvalidPayloadError("Stored payload is not valid JSON.") from exc
    if not isinstance(payload, dict):
        raise InvalidPayloadError("Stored payload is not a JSON object.")
    return payload
