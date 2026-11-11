from __future__ import annotations

import math
from time import monotonic
from typing import Any, Callable, TypeVar

from backend.agent.erp.adapter import ErpReadAdapter
from backend.agent.erp.config import DEFAULT_ERP_QUERY_TIMEOUT_SECONDS
from backend.agent.erp.errors import (
    ErpConfigurationError,
    ErpInternalError,
    ErpInvalidArgumentsError,
    ErpNotFoundError,
    ErpQueryTimeoutError,
)
from backend.agent.erp.models import (
    DispatchDetail,
    DispatchItemDetail,
    DispatchListResult,
    DispatchSummary,
    InventoryResult,
    InventoryRow,
    LowStockResult,
    LowStockRow,
    ProductDetail,
    ProductSearchResult,
    ProductSummary,
    SalesOrderDetail,
    SalesOrderDispatchesResult,
    SalesOrderHeader,
    SalesOrderItem,
    WarehouseListResult,
    WarehouseSummary,
)

_MODEL = TypeVar("_MODEL")

_DEFAULT_SEARCH_LIMIT = 20
_DEFAULT_LOW_STOCK_LIMIT = 20
_MAX_LIST_LIMIT = 50
_MAX_QUERY_LENGTH = 200
_MAX_ID_LENGTH = 64
_INVENTORY_LIMIT = 50
_WAREHOUSE_LIMIT = 50
_SALES_ORDER_ITEM_LIMIT = 100

_PRODUCT_EXISTS_SQL = """
SELECT 1 AS found
FROM products
WHERE product_id = ?
LIMIT 1
"""

_WAREHOUSE_EXISTS_SQL = """
SELECT 1 AS found
FROM warehouses
WHERE warehouse_id = ?
LIMIT 1
"""

_PRODUCT_SEARCH_SQL = r"""
SELECT
    product_id,
    sku,
    product_name,
    category,
    material,
    size,
    grade,
    unit
FROM products
WHERE product_name LIKE ? ESCAPE '\'
   OR sku LIKE ? ESCAPE '\'
   OR material LIKE ? ESCAPE '\'
   OR size LIKE ? ESCAPE '\'
   OR grade LIKE ? ESCAPE '\'
ORDER BY product_name COLLATE NOCASE ASC, product_id ASC
LIMIT ?
"""

_PRODUCT_DETAIL_SQL = """
SELECT
    product_id,
    sku,
    product_name,
    category,
    material,
    size,
    grade,
    unit,
    reorder_level
FROM products
WHERE product_id = ?
LIMIT 1
"""

_INVENTORY_SQL = """
SELECT
    p.product_id,
    p.product_name,
    i.warehouse_id,
    w.warehouse_name,
    i.on_hand_qty,
    i.reserved_qty,
    (i.on_hand_qty - i.reserved_qty) AS free_stock,
    p.reorder_level,
    ((i.on_hand_qty - i.reserved_qty) <= p.reorder_level) AS low_stock
FROM inventory AS i
JOIN products AS p ON p.product_id = i.product_id
JOIN warehouses AS w ON w.warehouse_id = i.warehouse_id
WHERE i.product_id = ?
ORDER BY i.warehouse_id ASC
LIMIT ?
"""

_INVENTORY_BY_WAREHOUSE_SQL = """
SELECT
    p.product_id,
    p.product_name,
    i.warehouse_id,
    w.warehouse_name,
    i.on_hand_qty,
    i.reserved_qty,
    (i.on_hand_qty - i.reserved_qty) AS free_stock,
    p.reorder_level,
    ((i.on_hand_qty - i.reserved_qty) <= p.reorder_level) AS low_stock
FROM inventory AS i
JOIN products AS p ON p.product_id = i.product_id
JOIN warehouses AS w ON w.warehouse_id = i.warehouse_id
WHERE i.product_id = ?
  AND i.warehouse_id = ?
ORDER BY i.warehouse_id ASC
LIMIT ?
"""

_WAREHOUSE_LIST_SQL = """
SELECT
    warehouse_id,
    warehouse_name,
    city
FROM warehouses
ORDER BY warehouse_id ASC
LIMIT ?
"""

_LOW_STOCK_SQL = """
SELECT
    p.product_id,
    p.product_name,
    i.warehouse_id,
    w.warehouse_name,
    i.on_hand_qty,
    i.reserved_qty,
    (i.on_hand_qty - i.reserved_qty) AS free_stock,
    p.reorder_level,
    ((i.on_hand_qty - i.reserved_qty) <= p.reorder_level) AS low_stock
FROM inventory AS i
JOIN products AS p ON p.product_id = i.product_id
JOIN warehouses AS w ON w.warehouse_id = i.warehouse_id
WHERE (i.on_hand_qty - i.reserved_qty) <= p.reorder_level
ORDER BY p.product_id ASC, i.warehouse_id ASC
LIMIT ?
"""

_LOW_STOCK_BY_WAREHOUSE_SQL = """
SELECT
    p.product_id,
    p.product_name,
    i.warehouse_id,
    w.warehouse_name,
    i.on_hand_qty,
    i.reserved_qty,
    (i.on_hand_qty - i.reserved_qty) AS free_stock,
    p.reorder_level,
    ((i.on_hand_qty - i.reserved_qty) <= p.reorder_level) AS low_stock
FROM inventory AS i
JOIN products AS p ON p.product_id = i.product_id
JOIN warehouses AS w ON w.warehouse_id = i.warehouse_id
WHERE (i.on_hand_qty - i.reserved_qty) <= p.reorder_level
  AND i.warehouse_id = ?
ORDER BY p.product_id ASC, i.warehouse_id ASC
LIMIT ?
"""

_SALES_ORDER_HEADER_SQL = """
SELECT
    so.so_id,
    so.customer_id,
    c.customer_name,
    so.order_date,
    so.required_date,
    so.status
FROM sales_orders AS so
JOIN customers AS c ON c.customer_id = so.customer_id
WHERE so.so_id = ?
LIMIT 1
"""

_SALES_ORDER_ITEMS_SQL = """
SELECT
    soi.product_id,
    p.product_name,
    soi.ordered_qty
FROM sales_order_items AS soi
JOIN products AS p ON p.product_id = soi.product_id
WHERE soi.so_id = ?
ORDER BY soi.so_item_id ASC
LIMIT ?
"""

_DISPATCH_ITEM_LIMIT = 100
_DISPATCH_LIST_DEFAULT_LIMIT = 20

_SALES_ORDER_EXISTS_SQL = """
SELECT 1 AS found
FROM sales_orders
WHERE so_id = ?
LIMIT 1
"""

_DISPATCH_DETAIL_SQL = """
SELECT
    dispatch_id,
    so_id,
    dispatch_date,
    carrier,
    tracking_number,
    status
FROM dispatches
WHERE dispatch_id = ?
LIMIT 1
"""

_DISPATCH_ITEMS_SQL = """
SELECT
    di.dispatch_item_id,
    di.product_id,
    p.product_name,
    di.picked_qty,
    di.dispatched_qty,
    di.barcode_verified
FROM dispatch_items AS di
JOIN products AS p ON p.product_id = di.product_id
WHERE di.dispatch_id = ?
ORDER BY di.dispatch_item_id ASC
LIMIT ?
"""

_DISPATCHES_BY_SO_SQL = """
SELECT
    dispatch_id,
    so_id,
    dispatch_date,
    carrier,
    tracking_number,
    status
FROM dispatches
WHERE so_id = ?
ORDER BY dispatch_date DESC, dispatch_id ASC
LIMIT ?
"""

_DISPATCH_LIST_SQL = """
SELECT
    dispatch_id,
    so_id,
    dispatch_date,
    carrier,
    tracking_number,
    status
FROM dispatches
{where}
ORDER BY dispatch_date DESC, dispatch_id ASC
LIMIT ?
"""


def _normalize_timeout(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ErpConfigurationError(
            "ERP query timeout must be a positive number"
        )

    timeout = float(value)
    if not math.isfinite(timeout) or timeout <= 0:
        raise ErpConfigurationError(
            "ERP query timeout must be a positive number"
        )
    return timeout


def _require_nonblank_string(
    value: object,
    field: str,
    max_length: int,
) -> str:
    if not isinstance(value, str):
        raise ErpInvalidArgumentsError(field)
    normalized = value.strip()
    if not normalized:
        raise ErpInvalidArgumentsError(field)
    if len(normalized) > max_length:
        raise ErpInvalidArgumentsError(field)
    return normalized


def _optional_identifier(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _require_nonblank_string(value, field, _MAX_ID_LENGTH)


def _validate_limit(value: object, field: str, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ErpInvalidArgumentsError(
            field,
            message=(
                f"Invalid argument: {field} must be an integer between "
                f"1 and {maximum}"
            ),
        )
    if value < 1 or value > maximum:
        raise ErpInvalidArgumentsError(
            field,
            message=(
                f"Invalid argument: {field} must be an integer between "
                f"1 and {maximum}"
            ),
        )
    return value


def _escape_like(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


class ErpReadService:
    """Fixed, parameterized read-only ERP operations."""

    def __init__(
        self,
        adapter: ErpReadAdapter,
        *,
        query_timeout_seconds: float | None = None,
    ) -> None:
        if not callable(getattr(adapter, "fetch_all", None)):
            raise TypeError("adapter must provide fetch_all")
        if not callable(getattr(adapter, "fetch_one", None)):
            raise TypeError("adapter must provide fetch_one")

        self._adapter = adapter
        if query_timeout_seconds is None:
            configured = getattr(
                adapter,
                "query_timeout_seconds",
                DEFAULT_ERP_QUERY_TIMEOUT_SECONDS,
            )
            self._query_timeout_seconds = _normalize_timeout(configured)
        else:
            self._query_timeout_seconds = _normalize_timeout(
                query_timeout_seconds
            )

    @classmethod
    def from_env(cls) -> ErpReadService:
        from backend.agent.erp.sqlite_adapter import SqliteErpReadAdapter

        return cls(SqliteErpReadAdapter.from_env())

    @property
    def query_timeout_seconds(self) -> float:
        return self._query_timeout_seconds

    def search_products(
        self,
        query: str,
        limit: int = _DEFAULT_SEARCH_LIMIT,
        *,
        timeout_seconds: float | None = None,
    ) -> ProductSearchResult:
        normalized_query = _require_nonblank_string(
            query,
            "query",
            _MAX_QUERY_LENGTH,
        )
        normalized_limit = _validate_limit(
            limit,
            "limit",
            _MAX_LIST_LIMIT,
        )
        deadline = self._deadline(timeout_seconds)
        pattern = f"%{_escape_like(normalized_query)}%"

        rows = self._fetch_all(
            _PRODUCT_SEARCH_SQL,
            (
                pattern,
                pattern,
                pattern,
                pattern,
                pattern,
                normalized_limit + 1,
            ),
            deadline,
        )
        items = [
            self._map_product_summary(row)
            for row in rows[:normalized_limit]
        ]
        return ProductSearchResult(
            items=items,
            row_count=len(items),
            truncated=len(rows) > normalized_limit,
        )

    def get_product(
        self,
        product_id: str,
        *,
        timeout_seconds: float | None = None,
    ) -> ProductDetail:
        normalized_id = _require_nonblank_string(
            product_id,
            "product_id",
            _MAX_ID_LENGTH,
        )
        deadline = self._deadline(timeout_seconds)
        row = self._fetch_one(
            _PRODUCT_DETAIL_SQL,
            (normalized_id,),
            deadline,
        )
        if row is None:
            raise ErpNotFoundError("product")
        return self._map_product_detail(row)

    def get_inventory(
        self,
        product_id: str,
        warehouse_id: str | None = None,
        *,
        timeout_seconds: float | None = None,
    ) -> InventoryResult:
        normalized_product_id = _require_nonblank_string(
            product_id,
            "product_id",
            _MAX_ID_LENGTH,
        )
        normalized_warehouse_id = _optional_identifier(
            warehouse_id,
            "warehouse_id",
        )
        deadline = self._deadline(timeout_seconds)

        self._ensure_product_exists(normalized_product_id, deadline)
        if normalized_warehouse_id is not None:
            self._ensure_warehouse_exists(normalized_warehouse_id, deadline)

        if normalized_warehouse_id is None:
            sql = _INVENTORY_SQL
            parameters: tuple[object, ...] = (
                normalized_product_id,
                _INVENTORY_LIMIT + 1,
            )
        else:
            sql = _INVENTORY_BY_WAREHOUSE_SQL
            parameters = (
                normalized_product_id,
                normalized_warehouse_id,
                _INVENTORY_LIMIT + 1,
            )

        rows = self._fetch_all(sql, parameters, deadline)
        items = [
            self._map_inventory_row(row, InventoryRow)
            for row in rows[:_INVENTORY_LIMIT]
        ]
        return InventoryResult(
            items=items,
            row_count=len(items),
            truncated=len(rows) > _INVENTORY_LIMIT,
        )

    def list_warehouses(
        self,
        *,
        timeout_seconds: float | None = None,
    ) -> WarehouseListResult:
        deadline = self._deadline(timeout_seconds)
        rows = self._fetch_all(
            _WAREHOUSE_LIST_SQL,
            (_WAREHOUSE_LIMIT + 1,),
            deadline,
        )
        items = [
            self._map_warehouse(row)
            for row in rows[:_WAREHOUSE_LIMIT]
        ]
        return WarehouseListResult(
            items=items,
            row_count=len(items),
            truncated=len(rows) > _WAREHOUSE_LIMIT,
        )

    def list_low_stock(
        self,
        warehouse_id: str | None = None,
        limit: int = _DEFAULT_LOW_STOCK_LIMIT,
        *,
        timeout_seconds: float | None = None,
    ) -> LowStockResult:
        normalized_warehouse_id = _optional_identifier(
            warehouse_id,
            "warehouse_id",
        )
        normalized_limit = _validate_limit(
            limit,
            "limit",
            _MAX_LIST_LIMIT,
        )
        deadline = self._deadline(timeout_seconds)

        if normalized_warehouse_id is not None:
            self._ensure_warehouse_exists(normalized_warehouse_id, deadline)
            sql = _LOW_STOCK_BY_WAREHOUSE_SQL
            parameters: tuple[object, ...] = (
                normalized_warehouse_id,
                normalized_limit + 1,
            )
        else:
            sql = _LOW_STOCK_SQL
            parameters = (normalized_limit + 1,)

        rows = self._fetch_all(sql, parameters, deadline)
        items = [
            self._map_inventory_row(row, LowStockRow)
            for row in rows[:normalized_limit]
        ]
        return LowStockResult(
            items=items,
            row_count=len(items),
            truncated=len(rows) > normalized_limit,
        )

    def get_sales_order(
        self,
        so_id: str,
        *,
        timeout_seconds: float | None = None,
    ) -> SalesOrderDetail:
        normalized_id = _require_nonblank_string(
            so_id,
            "so_id",
            _MAX_ID_LENGTH,
        )
        deadline = self._deadline(timeout_seconds)

        header_row = self._fetch_one(
            _SALES_ORDER_HEADER_SQL,
            (normalized_id,),
            deadline,
        )
        if header_row is None:
            raise ErpNotFoundError("sales_order")

        item_rows = self._fetch_all(
            _SALES_ORDER_ITEMS_SQL,
            (normalized_id, _SALES_ORDER_ITEM_LIMIT + 1),
            deadline,
        )
        items = [
            self._map_sales_order_item(row)
            for row in item_rows[:_SALES_ORDER_ITEM_LIMIT]
        ]
        return SalesOrderDetail(
            order=self._map_sales_order_header(header_row),
            items=items,
            items_row_count=len(items),
            items_truncated=len(item_rows) > _SALES_ORDER_ITEM_LIMIT,
        )

    def get_dispatch(
        self,
        dispatch_id: str,
        *,
        timeout_seconds: float | None = None,
    ) -> DispatchDetail:
        normalized_id = _require_nonblank_string(
            dispatch_id,
            "dispatch_id",
            _MAX_ID_LENGTH,
        )
        deadline = self._deadline(timeout_seconds)

        header_row = self._fetch_one(
            _DISPATCH_DETAIL_SQL,
            (normalized_id,),
            deadline,
        )
        if header_row is None:
            raise ErpNotFoundError("dispatch")

        item_rows = self._fetch_all(
            _DISPATCH_ITEMS_SQL,
            (normalized_id, _DISPATCH_ITEM_LIMIT + 1),
            deadline,
        )
        items = [
            self._map_dispatch_item(row)
            for row in item_rows[:_DISPATCH_ITEM_LIMIT]
        ]
        return DispatchDetail(
            dispatch_id=header_row["dispatch_id"],
            so_id=header_row["so_id"],
            dispatch_date=header_row["dispatch_date"],
            status=header_row["status"],
            carrier=header_row["carrier"],
            tracking_number=header_row["tracking_number"],
            items=items,
            items_row_count=len(items),
            items_truncated=len(item_rows) > _DISPATCH_ITEM_LIMIT,
        )

    def list_dispatches(
        self,
        limit: int = _DISPATCH_LIST_DEFAULT_LIMIT,
        *,
        so_id: str | None = None,
        status: str | None = None,
        carrier: str | None = None,
        timeout_seconds: float | None = None,
    ) -> DispatchListResult:
        normalized_limit = _validate_limit(
            limit,
            "limit",
            _MAX_LIST_LIMIT,
        )
        normalized_so_id = _optional_identifier(so_id, "so_id")
        normalized_status = _optional_identifier(status, "status")
        normalized_carrier = _optional_identifier(carrier, "carrier")
        deadline = self._deadline(timeout_seconds)

        conditions: list[str] = []
        parameters: list[object] = []

        if normalized_so_id is not None:
            conditions.append("so_id = ?")
            parameters.append(normalized_so_id)
        if normalized_status is not None:
            conditions.append("status = ?")
            parameters.append(normalized_status)
        if normalized_carrier is not None:
            conditions.append("carrier = ?")
            parameters.append(normalized_carrier)

        sql = _DISPATCH_LIST_SQL.format(
            where=("WHERE " + " AND ".join(conditions)) if conditions else "",
        )
        parameters.append(normalized_limit + 1)

        rows = self._fetch_all(sql, tuple(parameters), deadline)
        items = [
            self._map_dispatch_summary(row)
            for row in rows[:normalized_limit]
        ]
        return DispatchListResult(
            items=items,
            row_count=len(items),
            truncated=len(rows) > normalized_limit,
        )

    def get_dispatches_by_sales_order(
        self,
        so_id: str,
        *,
        timeout_seconds: float | None = None,
    ) -> SalesOrderDispatchesResult:
        normalized_id = _require_nonblank_string(
            so_id,
            "so_id",
            _MAX_ID_LENGTH,
        )
        deadline = self._deadline(timeout_seconds)
        self._ensure_sales_order_exists(normalized_id, deadline)

        dispatch_rows = self._fetch_all(
            _DISPATCHES_BY_SO_SQL,
            (normalized_id, _MAX_LIST_LIMIT + 1),
            deadline,
        )

        dispatches: list[DispatchDetail] = []
        for d_row in dispatch_rows[:_MAX_LIST_LIMIT]:
            item_rows = self._fetch_all(
                _DISPATCH_ITEMS_SQL,
                (d_row["dispatch_id"], _DISPATCH_ITEM_LIMIT + 1),
                deadline,
            )
            items = [
                self._map_dispatch_item(i_row)
                for i_row in item_rows[:_DISPATCH_ITEM_LIMIT]
            ]
            dispatches.append(
                DispatchDetail(
                    dispatch_id=d_row["dispatch_id"],
                    so_id=d_row["so_id"],
                    dispatch_date=d_row["dispatch_date"],
                    status=d_row["status"],
                    carrier=d_row["carrier"],
                    tracking_number=d_row["tracking_number"],
                    items=items,
                    items_row_count=len(items),
                    items_truncated=len(item_rows) > _DISPATCH_ITEM_LIMIT,
                )
            )

        return SalesOrderDispatchesResult(
            so_id=normalized_id,
            dispatches=dispatches,
            dispatches_row_count=len(dispatches),
            dispatches_truncated=len(dispatch_rows) > _MAX_LIST_LIMIT,
        )

    def _deadline(self, timeout_seconds: float | None) -> float:
        timeout = self._effective_timeout(timeout_seconds)
        deadline = monotonic() + timeout
        self._ensure_before_deadline(deadline)
        return deadline

    def _effective_timeout(self, timeout_seconds: float | None) -> float:
        if timeout_seconds is None:
            return self._query_timeout_seconds
        if isinstance(timeout_seconds, bool) or not isinstance(
            timeout_seconds,
            (int, float),
        ):
            raise ErpInvalidArgumentsError("timeout_seconds")

        timeout = float(timeout_seconds)
        if not math.isfinite(timeout):
            raise ErpInvalidArgumentsError("timeout_seconds")
        if timeout <= 0:
            raise ErpQueryTimeoutError()
        return min(self._query_timeout_seconds, timeout)

    @staticmethod
    def _ensure_before_deadline(deadline: float) -> None:
        if monotonic() >= deadline:
            raise ErpQueryTimeoutError()

    def _fetch_all(
        self,
        sql: str,
        parameters: tuple[object, ...],
        deadline: float,
    ) -> list[dict[str, Any]]:
        self._ensure_before_deadline(deadline)
        return self._adapter.fetch_all(
            sql,
            parameters,
            deadline=deadline,
        )

    def _fetch_one(
        self,
        sql: str,
        parameters: tuple[object, ...],
        deadline: float,
    ) -> dict[str, Any] | None:
        self._ensure_before_deadline(deadline)
        return self._adapter.fetch_one(
            sql,
            parameters,
            deadline=deadline,
        )

    def _ensure_product_exists(self, product_id: str, deadline: float) -> None:
        row = self._fetch_one(
            _PRODUCT_EXISTS_SQL,
            (product_id,),
            deadline,
        )
        if row is None:
            raise ErpNotFoundError("product")

    def _ensure_warehouse_exists(
        self,
        warehouse_id: str,
        deadline: float,
    ) -> None:
        row = self._fetch_one(
            _WAREHOUSE_EXISTS_SQL,
            (warehouse_id,),
            deadline,
        )
        if row is None:
            raise ErpNotFoundError("warehouse")

    def _map_model(
        self,
        model: Callable[..., _MODEL],
        row: dict[str, Any],
        fields: tuple[str, ...],
        transform: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    ) -> _MODEL:
        try:
            values = {field: row[field] for field in fields}
            if transform is not None:
                values = transform(values)
            return model(**values)
        except (KeyError, TypeError, ValueError) as exc:
            raise ErpInternalError() from exc

    def _map_product_summary(self, row: dict[str, Any]) -> ProductSummary:
        return self._map_model(
            ProductSummary,
            row,
            (
                "product_id",
                "sku",
                "product_name",
                "category",
                "material",
                "size",
                "grade",
                "unit",
            ),
        )

    def _map_product_detail(self, row: dict[str, Any]) -> ProductDetail:
        return self._map_model(
            ProductDetail,
            row,
            (
                "product_id",
                "sku",
                "product_name",
                "category",
                "material",
                "size",
                "grade",
                "unit",
                "reorder_level",
            ),
        )

    def _map_inventory_row(
        self,
        row: dict[str, Any],
        model: Callable[..., InventoryRow],
    ) -> InventoryRow:
        def normalize(values: dict[str, Any]) -> dict[str, Any]:
            values["low_stock"] = bool(values["low_stock"])
            return values

        return self._map_model(
            model,
            row,
            (
                "product_id",
                "product_name",
                "warehouse_id",
                "warehouse_name",
                "on_hand_qty",
                "reserved_qty",
                "free_stock",
                "reorder_level",
                "low_stock",
            ),
            normalize,
        )

    def _map_warehouse(self, row: dict[str, Any]) -> WarehouseSummary:
        return self._map_model(
            WarehouseSummary,
            row,
            ("warehouse_id", "warehouse_name", "city"),
        )

    def _map_sales_order_header(
        self,
        row: dict[str, Any],
    ) -> SalesOrderHeader:
        return self._map_model(
            SalesOrderHeader,
            row,
            (
                "so_id",
                "customer_id",
                "customer_name",
                "order_date",
                "required_date",
                "status",
            ),
        )

    def _map_sales_order_item(
        self,
        row: dict[str, Any],
    ) -> SalesOrderItem:
        return self._map_model(
            SalesOrderItem,
            row,
            ("product_id", "product_name", "ordered_qty"),
        )

    def _ensure_sales_order_exists(
        self,
        so_id: str,
        deadline: float,
    ) -> None:
        row = self._fetch_one(
            _SALES_ORDER_EXISTS_SQL,
            (so_id,),
            deadline,
        )
        if row is None:
            raise ErpNotFoundError("sales_order")

    def _map_dispatch_summary(self, row: dict[str, Any]) -> DispatchSummary:
        return self._map_model(
            DispatchSummary,
            row,
            (
                "dispatch_id",
                "so_id",
                "dispatch_date",
                "status",
                "carrier",
                "tracking_number",
            ),
        )

    def _map_dispatch_item(self, row: dict[str, Any]) -> DispatchItemDetail:
        return self._map_model(
            DispatchItemDetail,
            row,
            (
                "dispatch_item_id",
                "product_id",
                "product_name",
                "picked_qty",
                "dispatched_qty",
                "barcode_verified",
            ),
            transform=lambda v: {
                **v,
                "barcode_verified": bool(v["barcode_verified"]),
            },
        )


__all__ = ["ErpReadService"]
