from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ErpModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ProductSummary(ErpModel):
    product_id: str
    sku: str
    product_name: str
    category: str
    material: str
    size: str
    grade: str
    unit: str


class ProductDetail(ProductSummary):
    reorder_level: int = Field(ge=0)


class ProductCountResult(ErpModel):
    product_count: int = Field(ge=0)


class InventoryRow(ErpModel):
    product_id: str
    product_name: str
    warehouse_id: str
    warehouse_name: str
    on_hand_qty: int = Field(ge=0)
    reserved_qty: int = Field(ge=0)
    free_stock: int
    reorder_level: int = Field(ge=0)
    low_stock: bool


class LowStockRow(InventoryRow):
    pass


class WarehouseSummary(ErpModel):
    warehouse_id: str
    warehouse_name: str
    city: str


class SalesOrderHeader(ErpModel):
    so_id: str
    customer_id: str
    customer_name: str
    order_date: str
    required_date: str
    status: str


class SalesOrderItem(ErpModel):
    product_id: str
    product_name: str
    ordered_qty: int = Field(ge=0)


class ProductSearchResult(ErpModel):
    items: list[ProductSummary]
    row_count: int = Field(ge=0)
    truncated: bool


class InventoryResult(ErpModel):
    items: list[InventoryRow]
    row_count: int = Field(ge=0)
    truncated: bool


class LowStockResult(ErpModel):
    items: list[LowStockRow]
    row_count: int = Field(ge=0)
    truncated: bool


class WarehouseListResult(ErpModel):
    items: list[WarehouseSummary]
    row_count: int = Field(ge=0)
    truncated: bool


class SalesOrderDetail(ErpModel):
    order: SalesOrderHeader
    items: list[SalesOrderItem]
    items_row_count: int = Field(ge=0)
    items_truncated: bool


class DispatchItemDetail(ErpModel):
    dispatch_item_id: str
    product_id: str
    product_name: str
    picked_qty: int = Field(ge=0)
    dispatched_qty: int = Field(ge=0)
    barcode_verified: bool


class DispatchSummary(ErpModel):
    dispatch_id: str
    so_id: str
    dispatch_date: str | None = None
    status: str
    carrier: str | None = None
    tracking_number: str | None = None


class DispatchDetail(DispatchSummary):
    items: list[DispatchItemDetail]
    items_row_count: int = Field(ge=0)
    items_truncated: bool


class DispatchListResult(ErpModel):
    items: list[DispatchSummary]
    row_count: int = Field(ge=0)
    truncated: bool


class SalesOrderDispatchesResult(ErpModel):
    so_id: str
    dispatches: list[DispatchDetail]
    dispatches_row_count: int = Field(ge=0)
    dispatches_truncated: bool


__all__ = [
    "DispatchDetail",
    "DispatchItemDetail",
    "DispatchListResult",
    "DispatchSummary",
    "ErpModel",
    "InventoryResult",
    "InventoryRow",
    "LowStockResult",
    "LowStockRow",
    "ProductDetail",
    "ProductCountResult",
    "ProductSearchResult",
    "ProductSummary",
    "SalesOrderDetail",
    "SalesOrderDispatchesResult",
    "SalesOrderHeader",
    "SalesOrderItem",
    "WarehouseListResult",
    "WarehouseSummary",
]
