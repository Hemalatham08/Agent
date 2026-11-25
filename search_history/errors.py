"""Domain errors raised by the conversation history module."""

from __future__ import annotations


class HistoryError(Exception):
    """Base class for conversation history errors."""


class HistoryValidationError(HistoryError):
    """Raised when caller input is invalid (blank message, bad ID, ...)."""


class SessionNotFoundError(HistoryError):
    """Raised when a conversation does not exist or is not visible to a user."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        super().__init__(f"Conversation '{session_id}' was not found.")


class InvalidMessageRoleError(HistoryValidationError):
    """Raised when a message role is not ``user`` or ``assistant``."""


class InvalidPayloadError(HistoryValidationError):
    """Raised when a message payload is not a JSON object."""


class AssistantPayloadError(HistoryError):
    """Raised when the answer generator returns an unusable payload."""
