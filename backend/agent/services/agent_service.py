from __future__ import annotations

from backend.agent.erp.platform import ErpToolPlatform
from backend.agent.llm.base import LlmClient
from backend.agent.llm.config import DEFAULT_MAX_TOOL_CALLS, LlmConfig
from backend.agent.llm.llamacpp import LlamaCppConfig
from backend.agent.llm.provider import create_llm_client
from backend.agent.orchestration.models import AgentExecutionResult
from backend.agent.orchestration.orchestrator import AgentOrchestrator


class AgentService:
    """High-level service coordinating the ERP platform, local LLM, and orchestrator."""

    def __init__(
        self,
        *,
        platform: ErpToolPlatform,
        client: LlmClient,
        orchestrator: AgentOrchestrator,
    ) -> None:
        self.platform = platform
        self.client = client
        self.orchestrator = orchestrator

    @classmethod
    def from_platform(
        cls,
        platform: ErpToolPlatform,
        *,
        llm_config: LlmConfig | None = None,
        llm_client: LlmClient | None = None,
        provider: str | None = None,
        llamacpp_config: LlamaCppConfig | None = None,
    ) -> AgentService:
        client = llm_client or create_llm_client(
            provider,
            llm_config=llm_config,
            llamacpp_config=llamacpp_config,
        )
        max_tool_calls = getattr(
            getattr(client, "config", None),
            "max_tool_calls",
            DEFAULT_MAX_TOOL_CALLS,
        )
        orchestrator = AgentOrchestrator(
            client=client,
            runner=platform.runner,
            registry=platform.registry,
            max_tool_calls=max_tool_calls,
        )
        return cls(platform=platform, client=client, orchestrator=orchestrator)

    def answer_question(
        self,
        question: str,
        *,
        session_id: str | None = None,
    ) -> AgentExecutionResult:
        return self.orchestrator.process_question(question, session_id=session_id)

    def close(self) -> None:
        self.client.close()
