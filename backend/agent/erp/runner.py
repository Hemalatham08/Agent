from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from pydantic import JsonValue, TypeAdapter, ValidationError

from backend.agent.erp.errors import ErpInternalError
from backend.agent.models import ErrorCategory, utc_now
from backend.agent.tools.contracts import (
    ToolExecutionError,
    ToolExecutionRequest,
    ToolExecutionResult,
    ToolExecutionStatus,
)
from backend.agent.tools.executor import ToolExecutor

_JSON_VALUE_ADAPTER = TypeAdapter(JsonValue)
_UNSET_TIMEOUT = object()


class ErpToolRunner:
    """Translate internal ERP handler envelopes into tool results."""

    def __init__(self, executor: ToolExecutor) -> None:
        self._executor = executor

    def execute(
        self,
        request: ToolExecutionRequest,
        timeout: float | None | object = _UNSET_TIMEOUT,
    ) -> ToolExecutionResult:
        if timeout is _UNSET_TIMEOUT:
            result = self._executor.execute(request)
        else:
            result = self._executor.execute(request, timeout)

        if result.status is not ToolExecutionStatus.SUCCEEDED:
            return result

        output = result.output
        if not isinstance(output, Mapping):
            return self._malformed_result(result)

        if output.get("ok") is True:
            if set(output) != {"ok", "data"}:
                return self._malformed_result(result)
            data = output["data"]
            if not _is_json_compatible(data):
                return self._malformed_result(result)
            return ToolExecutionResult(
                execution_id=result.execution_id,
                tool_name=result.tool_name,
                status=ToolExecutionStatus.SUCCEEDED,
                output=deepcopy(data),
                started_at=result.started_at,
                finished_at=result.finished_at,
                duration_ms=result.duration_ms,
            )

        if output.get("ok") is False:
            if set(output) != {"ok", "error"}:
                return self._malformed_result(result)
            error = _parse_error_envelope(output["error"])
            if error is None:
                return self._malformed_result(result)
            return ToolExecutionResult(
                execution_id=result.execution_id,
                tool_name=result.tool_name,
                status=ToolExecutionStatus.FAILED,
                output=None,
                error=error,
                started_at=result.started_at,
                finished_at=result.finished_at,
                duration_ms=result.duration_ms,
            )

        return self._malformed_result(result)

    @staticmethod
    def _malformed_result(result: ToolExecutionResult) -> ToolExecutionResult:
        error = ErpInternalError()
        return ToolExecutionResult(
            execution_id=result.execution_id,
            tool_name=result.tool_name,
            status=ToolExecutionStatus.FAILED,
            output=None,
            error=ToolExecutionError(
                code=error.code,
                message=error.message,
                category=error.category,
                recoverable=error.recoverable,
                retryable=error.retryable,
                details={},
            ),
            started_at=result.started_at,
            finished_at=result.finished_at or utc_now(),
            duration_ms=result.duration_ms,
        )


def _parse_error_envelope(value: Any) -> ToolExecutionError | None:
    if not isinstance(value, Mapping):
        return None
    if set(value) != {
        "code",
        "message",
        "category",
        "recoverable",
        "retryable",
        "details",
    }:
        return None

    code = value["code"]
    message = value["message"]
    category_value = value["category"]
    recoverable = value["recoverable"]
    retryable = value["retryable"]
    details = value["details"]

    if not isinstance(code, str) or not code.strip():
        return None
    if not isinstance(message, str) or not message.strip():
        return None
    if not isinstance(category_value, str):
        return None
    if not isinstance(recoverable, bool):
        return None
    if not isinstance(retryable, bool):
        return None
    if not isinstance(details, Mapping):
        return None

    try:
        category = ErrorCategory(category_value)
    except ValueError:
        return None

    details_dict = dict(details)
    if not _is_json_compatible(details_dict):
        return None

    return ToolExecutionError(
        code=code,
        message=message,
        category=category,
        recoverable=recoverable,
        retryable=retryable,
        details=deepcopy(details_dict),
    )


def _is_json_compatible(value: Any) -> bool:
    try:
        _JSON_VALUE_ADAPTER.validate_python(value, strict=True)
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError, ValidationError):
        return False
    return True


__all__ = ["ErpToolRunner"]
