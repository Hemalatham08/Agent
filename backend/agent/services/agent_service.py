from __future__ import annotations

from typing import Any

from backend.agent.erp.platform import ErpToolPlatform
from backend.agent.llm.base import LlmClient
from backend.agent.llm.config import DEFAULT_MAX_TOOL_CALLS, LlmConfig
from backend.agent.llm.llamacpp import LlamaCppConfig
from backend.agent.llm.provider import create_llm_client
from backend.ai_providers.gemini.config import GeminiConfig
from backend.agent.charts.service import ChartService
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
        self.chart_service = ChartService()

    @classmethod
    def from_platform(
        cls,
        platform: ErpToolPlatform,
        *,
        llm_config: LlmConfig | None = None,
        llm_client: LlmClient | None = None,
        provider: str | None = None,
        llamacpp_config: LlamaCppConfig | None = None,
        gemini_config: GeminiConfig | None = None,
    ) -> AgentService:
        client = llm_client or create_llm_client(
            provider,
            llm_config=llm_config,
            llamacpp_config=llamacpp_config,
            gemini_config=gemini_config,
            tool_registry=platform.registry,
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
        result = self.orchestrator.process_question(question, session_id=session_id)
        charts = self._build_charts(result)
        if charts:
            return result.model_copy(update={"charts": charts})
        return result

    def _build_charts(self, result: AgentExecutionResult) -> list[dict[str, Any]]:
        successful_outputs = [
            (summary.tool_name, summary.output)
            for summary in result.tool_calls
            if summary.status == "succeeded" and isinstance(summary.output, dict)
        ]
        specs = self.chart_service.build_charts(successful_outputs)
        return [spec.model_dump() for spec in specs]

    def close(self) -> None:
        self.client.close()
