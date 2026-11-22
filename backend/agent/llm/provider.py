from __future__ import annotations

import os
from typing import Any

import httpx

from backend.agent.llm.base import LlmClient
from backend.agent.llm.client import OllamaClient
from backend.agent.llm.config import LlmConfig
from backend.agent.llm.llamacpp import LlamaCppClient, LlamaCppConfig

LLM_PROVIDER_ENV = "LLM_PROVIDER"

OLLAMA_PROVIDER = "ollama"
LLAMACPP_PROVIDER = "llamacpp"
GEMINI_PROVIDER = "gemini"
SUPPORTED_PROVIDERS = (OLLAMA_PROVIDER, LLAMACPP_PROVIDER, GEMINI_PROVIDER)

_PROVIDER_ALIASES = {
    "qwen": LLAMACPP_PROVIDER,
    "qwen3": LLAMACPP_PROVIDER,
    "llama.cpp": LLAMACPP_PROVIDER,
    "llama_cpp": LLAMACPP_PROVIDER,
    "google": GEMINI_PROVIDER,
    "google-gemini": GEMINI_PROVIDER,
    "google_genai": GEMINI_PROVIDER,
}


def configured_provider_names() -> tuple[str, ...]:
    """Return providers exposed by the runtime model selector.

    Gemini is only listed when an API key is configured, so Ollama-only
    installations (and existing local deployments) keep their current model
    list and behavior. Selecting Gemini explicitly still works when configured.
    """

    providers = [OLLAMA_PROVIDER, LLAMACPP_PROVIDER]
    if os.getenv("GEMINI_API_KEY", "").strip():
        providers.append(GEMINI_PROVIDER)
    return tuple(providers)


def resolve_provider_name(provider: str | None = None) -> str:
    """Resolve an explicit or environment-selected provider name.

    Defaults to Ollama so existing deployments keep their current behavior.
    """
    raw = (provider if provider is not None else os.getenv(LLM_PROVIDER_ENV, "")).strip()
    if not raw:
        return OLLAMA_PROVIDER

    normalized = _PROVIDER_ALIASES.get(raw.lower(), raw.lower())
    if normalized not in SUPPORTED_PROVIDERS:
        supported = ", ".join(SUPPORTED_PROVIDERS)
        raise ValueError(
            f"Unsupported LLM provider '{raw}'. Supported providers: {supported}."
        )
    return normalized


def create_llm_client(
    provider: str | None = None,
    *,
    llm_config: LlmConfig | None = None,
    llamacpp_config: LlamaCppConfig | None = None,
    gemini_config: Any | None = None,
    tool_registry: Any | None = None,
    http_client: httpx.Client | None = None,
) -> LlmClient:
    """Build the selected LLM provider client.

    ``provider`` accepts ``"ollama"`` (default), ``"llamacpp"`` (aliases:
    ``"qwen"``, ``"qwen3"``), or ``"gemini"``. When omitted, ``LLM_PROVIDER``
    is consulted.
    """
    name = resolve_provider_name(provider)
    if name == LLAMACPP_PROVIDER:
        config = llamacpp_config or LlamaCppConfig.from_env()
        return LlamaCppClient(config, http_client=http_client)

    if name == GEMINI_PROVIDER:
        from backend.ai_providers.gemini.adapter import GeminiLlmClientAdapter
        from backend.ai_providers.gemini.config import GeminiConfig

        config = gemini_config or GeminiConfig.from_env()
        if not isinstance(config, GeminiConfig):
            raise TypeError("Gemini provider requires a GeminiConfig")
        return GeminiLlmClientAdapter(
            config,
            tool_registry=tool_registry,
        )

    config = llm_config or LlmConfig.from_env()
    return OllamaClient(config, http_client=http_client)


__all__ = [
    "GEMINI_PROVIDER",
    "LLAMACPP_PROVIDER",
    "LLM_PROVIDER_ENV",
    "OLLAMA_PROVIDER",
    "SUPPORTED_PROVIDERS",
    "configured_provider_names",
    "create_llm_client",
    "resolve_provider_name",
]
