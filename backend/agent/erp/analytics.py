"""Read-only SQL builders and result mapping for ERP financial analytics.

Every statement in this module is a fixed ``SELECT`` (or ``WITH ... SELECT``).
Group-by columns and labels are selected from a small allowlist and are never
interpolated from user input. Dates are validated and bound as parameters.

Two invariants matter for correctness:

* Dispatched sales join dispatch quantities to order-line prices only through
  aggregated ``(so_id, product_id)`` CTEs, so a naive many-to-many join can
  never fan out quantities.
* Ordered, picked, and dispatched quantities are aggregated in separate CTEs
  before being combined for fulfilment metrics.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable

from backend.agent.erp.analytics_models import (
    FulfillmentSummaryResult,
    FulfillmentSummaryRow,
    FulfillmentSummaryTotals,
    MovementSummaryResult,
    MovementSummaryRow,
    MovementSummaryTotals,
    PurchaseSummaryResult,
    PurchaseSummaryRow,
    PurchaseSummaryTotals,
    SalesSummaryResult,
    SalesSummaryRow,
    SalesSummaryTotals,
)
from backend.agent.erp.errors import ErpInvalidArgumentsError

SALES_GROUP_BYS: tuple[str, ...] = (
    "month",
    "quarter",
    "product",
    "customer",
    "category",
)
SALES_BASES: tuple[str, ...] = ("dispatched", "booked", "invoiced")
INVOICED_GROUP_BYS: tuple[str, ...] = ("month", "quarter", "customer")
PURCHASE_GROUP_BYS: tuple[str, ...] = (
    "month",
    "quarter",
    "supplier",
    "product",
)
PURCHASE_BASES: tuple[str, ...] = ("received", "ordered")
MOVEMENT_GROUP_BYS: tuple[str, ...] = (
    "warehouse",
    "month",
    "quarter",
    "product",
    "movement_type",
)
FULFILLMENT_GROUP_BYS: tuple[str, ...] = ("carrier", "status", "product", "customer")

DEFAULT_ANALYTICS_LIMIT = 20
MAX_ANALYTICS_LIMIT = 50

_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_SALES_NOTES = (
    "Revenue basis dispatched recognises dispatched quantity at order unit price.",
    "Cost uses the product standard purchase price; gross profit is a "
    "standard-cost margin, not accounting COGS.",
    "Tax, discounts, and freight are not recorded in this ERP.",
)
_INVOICED_NOTES = (
    "Invoiced basis uses billed invoice totals and cannot be attributed to "
    "products or categories.",
    "Cost and gross profit are unavailable for the invoiced basis.",
)
_PURCHASE_NOTES = (
    "Received expenditure is received quantity multiplied by unit cost.",
    "Ordered value is the procurement commitment; open value is ordered minus "
    "received value.",
    "Purchase figures exclude tax, freight, and discounts.",
)
_MOVEMENT_NOTES = (
    "Quantities describe period movement flow, not ending stock levels.",
    "Opening balance is included in inbound quantity and net change.",
    "Receipts net quantity equals receipts minus sales dispatches.",
)
_FULFILLMENT_NOTES = (
    "Pick fill is dispatched quantity divided by picked quantity.",
    "Order fill is dispatched quantity divided by ordered quantity.",
    "All-order fill includes orders without a dispatch; dispatched-order fill "
    "uses only orders that have at least one dispatch.",
    "The ERP does not track confirmed customer delivery.",
)


@dataclass(frozen=True)
class AnalyticsQuery:
    rows_sql: str
    rows_params: tuple[object, ...]
    totals_sql: str
    totals_params: tuple[object, ...]


def validate_choice(value: object, allowed: Iterable[str], field: str) -> str:
    if not isinstance(value, str):
        raise ErpInvalidArgumentsError(field)
    normalized = value.strip()
    if normalized not in allowed:
        raise ErpInvalidArgumentsError(
            field,
            message=(
                f"Invalid argument: {field} must be one of "
                f"{', '.join(allowed)}"
            ),
        )
    return normalized


def validate_sales_group_by(value: object, basis: str) -> str:
    group_by = validate_choice(value, SALES_GROUP_BYS, "group_by")
    if basis == "invoiced" and group_by not in INVOICED_GROUP_BYS:
        raise ErpInvalidArgumentsError(
            "group_by",
            message=(
                "Invalid argument: group_by must be month, quarter, or "
                "customer when basis is invoiced"
            ),
        )
    return group_by


def normalize_date(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ErpInvalidArgumentsError(field)
    text = value.strip()
    if not _DATE_PATTERN.match(text):
        raise ErpInvalidArgumentsError(
            field,
            message=f"Invalid argument: {field} must use YYYY-MM-DD",
        )
    try:
        date.fromisoformat(text)
    except ValueError as exc:
        raise ErpInvalidArgumentsError(
            field,
            message=f"Invalid argument: {field} must be a real calendar date",
        ) from exc
    return text


def normalize_date_range(
    date_from: object,
    date_to: object,
) -> tuple[str | None, str | None]:
    normalized_from = normalize_date(date_from, "date_from")
    normalized_to = normalize_date(date_to, "date_to")
    if (
        normalized_from is not None
        and normalized_to is not None
        and normalized_from > normalized_to
    ):
        raise ErpInvalidArgumentsError(
            "date_from",
            message="Invalid argument: date_from must not be after date_to",
        )
    return normalized_from, normalized_to


def _period_sql(column: str, group_by: str) -> str:
    if group_by == "month":
        return f"substr({column}, 1, 7)"
    return (
        f"(strftime('%Y', {column}) || '-Q' || "
        f"((CAST(strftime('%m', {column}) AS INTEGER) - 1) / 3 + 1))"
    )


def _date_conditions(
    column: str,
    date_from: str | None,
    date_to: str | None,
) -> tuple[list[str], list[object]]:
    conditions: list[str] = []
    parameters: list[object] = []
    if date_from is not None:
        conditions.append(f"{column} >= ?")
        parameters.append(date_from)
    if date_to is not None:
        conditions.append(f"{column} <= ?")
        parameters.append(date_to)
    return conditions, parameters


def _where(conditions: list[str]) -> str:
    return f"WHERE {' AND '.join(conditions)}" if conditions else ""


# ---------------------------------------------------------------------------
# Sales
# ---------------------------------------------------------------------------


def _sales_dimensions(
    group_by: str,
    date_column: str,
) -> tuple[str, str, str]:
    if group_by in ("month", "quarter"):
        expression = _period_sql(date_column, group_by)
        return expression, expression, expression
    if group_by == "product":
        return "p.product_id", "p.product_name", "p.product_id"
    if group_by == "category":
        return "p.category", "p.category", "p.category"
    return "c.customer_id", "c.customer_name", "c.customer_id"


def _row_order(group_by: str, value_column: str) -> str:
    if group_by in ("month", "quarter"):
        return "key ASC"
    return f"{value_column} DESC, key ASC"


def build_sales_query(
    group_by: str,
    basis: str,
    date_from: str | None,
    date_to: str | None,
    limit: int,
) -> AnalyticsQuery:
    if basis == "booked":
        return _sales_booked(group_by, date_from, date_to, limit)
    if basis == "invoiced":
        return _sales_invoiced(group_by, date_from, date_to, limit)
    return _sales_dispatched(group_by, date_from, date_to, limit)


def _sales_booked(
    group_by: str,
    date_from: str | None,
    date_to: str | None,
    limit: int,
) -> AnalyticsQuery:
    key, label, group = _sales_dimensions(group_by, "so.order_date")
    conditions, date_params = _date_conditions(
        "so.order_date", date_from, date_to
    )
    where = _where(conditions)
    base = f"""
FROM sales_order_items AS soi
JOIN sales_orders AS so ON so.so_id = soi.so_id
JOIN products AS p ON p.product_id = soi.product_id
JOIN customers AS c ON c.customer_id = so.customer_id
{where}
"""
    rows_sql = f"""
SELECT
    {key} AS key,
    {label} AS label,
    COUNT(DISTINCT so.so_id) AS orders,
    CAST(COALESCE(SUM(soi.ordered_qty), 0) AS INTEGER) AS units,
    ROUND(COALESCE(SUM(soi.ordered_qty * soi.unit_price), 0), 2) AS revenue,
    ROUND(COALESCE(SUM(soi.ordered_qty * p.purchase_price), 0), 2) AS cost
{base}
GROUP BY {group}
ORDER BY {_row_order(group_by, 'revenue')}
LIMIT ?
"""
    totals_sql = f"""
SELECT
    COUNT(DISTINCT so.so_id) AS orders,
    CAST(COALESCE(SUM(soi.ordered_qty), 0) AS INTEGER) AS units,
    ROUND(COALESCE(SUM(soi.ordered_qty * soi.unit_price), 0), 2) AS revenue,
    ROUND(COALESCE(SUM(soi.ordered_qty * p.purchase_price), 0), 2) AS cost
{base}
"""
    return AnalyticsQuery(
        rows_sql=rows_sql,
        rows_params=tuple(date_params) + (limit + 1,),
        totals_sql=totals_sql,
        totals_params=tuple(date_params),
    )


def _sales_dispatched(
    group_by: str,
    date_from: str | None,
    date_to: str | None,
    limit: int,
) -> AnalyticsQuery:
    key, label, group = _sales_dimensions(group_by, "dq.dispatch_date")
    conditions, date_params = _date_conditions(
        "d.dispatch_date", date_from, date_to
    )
    where = _where(conditions)
    joins = f"""
FROM (
    SELECT
        d.so_id,
        di.product_id,
        d.dispatch_date,
        SUM(di.dispatched_qty) AS dispatched_qty
    FROM dispatches AS d
    JOIN dispatch_items AS di ON di.dispatch_id = d.dispatch_id
    {where}
    GROUP BY d.so_id, di.product_id, d.dispatch_date
) AS dq
JOIN (
    SELECT
        so_id,
        product_id,
        SUM(ordered_qty * unit_price) / NULLIF(SUM(ordered_qty), 0) AS unit_price
    FROM sales_order_items
    GROUP BY so_id, product_id
) AS op ON op.so_id = dq.so_id AND op.product_id = dq.product_id
JOIN sales_orders AS so ON so.so_id = dq.so_id
JOIN customers AS c ON c.customer_id = so.customer_id
JOIN products AS p ON p.product_id = dq.product_id
"""
    rows_sql = f"""
SELECT
    {key} AS key,
    {label} AS label,
    COUNT(DISTINCT dq.so_id) AS orders,
    CAST(COALESCE(SUM(dq.dispatched_qty), 0) AS INTEGER) AS units,
    ROUND(COALESCE(SUM(dq.dispatched_qty * op.unit_price), 0), 2) AS revenue,
    ROUND(COALESCE(SUM(dq.dispatched_qty * p.purchase_price), 0), 2) AS cost
{joins}
GROUP BY {group}
ORDER BY {_row_order(group_by, 'revenue')}
LIMIT ?
"""
    totals_sql = f"""
SELECT
    COUNT(DISTINCT dq.so_id) AS orders,
    CAST(COALESCE(SUM(dq.dispatched_qty), 0) AS INTEGER) AS units,
    ROUND(COALESCE(SUM(dq.dispatched_qty * op.unit_price), 0), 2) AS revenue,
    ROUND(COALESCE(SUM(dq.dispatched_qty * p.purchase_price), 0), 2) AS cost
{joins}
"""
    return AnalyticsQuery(
        rows_sql=rows_sql,
        rows_params=tuple(date_params) + (limit + 1,),
        totals_sql=totals_sql,
        totals_params=tuple(date_params),
    )


def _sales_invoiced(
    group_by: str,
    date_from: str | None,
    date_to: str | None,
    limit: int,
) -> AnalyticsQuery:
    key, label, group = _sales_dimensions(group_by, "i.invoice_date")
    conditions, date_params = _date_conditions(
        "i.invoice_date", date_from, date_to
    )
    conditions.insert(0, "i.invoice_type = 'Sales'")
    where = _where(conditions)
    base = f"""
FROM invoices AS i
JOIN sales_orders AS so ON so.so_id = i.so_id
JOIN customers AS c ON c.customer_id = so.customer_id
{where}
"""
    rows_sql = f"""
SELECT
    {key} AS key,
    {label} AS label,
    COUNT(DISTINCT i.invoice_id) AS orders,
    NULL AS units,
    ROUND(COALESCE(SUM(i.total_amount), 0), 2) AS revenue,
    NULL AS cost
{base}
GROUP BY {group}
ORDER BY {_row_order(group_by, 'revenue')}
LIMIT ?
"""
    totals_sql = f"""
SELECT
    COUNT(DISTINCT i.invoice_id) AS orders,
    NULL AS units,
    ROUND(COALESCE(SUM(i.total_amount), 0), 2) AS revenue,
    NULL AS cost
{base}
"""
    return AnalyticsQuery(
        rows_sql=rows_sql,
        rows_params=tuple(date_params) + (limit + 1,),
        totals_sql=totals_sql,
        totals_params=tuple(date_params),
    )


def make_sales_result(
    *,
    group_by: str,
    basis: str,
    currency: str,
    rows: list[dict[str, Any]],
    totals_row: dict[str, Any],
    limit: int,
) -> SalesSummaryResult:
    mapped = [_sales_row(row) for row in rows[:limit]]
    totals = _sales_totals(totals_row)
    notes = list(_SALES_NOTES)
    if basis == "invoiced":
        notes = list(_INVOICED_NOTES)
    return SalesSummaryResult(
        group_by=group_by,
        basis=basis,
        currency=currency,
        rows=mapped,
        totals=totals,
        row_count=len(mapped),
        truncated=len(rows) > limit,
        notes=notes,
    )


def _sales_row(row: dict[str, Any]) -> SalesSummaryRow:
    revenue = _round(row.get("revenue")) or 0.0
    cost = _round(row.get("cost"))
    gross_profit, margin = _profit(revenue, cost)
    units = row.get("units")
    return SalesSummaryRow(
        key=str(row.get("key") or ""),
        label=str(row.get("label") or ""),
        orders=int(row.get("orders") or 0),
        units=None if units is None else int(units),
        revenue=revenue,
        cost=cost,
        gross_profit=gross_profit,
        gross_margin_pct=margin,
    )


def _sales_totals(row: dict[str, Any]) -> SalesSummaryTotals:
    revenue = _round(row.get("revenue")) or 0.0
    cost = _round(row.get("cost"))
    gross_profit, margin = _profit(revenue, cost)
    units = row.get("units")
    return SalesSummaryTotals(
        orders=int(row.get("orders") or 0),
        units=None if units is None else int(units),
        revenue=revenue,
        cost=cost,
        gross_profit=gross_profit,
        gross_margin_pct=margin,
    )


# ---------------------------------------------------------------------------
# Purchases
# ---------------------------------------------------------------------------


def _purchase_dimensions(group_by: str) -> tuple[str, str, str]:
    if group_by in ("month", "quarter"):
        expression = _period_sql("po.order_date", group_by)
        return expression, expression, expression
    if group_by == "supplier":
        return "s.supplier_id", "s.supplier_name", "s.supplier_id"
    return "p.product_id", "p.product_name", "p.product_id"


def build_purchase_query(
    group_by: str,
    basis: str,
    date_from: str | None,
    date_to: str | None,
    limit: int,
) -> AnalyticsQuery:
    key, label, group = _purchase_dimensions(group_by)
    conditions, date_params = _date_conditions(
        "po.order_date", date_from, date_to
    )
    where = _where(conditions)
    base = f"""
FROM purchase_order_items AS poi
JOIN purchase_orders AS po ON po.po_id = poi.po_id
JOIN suppliers AS s ON s.supplier_id = po.supplier_id
JOIN products AS p ON p.product_id = poi.product_id
{where}
"""
    order_column = "ordered_value" if basis == "ordered" else "received_value"
    rows_sql = f"""
SELECT
    {key} AS key,
    {label} AS label,
    COUNT(DISTINCT po.po_id) AS orders,
    CAST(COALESCE(SUM(poi.ordered_qty), 0) AS INTEGER) AS units_ordered,
    CAST(COALESCE(SUM(poi.received_qty), 0) AS INTEGER) AS units_received,
    ROUND(COALESCE(SUM(poi.ordered_qty * poi.unit_cost), 0), 2) AS ordered_value,
    ROUND(COALESCE(SUM(poi.received_qty * poi.unit_cost), 0), 2) AS received_value,
    ROUND(
        COALESCE(SUM((poi.ordered_qty - poi.received_qty) * poi.unit_cost), 0),
        2
    ) AS open_value
{base}
GROUP BY {group}
ORDER BY {_row_order(group_by, order_column)}
LIMIT ?
"""
    totals_sql = f"""
SELECT
    COUNT(DISTINCT po.po_id) AS orders,
    CAST(COALESCE(SUM(poi.ordered_qty), 0) AS INTEGER) AS units_ordered,
    CAST(COALESCE(SUM(poi.received_qty), 0) AS INTEGER) AS units_received,
    ROUND(COALESCE(SUM(poi.ordered_qty * poi.unit_cost), 0), 2) AS ordered_value,
    ROUND(COALESCE(SUM(poi.received_qty * poi.unit_cost), 0), 2) AS received_value,
    ROUND(
        COALESCE(SUM((poi.ordered_qty - poi.received_qty) * poi.unit_cost), 0),
        2
    ) AS open_value
{base}
"""
    return AnalyticsQuery(
        rows_sql=rows_sql,
        rows_params=tuple(date_params) + (limit + 1,),
        totals_sql=totals_sql,
        totals_params=tuple(date_params),
    )


def make_purchase_result(
    *,
    group_by: str,
    basis: str,
    currency: str,
    rows: list[dict[str, Any]],
    totals_row: dict[str, Any],
    limit: int,
) -> PurchaseSummaryResult:
    mapped = [_purchase_row(row) for row in rows[:limit]]
    return PurchaseSummaryResult(
        group_by=group_by,
        basis=basis,
        currency=currency,
        rows=mapped,
        totals=_purchase_totals(totals_row),
        row_count=len(mapped),
        truncated=len(rows) > limit,
        notes=list(_PURCHASE_NOTES),
    )


def _purchase_row(row: dict[str, Any]) -> PurchaseSummaryRow:
    return PurchaseSummaryRow(
        key=str(row.get("key") or ""),
        label=str(row.get("label") or ""),
        orders=int(row.get("orders") or 0),
        units_ordered=int(row.get("units_ordered") or 0),
        units_received=int(row.get("units_received") or 0),
        ordered_value=_round(row.get("ordered_value")) or 0.0,
        received_value=_round(row.get("received_value")) or 0.0,
        open_value=_round(row.get("open_value")) or 0.0,
    )


def _purchase_totals(row: dict[str, Any]) -> PurchaseSummaryTotals:
    return PurchaseSummaryTotals(
        orders=int(row.get("orders") or 0),
        units_ordered=int(row.get("units_ordered") or 0),
        units_received=int(row.get("units_received") or 0),
        ordered_value=_round(row.get("ordered_value")) or 0.0,
        received_value=_round(row.get("received_value")) or 0.0,
        open_value=_round(row.get("open_value")) or 0.0,
    )


# ---------------------------------------------------------------------------
# Warehouse movements
# ---------------------------------------------------------------------------


def _movement_dimensions(group_by: str) -> tuple[str, str, str]:
    if group_by in ("month", "quarter"):
        expression = _period_sql("sm.movement_date", group_by)
        return expression, expression, expression
    if group_by == "warehouse":
        return "w.warehouse_id", "w.warehouse_name", "w.warehouse_id"
    if group_by == "product":
        return "p.product_id", "p.product_name", "p.product_id"
    return "sm.movement_type", "sm.movement_type", "sm.movement_type"


_MOVEMENT_AGGREGATES = """
    COUNT(*) AS movement_count,
    CAST(COALESCE(SUM(CASE WHEN sm.movement_type = 'Opening Balance'
        THEN sm.quantity_change ELSE 0 END), 0) AS INTEGER) AS opening_qty,
    CAST(COALESCE(SUM(CASE WHEN sm.movement_type = 'Purchase Receipt'
        THEN sm.quantity_change ELSE 0 END), 0) AS INTEGER) AS receipts_qty,
    CAST(COALESCE(SUM(CASE WHEN sm.movement_type = 'Sales Dispatch'
        THEN -sm.quantity_change ELSE 0 END), 0) AS INTEGER) AS dispatch_qty,
    CAST(COALESCE(SUM(CASE WHEN sm.movement_type NOT IN
        ('Opening Balance', 'Purchase Receipt', 'Sales Dispatch')
        THEN sm.quantity_change ELSE 0 END), 0) AS INTEGER) AS adjustment_qty,
    CAST(COALESCE(SUM(CASE WHEN sm.quantity_change > 0
        THEN sm.quantity_change ELSE 0 END), 0) AS INTEGER) AS inbound_qty,
    CAST(COALESCE(SUM(CASE WHEN sm.quantity_change < 0
        THEN -sm.quantity_change ELSE 0 END), 0) AS INTEGER) AS outbound_qty,
    CAST(COALESCE(SUM(sm.quantity_change), 0) AS INTEGER) AS net_change
"""


def build_movement_query(
    group_by: str,
    date_from: str | None,
    date_to: str | None,
    limit: int,
) -> AnalyticsQuery:
    key, label, group = _movement_dimensions(group_by)
    conditions, date_params = _date_conditions(
        "sm.movement_date", date_from, date_to
    )
    where = _where(conditions)
    base = f"""
FROM stock_movements AS sm
JOIN warehouses AS w ON w.warehouse_id = sm.warehouse_id
JOIN products AS p ON p.product_id = sm.product_id
{where}
"""
    rows_sql = f"""
SELECT
    {key} AS key,
    {label} AS label,
{_MOVEMENT_AGGREGATES}
{base}
GROUP BY {group}
ORDER BY key ASC
LIMIT ?
"""
    totals_sql = f"""
SELECT
{_MOVEMENT_AGGREGATES}
{base}
"""
    return AnalyticsQuery(
        rows_sql=rows_sql,
        rows_params=tuple(date_params) + (limit + 1,),
        totals_sql=totals_sql,
        totals_params=tuple(date_params),
    )


def make_movement_result(
    *,
    group_by: str,
    currency: str,
    rows: list[dict[str, Any]],
    totals_row: dict[str, Any],
    limit: int,
) -> MovementSummaryResult:
    mapped = [_movement_row(row) for row in rows[:limit]]
    return MovementSummaryResult(
        group_by=group_by,
        currency=currency,
        rows=mapped,
        totals=_movement_totals(totals_row),
        row_count=len(mapped),
        truncated=len(rows) > limit,
        notes=list(_MOVEMENT_NOTES),
    )


def _movement_row(row: dict[str, Any]) -> MovementSummaryRow:
    receipts = int(row.get("receipts_qty") or 0)
    dispatch = int(row.get("dispatch_qty") or 0)
    return MovementSummaryRow(
        key=str(row.get("key") or ""),
        label=str(row.get("label") or ""),
        movement_count=int(row.get("movement_count") or 0),
        opening_qty=int(row.get("opening_qty") or 0),
        receipts_qty=receipts,
        dispatch_qty=dispatch,
        adjustment_qty=int(row.get("adjustment_qty") or 0),
        inbound_qty=int(row.get("inbound_qty") or 0),
        outbound_qty=int(row.get("outbound_qty") or 0),
        receipts_net_qty=receipts - dispatch,
        net_change=int(row.get("net_change") or 0),
    )


def _movement_totals(row: dict[str, Any]) -> MovementSummaryTotals:
    receipts = int(row.get("receipts_qty") or 0)
    dispatch = int(row.get("dispatch_qty") or 0)
    return MovementSummaryTotals(
        movement_count=int(row.get("movement_count") or 0),
        opening_qty=int(row.get("opening_qty") or 0),
        receipts_qty=receipts,
        dispatch_qty=dispatch,
        adjustment_qty=int(row.get("adjustment_qty") or 0),
        inbound_qty=int(row.get("inbound_qty") or 0),
        outbound_qty=int(row.get("outbound_qty") or 0),
        receipts_net_qty=receipts - dispatch,
        net_change=int(row.get("net_change") or 0),
    )


# ---------------------------------------------------------------------------
# Fulfilment
# ---------------------------------------------------------------------------


def build_fulfillment_query(
    group_by: str,
    date_from: str | None,
    date_to: str | None,
    limit: int,
) -> AnalyticsQuery:
    conditions, date_params = _date_conditions(
        "d.dispatch_date", date_from, date_to
    )
    where = _where(conditions)
    params = tuple(date_params)

    totals_sql, totals_params = _fulfillment_totals(conditions, params)

    if group_by == "product":
        rows_sql = _fulfillment_product_rows(where)
        rows_params = params + (limit + 1,)
    elif group_by == "customer":
        rows_sql = _fulfillment_customer_rows(where)
        rows_params = params + (limit + 1,)
    elif group_by == "carrier":
        rows_sql = _fulfillment_carrier_rows(where)
        rows_params = params + params + (limit + 1,)
    else:
        rows_sql = _fulfillment_status_rows(where)
        rows_params = params + params + (limit + 1,)

    return AnalyticsQuery(
        rows_sql=rows_sql,
        rows_params=rows_params,
        totals_sql=totals_sql,
        totals_params=totals_params,
    )


def _fulfillment_totals(
    conditions: list[str],
    params: tuple[object, ...],
) -> tuple[str, tuple[object, ...]]:
    where = _where(conditions)
    exists_conditions = ["d.so_id = soi.so_id", *conditions]
    exists_where = _where(exists_conditions)
    sql = f"""
SELECT
    (SELECT COUNT(DISTINCT d.dispatch_id)
        FROM dispatches AS d {where}) AS dispatches,
    (SELECT COALESCE(SUM(ordered_qty), 0)
        FROM sales_order_items) AS ordered_all_qty,
    (SELECT COALESCE(SUM(di.picked_qty), 0)
        FROM dispatch_items AS di
        JOIN dispatches AS d ON d.dispatch_id = di.dispatch_id
        {where}) AS picked_qty,
    (SELECT COALESCE(SUM(di.dispatched_qty), 0)
        FROM dispatch_items AS di
        JOIN dispatches AS d ON d.dispatch_id = di.dispatch_id
        {where}) AS dispatched_qty,
    (SELECT COALESCE(SUM(soi.ordered_qty), 0)
        FROM sales_order_items AS soi
        WHERE EXISTS (
            SELECT 1 FROM dispatches AS d {exists_where}
        )) AS ordered_on_dispatched_orders
"""
    return sql, params + params + params + params


def _fulfillment_product_rows(where: str) -> str:
    return f"""
SELECT
    p.product_id AS key,
    p.product_name AS label,
    COALESCE(dsp.dispatches, 0) AS dispatches,
    CAST(COALESCE(o.ordered_qty, 0) AS INTEGER) AS ordered_qty,
    CAST(COALESCE(dsp.picked_qty, 0) AS INTEGER) AS picked_qty,
    CAST(COALESCE(dsp.dispatched_qty, 0) AS INTEGER) AS dispatched_qty
FROM products AS p
LEFT JOIN (
    SELECT product_id, SUM(ordered_qty) AS ordered_qty
    FROM sales_order_items
    GROUP BY product_id
) AS o ON o.product_id = p.product_id
LEFT JOIN (
    SELECT
        di.product_id,
        SUM(di.picked_qty) AS picked_qty,
        SUM(di.dispatched_qty) AS dispatched_qty,
        COUNT(DISTINCT d.dispatch_id) AS dispatches
    FROM dispatch_items AS di
    JOIN dispatches AS d ON d.dispatch_id = di.dispatch_id
    {where}
    GROUP BY di.product_id
) AS dsp ON dsp.product_id = p.product_id
WHERE COALESCE(o.ordered_qty, 0) > 0
   OR COALESCE(dsp.dispatched_qty, 0) > 0
ORDER BY dispatched_qty DESC, key ASC
LIMIT ?
"""


def _fulfillment_customer_rows(where: str) -> str:
    return f"""
SELECT
    c.customer_id AS key,
    c.customer_name AS label,
    COALESCE(dsp.dispatches, 0) AS dispatches,
    CAST(COALESCE(o.ordered_qty, 0) AS INTEGER) AS ordered_qty,
    CAST(COALESCE(dsp.picked_qty, 0) AS INTEGER) AS picked_qty,
    CAST(COALESCE(dsp.dispatched_qty, 0) AS INTEGER) AS dispatched_qty
FROM customers AS c
LEFT JOIN (
    SELECT so.customer_id, SUM(soi.ordered_qty) AS ordered_qty
    FROM sales_order_items AS soi
    JOIN sales_orders AS so ON so.so_id = soi.so_id
    GROUP BY so.customer_id
) AS o ON o.customer_id = c.customer_id
LEFT JOIN (
    SELECT
        so.customer_id,
        SUM(di.picked_qty) AS picked_qty,
        SUM(di.dispatched_qty) AS dispatched_qty,
        COUNT(DISTINCT d.dispatch_id) AS dispatches
    FROM dispatch_items AS di
    JOIN dispatches AS d ON d.dispatch_id = di.dispatch_id
    JOIN sales_orders AS so ON so.so_id = d.so_id
    {where}
    GROUP BY so.customer_id
) AS dsp ON dsp.customer_id = c.customer_id
WHERE COALESCE(o.ordered_qty, 0) > 0
   OR COALESCE(dsp.dispatched_qty, 0) > 0
ORDER BY dispatched_qty DESC, key ASC
LIMIT ?
"""


def _fulfillment_carrier_rows(where: str) -> str:
    return f"""
SELECT
    dsp.carrier AS key,
    dsp.carrier AS label,
    dsp.dispatches AS dispatches,
    CAST(COALESCE(obc.ordered_qty, 0) AS INTEGER) AS ordered_qty,
    CAST(COALESCE(dsp.picked_qty, 0) AS INTEGER) AS picked_qty,
    CAST(COALESCE(dsp.dispatched_qty, 0) AS INTEGER) AS dispatched_qty
FROM (
    SELECT
        COALESCE(d.carrier, 'Unassigned') AS carrier,
        SUM(di.picked_qty) AS picked_qty,
        SUM(di.dispatched_qty) AS dispatched_qty,
        COUNT(DISTINCT d.dispatch_id) AS dispatches
    FROM dispatch_items AS di
    JOIN dispatches AS d ON d.dispatch_id = di.dispatch_id
    {where}
    GROUP BY COALESCE(d.carrier, 'Unassigned')
) AS dsp
LEFT JOIN (
    SELECT co.carrier, SUM(order_totals.ordered_qty) AS ordered_qty
    FROM (
        SELECT DISTINCT COALESCE(d.carrier, 'Unassigned') AS carrier, d.so_id
        FROM dispatches AS d
        {where}
    ) AS co
    JOIN (
        SELECT so_id, SUM(ordered_qty) AS ordered_qty
        FROM sales_order_items
        GROUP BY so_id
    ) AS order_totals ON order_totals.so_id = co.so_id
    GROUP BY co.carrier
) AS obc ON obc.carrier = dsp.carrier
ORDER BY dispatched_qty DESC, key ASC
LIMIT ?
"""


def _fulfillment_status_rows(where: str) -> str:
    return f"""
SELECT
    dsp.status AS key,
    dsp.status AS label,
    dsp.dispatches AS dispatches,
    CAST(COALESCE(obs.ordered_qty, 0) AS INTEGER) AS ordered_qty,
    CAST(COALESCE(dsp.picked_qty, 0) AS INTEGER) AS picked_qty,
    CAST(COALESCE(dsp.dispatched_qty, 0) AS INTEGER) AS dispatched_qty
FROM (
    SELECT
        d.status AS status,
        SUM(di.picked_qty) AS picked_qty,
        SUM(di.dispatched_qty) AS dispatched_qty,
        COUNT(DISTINCT d.dispatch_id) AS dispatches
    FROM dispatch_items AS di
    JOIN dispatches AS d ON d.dispatch_id = di.dispatch_id
    {where}
    GROUP BY d.status
) AS dsp
LEFT JOIN (
    SELECT so_totals.status, SUM(order_totals.ordered_qty) AS ordered_qty
    FROM (
        SELECT DISTINCT d.status AS status, d.so_id
        FROM dispatches AS d
        {where}
    ) AS so_totals
    JOIN (
        SELECT so_id, SUM(ordered_qty) AS ordered_qty
        FROM sales_order_items
        GROUP BY so_id
    ) AS order_totals ON order_totals.so_id = so_totals.so_id
    GROUP BY so_totals.status
) AS obs ON obs.status = dsp.status
ORDER BY dispatched_qty DESC, key ASC
LIMIT ?
"""


def make_fulfillment_result(
    *,
    group_by: str,
    rows: list[dict[str, Any]],
    totals_row: dict[str, Any],
    limit: int,
) -> FulfillmentSummaryResult:
    mapped = [_fulfillment_row(row) for row in rows[:limit]]
    totals = _fulfillment_totals_row(totals_row, group_by)
    return FulfillmentSummaryResult(
        group_by=group_by,
        rows=mapped,
        totals=totals,
        row_count=len(mapped),
        truncated=len(rows) > limit,
        notes=list(_FULFILLMENT_NOTES),
    )


def _fulfillment_row(row: dict[str, Any]) -> FulfillmentSummaryRow:
    ordered = int(row.get("ordered_qty") or 0)
    picked = int(row.get("picked_qty") or 0)
    dispatched = int(row.get("dispatched_qty") or 0)
    return FulfillmentSummaryRow(
        key=str(row.get("key") or ""),
        label=str(row.get("label") or ""),
        dispatches=int(row.get("dispatches") or 0),
        ordered_qty=ordered,
        picked_qty=picked,
        dispatched_qty=dispatched,
        open_qty=max(ordered - dispatched, 0),
        pick_fill_pct=_percent(dispatched, picked),
        order_fill_pct=_percent(dispatched, ordered),
    )


def _fulfillment_totals_row(
    row: dict[str, Any],
    group_by: str,
) -> FulfillmentSummaryTotals:
    picked = int(row.get("picked_qty") or 0)
    dispatched = int(row.get("dispatched_qty") or 0)
    ordered_all = int(row.get("ordered_all_qty") or 0)
    ordered_dispatched = int(row.get("ordered_on_dispatched_orders") or 0)
    ordered = (
        ordered_dispatched
        if group_by in ("carrier", "status")
        else ordered_all
    )
    return FulfillmentSummaryTotals(
        dispatches=int(row.get("dispatches") or 0),
        ordered_qty=ordered,
        picked_qty=picked,
        dispatched_qty=dispatched,
        open_qty=max(ordered - dispatched, 0),
        pick_fill_pct=_percent(dispatched, picked),
        order_fill_pct=_percent(dispatched, ordered),
        ordered_on_dispatched_orders=ordered_dispatched,
        dispatched_order_fill_pct=_percent(dispatched, ordered_dispatched),
    )


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _round(value: object) -> float | None:
    if value is None:
        return None
    return round(float(value), 2)


def _percent(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(100.0 * numerator / denominator, 2)


def _profit(
    revenue: float,
    cost: float | None,
) -> tuple[float | None, float | None]:
    if cost is None:
        return None, None
    gross_profit = round(revenue - cost, 2)
    margin = None if revenue == 0 else round(100.0 * gross_profit / revenue, 2)
    return gross_profit, margin


__all__ = [
    "AnalyticsQuery",
    "DEFAULT_ANALYTICS_LIMIT",
    "FULFILLMENT_GROUP_BYS",
    "MAX_ANALYTICS_LIMIT",
    "MOVEMENT_GROUP_BYS",
    "PURCHASE_BASES",
    "PURCHASE_GROUP_BYS",
    "SALES_BASES",
    "SALES_GROUP_BYS",
    "build_fulfillment_query",
    "build_movement_query",
    "build_purchase_query",
    "build_sales_query",
    "make_fulfillment_result",
    "make_movement_result",
    "make_purchase_result",
    "make_sales_result",
    "normalize_date_range",
    "validate_choice",
    "validate_sales_group_by",
]
