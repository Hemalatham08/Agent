from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse

DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "llama3.2"
DEFAULT_OLLAMA_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_TOOL_CALLS = 5


@dataclass(frozen=True)
class LlmConfig:
    """Configuration for local Ollama LLM integration."""

    base_url: str = DEFAULT_OLLAMA_BASE_URL
    model: str = DEFAULT_OLLAMA_MODEL
    timeout_seconds: float = DEFAULT_OLLAMA_TIMEOUT_SECONDS
    max_tool_calls: int = DEFAULT_MAX_TOOL_CALLS

    def __post_init__(self) -> None:
        url = self.base_url.strip()
        if not url:
            raise ValueError("base_url must not be empty")

        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError(f"base_url scheme must be http or https, got '{parsed.scheme}'")
        if not parsed.netloc:
            raise ValueError("base_url must contain a valid host and port")

        # Normalize trailing slash
        normalized_url = url.rstrip("/")
        object.__setattr__(self, "base_url", normalized_url)

        model_name = self.model.strip()
        if not model_name:
            raise ValueError("model must not be empty")
        object.__setattr__(self, "model", model_name)

        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

        if self.max_tool_calls < 1:
            raise ValueError("max_tool_calls must be at least 1")

    @classmethod
    def from_env(cls) -> LlmConfig:
        base_url = os.getenv("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL).strip()
        if not base_url:
            base_url = DEFAULT_OLLAMA_BASE_URL

        model = os.getenv("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL).strip()
        if not model:
            model = DEFAULT_OLLAMA_MODEL

        timeout_raw = os.getenv("OLLAMA_TIMEOUT_SECONDS", "").strip()
        timeout = DEFAULT_OLLAMA_TIMEOUT_SECONDS
        if timeout_raw:
            try:
                timeout = float(timeout_raw)
            except ValueError:
                timeout = DEFAULT_OLLAMA_TIMEOUT_SECONDS

        max_calls_raw = os.getenv("AGENT_MAX_TOOL_CALLS", "").strip()
        max_calls = DEFAULT_MAX_TOOL_CALLS
        if max_calls_raw:
            try:
                max_calls = int(max_calls_raw)
            except ValueError:
                max_calls = DEFAULT_MAX_TOOL_CALLS

        return cls(
            base_url=base_url,
            model=model,
            timeout_seconds=timeout,
            max_tool_calls=max_calls,
        )

