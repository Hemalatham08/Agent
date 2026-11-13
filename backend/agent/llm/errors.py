from __future__ import annotations


class LlmError(Exception):
    """Base exception for LLM operations."""


class LlmConnectionError(LlmError):
    """Raised when the Ollama service cannot be reached."""

    def __init__(self, base_url: str, detail: str | None = None) -> None:
        self.base_url = base_url
        self.detail = detail
        message = (
            f"Cannot connect to local Ollama service at '{base_url}'. "
            "Please ensure Ollama is installed and running (`ollama serve`)."
        )
        if detail:
            message += f" Details: {detail}"
        super().__init__(message)


class LlmModelNotFoundError(LlmError):
    """Raised when the requested model is not installed locally in Ollama."""

    def __init__(self, model_name: str, available_models: list[str] | None = None) -> None:
        self.model_name = model_name
        self.available_models = available_models or []
        available_str = ", ".join(f"'{m}'" for m in self.available_models) if self.available_models else "none"
        message = (
            f"Configured model '{model_name}' is not installed in Ollama. "
            f"Run `ollama pull {model_name}` to download it, or set OLLAMA_MODEL to an available model. "
            f"Currently available models: [{available_str}]."
        )
        super().__init__(message)


class LlmTimeoutError(LlmError):
    """Raised when an Ollama call times out."""

    def __init__(self, timeout_seconds: float) -> None:
        self.timeout_seconds = timeout_seconds
        super().__init__(f"Ollama request timed out after {timeout_seconds:.1f} seconds.")


class LlmResponseError(LlmError):
    """Raised when Ollama returns an unexpected HTTP error or invalid response."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        self.status_code = status_code
        super().__init__(message)
