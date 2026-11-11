from __future__ import annotations


class ToolRegistryError(Exception):
    """Base class for tool registry failures."""


class DuplicateToolError(ToolRegistryError):
    def __init__(self, tool_name: str) -> None:
        self.tool_name = tool_name
        super().__init__(f"tool already registered: {tool_name}")


class ToolNotFoundError(ToolRegistryError):
    def __init__(self, tool_name: str) -> None:
        self.tool_name = tool_name
        super().__init__(f"tool not found: {tool_name}")


class ToolHandlerError(ToolRegistryError):
    """Base class for tool handler registration failures."""


class DuplicateHandlerError(ToolHandlerError):
    def __init__(self, tool_name: str) -> None:
        self.tool_name = tool_name
        super().__init__(f"handler already registered: {tool_name}")


class HandlerNotFoundError(ToolHandlerError):
    def __init__(self, tool_name: str) -> None:
        self.tool_name = tool_name
        super().__init__(f"handler not found: {tool_name}")


class InvalidToolSchemaError(ToolRegistryError):
    """Raised when a tool input schema cannot be validated safely."""


__all__ = [
    "DuplicateHandlerError",
    "DuplicateToolError",
    "HandlerNotFoundError",
    "InvalidToolSchemaError",
    "ToolHandlerError",
    "ToolNotFoundError",
    "ToolRegistryError",
]
