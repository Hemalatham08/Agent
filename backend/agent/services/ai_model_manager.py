from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

from backend.agent.erp.platform import ErpToolPlatform
from backend.agent.llm.base import LlmClient
from backend.agent.llm.config import LlmConfig
from backend.agent.llm.errors import LlmError
from backend.agent.llm.llamacpp import LlamaCppConfig
from backend.agent.llm.models import ChatMessage, LLMResponse
from backend.agent.llm.provider import (
    GEMINI_PROVIDER,
    LLAMACPP_PROVIDER,
    OLLAMA_PROVIDER,
    configured_provider_names,
    create_llm_client,
    resolve_provider_name,
)
from backend.agent.services.agent_service import AgentService
from backend.ai_providers.gemini.config import GeminiConfig

_LOGGER = logging.getLogger(__name__)

PROBE_TIMEOUT_SECONDS = 5.0
SWITCH_VALIDATION_TIMEOUT_SECONDS = 10.0

PROVIDER_DISPLAY_NAMES = {
    OLLAMA_PROVIDER: "Llama 3.2 (Ollama)",
    LLAMACPP_PROVIDER: "Qwen3 1.7B (llama.cpp)",
    GEMINI_PROVIDER: "Gemini (Google)",
}

ProviderConfig = LlmConfig | LlamaCppConfig | GeminiConfig
ClientFactory = Callable[[str, ProviderConfig], LlmClient]


class ProviderUnavailableError(RuntimeError):
    """Raised when a provider cannot be validated for switching."""

    def __init__(self, provider: str, reason: str | None = None) -> None:
        self.provider = provider
        self.reason = reason
        label = PROVIDER_DISPLAY_NAMES.get(provider, provider)
        message = f"{label} is currently unavailable."
        if reason:
            message += f" {reason}"
        super().__init__(message)


@dataclass(frozen=True)
class ProviderInfo:
    """Public description of a provider and its current state."""

    provider: str
    model: str
    base_url: str
    available: bool
    active: bool
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "base_url": self.base_url,
            "available": self.available,
            "active": self.active,
            "reason": self.reason,
        }


class _ClientLease:
    """Reference-counted holder for one provider client generation."""

    __slots__ = ("client", "refcount", "retired", "closed")

    def __init__(self, client: LlmClient) -> None:
        self.client = client
        self.refcount = 0
        self.retired = False
        self.closed = False


def _default_client_factory(provider: str, config: ProviderConfig) -> LlmClient:
    if provider == LLAMACPP_PROVIDER:
        if not isinstance(config, LlamaCppConfig):
            raise TypeError("llama.cpp provider requires a LlamaCppConfig")
        return create_llm_client(provider, llamacpp_config=config)

    if provider == GEMINI_PROVIDER:
        if not isinstance(config, GeminiConfig):
            raise TypeError("Gemini provider requires a GeminiConfig")
        return create_llm_client(provider, gemini_config=config)

    if not isinstance(config, LlmConfig):
        raise TypeError("Ollama provider requires an LlmConfig")
    return create_llm_client(provider, llm_config=config)


class ProviderRouterClient:
    """LLM client that delegates to whichever provider is currently active.

    Each call leases the active client for its full duration. A provider switch
    only retires the old generation; the old client is closed after the last
    in-flight call releases its lease.
    """

    def __init__(self, manager: RuntimeAiModelManager) -> None:
        self._manager = manager

    @property
    def config(self) -> ProviderConfig:
        return self._manager.active_config

    def chat(
        self,
        messages: list[ChatMessage],
        *,
        format: str | None = None,
        temperature: float = 0.0,
        timeout: float | None = None,
    ) -> LLMResponse:
        lease = self._manager.acquire_client()
        try:
            return lease.client.chat(
                messages,
                format=format,
                temperature=temperature,
                timeout=timeout,
            )
        finally:
            self._manager.release_client(lease)

    def validate_availability(self) -> None:
        lease = self._manager.acquire_client()
        try:
            lease.client.validate_availability()
        finally:
            self._manager.release_client(lease)

    def close(self) -> None:
        self._manager.close()


class RuntimeAiModelManager:
    """Owns the active LLM provider and supports safe runtime switching."""

    def __init__(
        self,
        platform: ErpToolPlatform,
        *,
        provider: str | None = None,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self._platform = platform
        self._client_factory = client_factory or self._default_client_factory
        self._lock = threading.RLock()
        self._switch_lock = threading.Lock()
        self._closed = False

        initial_provider = resolve_provider_name(provider)
        initial_client = self._client_factory(
            initial_provider,
            self._config_for(initial_provider),
        )
        self._active_provider = initial_provider
        self._active_lease = _ClientLease(initial_client)

        self._router = ProviderRouterClient(self)
        self._agent_service = AgentService.from_platform(
            platform,
            llm_client=self._router,
        )

    @property
    def agent_service(self) -> AgentService:
        return self._agent_service

    @property
    def client(self) -> ProviderRouterClient:
        return self._router

    @property
    def active_provider(self) -> str:
        with self._lock:
            return self._active_provider

    @property
    def active_model(self) -> str:
        with self._lock:
            return self._active_lease.client.config.model

    @property
    def active_config(self) -> ProviderConfig:
        with self._lock:
            return self._active_lease.client.config

    def _default_client_factory(
        self,
        provider: str,
        config: ProviderConfig,
    ) -> LlmClient:
        """Build the default client, wiring the ERP tool registry into Gemini."""

        if provider == GEMINI_PROVIDER:
            if not isinstance(config, GeminiConfig):
                raise TypeError("Gemini provider requires a GeminiConfig")
            return create_llm_client(
                provider,
                gemini_config=config,
                tool_registry=self._platform.registry,
            )
        return _default_client_factory(provider, config)

    def _config_for(self, provider: str) -> ProviderConfig:
        if provider == LLAMACPP_PROVIDER:
            return LlamaCppConfig.from_env()
        if provider == GEMINI_PROVIDER:
            return GeminiConfig.from_env()
        return LlmConfig.from_env()

    def _probe_timeout(self, config: ProviderConfig) -> float:
        return min(config.timeout_seconds, PROBE_TIMEOUT_SECONDS)

    def _probe(self, provider: str) -> ProviderInfo:
        try:
            config = self._config_for(provider)
        except Exception as err:
            return ProviderInfo(
                provider=provider,
                model="",
                base_url="",
                available=False,
                active=False,
                reason=str(err),
            )
        probe_config = replace(
            config,
            timeout_seconds=self._probe_timeout(config),
        )
        try:
            client = self._client_factory(provider, probe_config)
        except Exception as err:
            return ProviderInfo(
                provider=provider,
                model=config.model,
                base_url=config.base_url,
                available=False,
                active=False,
                reason=str(err),
            )
        try:
            client.validate_availability()
            available = True
            reason = None
        except LlmError as err:
            available = False
            reason = str(err)
        except Exception as err:  # pragma: no cover - defensive
            available = False
            reason = f"Could not validate provider: {err}"
        finally:
            client.close()

        return ProviderInfo(
            provider=provider,
            model=config.model,
            base_url=config.base_url,
            available=available,
            active=False,
            reason=reason,
        )

    def list_providers(self) -> list[ProviderInfo]:
        """Probe every configured provider without changing the active one."""
        infos = [self._probe(provider) for provider in configured_provider_names()]
        with self._lock:
            active_provider = self._active_provider
        return [
            replace(info, active=info.provider == active_provider)
            for info in infos
        ]

    def _describe_lease(
        self,
        provider: str,
        lease: _ClientLease,
    ) -> ProviderInfo:
        config = lease.client.config
        try:
            lease.client.validate_availability()
            available = True
            reason = None
        except LlmError as err:
            available = False
            reason = str(err)
        except Exception as err:  # pragma: no cover - defensive
            available = False
            reason = f"Could not validate provider: {err}"

        return ProviderInfo(
            provider=provider,
            model=config.model,
            base_url=config.base_url,
            available=available,
            active=True,
            reason=reason,
        )

    def active_descriptor(self) -> ProviderInfo:
        """Return the active provider with a live availability check."""
        with self._lock:
            if self._closed:
                raise RuntimeError("AI model manager is closed")
            provider = self._active_provider
            lease = self._active_lease
            lease.refcount += 1
        try:
            return self._describe_lease(provider, lease)
        finally:
            self.release_client(lease)

    def switch(self, provider: str) -> ProviderInfo:
        """Validate and activate a provider, preserving the previous on failure."""
        target = resolve_provider_name(provider)

        # Serialize switches; chats continue against the old client meanwhile.
        with self._switch_lock:
            with self._lock:
                if self._closed:
                    raise RuntimeError("AI model manager is closed")
                already_active = target == self._active_provider

            if already_active:
                lease = self.acquire_client()
                try:
                    descriptor = self._describe_lease(target, lease)
                finally:
                    self.release_client(lease)
                if not descriptor.available:
                    raise ProviderUnavailableError(target, descriptor.reason)
                return descriptor

            try:
                config = self._config_for(target)
            except Exception as err:
                raise ProviderUnavailableError(target, str(err)) from err
            probe_config = replace(
                config,
                timeout_seconds=min(
                    config.timeout_seconds,
                    SWITCH_VALIDATION_TIMEOUT_SECONDS,
                ),
            )
            try:
                probe = self._client_factory(target, probe_config)
            except Exception as err:
                raise ProviderUnavailableError(target, str(err)) from err
            try:
                probe.validate_availability()
            except LlmError as err:
                raise ProviderUnavailableError(target, str(err)) from err
            except Exception as err:
                raise ProviderUnavailableError(target, str(err)) from err
            finally:
                probe.close()

            new_client = self._client_factory(target, config)
            try:
                with self._lock:
                    if self._closed:
                        raise RuntimeError("AI model manager is closed")
                    previous_provider = self._active_provider
                    previous_lease = self._active_lease
                    previous_lease.retired = True
                    self._active_lease = _ClientLease(new_client)
                    self._active_provider = target
                    close_previous = previous_lease.refcount == 0
                    if close_previous:
                        previous_lease.closed = True
            except Exception:
                new_client.close()
                raise

            if close_previous:
                previous_lease.client.close()

            _LOGGER.info(
                "ai_model_switched previous=%s active=%s",
                previous_provider,
                target,
            )
            return ProviderInfo(
                provider=target,
                model=config.model,
                base_url=config.base_url,
                available=True,
                active=True,
                reason=None,
            )

    def acquire_client(self) -> _ClientLease:
        with self._lock:
            if self._closed:
                raise RuntimeError("AI model manager is closed")
            lease = self._active_lease
            lease.refcount += 1
            return lease

    def release_client(self, lease: _ClientLease) -> None:
        to_close: LlmClient | None = None
        with self._lock:
            lease.refcount -= 1
            if lease.retired and lease.refcount == 0 and not lease.closed:
                lease.closed = True
                to_close = lease.client
        if to_close is not None:
            to_close.close()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            lease = self._active_lease
            lease.retired = True
            close_now = lease.refcount == 0
            if close_now:
                lease.closed = True
        if close_now:
            lease.client.close()


__all__ = [
    "PROVIDER_DISPLAY_NAMES",
    "ProviderInfo",
    "ProviderRouterClient",
    "ProviderUnavailableError",
    "RuntimeAiModelManager",
]
