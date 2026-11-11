from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from typing import Any

from backend.agent.erp.runner import ErpToolRunner
from backend.agent.llm.client import OllamaClient
from backend.agent.llm.errors import (
    LlmConnectionError,
    LlmError,
    LlmModelNotFoundError,
    LlmTimeoutError,
)
from backend.agent.llm.models import (
    ChatMessage,
    ChatRole,
    ToolSelectionDecision,
)
from backend.agent.orchestration.models import (
    AgentExecutionResult,
    ToolCallSummary,
)
from backend.agent.orchestration.prompts import build_system_prompt
from backend.agent.tools.contracts import (
    ToolDefinition,
    ToolExecutionRequest,
    ToolExecutionStatus,
)
from backend.agent.tools.registry import ToolRegistry

_DROP = object()
_INTEGER_TEXT_PATTERN = re.compile(r"^[+-]?\d+$")

_DISPATCH_TOOL_PREFIX = "erp.dispatches."
_DELIVERY_SEMANTICS_NOTE = (
    "Note: dispatch records establish that goods were handed over to the "
    "carrier at the warehouse; confirmed customer delivery receipts are not "
    "tracked in this ERP."
)
_MAX_FALLBACK_OUTPUT_CHARS = 1200


def _clean_json_text(text: str) -> str:
    """Strip markdown fences and whitespace from model JSON output."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # Remove opening fence
        first_newline = cleaned.find("\n")
        if first_newline != -1:
            cleaned = cleaned[first_newline + 1 :]
        else:
            cleaned = cleaned[3:]
        # Remove closing fence
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

    # If surrounded by other text, try to locate first '{' and matching '}'
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        cleaned = cleaned[start : end + 1]

    return cleaned


def _coerce_schema_value(value: Any, expected_type: Any) -> Any:
    """Coerce one model-supplied argument value toward ``expected_type``.

    Returns the coerced value, or the ``_DROP`` sentinel when the value
    cannot be used for the declared type and should fall back to the
    handler default (or a clear missing-required validation error).
    """

    if value is None:
        return _DROP
    if expected_type == "integer":
        if isinstance(value, bool):
            return _DROP
        if isinstance(value, int):
            return value
        if isinstance(value, float) and math.isfinite(value):
            return int(value) if value.is_integer() else _DROP
        if isinstance(value, str):
            text = value.strip()
            if _INTEGER_TEXT_PATTERN.fullmatch(text):
                return int(text)
            return _DROP
        return _DROP
    if expected_type == "number":
        if isinstance(value, bool):
            return _DROP
        if isinstance(value, (int, float)):
            return value
        if isinstance(value, str):
            try:
                return float(value.strip())
            except ValueError:
                return _DROP
        return _DROP
    if expected_type == "string":
        if isinstance(value, str):
            return value
        if isinstance(value, int) and not isinstance(value, bool):
            return str(value)
        return _DROP
    if expected_type == "boolean":
        return value if isinstance(value, bool) else _DROP
    return value


def normalize_tool_arguments(
    arguments: Mapping[str, Any],
    definition: ToolDefinition,
) -> dict[str, Any]:
    """Validate and safely normalize model-supplied tool arguments.

    Small language models frequently emit ``null`` for optional arguments,
    quote integers (``"20"``), or send identifiers as bare numbers. The
    executor enforces strict JSON types, so those harmless mistakes would
    otherwise fail validation and trigger repeated tool calls. This
    normalizer only performs schema-driven, loss-free coercions:

    * ``null`` values are dropped so handler defaults apply;
    * integer-typed arguments accept digit strings and integral floats;
    * number-typed arguments accept numeric strings;
    * string-typed arguments accept integers (identifier-like values).

    Values that cannot satisfy the declared type are dropped rather than
    executed, and undeclared properties are preserved so the executor still
    reports them as unexpected arguments.
    """

    if not isinstance(arguments, Mapping):
        return {}

    schema = definition.input_schema
    properties = (
        schema.get("properties") if isinstance(schema, Mapping) else None
    )
    if not isinstance(properties, Mapping):
        return dict(arguments)

    normalized: dict[str, Any] = {}
    for name, value in arguments.items():
        property_schema = properties.get(name)
        if not isinstance(property_schema, Mapping):
            normalized[name] = value
            continue
        coerced = _coerce_schema_value(value, property_schema.get("type"))
        if coerced is _DROP:
            continue
        normalized[name] = coerced
    return normalized


def _failure_feedback_lines(tool_name: str, result: Any) -> list[str]:
    """Build actionable feedback for a failed tool execution."""

    error = getattr(result, "error", None)
    code = getattr(error, "code", None) or "tool_error"
    message = getattr(error, "message", None) or "Unknown tool error"
    lines = [f"Tool `{tool_name}` failed with error [{code}]: {message}"]

    details = getattr(error, "details", None)
    if isinstance(details, Mapping):
        issues = details.get("issues")
        if isinstance(issues, list):
            for issue in issues:
                if isinstance(issue, Mapping):
                    issue_message = issue.get("message")
                    if isinstance(issue_message, str) and issue_message.strip():
                        lines.append(f"- {issue_message}")

    if code == "erp_not_found":
        lines.append(
            "Do not guess identifiers. Only use identifiers that appear in "
            "earlier tool output or that the user explicitly provided."
        )

    lines.append(
        "Either correct the arguments for this tool based on the error above, "
        "or provide a final answer using the data already retrieved."
    )
    return lines


def _used_dispatch_tools(summaries: list[ToolCallSummary]) -> bool:
    return any(
        summary.tool_name.startswith(_DISPATCH_TOOL_PREFIX)
        and summary.status == ToolExecutionStatus.SUCCEEDED.value
        for summary in summaries
    )


class AgentOrchestrator:
    """Orchestrates natural-language question understanding, tool calling, and grounded answers."""

    def __init__(
        self,
        *,
        client: OllamaClient,
        runner: ErpToolRunner,
        registry: ToolRegistry,
        max_tool_calls: int = 5,
    ) -> None:
        self.client = client
        self.runner = runner
        self.registry = registry
        self.max_tool_calls = max(1, max_tool_calls)
        # LLM round trips (including retries, corrective feedback, and
        # unparseable output) are bounded separately from executed tool calls
        # so that invalid arguments never burn the tool-call budget.
        self.max_llm_rounds = self.max_tool_calls * 3

    def process_question(
        self,
        question: str,
        *,
        session_id: str | None = None,
    ) -> AgentExecutionResult:
        stripped_question = (question or "").strip()
        if not stripped_question:
            return AgentExecutionResult(
                answer="Please provide a business question.",
                status="completed",
                tool_calls=[],
                session_id=session_id,
            )

        # 1. Health & model availability check
        try:
            self.client.validate_availability()
        except LlmConnectionError as err:
            return AgentExecutionResult(
                answer=(
                    f"The AI assistant is currently unable to reach the local Ollama service "
                    f"at '{self.client.config.base_url}'. Please ensure Ollama is installed and running (`ollama serve`)."
                ),
                status="error",
                error="ollama_unavailable",
                session_id=session_id,
            )
        except LlmModelNotFoundError as err:
            return AgentExecutionResult(
                answer=str(err),
                status="error",
                error="model_not_found",
                session_id=session_id,
            )
        except Exception as err:
            return AgentExecutionResult(
                answer=f"Could not connect to the local language model: {err}",
                status="error",
                error="llm_initialization_error",
                session_id=session_id,
            )

        # 2. Build system prompt from dynamic tool catalog
        tool_definitions = self.registry.export_definitions()
        system_prompt = build_system_prompt(tool_definitions)

        messages: list[ChatMessage] = [
            ChatMessage(role=ChatRole.SYSTEM, content=system_prompt),
            ChatMessage(role=ChatRole.USER, content=stripped_question),
        ]

        executed_summaries: list[ToolCallSummary] = []
        executed_calls_set: set[tuple[str, str]] = set()
        successful_outputs: list[tuple[str, Any]] = []

        iteration = 0
        tool_executions = 0

        while (
            tool_executions < self.max_tool_calls
            and iteration < self.max_llm_rounds
        ):
            iteration += 1

            # 3. Call LLM
            try:
                response = self.client.chat(messages, format="json", temperature=0.0)
            except LlmTimeoutError:
                return AgentExecutionResult(
                    answer="The request to the local AI service timed out while processing your question.",
                    tool_calls=executed_summaries,
                    status="error",
                    error="llm_timeout",
                    iterations=iteration,
                    session_id=session_id,
                )
            except LlmError as err:
                return AgentExecutionResult(
                    answer=f"The AI service encountered an error: {err}",
                    tool_calls=executed_summaries,
                    status="error",
                    error="llm_error",
                    iterations=iteration,
                    session_id=session_id,
                )

            # 4. Parse decision
            raw_content = response.content
            cleaned_json = _clean_json_text(raw_content)

            try:
                data = json.loads(cleaned_json)
                decision = ToolSelectionDecision.model_validate(data)
            except Exception:
                # Give model one chance to correct its JSON output
                messages.append(ChatMessage(role=ChatRole.ASSISTANT, content=raw_content))
                messages.append(
                    ChatMessage(
                        role=ChatRole.USER,
                        content=(
                            "Your previous response was not valid JSON conforming to the schema. "
                            "Please respond with a single valid JSON object with keys 'thought', 'action', "
                            "'tool_name', 'arguments', and 'final_answer'."
                        ),
                    )
                )
                continue

            # 5. Handle Final Answer
            if decision.action == "final_answer":
                answer_text = (decision.final_answer or "").strip()
                if not answer_text:
                    answer_text = "I have processed your request, but no additional explanation was generated."
                return AgentExecutionResult(
                    answer=answer_text,
                    tool_calls=executed_summaries,
                    status="completed",
                    iterations=iteration,
                    session_id=session_id,
                )

            # 6. Handle Tool Call
            if decision.action == "call_tool":
                tool_name = (decision.tool_name or "").strip()
                arguments = decision.arguments or {}

                # Check if tool is registered
                if not tool_name or not self.registry.exists(tool_name):
                    valid_tools = ", ".join(f"`{d['name']}`" for d in tool_definitions)
                    messages.append(ChatMessage(role=ChatRole.ASSISTANT, content=raw_content))
                    messages.append(
                        ChatMessage(
                            role=ChatRole.USER,
                            content=(
                                f"Tool '{tool_name}' is not recognized in the approved ERP catalog. "
                                f"Available tools: [{valid_tools}]. Please choose an approved tool or provide a final answer."
                            ),
                        )
                    )
                    continue

                # Validate and normalize model arguments against the tool schema
                definition = self.registry.get(tool_name)
                arguments = normalize_tool_arguments(arguments, definition)

                # Check for repeated identical tool call
                args_key = json.dumps(arguments, sort_keys=True, default=str)
                call_sig = (tool_name, args_key)
                if call_sig in executed_calls_set:
                    messages.append(ChatMessage(role=ChatRole.ASSISTANT, content=raw_content))
                    messages.append(
                        ChatMessage(
                            role=ChatRole.USER,
                            content=(
                                f"Tool '{tool_name}' was already called with arguments {arguments}. "
                                "Do not repeat identical calls. Please proceed to answer the user's question "
                                "using the retrieved data or pick a different tool."
                            ),
                        )
                    )
                    continue

                # Execute tool through ErpToolRunner
                request = ToolExecutionRequest(tool_name=tool_name, arguments=arguments)
                result = self.runner.execute(request)

                executed_calls_set.add(call_sig)

                # Only calls that actually reached a handler consume the
                # tool-call budget; pre-flight validation failures do not.
                if result.started_at is not None:
                    tool_executions += 1

                summary = ToolCallSummary(
                    tool_name=tool_name,
                    arguments=arguments,
                    status=result.status.value,
                    duration_ms=result.duration_ms,
                    error=result.error.message if result.error else None,
                )
                executed_summaries.append(summary)

                # Feed result back to model
                messages.append(ChatMessage(role=ChatRole.ASSISTANT, content=raw_content))

                if result.status is ToolExecutionStatus.SUCCEEDED:
                    successful_outputs.append((tool_name, result.output))
                    output_str = json.dumps(result.output, ensure_ascii=False, default=str)
                    messages.append(
                        ChatMessage(
                            role=ChatRole.USER,
                            content=f"Tool `{tool_name}` output:\n{output_str}",
                        )
                    )
                elif result.status is ToolExecutionStatus.FAILED:
                    messages.append(
                        ChatMessage(
                            role=ChatRole.USER,
                            content="\n".join(
                                _failure_feedback_lines(tool_name, result)
                            ),
                        )
                    )
                else:  # CANCELLED / TIMEOUT
                    messages.append(
                        ChatMessage(
                            role=ChatRole.USER,
                            content=f"Tool `{tool_name}` execution was cancelled or timed out.",
                        )
                    )
                continue

            # 6b. Unrecognized action - ask the model to correct itself
            messages.append(ChatMessage(role=ChatRole.ASSISTANT, content=raw_content))
            messages.append(
                ChatMessage(
                    role=ChatRole.USER,
                    content=(
                        f"Unknown action '{decision.action}'. The 'action' field must be either "
                        "'call_tool' (with 'tool_name' and 'arguments') or 'final_answer' "
                        "(with 'final_answer'). Please respond again."
                    ),
                )
            )

        # 7. Tool-call budget or LLM round limit reached - synthesize answer
        return self._synthesize_final_answer(
            messages,
            executed_summaries,
            successful_outputs,
            iteration,
            session_id=session_id,
        )

    def _synthesize_final_answer(
        self,
        messages: list[ChatMessage],
        executed_summaries: list[ToolCallSummary],
        successful_outputs: list[tuple[str, Any]],
        iteration: int,
        *,
        session_id: str | None,
    ) -> AgentExecutionResult:
        """Compose a final answer after the loop budget was exhausted.

        The model gets one last chance to answer. If it fails, previously
        retrieved data is preserved in a deterministic summary so partial
        failures never invalidate successful tool results.
        """

        reminder = (
            f"You have reached the maximum allowed tool calls ({self.max_tool_calls}). "
            "Please provide your final answer now based on the data retrieved so far, "
            "explaining any limitations."
        )
        if _used_dispatch_tools(executed_summaries):
            reminder += (
                " Clearly distinguish dispatched quantities (handed over to the "
                "carrier) from confirmed customer delivery, which this ERP does "
                "not track."
            )
        messages.append(ChatMessage(role=ChatRole.USER, content=reminder))

        final_text = ""
        try:
            final_resp = self.client.chat(messages, format="json", temperature=0.0)
            cleaned = _clean_json_text(final_resp.content)
            data = json.loads(cleaned)
            final_decision = ToolSelectionDecision.model_validate(data)
            final_text = (final_decision.final_answer or "").strip()
        except Exception:
            final_text = ""

        if final_text:
            return AgentExecutionResult(
                answer=final_text,
                tool_calls=executed_summaries,
                status="completed",
                iterations=iteration,
                session_id=session_id,
            )

        return AgentExecutionResult(
            answer=self._fallback_answer(executed_summaries, successful_outputs),
            tool_calls=executed_summaries,
            status="incomplete",
            iterations=iteration,
            session_id=session_id,
        )

    @staticmethod
    def _fallback_answer(
        executed_summaries: list[ToolCallSummary],
        successful_outputs: list[tuple[str, Any]],
    ) -> str:
        """Grounded deterministic answer used when the model cannot compose one."""

        lines: list[str] = [
            "The tool-call limit was reached before a final answer could be "
            "composed. The following data was successfully retrieved:"
        ]
        for tool_name, output in successful_outputs:
            rendered = json.dumps(output, ensure_ascii=False, default=str)
            if len(rendered) > _MAX_FALLBACK_OUTPUT_CHARS:
                rendered = rendered[:_MAX_FALLBACK_OUTPUT_CHARS] + "... (truncated)"
            lines.append(f"- `{tool_name}`: {rendered}")
        if not successful_outputs:
            lines.append("- No tool data could be retrieved.")

        failed = [
            f"`{summary.tool_name}` ({summary.error or summary.status})"
            for summary in executed_summaries
            if summary.status != ToolExecutionStatus.SUCCEEDED.value
        ]
        if failed:
            lines.append(
                "Tool calls that did not return data: " + ", ".join(failed)
            )
        if _used_dispatch_tools(executed_summaries):
            lines.append(_DELIVERY_SEMANTICS_NOTE)
        return "\n".join(lines)

