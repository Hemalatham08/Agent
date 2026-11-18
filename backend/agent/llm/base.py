from __future__ import annotations

from typing import Any, Protocol

from backend.agent.llm.models import ChatMessage, LLMResponse


class LlmClient(Protocol):
    """Common interface shared by local LLM provider clients.

    ``OllamaClient`` and ``LlamaCppClient`` both implement this structural
    interface, so the orchestrator and service layer can depend on it without
    changing provider-specific behavior.
    """

    config: Any

    def chat(
        self,
        messages: list[ChatMessage],
        *,
        format: str | None = None,
        temperature: float = 0.0,
        timeout: float | None = None,
    ) -> LLMResponse:
        """Send chat messages and return the assistant response."""

    def validate_availability(self) -> None:
        """Ensure the provider is reachable and the configured model exists."""

    def close(self) -> None:
        """Release provider resources."""


__all__ = ["LlmClient"]
