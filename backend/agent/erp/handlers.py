from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Callable

from pydantic import JsonValue, TypeAdapter, ValidationError

from backend.agent.erp.definitions import ERP_TOOL_DEFINITIONS_BY_NAME
from backend.agent.erp.errors import (
    ErpError,
    ErpInternalError,
    ErpInvalidArgumentsError,
)
from backend.agent.erp.service import ErpReadService
from backend.agent.tools.contracts import ToolExecutionContext
from backend.agent.tools.validation import validate_arguments

_Handler = Callable[[dict[str, JsonValue], ToolExecutionContext], Any]
_Operation = Callable[[Mapping[str, JsonValue]], Any]
_JSON_VALUE_ADAPTER = TypeAdapter(JsonValue)


def _success(data: Any) -> dict[str, JsonValue]:
    if hasattr(data, "model_dump"):
        data = data.model_dump(mode="json")
    try:
        _JSON_VALUE_ADAPTER.validate_python(data, strict=True)
        json.dumps(data, allow_nan=False)
    except (TypeError, ValueError, ValidationError) as exc:
        raise ErpInternalError() from exc
    return {"ok": True, "data": data}


class ErpToolHandlers:
    """Thin handlers that adapt ERP tools to ``ErpReadService``."""

    def __init__(self, service: ErpReadService) -> None:
        self._service = service

    def as_mapping(self) -> dict[str, _Handler]:
        return {
            "erp.products.search": self.search_products,
            "erp.products.get": self.get_product,
            "erp.products.count": self.count_products,
            "erp.inventory.get": self.get_inventory,
            "erp.warehouses.list": self.list_warehouses,
            "erp.inventory.low_stock": self.list_low_stock,
            "erp.sales_orders.get": self.get_sales_order,
            "erp.dispatches.get": self.get_dispatch,
            "erp.dispatches.list": self.list_dispatches,
            "erp.dispatches.by_sales_order": self.get_dispatches_by_sales_order,
        }

    def search_products(
        self,
        arguments: dict[str, JsonValue],
        context: ToolExecutionContext,
    ) -> dict[str, JsonValue]:
        def operation(args: Mapping[str, JsonValue]) -> Any:
            limit = args.get("limit", 20)
            query = args.get("query")
            if isinstance(query, str):
                query = query.strip()

            if not query:
                return self._service.list_products(
                    limit,
                    timeout_seconds=context.timeout_seconds,
                )
            return self._service.search_products(
                query,
                limit,
                timeout_seconds=context.timeout_seconds,
            )

        return self._handle(
            "erp.products.search",
            arguments,
            operation,
        )

    def get_product(
        self,
        arguments: dict[str, JsonValue],
        context: ToolExecutionContext,
    ) -> dict[str, JsonValue]:
        return self._handle(
            "erp.products.get",
            arguments,
            lambda args: self._service.get_product(
                args["product_id"],
                timeout_seconds=context.timeout_seconds,
            ),
        )

    def count_products(
        self,
        arguments: dict[str, JsonValue],
        context: ToolExecutionContext,
    ) -> dict[str, JsonValue]:
        return self._handle(
            "erp.products.count",
            arguments,
            lambda _args: self._service.count_products(
                timeout_seconds=context.timeout_seconds,
            ),
        )

    def get_inventory(
        self,
        arguments: dict[str, JsonValue],
        context: ToolExecutionContext,
    ) -> dict[str, JsonValue]:
        return self._handle(
            "erp.inventory.get",
            arguments,
            lambda args: self._service.get_inventory(
                args["product_id"],
                args.get("warehouse_id"),
                timeout_seconds=context.timeout_seconds,
            ),
        )

    def list_warehouses(
        self,
        arguments: dict[str, JsonValue],
        context: ToolExecutionContext,
    ) -> dict[str, JsonValue]:
        return self._handle(
            "erp.warehouses.list",
            arguments,
            lambda _args: self._service.list_warehouses(
                timeout_seconds=context.timeout_seconds,
            ),
        )

    def list_low_stock(
        self,
        arguments: dict[str, JsonValue],
        context: ToolExecutionContext,
    ) -> dict[str, JsonValue]:
        return self._handle(
            "erp.inventory.low_stock",
            arguments,
            lambda args: self._service.list_low_stock(
                args.get("warehouse_id"),
                args.get("limit", 20),
                timeout_seconds=context.timeout_seconds,
            ),
        )

    def get_sales_order(
        self,
        arguments: dict[str, JsonValue],
        context: ToolExecutionContext,
    ) -> dict[str, JsonValue]:
        return self._handle(
            "erp.sales_orders.get",
            arguments,
            lambda args: self._service.get_sales_order(
                args["so_id"],
                timeout_seconds=context.timeout_seconds,
            ),
        )

    def get_dispatch(
        self,
        arguments: dict[str, JsonValue],
        context: ToolExecutionContext,
    ) -> dict[str, JsonValue]:
        return self._handle(
            "erp.dispatches.get",
            arguments,
            lambda args: self._service.get_dispatch(
                args["dispatch_id"],
                timeout_seconds=context.timeout_seconds,
            ),
        )

    def list_dispatches(
        self,
        arguments: dict[str, JsonValue],
        context: ToolExecutionContext,
    ) -> dict[str, JsonValue]:
        return self._handle(
            "erp.dispatches.list",
            arguments,
            lambda args: self._service.list_dispatches(
                limit=args.get("limit", 20),
                so_id=args.get("so_id"),
                status=args.get("status"),
                carrier=args.get("carrier"),
                timeout_seconds=context.timeout_seconds,
            ),
        )

    def get_dispatches_by_sales_order(
        self,
        arguments: dict[str, JsonValue],
        context: ToolExecutionContext,
    ) -> dict[str, JsonValue]:
        return self._handle(
            "erp.dispatches.by_sales_order",
            arguments,
            lambda args: self._service.get_dispatches_by_sales_order(
                args["so_id"],
                timeout_seconds=context.timeout_seconds,
            ),
        )

    def _handle(
        self,
        tool_name: str,
        arguments: object,
        operation: _Operation,
    ) -> dict[str, JsonValue]:
        try:
            validated = self._validate_arguments(tool_name, arguments)
            return _success(operation(validated))
        except ErpError as exc:
            return exc.to_envelope()
        except Exception:
            return ErpInternalError().to_envelope()

    @staticmethod
    def _validate_arguments(
        tool_name: str,
        arguments: object,
    ) -> dict[str, JsonValue]:
        if not isinstance(arguments, Mapping):
            raise ErpInvalidArgumentsError("arguments")

        definition = ERP_TOOL_DEFINITIONS_BY_NAME[tool_name]
        issues = validate_arguments(arguments, definition.input_schema)
        if issues:
            raise ErpInvalidArgumentsError(issues[0].path)
        return dict(arguments)


__all__ = ["ErpToolHandlers"]
