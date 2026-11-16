"""Sanitized RAG domain errors and the ERP-compatible tool envelope.

The envelope shape matches ``backend.agent.erp.errors.ErpError`` exactly so
that RAG handlers can be executed by the existing tool executor/runner
contracts without adapters.
"""

from __future__ import annotations

from pydantic import JsonValue

from backend.agent.models import ErrorCategory


class RagError(Exception):
    """Base class for sanitized RAG domain errors."""

    def __init__(
        self,
        *,
        code: str,
        message: str,
        category: ErrorCategory,
        recoverable: bool = False,
        retryable: bool = False,
        details: dict[str, JsonValue] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.category = category
        self.recoverable = recoverable
        self.retryable = retryable
        self.details = dict(details or {})
        super().__init__(message)

    def to_envelope(self) -> dict[str, JsonValue]:
        return {
            "ok": False,
            "error": {
                "code": self.code,
                "message": self.message,
                "category": self.category.value,
                "recoverable": self.recoverable,
                "retryable": self.retryable,
                "details": self.details,
            },
        }


class RagConfigurationError(RagError):
    def __init__(self, message: str = "RAG configuration is invalid") -> None:
        super().__init__(
            code="rag_configuration_error",
            message=message,
            category=ErrorCategory.INTERNAL,
        )


class RagCorpusError(RagError):
    def __init__(
        self,
        message: str = "RAG knowledge corpus is invalid",
        *,
        path: str | None = None,
        line: int | None = None,
        rule: str | None = None,
    ) -> None:
        details: dict[str, JsonValue] = {}
        if path is not None:
            details["path"] = path
        if line is not None:
            details["line"] = line
        if rule is not None:
            details["rule"] = rule
        super().__init__(
            code="rag_corpus_error",
            message=message,
            category=ErrorCategory.INTERNAL,
            details=details,
        )


class RagIndexError(RagError):
    def __init__(self, message: str = "RAG index build failed") -> None:
        super().__init__(
            code="rag_index_error",
            message=message,
            category=ErrorCategory.INTERNAL,
            retryable=True,
        )


class RagInvalidArgumentsError(RagError):
    def __init__(self, field: str, message: str | None = None) -> None:
        super().__init__(
            code="rag_invalid_arguments",
            message=message or f"Invalid argument: {field}",
            category=ErrorCategory.VALIDATION,
            recoverable=True,
            details={"field": field},
        )


class RagNotFoundError(RagError):
    def __init__(self, resource: str, message: str | None = None) -> None:
        super().__init__(
            code="rag_not_found",
            message=message
            or f"{resource.replace('_', ' ').title()} not found",
            category=ErrorCategory.NOT_FOUND,
            recoverable=True,
            details={"resource": resource},
        )


class RagInternalError(RagError):
    def __init__(self, message: str = "RAG data could not be processed") -> None:
        super().__init__(
            code="rag_internal_error",
            message=message,
            category=ErrorCategory.INTERNAL,
        )


__all__ = [
    "RagConfigurationError",
    "RagCorpusError",
    "RagError",
    "RagIndexError",
    "RagInternalError",
    "RagInvalidArgumentsError",
    "RagNotFoundError",
]
