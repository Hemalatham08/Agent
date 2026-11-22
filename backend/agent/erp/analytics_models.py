"""Frozen result models for the read-only ERP financial analytics tools."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AnalyticsModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SalesSummaryRow(AnalyticsModel):
    key: str
    label: str
    orders: int = Field(ge=0)
    units: int | None = Field(default=None, ge=0)
    revenue: float
    cost: float | None = None
    gross_profit: float | None = None
    gross_margin_pct: float | None = None


class SalesSummaryTotals(AnalyticsModel):
    orders: int = Field(ge=0)
    units: int | None = Field(default=None, ge=0)
    revenue: float
    cost: float | None = None
    gross_profit: float | None = None
    gross_margin_pct: float | None = None


class SalesSummaryResult(AnalyticsModel):
    group_by: str
    basis: str
    currency: str
    rows: list[SalesSummaryRow]
    totals: SalesSummaryTotals
    row_count: int = Field(ge=0)
    truncated: bool
    notes: list[str]


class PurchaseSummaryRow(AnalyticsModel):
    key: str
    label: str
    orders: int = Field(ge=0)
    units_ordered: int = Field(ge=0)
    units_received: int = Field(ge=0)
    ordered_value: float
    received_value: float
    open_value: float


class PurchaseSummaryTotals(AnalyticsModel):
    orders: int = Field(ge=0)
    units_ordered: int = Field(ge=0)
    units_received: int = Field(ge=0)
    ordered_value: float
    received_value: float
    open_value: float


class PurchaseSummaryResult(AnalyticsModel):
    group_by: str
    basis: str
    currency: str
    rows: list[PurchaseSummaryRow]
    totals: PurchaseSummaryTotals
    row_count: int = Field(ge=0)
    truncated: bool
    notes: list[str]


class MovementSummaryRow(AnalyticsModel):
    key: str
    label: str
    movement_count: int = Field(ge=0)
    opening_qty: int
    receipts_qty: int
    dispatch_qty: int
    adjustment_qty: int
    inbound_qty: int
    outbound_qty: int
    receipts_net_qty: int
    net_change: int


class MovementSummaryTotals(AnalyticsModel):
    movement_count: int = Field(ge=0)
    opening_qty: int
    receipts_qty: int
    dispatch_qty: int
    adjustment_qty: int
    inbound_qty: int
    outbound_qty: int
    receipts_net_qty: int
    net_change: int


class MovementSummaryResult(AnalyticsModel):
    group_by: str
    currency: str
    rows: list[MovementSummaryRow]
    totals: MovementSummaryTotals
    row_count: int = Field(ge=0)
    truncated: bool
    notes: list[str]


class FulfillmentSummaryRow(AnalyticsModel):
    key: str
    label: str
    dispatches: int = Field(ge=0)
    ordered_qty: int = Field(ge=0)
    picked_qty: int = Field(ge=0)
    dispatched_qty: int = Field(ge=0)
    open_qty: int = Field(ge=0)
    pick_fill_pct: float | None = None
    order_fill_pct: float | None = None


class FulfillmentSummaryTotals(AnalyticsModel):
    dispatches: int = Field(ge=0)
    ordered_qty: int = Field(ge=0)
    picked_qty: int = Field(ge=0)
    dispatched_qty: int = Field(ge=0)
    open_qty: int = Field(ge=0)
    pick_fill_pct: float | None = None
    order_fill_pct: float | None = None
    ordered_on_dispatched_orders: int = Field(ge=0)
    dispatched_order_fill_pct: float | None = None


class FulfillmentSummaryResult(AnalyticsModel):
    group_by: str
    rows: list[FulfillmentSummaryRow]
    totals: FulfillmentSummaryTotals
    row_count: int = Field(ge=0)
    truncated: bool
    notes: list[str]


__all__ = [
    "FulfillmentSummaryResult",
    "FulfillmentSummaryRow",
    "FulfillmentSummaryTotals",
    "MovementSummaryResult",
    "MovementSummaryRow",
    "MovementSummaryTotals",
    "PurchaseSummaryResult",
    "PurchaseSummaryRow",
    "PurchaseSummaryTotals",
    "SalesSummaryResult",
    "SalesSummaryRow",
    "SalesSummaryTotals",
]
