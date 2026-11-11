from __future__ import annotations

from dataclasses import dataclass

from backend.agent.erp.definitions import (
    ERP_TOOL_DEFINITIONS,
    ERP_TOOL_NAMES,
)
from backend.agent.erp.handlers import ErpToolHandlers
from backend.agent.erp.service import ErpReadService
from backend.agent.tools.errors import (
    DuplicateHandlerError,
    DuplicateToolError,
)
from backend.agent.tools.executor import ToolExecutor
from backend.agent.tools.registry import ToolRegistry


@dataclass(frozen=True)
class ErpToolRegistration:
    """Handle for explicitly unregistering one ERP tool registration."""

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

    def __enter__(self) -> ErpToolRegistration:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.unregister()


def register_erp_tools(
    registry: ToolRegistry,
    executor: ToolExecutor,
    service: ErpReadService,
) -> ErpToolRegistration:
    """Register all ERP definitions and handlers without overwriting."""

    handlers = ErpToolHandlers(service).as_mapping()
    handler_names = set(handlers)
    expected_names = set(ERP_TOOL_NAMES)
    if handler_names != expected_names:
        missing = sorted(expected_names - handler_names)
        extra = sorted(handler_names - expected_names)
        raise ValueError(
            f"ERP handler catalog mismatch; missing={missing}, extra={extra}"
        )

    for definition in ERP_TOOL_DEFINITIONS:
        if registry.exists(definition.name):
            raise DuplicateToolError(definition.name)
    for name in ERP_TOOL_NAMES:
        if executor.has_handler(name):
            raise DuplicateHandlerError(name)

    registered_definitions: list[str] = []
    registered_handlers: list[str] = []
    try:
        for definition in ERP_TOOL_DEFINITIONS:
            registry.register(definition)
            registered_definitions.append(definition.name)
        for name in ERP_TOOL_NAMES:
            executor.register_handler(name, handlers[name])
            registered_handlers.append(name)
    except Exception:
        for name in reversed(registered_handlers):
            if executor.has_handler(name):
                executor.unregister_handler(name)
        for name in reversed(registered_definitions):
            if registry.exists(name):
                registry.unregister(name)
        raise

    return ErpToolRegistration(
        registry=registry,
        executor=executor,
        tool_names=ERP_TOOL_NAMES,
    )


__all__ = ["ErpToolRegistration", "register_erp_tools"]
