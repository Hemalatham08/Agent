"""Provider router for selecting between Ollama and Gemini LLM clients.

This module provides a factory function that instantiates the appropriate
LLM client based on the requested provider. Gemini imports are lazy so that
Ollama-only installations do not require google-genai or GEMINI_API_KEY.

No frontend files are modified. No Ollama code is changed.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional


class ProviderType(str, Enum):
    """Supported AI provider types."""

    OLLAMA = "ollama"
    GEMINI = "gemini"


SUPPORTED_PROVIDERS: frozenset[ProviderType] = frozenset(ProviderType)


def get_llm_client(
    provider: str = ProviderType.OLLAMA,
    model: Optional[str] = None,
) -> Any:
    """Factory that returns an LLM client for the given provider.

    Args:
        provider: Provider name ("ollama" or "gemini"). Defaults to "ollama".
        model: Optional model name override. If not provided, the provider's
            default model from its config is used.

    Returns:
        An LLM client instance (OllamaClient or GeminiClient).

    Raises:
        ValueError: If the provider is not supported.
        GeminiConfigurationError: If Gemini is selected but GEMINI_API_KEY
            is not set or google-genai is not installed.
    """
    provider_type = ProviderType(provider)

    if provider_type == ProviderType.OLLAMA:
        from backend.agent.llm.client import OllamaClient
        from backend.agent.llm.config import LlmConfig

        config = LlmConfig.from_env()
        if model:
            object.__setattr__(config, "model", model)
        return OllamaClient(config)

    if provider_type == ProviderType.GEMINI:
        # Lazy import so Ollama-only installations never import google-genai.
        from backend.ai_providers.gemini.client import GeminiClient
        from backend.ai_providers.gemini.config import GeminiConfig

        config = GeminiConfig.from_env()
        if model:
            object.__setattr__(config, "model", model)
        return GeminiClient(config)

    # Should not reach here because ProviderType is an enum, but be defensive.
    raise ValueError(f"Unsupported provider: {provider}")


def is_supported_provider(provider: str) -> bool:
    """Return True if the provider name is supported."""
    try:
        ProviderType(provider)
        return True
    except ValueError:
        return False


__all__ = [
    "ProviderType",
    "SUPPORTED_PROVIDERS",
    "get_llm_client",
    "is_supported_provider",
]
