from __future__ import annotations


class LlmError(Exception):
    """Base exception for LLM operations."""


class LlmConnectionError(LlmError):
    """Raised when a local LLM service cannot be reached."""

    def __init__(
        self,
        base_url: str,
        detail: str | None = None,
        *,
        service_name: str = "Ollama",
        hint: str | None = None,
    ) -> None:
        self.base_url = base_url
        self.detail = detail
        self.service_name = service_name
        self.hint = hint or (
            "Please ensure Ollama is installed and running (`ollama serve`)."
        )
        message = (
            f"Cannot connect to local {service_name} service at '{base_url}'. "
            f"{self.hint}"
        )
        if detail:
            message += f" Details: {detail}"
        super().__init__(message)


class LlmModelNotFoundError(LlmError):
    """Raised when the requested model is not available from the provider."""

    def __init__(
        self,
        model_name: str,
        available_models: list[str] | None = None,
        *,
        service_name: str = "Ollama",
        remedy: str | None = None,
    ) -> None:
        self.model_name = model_name
        self.available_models = available_models or []
        self.service_name = service_name
        available_str = ", ".join(f"'{m}'" for m in self.available_models) if self.available_models else "none"
        if service_name == "Ollama" and remedy is None:
            message = (
                f"Configured model '{model_name}' is not installed in Ollama. "
                f"Run `ollama pull {model_name}` to download it, or set OLLAMA_MODEL to an available model. "
                f"Currently available models: [{available_str}]."
            )
        else:
            remedy_text = remedy or (
                f"Load this model in the {service_name} server or configure an "
                "available model."
            )
            message = (
                f"Configured model '{model_name}' is not available from "
                f"{service_name}. {remedy_text} "
                f"Currently available models: [{available_str}]."
            )
        super().__init__(message)


class LlmTimeoutError(LlmError):
    """Raised when a local LLM call times out."""

    def __init__(
        self,
        timeout_seconds: float,
        *,
        service_name: str = "Ollama",
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.service_name = service_name
        super().__init__(
            f"{service_name} request timed out after {timeout_seconds:.1f} seconds."
        )


class LlmResponseError(LlmError):
    """Raised when Ollama returns an unexpected HTTP error or invalid response."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        self.status_code = status_code
        super().__init__(message)
