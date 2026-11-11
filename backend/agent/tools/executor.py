"""Bounded, in-process tool execution with optional timeouts.

Handlers are trusted Python callables and are not sandboxed. Timeouts cover
worker-queue waiting plus handler execution. They do not bound pre-flight
validation or guarantee total ``execute`` call latency. A handler that has
already started when its timeout expires may continue running and may produce
side effects.
"""

from __future__ import annotations

import json
import math
from concurrent.futures import (
    CancelledError,
    ThreadPoolExecutor,
    TimeoutError as FutureTimeoutError,
)
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from threading import RLock
from time import perf_counter
from typing import Any, Callable

from pydantic import JsonValue, TypeAdapter, ValidationError

from backend.agent.models import ErrorCategory, utc_now
from backend.agent.tools.contracts import (
    ToolExecutionContext,
    ToolExecutionError,
    ToolExecutionRequest,
    ToolExecutionResult,
    ToolExecutionStatus,
)
from backend.agent.tools.errors import (
    DuplicateHandlerError,
    HandlerNotFoundError,
    InvalidToolSchemaError,
    ToolNotFoundError,
)
from backend.agent.tools.registry import ToolRegistry
from backend.agent.tools.validation import validate_arguments

ToolHandler = Callable[[dict[str, JsonValue], ToolExecutionContext], Any]

_JSON_VALUE_ADAPTER = TypeAdapter(JsonValue)
_UNSET_TIMEOUT = object()


@dataclass(frozen=True)
class _HandlerOutcome:
    output: Any = None
    exception: Exception | None = None


class ToolExecutor:
    """Execute registered tools through a bounded synchronous handler pool.

    Tool definitions remain in :class:`ToolRegistry`; this class owns only the
    handler mapping and worker pool. Handler registration, lookup, and shutdown
    are thread-safe. Handlers receive deep copies of the request arguments and
    metadata through an immutable :class:`ToolExecutionContext`.
    """

    def __init__(
        self,
        registry: ToolRegistry,
        *,
        max_workers: int = 4,
        default_timeout: float | None = None,
        include_exception_messages: bool = False,
    ) -> None:
        if (
            isinstance(max_workers, bool)
            or not isinstance(max_workers, int)
            or max_workers < 1
        ):
            raise ValueError("max_workers must be a positive integer")

        self._registry = registry
        self._default_timeout = _normalize_timeout(
            default_timeout,
            name="default_timeout",
        )
        self._include_exception_messages = include_exception_messages
        self._lock = RLock()
        self._handlers: dict[str, ToolHandler] = {}
        self._shutdown = False
        self._pool = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="tool-executor",
        )

    def register_handler(
        self,
        tool_name: str,
        handler: ToolHandler,
    ) -> None:
        """Register one handler, rejecting duplicate names."""

        name = self._normalize_name(tool_name)
        if not callable(handler):
            raise TypeError("handler must be callable")

        with self._lock:
            if name in self._handlers:
                raise DuplicateHandlerError(name)
            self._handlers[name] = handler

    def get_handler(self, tool_name: str) -> ToolHandler:
        """Return the registered handler or raise ``HandlerNotFoundError``."""

        name = self._normalize_name(tool_name)
        with self._lock:
            handler = self._handlers.get(name)
            if handler is None:
                raise HandlerNotFoundError(name)
            return handler

    def has_handler(self, tool_name: str) -> bool:
        """Return whether a handler is registered for ``tool_name``."""

        name = self._normalize_name(tool_name)
        with self._lock:
            return name in self._handlers

    def unregister_handler(self, tool_name: str) -> ToolHandler:
        """Remove and return a handler, or raise ``HandlerNotFoundError``."""

        name = self._normalize_name(tool_name)
        with self._lock:
            handler = self._handlers.pop(name, None)
            if handler is None:
                raise HandlerNotFoundError(name)
            return handler

    def execute(
        self,
        request: ToolExecutionRequest,
        timeout: float | None | object = _UNSET_TIMEOUT,
    ) -> ToolExecutionResult:
        """Execute one request and return a terminal result.

        ``timeout`` omitted inherits the executor default. ``timeout=None``
        means unlimited. A positive finite number overrides the default.
        ``BaseException`` subclasses raised by handlers are not swallowed.
        """

        with self._lock:
            if self._shutdown:
                raise RuntimeError("tool executor is shut down")

        try:
            definition = self._registry.get(request.tool_name)
        except ToolNotFoundError:
            return self._preflight_failure(
                request,
                code="tool_not_found",
                message="tool definition not found",
                category=ErrorCategory.NOT_FOUND,
            )

        try:
            handler = self.get_handler(request.tool_name)
        except HandlerNotFoundError:
            return self._preflight_failure(
                request,
                code="handler_not_found",
                message="tool handler not found",
                category=ErrorCategory.NOT_FOUND,
            )

        try:
            issues = validate_arguments(
                request.arguments,
                definition.input_schema,
            )
        except InvalidToolSchemaError:
            return self._preflight_failure(
                request,
                code="invalid_tool_schema",
                message="tool input schema is invalid",
                category=ErrorCategory.VALIDATION,
            )

        if issues:
            return self._preflight_failure(
                request,
                code="invalid_arguments",
                message="tool arguments failed validation",
                category=ErrorCategory.VALIDATION,
                details={
                    "issues": [
                        issue.model_dump(mode="json") for issue in issues
                    ]
                },
                recoverable=True,
            )

        effective_timeout = (
            self._default_timeout
            if timeout is _UNSET_TIMEOUT
            else _normalize_timeout(timeout, name="timeout")
        )

        started_at = utc_now()
        started_counter = perf_counter()
        context = ToolExecutionContext(
            execution_id=request.execution_id,
            tool_name=request.tool_name,
            started_at=started_at,
            timeout_seconds=effective_timeout,
            metadata=deepcopy(request.metadata),
        )
        arguments = deepcopy(request.arguments)

        with self._lock:
            if self._shutdown:
                raise RuntimeError("tool executor is shut down")
            future = self._pool.submit(
                _invoke_handler,
                handler,
                arguments,
                context,
            )

        try:
            outcome = future.result(timeout=effective_timeout)
        except FutureTimeoutError:
            future.cancel()
            return self._cancelled_result(
                request,
                started_at=started_at,
                finished_at=utc_now(),
                duration_ms=self._elapsed_ms(started_counter),
            )
        except CancelledError:
            return self._cancelled_result(
                request,
                started_at=started_at,
                finished_at=utc_now(),
                duration_ms=self._elapsed_ms(started_counter),
            )

        finished_at = utc_now()
        duration_ms = self._elapsed_ms(started_counter)

        if outcome.exception is not None:
            message = "tool handler raised an exception"
            if self._include_exception_messages:
                message = (
                    "tool handler raised "
                    f"{type(outcome.exception).__name__}: "
                    f"{outcome.exception}"
                )
            return self._failed_result(
                request,
                code="handler_error",
                message=message,
                category=ErrorCategory.TOOL,
                details={"exception_type": type(outcome.exception).__name__},
                started_at=started_at,
                finished_at=finished_at,
                duration_ms=duration_ms,
            )

        if not _is_json_compatible(outcome.output):
            return self._failed_result(
                request,
                code="invalid_output",
                message="tool handler returned a non-JSON-compatible value",
                category=ErrorCategory.TOOL,
                details={"output_type": type(outcome.output).__name__},
                started_at=started_at,
                finished_at=finished_at,
                duration_ms=duration_ms,
            )

        return ToolExecutionResult(
            execution_id=request.execution_id,
            tool_name=request.tool_name,
            status=ToolExecutionStatus.SUCCEEDED,
            output=deepcopy(outcome.output),
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
        )

    def shutdown(self, wait: bool = True) -> None:
        """Stop accepting work and shut down the worker pool.

        Repeated calls are safe. ``wait=False`` does not wait for queued or
        running handlers; they may continue and may produce side effects.
        """

        with self._lock:
            self._shutdown = True
        self._pool.shutdown(wait=wait)

    @staticmethod
    def _normalize_name(tool_name: str) -> str:
        if not isinstance(tool_name, str):
            raise TypeError("tool_name must be a string")
        name = tool_name.strip()
        if not name:
            raise ValueError("tool_name must be a nonblank string")
        return name

    @staticmethod
    def _elapsed_ms(started_counter: float) -> float:
        return max((perf_counter() - started_counter) * 1000.0, 0.0)

    def _preflight_failure(
        self,
        request: ToolExecutionRequest,
        *,
        code: str,
        message: str,
        category: ErrorCategory,
        details: dict[str, JsonValue] | None = None,
        recoverable: bool = False,
        retryable: bool = False,
    ) -> ToolExecutionResult:
        return self._failed_result(
            request,
            code=code,
            message=message,
            category=category,
            details=details,
            recoverable=recoverable,
            retryable=retryable,
            started_at=None,
            finished_at=utc_now(),
            duration_ms=None,
        )

    def _cancelled_result(
        self,
        request: ToolExecutionRequest,
        *,
        started_at: datetime,
        finished_at: datetime,
        duration_ms: float,
    ) -> ToolExecutionResult:
        return ToolExecutionResult(
            execution_id=request.execution_id,
            tool_name=request.tool_name,
            status=ToolExecutionStatus.CANCELLED,
            output=None,
            error=None,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
        )

    def _failed_result(
        self,
        request: ToolExecutionRequest,
        *,
        code: str,
        message: str,
        category: ErrorCategory,
        details: dict[str, JsonValue] | None = None,
        recoverable: bool = False,
        retryable: bool = False,
        started_at: datetime | None,
        finished_at: datetime | None,
        duration_ms: float | None,
    ) -> ToolExecutionResult:
        return ToolExecutionResult(
            execution_id=request.execution_id,
            tool_name=request.tool_name,
            status=ToolExecutionStatus.FAILED,
            error=ToolExecutionError(
                code=code,
                message=message,
                category=category,
                recoverable=recoverable,
                retryable=retryable,
                details=details or {},
            ),
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
        )


def _invoke_handler(
    handler: ToolHandler,
    arguments: dict[str, JsonValue],
    context: ToolExecutionContext,
) -> _HandlerOutcome:
    try:
        return _HandlerOutcome(output=handler(arguments, context))
    except Exception as exc:
        return _HandlerOutcome(exception=exc)


def _normalize_timeout(value: Any, *, name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a positive number or None")

    timeout = float(value)
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError(f"{name} must be a positive finite number or None")
    return timeout


def _is_json_compatible(value: Any) -> bool:
    try:
        _JSON_VALUE_ADAPTER.validate_python(value, strict=True)
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError, ValidationError):
        return False
    return True


__all__ = ["ToolExecutor", "ToolHandler"]
