"""Configuration for the Google Gemini AI provider.

Reads settings from environment variables. Validation happens here so that a
missing or invalid ``GEMINI_API_KEY`` produces a clear, sanitized error only
when Gemini is explicitly selected/initialized. Ollama-only usage never touches
this module.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse

from backend.ai_providers.gemini.errors import (
    GeminiAuthError,
    GeminiConfigurationError,
)

DEFAULT_GEMINI_MODEL = "gemini-3.5-flash-lite"
DEFAULT_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com"
DEFAULT_GEMINI_TIMEOUT_SECONDS = 30.0

_GEMINI_API_KEY_ENV = "GEMINI_API_KEY"
_GEMINI_MODEL_ENV = "GEMINI_MODEL"
_GEMINI_BASE_URL_ENV = "GEMINI_BASE_URL"
_GEMINI_TIMEOUT_ENV = "GEMINI_TIMEOUT_SECONDS"


@dataclass(frozen=True)
class GeminiConfig:
    """Configuration for the Gemini provider.

    The API key is validated to be non-blank but is never included in
    ``repr()`` output, logs, exceptions, or API responses.
    """

    api_key: str
    model: str = DEFAULT_GEMINI_MODEL
    base_url: str = DEFAULT_GEMINI_BASE_URL
    timeout_seconds: float = DEFAULT_GEMINI_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        api_key = self.api_key.strip()
        if not api_key:
            raise GeminiConfigurationError(
                "GEMINI_API_KEY must not be empty. Set the GEMINI_API_KEY "
                "environment variable before selecting the Gemini provider."
            )
        object.__setattr__(self, "api_key", api_key)

        model = self.model.strip()
        if not model:
            model = DEFAULT_GEMINI_MODEL
        object.__setattr__(self, "model", model)

        base_url = self.base_url.strip().rstrip("/")
        if not base_url:
            base_url = DEFAULT_GEMINI_BASE_URL
        parsed = urlparse(base_url)
        if parsed.scheme not in ("http", "https"):
            raise GeminiConfigurationError(
                f"GEMINI_BASE_URL scheme must be http or https, got '{parsed.scheme}'"
            )
        if not parsed.netloc:
            raise GeminiConfigurationError(
                "GEMINI_BASE_URL must contain a valid host"
            )
        object.__setattr__(self, "base_url", base_url)

        if self.timeout_seconds <= 0:
            raise GeminiConfigurationError("GEMINI_TIMEOUT_SECONDS must be positive")

    def __repr__(self) -> str:
        # Never reveal the API key in repr output.
        return (
            f"GeminiConfig(model={self.model!r}, "
            f"base_url={self.base_url!r}, "
            f"timeout_seconds={self.timeout_seconds!r}, "
            f"api_key='***')"
        )

    @classmethod
    def from_env(cls) -> GeminiConfig:
        """Build configuration from environment variables.

        Raises :class:`GeminiConfigurationError` when ``GEMINI_API_KEY`` is not
        set. This is the entry point used when Gemini is selected; importing the
        package or using Ollama never calls it.
        """
        api_key = os.getenv(_GEMINI_API_KEY_ENV, "").strip()
        if not api_key:
            raise GeminiConfigurationError(
                "GEMINI_API_KEY environment variable is not set. "
                "Configure it before selecting the Gemini provider."
            )

        model = os.getenv(_GEMINI_MODEL_ENV, DEFAULT_GEMINI_MODEL).strip()
        if not model:
            model = DEFAULT_GEMINI_MODEL

        base_url = os.getenv(_GEMINI_BASE_URL_ENV, DEFAULT_GEMINI_BASE_URL).strip()

        timeout_raw = os.getenv(_GEMINI_TIMEOUT_ENV, "").strip()
        timeout = DEFAULT_GEMINI_TIMEOUT_SECONDS
        if timeout_raw:
            try:
                timeout = float(timeout_raw)
            except ValueError:
                timeout = DEFAULT_GEMINI_TIMEOUT_SECONDS

        return cls(
            api_key=api_key,
            model=model,
            base_url=base_url,
            timeout_seconds=timeout,
        )


__all__ = [
    "DEFAULT_GEMINI_BASE_URL",
    "DEFAULT_GEMINI_MODEL",
    "DEFAULT_GEMINI_TIMEOUT_SECONDS",
    "GeminiConfig",
]
