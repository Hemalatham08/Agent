"""In-memory, thread-safe registry for tool definitions."""

from __future__ import annotations

from threading import RLock

from pydantic import JsonValue

from backend.agent.tools.contracts import ToolDefinition
from backend.agent.tools.errors import DuplicateToolError, ToolNotFoundError


class ToolRegistry:
    """Manage validated tool definitions without executing them.

    Definitions are stored and returned as deep copies so callers cannot
    mutate registry state through the shallowly immutable Phase 3A models.
    """

    def __init__(self) -> None:
        self._lock = RLock()
        self._definitions: dict[str, ToolDefinition] = {}

    def register(self, definition: ToolDefinition) -> None:
        with self._lock:
            if definition.name in self._definitions:
                raise DuplicateToolError(definition.name)
            self._definitions[definition.name] = definition.model_copy(
                deep=True
            )

    def get(self, name: str) -> ToolDefinition:
        with self._lock:
            definition = self._definitions.get(name)
            if definition is None:
                raise ToolNotFoundError(name)
            return definition.model_copy(deep=True)

    def list_tools(self) -> list[ToolDefinition]:
        with self._lock:
            return [
                self._definitions[name].model_copy(deep=True)
                for name in sorted(self._definitions)
            ]

    def exists(self, name: str) -> bool:
        with self._lock:
            return name in self._definitions

    def unregister(self, name: str) -> ToolDefinition:
        with self._lock:
            definition = self._definitions.pop(name, None)
            if definition is None:
                raise ToolNotFoundError(name)
            return definition.model_copy(deep=True)

    def export_definitions(self) -> list[dict[str, JsonValue]]:
        with self._lock:
            return [
                self._definitions[name].model_dump(mode="json")
                for name in sorted(self._definitions)
            ]


__all__ = ["ToolRegistry"]
