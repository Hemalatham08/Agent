"""Public exports for the Gemini AI provider."""

from __future__ import annotations

from backend.ai_providers.gemini.client import GeminiClient
from backend.ai_providers.gemini.config import (
    DEFAULT_GEMINI_BASE_URL,
    DEFAULT_GEMINI_MODEL,
    DEFAULT_GEMINI_TIMEOUT_SECONDS,
    GeminiConfig,
)
from backend.ai_providers.gemini.errors import (
    GeminiAuthError,
    GeminiConfigurationError,
    GeminiConnectionError,
    GeminiError,
    GeminiModelNotFoundError,
    GeminiResponseError,
    GeminiTimeoutError,
)
from backend.ai_providers.gemini.models import (
    GeminiChatMessage,
    GeminiChatRole,
    GeminiModelInfo,
    GeminiResponse,
)
from backend.ai_providers.gemini.response_parser import (
    ParsedGeminiResponse,
    extract_function_call_arguments,
    extract_function_call_name,
    parse_generate_content_response,
)
from backend.ai_providers.gemini.tool_adapter import (
    ToolArgumentIssue,
    adapt_all_erp_tools,
    to_function_declaration,
    to_function_declarations,
    to_function_response,
    to_gemini_tools,
    to_tool_execution_request,
    validate_function_call,
)

__all__ = [
    "DEFAULT_GEMINI_BASE_URL",
    "DEFAULT_GEMINI_MODEL",
    "DEFAULT_GEMINI_TIMEOUT_SECONDS",
    "GeminiAuthError",
    "GeminiClient",
    "GeminiConfigurationError",
    "GeminiConnectionError",
    "GeminiConfig",
    "GeminiChatMessage",
    "GeminiChatRole",
    "GeminiError",
    "GeminiModelInfo",
    "GeminiModelNotFoundError",
    "GeminiResponse",
    "GeminiResponseError",
    "GeminiTimeoutError",
    "ParsedGeminiResponse",
    "ToolArgumentIssue",
    "adapt_all_erp_tools",
    "extract_function_call_arguments",
    "extract_function_call_name",
    "parse_generate_content_response",
    "to_function_declaration",
    "to_function_declarations",
    "to_function_response",
    "to_gemini_tools",
    "to_tool_execution_request",
    "validate_function_call",
]
