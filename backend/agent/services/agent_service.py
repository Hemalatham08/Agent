from __future__ import annotations

from backend.agent.erp.platform import ErpToolPlatform
from backend.agent.llm.client import OllamaClient
from backend.agent.llm.config import LlmConfig
from backend.agent.orchestration.models import AgentExecutionResult
from backend.agent.orchestration.orchestrator import AgentOrchestrator


class AgentService:
    """High-level service coordinating the ERP platform, local LLM, and orchestrator."""

    def __init__(
        self,
        *,
        platform: ErpToolPlatform,
        client: OllamaClient,
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
        llm_client: OllamaClient | None = None,
    ) -> AgentService:
        config = llm_config or LlmConfig.from_env()
        client = llm_client or OllamaClient(config)
        orchestrator = AgentOrchestrator(
            client=client,
            runner=platform.runner,
            registry=platform.registry,
            max_tool_calls=config.max_tool_calls,
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

