"""Exceptions for the Gemini AI provider.

All error types are defined here so that Gemini-specific error handling stays
inside the Gemini package and never leaks into the Ollama or orchestration code.
Messages never contain the Gemini API key or other secrets.
"""

from __future__ import annotations


class GeminiError(Exception):
    """Base exception for all Gemini provider operations."""


class GeminiConfigurationError(GeminiError):
    """Raised when Gemini configuration is invalid or incomplete.

    For example, when ``GEMINI_API_KEY`` is missing or malformed. This error is
    raised only when Gemini is explicitly selected/initialized; it never affects
    Ollama-only usage.
    """


class GeminiAuthError(GeminiConfigurationError):
    """Raised when the Gemini API key is invalid or not authorized."""


class GeminiConnectionError(GeminiError):
    """Raised when the Gemini service cannot be reached."""


class GeminiModelNotFoundError(GeminiError):
    """Raised when the requested Gemini model is not available."""


class GeminiTimeoutError(GeminiError):
    """Raised when a Gemini request times out."""


class GeminiResponseError(GeminiError):
    """Raised when Gemini returns an unexpected or unparsable response."""


class GeminiInvalidRequestError(GeminiError):
    """Raised when the request is malformed or invalid (HTTP 400)."""


class GeminiPermissionError(GeminiError):
    """Raised when the API key lacks permission for the requested operation (HTTP 403)."""


class GeminiQuotaError(GeminiError):
    """Raised when the API quota or rate limit is exceeded (HTTP 429)."""


__all__ = [
    "GeminiAuthError",
    "GeminiConfigurationError",
    "GeminiConnectionError",
    "GeminiError",
    "GeminiInvalidRequestError",
    "GeminiModelNotFoundError",
    "GeminiPermissionError",
    "GeminiQuotaError",
    "GeminiResponseError",
    "GeminiTimeoutError",
]
