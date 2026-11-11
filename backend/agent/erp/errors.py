from __future__ import annotations

from pydantic import JsonValue

from backend.agent.models import ErrorCategory


class ErpError(Exception):
    """Base class for sanitized ERP domain errors."""

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


class ErpConfigurationError(ErpError):
    def __init__(self, message: str = "ERP database is unavailable") -> None:
        super().__init__(
            code="erp_database_unavailable",
            message=message,
            category=ErrorCategory.INTERNAL,
        )


class ErpInvalidArgumentsError(ErpError):
    def __init__(self, field: str, message: str | None = None) -> None:
        super().__init__(
            code="erp_invalid_arguments",
            message=message or f"Invalid argument: {field}",
            category=ErrorCategory.VALIDATION,
            recoverable=True,
            details={"field": field},
        )


class ErpNotFoundError(ErpError):
    def __init__(self, resource: str, message: str | None = None) -> None:
        super().__init__(
            code="erp_not_found",
            message=message or f"{resource.replace('_', ' ').title()} not found",
            category=ErrorCategory.NOT_FOUND,
            recoverable=True,
            details={"resource": resource},
        )


class ErpAmbiguousResultError(ErpError):
    def __init__(self, resource: str) -> None:
        super().__init__(
            code="erp_ambiguous_result",
            message=f"Ambiguous {resource.replace('_', ' ')} result",
            category=ErrorCategory.VALIDATION,
            recoverable=True,
            details={"resource": resource},
        )


class ErpDatabaseError(ErpError):
    def __init__(self, message: str = "ERP database read failed") -> None:
        super().__init__(
            code="erp_database_error",
            message=message,
            category=ErrorCategory.INTERNAL,
            retryable=True,
        )


class ErpQueryTimeoutError(ErpError):
    def __init__(self, message: str = "ERP query deadline exceeded") -> None:
        super().__init__(
            code="erp_query_timeout",
            message=message,
            category=ErrorCategory.TIMEOUT,
            retryable=True,
        )


class ErpPermissionDeniedError(ErpError):
    def __init__(self, message: str = "ERP operation is not permitted") -> None:
        super().__init__(
            code="erp_permission_denied",
            message=message,
            category=ErrorCategory.PERMISSION,
        )


class ErpInternalError(ErpError):
    def __init__(self, message: str = "ERP data could not be processed") -> None:
        super().__init__(
            code="erp_internal_error",
            message=message,
            category=ErrorCategory.INTERNAL,
        )


__all__ = [
    "ErpAmbiguousResultError",
    "ErpConfigurationError",
    "ErpDatabaseError",
    "ErpError",
    "ErpInternalError",
    "ErpInvalidArgumentsError",
    "ErpNotFoundError",
    "ErpPermissionDeniedError",
    "ErpQueryTimeoutError",
]
