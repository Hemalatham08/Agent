"""Tests for the Gemini client module.

Uses mocks only. No real Gemini API calls are made.
"""

from __future__ import annotations

import logging
import subprocess
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from google.genai import errors as genai_errors

from backend.ai_providers.gemini.client import (
    GeminiClient,
    _GEN_AI_AVAILABLE,
)
from backend.ai_providers.gemini.config import GeminiConfig
from backend.ai_providers.gemini.errors import (
    GeminiAuthError,
    GeminiConfigurationError,
    GeminiConnectionError,
    GeminiInvalidRequestError,
    GeminiModelNotFoundError,
    GeminiPermissionError,
    GeminiQuotaError,
    GeminiResponseError,
    GeminiTimeoutError,
)
from backend.ai_providers.gemini.models import (
    GeminiChatMessage,
    GeminiChatRole,
)


def _make_config(api_key: str = "test-key-12345") -> GeminiConfig:
    return GeminiConfig(api_key=api_key, model="gemini-3.5-flash-lite")


def _make_fake_model_list(names):
    return [
        SimpleNamespace(name=name, version="1") for name in names
    ]


def _make_fake_generate_response(text="Hello from Gemini", model="gemini-3.5-flash-lite"):
    return SimpleNamespace(
        text=text,
        model_version=model,
        candidates=[
            SimpleNamespace(finish_reason="STOP", safety_ratings=[])
        ],
    )


class TestGeminiClientConstruction(unittest.TestCase):
    def test_client_constructs_without_network(self) -> None:
        # Constructing the client must not call the Gemini service.
        client = GeminiClient(_make_config())
        self.assertIsNone(client._sdk_client)
        client.close()

    def test_client_constructs_does_not_call_service(self) -> None:
        # With a valid key, construction still makes no network call.
        client = GeminiClient(_make_config(api_key="valid-key"))
        self.assertIsNone(client._sdk_client)
        client.close()

    def test_close_is_safe_repeated(self) -> None:
        client = GeminiClient(_make_config())
        client.close()
        client.close()


class TestGeminiClientHealthAndModels(unittest.TestCase):
    def _patched_client(self, models_list_return):
        client = GeminiClient(_make_config())
        with patch(
            "backend.ai_providers.gemini.client.genai.Client"
        ) as mock_client_class:
            mock_client = mock_client_class.return_value
            mock_client.models.list.return_value = models_list_return
            yield client, mock_client

    def test_is_healthy_success(self) -> None:
        for client, mock_client in self._patched_client(
            _make_fake_model_list(["gemini-1.5-flash"])
        ):
            self.assertTrue(client.is_healthy())
            mock_client.models.list.assert_called_once()

    def test_is_healthy_failure(self) -> None:
        for client, mock_client in self._patched_client([]):
            mock_client.models.list.side_effect = genai_errors.ClientError(
                401, {"error": {"message": "invalid key"}}, None
            )
            self.assertFalse(client.is_healthy())

    def test_list_models(self) -> None:
        for client, mock_client in self._patched_client(
            _make_fake_model_list(["gemini-1.5-flash", "gemini-1.5-pro"])
        ):
            models = client.list_models()
            self.assertEqual(len(models), 2)
            self.assertEqual(models[0].name, "gemini-1.5-flash")
            self.assertEqual(models[1].name, "gemini-1.5-pro")

    def test_list_models_error_maps_to_connection_error(self) -> None:
        for client, mock_client in self._patched_client([]):
            mock_client.models.list.side_effect = genai_errors.ServerError(
                500, {"error": {"message": "down"}}, None
            )
            with self.assertRaises(GeminiResponseError):
                client.list_models()

    def test_is_model_available_true(self) -> None:
        for client, mock_client in self._patched_client(
            _make_fake_model_list(["gemini-3.5-flash-lite"])
        ):
            self.assertTrue(client.is_model_available("gemini-3.5-flash-lite"))
            self.assertTrue(client.is_model_available())

    def test_is_model_available_false(self) -> None:
        for client, mock_client in self._patched_client(
            _make_fake_model_list(["gemini-1.5-pro"])
        ):
            self.assertFalse(client.is_model_available("gemini-3.5-flash-lite"))

    def test_validate_availability_missing_raises(self) -> None:
        for client, mock_client in self._patched_client(
            _make_fake_model_list(["gemini-1.5-pro"])
        ):
            with self.assertRaises(GeminiModelNotFoundError):
                client.validate_availability()

    def test_validate_availability_ok(self) -> None:
        for client, mock_client in self._patched_client(
            _make_fake_model_list(["gemini-3.5-flash-lite"])
        ):
            client.validate_availability()  # should not raise

    def test_is_model_available_returns_false_on_list_models_error(self) -> None:
        for client, mock_client in self._patched_client([]):
            mock_client.models.list.side_effect = GeminiConnectionError(
                "Cannot connect to the Gemini service."
            )
            self.assertFalse(client.is_model_available("gemini-3.5-flash-lite"))

    def test_validate_availability_propagates_list_models_error(self) -> None:
        for client, mock_client in self._patched_client([]):
            # An SDK 404 error maps to GeminiModelNotFoundError via
            # _map_sdk_error and should propagate from validate_availability.
            mock_client.models.list.side_effect = genai_errors.ClientError(
                404, {"error": {"message": "not found", "code": 404}}, None
            )
            with self.assertRaises(GeminiModelNotFoundError):
                client.validate_availability()

    def test_is_model_available_with_models_prefix(self) -> None:
        """Model names with 'models/' prefix are normalized for comparison."""
        for client, mock_client in self._patched_client(
            _make_fake_model_list(["models/gemini-3.5-flash-lite"])
        ):
            self.assertTrue(client.is_model_available("gemini-3.5-flash-lite"))
            self.assertTrue(client.is_model_available("models/gemini-3.5-flash-lite"))

    def test_validate_availability_with_models_prefix(self) -> None:
        """validate_availability works when API returns models with 'models/' prefix."""
        for client, mock_client in self._patched_client(
            _make_fake_model_list(["models/gemini-3.5-flash-lite"])
        ):
            client.validate_availability()  # should not raise

    def test_is_model_available_with_version_suffix(self) -> None:
        """Model names with version suffix (e.g. ':latest') are handled."""
        for client, mock_client in self._patched_client(
            _make_fake_model_list(["gemini-3.5-flash-lite:latest"])
        ):
            self.assertTrue(client.is_model_available("gemini-3.5-flash-lite"))
            self.assertTrue(client.is_model_available("gemini-3.5-flash-lite:latest"))


class TestGeminiClientChat(unittest.TestCase):
    def _patched_chat_client(self, generate_return):
        client = GeminiClient(_make_config())
        with patch(
            "backend.ai_providers.gemini.client.genai.Client"
        ) as mock_client_class:
            mock_client = mock_client_class.return_value
            mock_client.models.generate_content.return_value = generate_return
            yield client, mock_client

    def test_chat_success_returns_normalized_response(self) -> None:
        for client, mock_client in self._patched_chat_client(
            _make_fake_generate_response("Hello from Gemini")
        ):
            response = client.chat(
                [GeminiChatMessage(role=GeminiChatRole.USER, content="Say hi")]
            )
            self.assertEqual(response.content, "Hello from Gemini")
            self.assertEqual(response.model, "gemini-3.5-flash-lite")
            self.assertFalse(response.truncated)

    def test_chat_maps_system_to_system_instruction(self) -> None:
        for client, mock_client in self._patched_chat_client(
            _make_fake_generate_response()
        ):
            client.chat(
                [
                    GeminiChatMessage(
                        role=GeminiChatRole.SYSTEM, content="You are helpful."
                    ),
                    GeminiChatMessage(
                        role=GeminiChatRole.USER, content="Hello."
                    ),
                ]
            )
            call_kwargs = mock_client.models.generate_content.call_args.kwargs
            config = call_kwargs["config"]
            self.assertEqual(config.system_instruction, "You are helpful.")
            contents = call_kwargs["contents"]
            self.assertEqual(contents[0].role, "user")

    def test_chat_maps_user_and_model_roles(self) -> None:
        for client, mock_client in self._patched_chat_client(
            _make_fake_generate_response()
        ):
            client.chat(
                [
                    GeminiChatMessage(role=GeminiChatRole.USER, content="Q"),
                    GeminiChatMessage(
                        role=GeminiChatRole.MODEL, content="A"
                    ),
                ]
            )
            contents = mock_client.models.generate_content.call_args.kwargs["contents"]
            self.assertEqual(contents[0].role, "user")
            self.assertEqual(contents[1].role, "model")

    def test_chat_maps_model_role(self) -> None:
        """A MODEL role message is mapped to Gemini 'model' role content."""
        for client, mock_client in self._patched_chat_client(
            _make_fake_generate_response()
        ):
            client.chat(
                [
                    GeminiChatMessage(
                        role=GeminiChatRole.MODEL, content="Prior answer."
                    ),
                    GeminiChatMessage(
                        role=GeminiChatRole.USER, content="Follow-up."
                    ),
                ]
            )
            contents = mock_client.models.generate_content.call_args.kwargs[
                "contents"
            ]
            self.assertEqual(contents[0].role, "model")
            self.assertEqual(contents[1].role, "user")

    def test_chat_uses_configured_model(self) -> None:
        for client, mock_client in self._patched_chat_client(
            _make_fake_generate_response()
        ):
            client.chat([GeminiChatMessage(role=GeminiChatRole.USER, content="Q")])
            call_kwargs = mock_client.models.generate_content.call_args.kwargs
            self.assertEqual(call_kwargs["model"], "gemini-3.5-flash-lite")

    def test_chat_auth_error_raises_sanitized(self) -> None:
        for client, mock_client in self._patched_chat_client(
            _make_fake_generate_response()
        ):
            mock_client.models.generate_content.side_effect = genai_errors.ClientError(
                401,
                {"error": {"message": "invalid credentials", "code": 401}},
                None,
            )
            with self.assertRaises(GeminiAuthError) as ctx:
                client.chat([GeminiChatMessage(role=GeminiChatRole.USER, content="Q")])
            self.assertNotIn("test-key", str(ctx.exception))

    def test_chat_model_not_found_raises(self) -> None:
        for client, mock_client in self._patched_chat_client(
            _make_fake_generate_response()
        ):
            mock_client.models.generate_content.side_effect = genai_errors.ClientError(
                404,
                {"error": {"message": "not found", "code": 404}},
                None,
            )
            with self.assertRaises(GeminiModelNotFoundError):
                client.chat([GeminiChatMessage(role=GeminiChatRole.USER, content="Q")])

    def test_chat_server_error_raises(self) -> None:
        for client, mock_client in self._patched_chat_client(
            _make_fake_generate_response()
        ):
            mock_client.models.generate_content.side_effect = genai_errors.ServerError(
                500, {"error": {"message": "internal"}}, None
            )
            with self.assertRaises(GeminiResponseError):
                client.chat([GeminiChatMessage(role=GeminiChatRole.USER, content="Q")])

    def test_chat_connection_error_raises(self) -> None:
        for client, mock_client in self._patched_chat_client(
            _make_fake_generate_response()
        ):
            mock_client.models.generate_content.side_effect = ConnectionError(
                "connection refused"
            )
            with self.assertRaises(GeminiConnectionError):
                client.chat([GeminiChatMessage(role=GeminiChatRole.USER, content="Q")])

    def test_chat_bad_request_raises(self) -> None:
        for client, mock_client in self._patched_chat_client(
            _make_fake_generate_response()
        ):
            mock_client.models.generate_content.side_effect = genai_errors.ClientError(
                400,
                {"error": {"message": "invalid request", "code": 400}},
                None,
            )
            with self.assertRaises(GeminiInvalidRequestError):
                client.chat([GeminiChatMessage(role=GeminiChatRole.USER, content="Q")])

    def test_chat_forbidden_raises(self) -> None:
        for client, mock_client in self._patched_chat_client(
            _make_fake_generate_response()
        ):
            mock_client.models.generate_content.side_effect = genai_errors.ClientError(
                403,
                {"error": {"message": "access denied", "code": 403}},
                None,
            )
            with self.assertRaises(GeminiPermissionError):
                client.chat([GeminiChatMessage(role=GeminiChatRole.USER, content="Q")])

    def test_chat_quota_exceeded_raises(self) -> None:
        for client, mock_client in self._patched_chat_client(
            _make_fake_generate_response()
        ):
            mock_client.models.generate_content.side_effect = genai_errors.ClientError(
                429,
                {"error": {"message": "quota exceeded", "code": 429}},
                None,
            )
            with self.assertRaises(GeminiQuotaError):
                client.chat([GeminiChatMessage(role=GeminiChatRole.USER, content="Q")])

    def test_chat_unknown_http_status_raises(self) -> None:
        for client, mock_client in self._patched_chat_client(
            _make_fake_generate_response()
        ):
            # Unhandled 4xx status code (e.g., 418 I'm a teapot)
            mock_client.models.generate_content.side_effect = genai_errors.ClientError(
                418,
                {"error": {"message": "I'm a teapot", "code": 418}},
                None,
            )
            with self.assertRaises(GeminiResponseError) as ctx:
                client.chat([GeminiChatMessage(role=GeminiChatRole.USER, content="Q")])
            # Verify the status code is included in the error message
            self.assertIn("418", str(ctx.exception))

    def test_api_key_not_in_logged_message(self) -> None:
        for client, mock_client in self._patched_chat_client(
            _make_fake_generate_response()
        ):
            with self.assertLogs("backend.ai_providers.gemini.client", level="INFO") as captured:
                client.chat([GeminiChatMessage(role=GeminiChatRole.USER, content="Q")])
            joined = "\n".join(c.getMessage() for c in captured.records)
            self.assertNotIn("test-key-12345", joined)
            self.assertNotIn("api_key", joined.lower())

    def test_chat_sanitizes_sensitive_sdk_error_message(self) -> None:
        """A raw SDK error containing a secret must not leak into exceptions."""
        for client, mock_client in self._patched_chat_client(
            _make_fake_generate_response()
        ):
            # The SDK error message contains a fake API key / secret.
            sensitive_msg = "invalid credentials for key AIzaSySecretKey1234567890"
            mock_client.models.generate_content.side_effect = (
                genai_errors.ClientError(
                    401,
                    {"error": {"message": sensitive_msg, "code": 401}},
                    None,
                )
            )
            with self.assertRaises(GeminiAuthError) as ctx:
                client.chat([GeminiChatMessage(role=GeminiChatRole.USER, content="Q")])
            # The raised exception must not contain the raw secret.
            self.assertNotIn("AIzaSySecretKey1234567890", str(ctx.exception))
            self.assertNotIn(sensitive_msg, str(ctx.exception))

    def test_chat_converts_tool_function_messages(self) -> None:
        """TOOL/FUNCTION roles are converted to function_response parts."""
        for client, mock_client in self._patched_chat_client(
            _make_fake_generate_response()
        ):
            result = client.chat(
                [
                    GeminiChatMessage(
                        role=GeminiChatRole.USER, content="Q"
                    ),
                    GeminiChatMessage(
                        role=GeminiChatRole.TOOL, content='{"result": "x"}',
                        call_id="call-1", tool_name="erp.products.get"
                    ),
                ]
            )
            self.assertEqual(result.content, "Hello from Gemini")
            # Ensure generate_content was called (messages were not rejected)
            mock_client.models.generate_content.assert_called_once()
            # Verify the tool response was passed with correct structure
            call_kwargs = mock_client.models.generate_content.call_args
            contents = call_kwargs.kwargs["contents"]
            # Last content part should have role "user" with function_response part
            last_content = contents[-1]
            self.assertEqual(last_content.role, "user")
            last_part = last_content.parts[0]
            self.assertEqual(last_part.function_response.name, "erp.products.get")
            self.assertEqual(last_part.function_response.id, "call-1")
            self.assertEqual(last_part.function_response.response, {"result": "x"})

    def test_per_call_timeout_does_not_persist(self) -> None:
        """A timeout supplied to one chat() call must not change later calls.

        Timeouts are expressed in seconds in the public interface but converted
        to milliseconds for the SDK HttpOptions. The first call uses timeout=5
        seconds (5000 ms); the second call (no timeout) uses the persistent
        client with a fixed metadata timeout (120000 ms).
        """
        recorded_timeouts: list = []

        def fake_generate_content(model=None, contents=None, config=None):
            return _make_fake_generate_response()

        class TrackingClient:
            def __init__(self, api_key=None, http_options=None, **kwargs):
                if http_options is not None:
                    recorded_timeouts.append(http_options.timeout)
                self.models = SimpleNamespace(
                    generate_content=fake_generate_content
                )

        client = GeminiClient(_make_config())
        with patch(
            "backend.ai_providers.gemini.client.genai.Client",
            new=TrackingClient,
        ):
            # First call: per-call timeout 5 seconds -> 5000 ms.
            client.chat(
                [GeminiChatMessage(role=GeminiChatRole.USER, content="Q")],
                timeout=5,
            )
            # Second call: no timeout -> persistent client with fixed 120000 ms.
            client.chat(
                [GeminiChatMessage(role=GeminiChatRole.USER, content="Q2")],
            )

        # Verify units are milliseconds, not seconds.
        self.assertEqual(recorded_timeouts, [5000, 120000])

    def test_first_call_custom_timeout_uses_temp_client(self) -> None:
        """A custom timeout works on the first-ever chat call (no persistent
        client exists yet). Timeouts are converted to milliseconds."""
        recorded_timeouts: list = []

        def fake_generate_content(model=None, contents=None, config=None):
            return _make_fake_generate_response()

        class TrackingClient:
            def __init__(self, api_key=None, http_options=None, **kwargs):
                if http_options is not None:
                    recorded_timeouts.append(http_options.timeout)
                self.models = SimpleNamespace(
                    generate_content=fake_generate_content
                )

        client = GeminiClient(_make_config())
        # No persistent client exists yet (_sdk_client is None).
        self.assertIsNone(client._sdk_client)
        with patch(
            "backend.ai_providers.gemini.client.genai.Client",
            new=TrackingClient,
        ):
            client.chat(
                [GeminiChatMessage(role=GeminiChatRole.USER, content="Q")],
                timeout=7.5,
            )
        # 7.5 seconds → 7500 milliseconds (fractional seconds preserved).
        self.assertEqual(recorded_timeouts, [7500])
        # The temp client was closed; no persistent client remains.
        self.assertIsNone(client._sdk_client)

    def test_second_call_uses_configured_default_timeout(self) -> None:
        """After a custom-timeout call, a subsequent call with no timeout uses
        the persistent client with fixed metadata timeout (120000 ms)."""
        recorded_timeouts: list = []

        def fake_generate_content(model=None, contents=None, config=None):
            return _make_fake_generate_response()

        class TrackingClient:
            def __init__(self, api_key=None, http_options=None, **kwargs):
                if http_options is not None:
                    recorded_timeouts.append(http_options.timeout)
                self.models = SimpleNamespace(
                    generate_content=fake_generate_content
                )

        client = GeminiClient(_make_config())
        with patch(
            "backend.ai_providers.gemini.client.genai.Client",
            new=TrackingClient,
        ):
            # First call: custom timeout 5 seconds -> 5000 ms.
            client.chat(
                [GeminiChatMessage(role=GeminiChatRole.USER, content="Q")],
                timeout=5,
            )
            # Second call: no timeout -> persistent client with fixed 120000 ms.
            client.chat(
                [GeminiChatMessage(role=GeminiChatRole.USER, content="Q2")],
            )
        self.assertEqual(recorded_timeouts, [5000, 120000])

    def test_persistent_client_uses_configured_timeout_in_milliseconds(self) -> None:
        """The persistent client created via _client property uses the configured
        timeout (seconds) converted to milliseconds for metadata operations."""
        recorded_timeouts: list = []

        def fake_list_models():
            return _make_fake_model_list(["gemini-3.5-flash-lite"])

        class TrackingClient:
            def __init__(self, api_key=None, http_options=None, **kwargs):
                if http_options is not None:
                    recorded_timeouts.append(http_options.timeout)
                self.models = SimpleNamespace(
                    list=fake_list_models
                )

        # Use a config with a non-default timeout to verify conversion
        config = _make_config(api_key="test-key-12345")
        # Override timeout to a non-integer value to test conversion
        object.__setattr__(config, "timeout_seconds", 7.5)

        client = GeminiClient(config)
        with patch(
            "backend.ai_providers.gemini.client.genai.Client",
            new=TrackingClient,
        ):
            # Trigger persistent client creation via _client property (metadata operation)
            client.list_models()

        # Verify timeout was converted from 7.5 seconds to 7500 milliseconds
        self.assertEqual(recorded_timeouts, [7500])

    def test_custom_timeout_request_that_raises_still_closes_temp_client(
        self,
    ) -> None:
        """A custom-timeout request that raises an SDK exception still closes
        the temporary client."""
        closed = []

        def fake_generate_content_raises(model=None, contents=None, config=None):
            raise genai_errors.ServerError(
                500, {"error": {"message": "internal"}}, None
            )

        class TrackingClient:
            def __init__(self, api_key=None, http_options=None, **kwargs):
                self.http_options = http_options
                self.models = SimpleNamespace(
                    generate_content=fake_generate_content_raises
                )

            def close(self) -> None:
                closed.append(True)

        client = GeminiClient(_make_config())
        with patch(
            "backend.ai_providers.gemini.client.genai.Client",
            new=TrackingClient,
        ):
            with self.assertRaises(GeminiResponseError):
                client.chat(
                    [GeminiChatMessage(role=GeminiChatRole.USER, content="Q")],
                    timeout=2.0,
                )
        self.assertEqual(len(closed), 1)
        self.assertIsNone(client._sdk_client)

    def test_temp_client_closed_on_success(self) -> None:
        """The temporary client created for a per-call timeout is closed after
        a successful generation."""
        closed = []

        def fake_generate_content(model=None, contents=None, config=None):
            return _make_fake_generate_response()

        class TrackingClient:
            def __init__(self, api_key=None, http_options=None, **kwargs):
                self.models = SimpleNamespace(
                    generate_content=fake_generate_content
                )

            def close(self) -> None:
                closed.append(True)

        client = GeminiClient(_make_config())
        with patch(
            "backend.ai_providers.gemini.client.genai.Client",
            new=TrackingClient,
        ):
            client.chat(
                [GeminiChatMessage(role=GeminiChatRole.USER, content="Q")],
                timeout=3.0,
            )
        self.assertEqual(len(closed), 1)
        self.assertIsNone(client._sdk_client)

    def test_raw_sdk_error_does_not_leak_through_traceback(self) -> None:
        """A sensitive raw SDK error message must not appear in the exception
        string, the formatted traceback, or application logs."""
        import traceback

        for client, mock_client in self._patched_chat_client(
            _make_fake_generate_response()
        ):
            sensitive_msg = "invalid credentials for key AIzaSyLeakedSecret999"
            mock_client.models.generate_content.side_effect = (
                genai_errors.ClientError(
                    401,
                    {"error": {"message": sensitive_msg, "code": 401}},
                    None,
                )
            )
            try:
                client.chat(
                    [GeminiChatMessage(role=GeminiChatRole.USER, content="Q")]
                )
            except GeminiAuthError as exc:
                # Exception string must not contain the secret.
                exc_str = str(exc)
                self.assertNotIn("AIzaSyLeakedSecret999", exc_str)
                self.assertNotIn(sensitive_msg, exc_str)

                # Formatted traceback must not contain the secret.
                tb_str = "".join(
                    traceback.format_exception(type(exc), exc, exc.__traceback__)
                )
                self.assertNotIn("AIzaSyLeakedSecret999", tb_str)
                self.assertNotIn(sensitive_msg, tb_str)

                # Captured logs must not contain the secret.
                with self.assertLogs(
                    "backend.ai_providers.gemini.client", level="WARNING"
                ) as captured:
                    try:
                        client.chat(
                            [
                                GeminiChatMessage(
                                    role=GeminiChatRole.USER, content="Q2"
                                )
                            ]
                        )
                    except GeminiAuthError:
                        pass
                log_joined = "\n".join(c.getMessage() for c in captured.records)
                self.assertNotIn("AIzaSyLeakedSecret999", log_joined)
                self.assertNotIn(sensitive_msg, log_joined)
                return
        self.fail("GeminiAuthError was not raised")


class TestGeminiImportSafety(unittest.TestCase):
    """Verifies the Gemini package imports and behaves safely without
    google-genai installed. Ollama-only installations must not require it.
    """

    def test_client_raises_when_genai_not_available(self) -> None:
        """Constructing GeminiClient must raise a clear error when
        google-genai is not importable."""
        with patch(
            "backend.ai_providers.gemini.client._GEN_AI_AVAILABLE", False
        ):
            with patch(
                "backend.ai_providers.gemini.client.genai", None
            ):
                with self.assertRaises(GeminiConfigurationError) as ctx:
                    GeminiClient(_make_config())
        self.assertIn("google-genai", str(ctx.exception))
        self.assertIn("requirements-gemini.txt", str(ctx.exception))

    def test_gemini_package_importable_in_isolated_subprocess_without_genai(
        self,
    ) -> None:
        """Subprocess test: the Gemini package can be imported in a fresh
        Python process where google-genai is not installed (simulated by
        blocking its import via sys.meta_path).

        This is a genuine import-isolation check, not a monkeypatch of an
        already-loaded module.
        """
        import os
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        code = (
            "import sys\n"
            "for name in list(sys.modules):\n"
            "    if name == 'google' or name.startswith('google.'):\n"
            "        del sys.modules[name]\n"
            "class BlockFinder:\n"
            "    def find_spec(self, name, path=None, target=None):\n"
            "        if name == 'google' or name.startswith('google.'):\n"
            "            raise ImportError(f'Blocked: {name}')\n"
            "        return None\n"
            "sys.meta_path.insert(0, BlockFinder())\n"
            "from backend.ai_providers.gemini.client import (\n"
            "    GeminiClient,\n"
            "    _GEN_AI_AVAILABLE,\n"
            ")\n"
            "assert _GEN_AI_AVAILABLE is False\n"
            "from backend.ai_providers.gemini.config import GeminiConfig\n"
            "try:\n"
            "    GeminiClient(GeminiConfig(api_key='x'))\n"
            "    raise SystemExit('Should have raised')\n"
            "except Exception as exc:\n"
            "    assert 'google-genai' in str(exc), str(exc)\n"
            "print('OK')\n"
        )
        env = os.environ.copy()
        env["PYTHONPATH"] = project_root + (os.pathsep + env["PYTHONPATH"]) if env.get("PYTHONPATH") else project_root
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("OK", result.stdout)



if __name__ == "__main__":
    unittest.main()
