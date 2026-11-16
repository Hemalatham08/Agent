"""Isolated registration of the RAG tool catalog.

Registration is deliberately explicit and reversible. No production agent,
orchestrator, prompt, or ERP registry is modified here. The caller owns the
registry and executor, and receives a handle that can unregister exactly the
three ``rag.knowledge.*`` tools it added.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.agent.rag.definitions import (
    RAG_TOOL_DEFINITIONS,
    RAG_TOOL_NAMES,
)
from backend.agent.rag.handlers import RagToolHandlers
from backend.agent.tools.errors import (
    DuplicateHandlerError,
    DuplicateToolError,
)
from backend.agent.tools.executor import ToolExecutor
from backend.agent.tools.registry import ToolRegistry


@dataclass(frozen=True)
class RagToolRegistration:
    """Handle for explicitly unregistering one RAG tool registration."""

    registry: ToolRegistry
    executor: ToolExecutor
    tool_names: tuple[str, ...]

    def unregister(self) -> None:
        for name in reversed(self.tool_names):
            if self.executor.has_handler(name):
                self.executor.unregister_handler(name)
        for name in reversed(self.tool_names):
            if self.registry.exists(name):
                self.registry.unregister(name)

    def __enter__(self) -> RagToolRegistration:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.unregister()


def register_rag_tools(
    registry: ToolRegistry,
    executor: ToolExecutor,
    handlers: RagToolHandlers,
) -> RagToolRegistration:
    """Register all RAG definitions and handlers without overwriting."""

    if not isinstance(handlers, RagToolHandlers):
        raise TypeError("handlers must be a RagToolHandlers")

    handler_mapping = handlers.as_mapping()
    handler_names = set(handler_mapping)
    expected_names = set(RAG_TOOL_NAMES)
    if handler_names != expected_names:
        missing = sorted(expected_names - handler_names)
        extra = sorted(handler_names - expected_names)
        raise ValueError(
            f"RAG handler catalog mismatch; missing={missing}, extra={extra}"
        )

    for definition in RAG_TOOL_DEFINITIONS:
        if registry.exists(definition.name):
            raise DuplicateToolError(definition.name)
    for name in RAG_TOOL_NAMES:
        if executor.has_handler(name):
            raise DuplicateHandlerError(name)

    registered_definitions: list[str] = []
    registered_handlers: list[str] = []
    try:
        for definition in RAG_TOOL_DEFINITIONS:
            registry.register(definition)
            registered_definitions.append(definition.name)
        for name in RAG_TOOL_NAMES:
            executor.register_handler(name, handler_mapping[name])
            registered_handlers.append(name)
    except Exception:
        for name in reversed(registered_handlers):
            if executor.has_handler(name):
                executor.unregister_handler(name)
        for name in reversed(registered_definitions):
            if registry.exists(name):
                registry.unregister(name)
        raise

    return RagToolRegistration(
        registry=registry,
        executor=executor,
        tool_names=RAG_TOOL_NAMES,
    )


__all__ = ["RagToolRegistration", "register_rag_tools"]
