"""Tests for the Gemini configuration module.

Uses only environment manipulation and mocks. No real Gemini API calls are made.
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from backend.ai_providers.gemini.config import (
    DEFAULT_GEMINI_BASE_URL,
    DEFAULT_GEMINI_MODEL,
    DEFAULT_GEMINI_TIMEOUT_SECONDS,
    GeminiConfig,
)
from backend.ai_providers.gemini.errors import GeminiConfigurationError


class TestGeminiConfig(unittest.TestCase):
    def setUp(self) -> None:
        self._env_vars = [
            "GEMINI_API_KEY",
            "GEMINI_MODEL",
            "GEMINI_BASE_URL",
            "GEMINI_TIMEOUT_SECONDS",
        ]
        self._saved = {key: os.environ.get(key) for key in self._env_vars}
        for key in self._env_vars:
            os.environ.pop(key, None)

    def tearDown(self) -> None:
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_from_env_loads_api_key(self) -> None:
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key-12345"}):
            config = GeminiConfig.from_env()
        self.assertEqual(config.api_key, "test-key-12345")
        self.assertEqual(config.model, DEFAULT_GEMINI_MODEL)
        self.assertEqual(config.base_url, DEFAULT_GEMINI_BASE_URL)
        self.assertEqual(config.timeout_seconds, DEFAULT_GEMINI_TIMEOUT_SECONDS)

    def test_from_env_applies_overrides(self) -> None:
        with patch.dict(
            os.environ,
            {
                "GEMINI_API_KEY": "test-key-12345",
                "GEMINI_MODEL": "gemini-1.5-pro",
                "GEMINI_BASE_URL": "https://custom.googleapis.com/",
                "GEMINI_TIMEOUT_SECONDS": "60",
            },
        ):
            config = GeminiConfig.from_env()
        self.assertEqual(config.api_key, "test-key-12345")
        self.assertEqual(config.model, "gemini-1.5-pro")
        self.assertEqual(config.base_url, "https://custom.googleapis.com")
        self.assertEqual(config.timeout_seconds, 60.0)

    def test_missing_api_key_raises_clear_error(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(GeminiConfigurationError) as ctx:
                GeminiConfig.from_env()
        self.assertIn("GEMINI_API_KEY", str(ctx.exception))
        # The message must not contain a secret value.
        self.assertNotIn("test-key", str(ctx.exception))

    def test_empty_api_key_raises_clear_error(self) -> None:
        with patch.dict(os.environ, {"GEMINI_API_KEY": "   "}):
            with self.assertRaises(GeminiConfigurationError):
                GeminiConfig.from_env()

    def test_invalid_timeout_uses_default(self) -> None:
        with patch.dict(
            os.environ,
            {"GEMINI_API_KEY": "test-key-12345", "GEMINI_TIMEOUT_SECONDS": "not-a-number"},
        ):
            config = GeminiConfig.from_env()
        self.assertEqual(config.timeout_seconds, DEFAULT_GEMINI_TIMEOUT_SECONDS)

    def test_negative_timeout_raises(self) -> None:
        with self.assertRaises(GeminiConfigurationError):
            GeminiConfig(
                api_key="test-key-12345", timeout_seconds=-1
            )

    def test_api_key_whitespace_is_stripped(self) -> None:
        config = GeminiConfig(api_key="  test-key-12345  ")
        self.assertEqual(config.api_key, "test-key-12345")

    def test_invalid_base_url_scheme_raises(self) -> None:
        with self.assertRaises(GeminiConfigurationError):
            GeminiConfig(api_key="test-key-12345", base_url="ftp://example.com")

    def test_base_url_trailing_slash_is_stripped(self) -> None:
        config = GeminiConfig(api_key="test-key-12345", base_url="https://example.com/")
        self.assertEqual(config.base_url, "https://example.com")

    def test_repr_masks_api_key(self) -> None:
        config = GeminiConfig(api_key="super-secret-key-12345")
        text = repr(config)
        self.assertIn("api_key='***'", text)
        self.assertNotIn("super-secret-key-12345", text)

    def test_repr_contains_model_and_base_url(self) -> None:
        config = GeminiConfig(api_key="test-key-12345", model="gemini-1.5-pro")
        text = repr(config)
        self.assertIn("gemini-1.5-pro", text)
        self.assertIn(DEFAULT_GEMINI_BASE_URL, text)

    def test_import_does_not_require_api_key(self) -> None:
        # Importing the config module and referencing defaults works with no key.
        self.assertEqual(DEFAULT_GEMINI_MODEL, "gemini-3.5-flash-lite")
        self.assertEqual(DEFAULT_GEMINI_BASE_URL, "https://generativelanguage.googleapis.com")


if __name__ == "__main__":
    unittest.main()
