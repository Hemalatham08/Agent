from __future__ import annotations

from pydantic import JsonValue

from backend.agent.tools.contracts import ToolDefinition

_ERP_TOOL_VERSION = "1.0.0"
_ERP_READ_ONLY_METADATA: dict[str, JsonValue] = {"read_only": True}

ERP_TOOL_DEFINITIONS: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        name="erp.products.search",
        description=(
            "Find products by name, SKU, material, size, or grade. Omit the "
            "query argument (or leave it blank) to list all products in one "
            "call, optionally bounded by limit (1-50, default 20)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "additionalProperties": False,
        },
        version=_ERP_TOOL_VERSION,
        metadata=dict(_ERP_READ_ONLY_METADATA),
    ),
    ToolDefinition(
        name="erp.products.get",
        description="Retrieve one product by ID.",
        input_schema={
            "type": "object",
            "properties": {
                "product_id": {"type": "string"},
            },
            "required": ["product_id"],
            "additionalProperties": False,
        },
        version=_ERP_TOOL_VERSION,
        metadata=dict(_ERP_READ_ONLY_METADATA),
    ),
    ToolDefinition(
        name="erp.products.count",
        description="Return the authoritative total number of products.",
        input_schema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        version=_ERP_TOOL_VERSION,
        metadata=dict(_ERP_READ_ONLY_METADATA),
    ),
    ToolDefinition(
        name="erp.inventory.get",
        description=(
            "Check inventory for a product, optionally by warehouse."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "product_id": {"type": "string"},
                "warehouse_id": {"type": "string"},
            },
            "required": ["product_id"],
            "additionalProperties": False,
        },
        version=_ERP_TOOL_VERSION,
        metadata=dict(_ERP_READ_ONLY_METADATA),
    ),
    ToolDefinition(
        name="erp.inventory.list",
        description=(
            "List inventory for all products across warehouses. Optionally "
            "filter by warehouse_id. Returns product, warehouse, and stock "
            "quantities. Bounded by limit (1-50, default 50)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "warehouse_id": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "additionalProperties": False,
        },
        version=_ERP_TOOL_VERSION,
        metadata=dict(_ERP_READ_ONLY_METADATA),
    ),
    ToolDefinition(
        name="erp.warehouses.list",
        description="List available warehouses.",
        input_schema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        version=_ERP_TOOL_VERSION,
        metadata=dict(_ERP_READ_ONLY_METADATA),
    ),
    ToolDefinition(
        name="erp.inventory.low_stock",
        description=(
            "Identify per-warehouse inventory at or below reorder level."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "warehouse_id": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "additionalProperties": False,
        },
        version=_ERP_TOOL_VERSION,
        metadata=dict(_ERP_READ_ONLY_METADATA),
    ),
    ToolDefinition(
        name="erp.sales_orders.get",
        description="Retrieve a sales order header and items.",
        input_schema={
            "type": "object",
            "properties": {
                "so_id": {"type": "string"},
            },
            "required": ["so_id"],
            "additionalProperties": False,
        },
        version=_ERP_TOOL_VERSION,
        metadata=dict(_ERP_READ_ONLY_METADATA),
    ),
    ToolDefinition(
        name="erp.sales_orders.search",
        description=(
            "Find sales orders by customer name, customer ID, or order status "
            "(such as Pending, Partially Dispatched, Dispatched). Omit all arguments "
            "(or leave query blank) to list recent sales orders, optionally bounded "
            "by limit (1-50, default 20)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "status": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "additionalProperties": False,
        },
        version=_ERP_TOOL_VERSION,
        metadata=dict(_ERP_READ_ONLY_METADATA),
    ),
    ToolDefinition(
        name="erp.dispatches.get",
        description=(
            "Retrieve one dispatch record (header plus picked/dispatched items) by its "
            "exact dispatch ID, such as DSP001. Required argument: dispatch_id "
            "(string, dispatch ID taken from a previous tool result or the user). "
            "Only use this for a single specific dispatch; to enumerate dispatches "
            "use erp.dispatches.list instead."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "dispatch_id": {"type": "string"},
            },
            "required": ["dispatch_id"],
            "additionalProperties": False,
        },
        version=_ERP_TOOL_VERSION,
        metadata=dict(_ERP_READ_ONLY_METADATA),
    ),
    ToolDefinition(
        name="erp.dispatches.list",
        description=(
            "List dispatch records, newest first, with optional exact-match filters. "
            "Optional arguments: so_id (sales order ID such as SO001), status "
            "(one of 'Dispatched' or 'Partially Dispatched'; there is no 'delivered' "
            "status), carrier (such as BlueDart or DTDC), limit (integer between 1 "
            "and 50, default 20). Omit all filters to list every dispatch. This is "
            "the preferred tool for any question that asks for a list of "
            "dispatched/delivered elements."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "limit": {"type": "integer"},
                "so_id": {"type": "string"},
                "status": {"type": "string"},
                "carrier": {"type": "string"},
            },
            "additionalProperties": False,
        },
        version=_ERP_TOOL_VERSION,
        metadata=dict(_ERP_READ_ONLY_METADATA),
    ),
    ToolDefinition(
        name="erp.dispatches.by_sales_order",
        description=(
            "Retrieve all dispatch records and item-level dispatch quantities for "
            "one sales order. Required argument: so_id (string, an existing sales "
            "order ID such as SO001; unknown IDs return 'Sales Order not found'). "
            "Only use this when the user asks about a specific sales order."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "so_id": {"type": "string"},
            },
            "required": ["so_id"],
            "additionalProperties": False,
        },
        version=_ERP_TOOL_VERSION,
        metadata=dict(_ERP_READ_ONLY_METADATA),
    ),
    ToolDefinition(
        name="erp.finance.sales_summary",
        description=(
            "Summarize sales revenue, standard cost, gross profit, and gross margin "
            "by month, quarter, product, customer, or category. Arguments: group_by "
            "(one of 'month', 'quarter', 'product', 'customer', 'category'; default "
            "'month'), basis (one of 'dispatched', 'booked', 'invoiced'; default "
            "'dispatched'), date_from and date_to (inclusive YYYY-MM-DD), limit "
            "(integer 1-50, default 20). The invoiced basis supports only month, "
            "quarter, and customer because invoices have no product lines. Cost uses "
            "the standard product purchase price; gross profit is a standard-cost "
            "margin, not accounting COGS. Never invent totals."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "group_by": {
                    "type": "string",
                    "enum": [
                        "month",
                        "quarter",
                        "product",
                        "customer",
                        "category",
                    ],
                },
                "basis": {
                    "type": "string",
                    "enum": ["dispatched", "booked", "invoiced"],
                },
                "date_from": {"type": "string"},
                "date_to": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "additionalProperties": False,
        },
        version=_ERP_TOOL_VERSION,
        metadata=dict(_ERP_READ_ONLY_METADATA),
    ),
    ToolDefinition(
        name="erp.finance.purchase_summary",
        description=(
            "Summarize purchase expenditure by month, quarter, supplier, or product. "
            "Arguments: group_by (one of 'month', 'quarter', 'supplier', 'product'; "
            "default 'month'), basis (one of 'received', 'ordered'; default "
            "'received'), date_from and date_to (inclusive YYYY-MM-DD, by order "
            "date), limit (integer 1-50, default 20). Received value is received "
            "quantity multiplied by unit cost; ordered value is the procurement "
            "commitment; open value is ordered minus received value. Use this for "
            "procurement spend, not for a list of pending purchase orders."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "group_by": {
                    "type": "string",
                    "enum": ["month", "quarter", "supplier", "product"],
                },
                "basis": {
                    "type": "string",
                    "enum": ["received", "ordered"],
                },
                "date_from": {"type": "string"},
                "date_to": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "additionalProperties": False,
        },
        version=_ERP_TOOL_VERSION,
        metadata=dict(_ERP_READ_ONLY_METADATA),
    ),
    ToolDefinition(
        name="erp.warehouse.movement_summary",
        description=(
            "Summarize stock movement quantities by warehouse, month, quarter, "
            "product, or movement type. Arguments: group_by (one of 'warehouse', "
            "'month', 'quarter', 'product', 'movement_type'; default 'warehouse'), "
            "date_from and date_to (inclusive YYYY-MM-DD), limit (integer 1-50, "
            "default 20). Returns opening quantity, receipts, dispatches, inbound, "
            "outbound, receipts net of dispatch, and net change. These are period "
            "movement flows, not ending stock levels."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "group_by": {
                    "type": "string",
                    "enum": [
                        "warehouse",
                        "month",
                        "quarter",
                        "product",
                        "movement_type",
                    ],
                },
                "date_from": {"type": "string"},
                "date_to": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "additionalProperties": False,
        },
        version=_ERP_TOOL_VERSION,
        metadata=dict(_ERP_READ_ONLY_METADATA),
    ),
    ToolDefinition(
        name="erp.fulfillment.summary",
        description=(
            "Summarize fulfilment performance by carrier, dispatch status, product, "
            "or customer. Arguments: group_by (one of 'carrier', 'status', "
            "'product', 'customer'; default 'carrier'), date_from and date_to "
            "(inclusive YYYY-MM-DD, by dispatch date), limit (integer 1-50, default "
            "20). Returns ordered, picked, dispatched, and open quantities plus pick "
            "fill and order fill percentages. All-order fill includes orders with no "
            "dispatch; dispatched-order fill uses only dispatched orders. The ERP "
            "does not track confirmed customer delivery."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "group_by": {
                    "type": "string",
                    "enum": ["carrier", "status", "product", "customer"],
                },
                "date_from": {"type": "string"},
                "date_to": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "additionalProperties": False,
        },
        version=_ERP_TOOL_VERSION,
        metadata=dict(_ERP_READ_ONLY_METADATA),
    ),
)

ERP_TOOL_NAMES: tuple[str, ...] = tuple(
    definition.name for definition in ERP_TOOL_DEFINITIONS
)

ERP_TOOL_DEFINITIONS_BY_NAME: dict[str, ToolDefinition] = {
    definition.name: definition for definition in ERP_TOOL_DEFINITIONS
}

__all__ = [
    "ERP_TOOL_DEFINITIONS",
    "ERP_TOOL_DEFINITIONS_BY_NAME",
    "ERP_TOOL_NAMES",
]
