# Phase 3D - Read-Only ERP Tool Integration Design

Status: Design completed. Phase 3D implementation is pending explicit approval.

## 1. Executive Summary

Phase 3D defines a read-only ERP tool integration for the iFive agent platform. The design connects the completed Phase 3C tool contracts, registry, and executor to the existing SQLite ERP database without exposing arbitrary SQL, write access, or unnecessary sensitive ERP fields.

The recommended MVP is a six-tool catalog:

- `erp.products.search`
- `erp.products.get`
- `erp.inventory.get`
- `erp.warehouses.list`
- `erp.inventory.low_stock`
- `erp.sales_orders.get`

The tools use a dedicated ERP read service with fixed parameterized queries, explicit column projections, deterministic ordering, bounded result sizes, and read-only database connections. They do not reuse the existing generic SQL execution path.

Phase 3C remains unchanged. A thin Phase 3D `ErpToolRunner` adapter translates typed ERP business-error envelopes into the existing `ToolExecutionResult` and `ToolExecutionError` contracts. No ERP handlers are registered in application startup as part of this design phase.

## 2. Current Architecture Findings

### 2.1 Agent platform

The agent foundation currently provides:

- `ToolDefinition`, `ToolExecutionRequest`, `ToolExecutionContext`, `ToolExecutionResult`, `ToolExecutionStatus`, and `ToolExecutionError`.
- `ToolRegistry` for validated tool definitions.
- `ToolExecutor` with bounded workers, per-execution timeouts, queued-work cancellation, `CANCELLED` timeout results, and sanitized handler failures.
- Handler signature: `handler(arguments, context) -> Any`.
- No typed business-error channel from handlers; unexpected handler exceptions become `handler_error`.
- No ERP tools, LLM integration, planner, approval policy, or execution persistence.

### 2.2 ERP database

The ERP database is `backend/data/ifive_erp.db`, SQLite, with 17 application tables:

`company`, `customers`, `dispatch_items`, `dispatches`, `goods_receipts`, `inventory`, `invoices`, `payments`, `products`, `purchase_order_items`, `purchase_orders`, `quality_inspections`, `sales_order_items`, `sales_orders`, `stock_movements`, `suppliers`, and `warehouses`.

Current seed data includes 6 products, 12 inventory rows, 2 warehouses, 5 customers, 6 sales orders, 4 purchase orders, 3 dispatches, 6 dispatch items, and 5 invoices.

The ERP database SHA-256 during design inspection was:

`23AB19DB0C475894CCE54101D44493E9AE2C9631632EB9AECA575F0F1E449C54`

### 2.3 ERP API and services

`backend/main.py` exposes 15 total FastAPI routes, including 11 business GET endpoints. There is no authentication, CORS, chat endpoint, or write endpoint.

`backend/tools/database.py` provides reusable read queries, but:

- `get_connection()` opens a normal read-write SQLite connection.
- `fetch_all()` accepts arbitrary SQL text.
- `get_all_products()` and `get_product_by_id()` use `SELECT *`, exposing pricing fields.
- `search_products()` has no row limit and does not escape `%` or `_`.
- Pending sales and purchase order services return headers only, not order items.
- `get_stock_by_product_name()` returns ad hoc error dictionaries rather than tool-contract errors.

### 2.4 SQL pipeline and security controls

`backend/tools/sql_security.py`:

- Allows one `SELECT` statement.
- Rejects non-`SELECT` statements and multiple statements.
- Checks referenced table names against all non-system SQLite tables.
- Does not enforce column allowlists or function denylists.
- Accepts `SELECT load_extension(...)`.
- Rejects valid CTEs inconsistently because the CTE alias is treated as a table.
- Allows subqueries, joins, cross joins, and tautologies such as `OR 1=1`.
- Does not enforce row-level or column-level restrictions.

`backend/tools/sql_executor.py`:

- Opens SQLite with `mode=ro`.
- Caps results at 100 rows.
- Uses a VM-step counter named `QUERY_TIMEOUT_SECONDS`; this is not a wall-clock timeout.
- Returns raw SQLite error text on database failure.

These controls are useful defense-in-depth for the legacy SQL pipeline but are not sufficient as the security boundary for ERP tools.

### 2.5 Legacy agent and low-stock semantics

`backend/legacy/agent.py` contains useful tool descriptions but broad exception handling and raw error exposure. It should not be reused as the Phase 3D execution layer.

The existing per-warehouse low-stock definition is:

`(on_hand_qty - reserved_qty) <= reorder_level`

The SQL generator contains a contradictory product-level rollup definition. Phase 3D uses the per-warehouse definition and must not silently use a product-level rollup for replenishment alerts.

### 2.6 Reuse assessment

The existing query shapes for product search, product detail, inventory, and low stock can inform the new service. The new service must not reuse the existing read-write connection helper or generic SQL executor. Sales-order detail requires a new query because the existing service returns only order headers.

## 3. Proposed Architecture and Data Flow

### 3.1 Architecture

```text
Future LLM / orchestrator
        |
        v
ToolRegistry definitions
        |
        v
ErpToolRunner
        |
        v
Phase 3C ToolExecutor
        |
        v
ERP tool handler
        |
        v
ErpReadService
        |
        v
SqliteErpReadAdapter
        |
        v
ERP database (read-only connection)
```

### 3.2 Component responsibilities

| Component | Responsibility |
|---|---|
| `ToolDefinition` | LLM-facing name, description, strict input schema, version, read-only metadata. |
| `ToolRegistry` | Stores and exports definitions; does not execute. |
| `ToolExecutor` | Phase 3C preflight validation, bounded execution, timeout, cancellation, sanitized failures. |
| `ErpToolRunner` | Phase 3D adapter; calls executor, validates result envelopes, translates business errors to `ToolExecutionResult`. |
| ERP handler | Thin argument/context adapter; semantic validation; calls `ErpReadService`; returns success/error envelope. |
| `ErpReadService` | Fixed ERP operations, parameterized queries, explicit projections, row mapping, domain errors. |
| `SqliteErpReadAdapter` | Opens dedicated read-only connections, applies SQLite safety pragmas, executes fixed queries. |
| Future LLM | Selects tools from registry definitions and consumes tool output; not part of Phase 3D. |

### 3.3 Data flow

1. A future orchestrator selects a tool from `ToolRegistry.export_definitions()`.
2. It creates a `ToolExecutionRequest` with `execution_id`, `tool_name`, arguments, and metadata.
3. `ErpToolRunner` calls `ToolExecutor.execute()` with the configured timeout.
4. The executor performs preflight checks: definition exists, handler exists, arguments match the schema.
5. The handler receives deep-copied arguments and an immutable `ToolExecutionContext`.
6. The handler performs semantic validation and calls the relevant `ErpReadService` method.
7. The service executes one fixed parameterized query on a read-only connection and maps rows to JSON-compatible dictionaries.
8. The handler returns a success or error envelope.
9. `ErpToolRunner` converts an error envelope into a `FAILED` `ToolExecutionResult` with a typed `ToolExecutionError`; success output is returned as the tool's data.
10. The future LLM consumes only the final tool output, never SQL or database internals.

### 3.4 ErpToolRunner business-error translation

Phase 3C does not provide a typed business-error channel from handlers. A handler exception becomes the generic `handler_error` result, which loses the ERP error category. To preserve typed ERP errors without modifying Phase 3C, handlers return an internal JSON envelope:

```json
{"ok": true, "data": {}}
```

or

```json
{
  "ok": false,
  "error": {
    "code": "erp_not_found",
    "message": "Product not found",
    "category": "not_found",
    "recoverable": true,
    "retryable": false,
    "details": {}
  }
}
```

`ErpToolRunner.execute(request, timeout=...)` performs these steps:

1. Call `ToolExecutor.execute(request, timeout=timeout)`.
2. If the executor result is `FAILED` or `CANCELLED`, return it unchanged.
3. If the executor result is `SUCCEEDED`, validate that `output` is a mapping with a boolean `ok` field.
4. If `ok` is true, require a JSON-compatible `data` value and return a new `SUCCEEDED` `ToolExecutionResult` whose output is `data`. Preserve `execution_id`, `tool_name`, `started_at`, `finished_at`, and `duration_ms` from the executor result.
5. If `ok` is false, validate the error envelope: nonblank `code` and `message`, a valid `ErrorCategory` value, boolean `recoverable` and `retryable`, and JSON-compatible `details`. Return a new `FAILED` `ToolExecutionResult` with output `None`, the typed `ToolExecutionError`, and the original timing fields.
6. If the envelope is malformed, fail closed with a sanitized `erp_internal_error` `FAILED` result. Do not expose the malformed output.
7. Never modify or wrap `CANCELLED` results. Never change Phase 3C contracts or executor code.

The executor briefly reports `SUCCEEDED` before the runner translates a business-error envelope. Any future execution persistence must store the final runner result, not the intermediate executor result.

The rejected alternative is raising ERP exceptions from handlers. Phase 3C would convert them to generic `handler_error` results, losing not-found, permission, timeout, and ambiguity categories.

## 4. Proposed MVP ERP Tool Catalog

### 4.1 Recommended MVP

| Tool | Purpose | Inputs | Output | Tables |
|---|---|---|---|---|
| `erp.products.search` | Find products by name, SKU, material, size, or grade. | `query` required; `limit` optional. | Product summaries, count, truncation flag. | `products` |
| `erp.products.get` | Retrieve one product by ID. | `product_id` required. | Product master fields. | `products` |
| `erp.inventory.get` | Check inventory for a product, optionally by warehouse. | `product_id` required; `warehouse_id` optional. | Per-warehouse stock rows with free stock. | `inventory`, `products`, `warehouses` |
| `erp.warehouses.list` | List available warehouses. | None. | Warehouse ID, name, city. | `warehouses` |
| `erp.inventory.low_stock` | Identify per-warehouse inventory at or below reorder level. | Optional `warehouse_id`; optional `limit`. | Low-stock rows with free stock and reorder level. | `inventory`, `products`, `warehouses` |
| `erp.sales_orders.get` | Retrieve a sales order header and items. | `so_id` required. | Order header, customer name, item quantities. | `sales_orders`, `customers`, `sales_order_items`, `products` |

### 4.2 Rationale

This catalog covers the most common read-only ERP questions while keeping the surface small:

- Product search and detail are needed to resolve product references.
- Inventory lookup and low-stock reporting are the primary operational use cases.
- Warehouse listing supports inventory interpretation.
- Sales-order detail is a practical order-status use case and demonstrates header/detail joins.

Purchase-order detail, customer search, invoices, payments, stock movements, dispatch, and quality tools are deferred. Customer search is less urgent because sales-order output can include the customer name. Purchase-order detail is a likely Phase 3D.1 addition.

## 5. Input/Output Schemas and Examples

### 5.1 Schema conventions

All tool schemas:

- Declare `type: "object"`.
- Use `additionalProperties: false`.
- Use only the Phase 3C-supported keywords: `type`, `properties`, `required`, `additionalProperties`, and property-level `enum`.
- Rely on handler-level semantic validation for blank strings, length limits, numeric bounds, and identifier existence.

All outputs:

- Are JSON-compatible.
- Use ISO date strings.
- Use finite numbers only.
- Return `row_count` and `truncated` for list results.
- Never contain raw SQL, database paths, stack traces, or internal exception text.

### 5.2 Fixed output models and allowed columns

No tool uses `SELECT *`. The following fields are the only allowed output fields.

#### `ProductSummary`

Allowed fields:

- `products.product_id`
- `products.sku`
- `products.product_name`
- `products.category`
- `products.material`
- `products.size`
- `products.grade`
- `products.unit`

Explicitly excluded: `purchase_price`, `selling_price`, `reorder_level` in search summaries.

#### `ProductDetail`

Allowed fields:

- `products.product_id`
- `products.sku`
- `products.product_name`
- `products.category`
- `products.material`
- `products.size`
- `products.grade`
- `products.unit`
- `products.reorder_level`

Explicitly excluded: `purchase_price`, `selling_price`.

#### `InventoryRow`

Allowed fields:

- `products.product_id`
- `products.product_name`
- `inventory.warehouse_id`
- `warehouses.warehouse_name`
- `inventory.on_hand_qty`
- `inventory.reserved_qty`
- `(inventory.on_hand_qty - inventory.reserved_qty) AS free_stock`
- `products.reorder_level`
- `((inventory.on_hand_qty - inventory.reserved_qty) <= products.reorder_level) AS low_stock`

Explicitly excluded: `inventory.inventory_id`, pricing fields, warehouse city.

#### `WarehouseSummary`

Allowed fields:

- `warehouses.warehouse_id`
- `warehouses.warehouse_name`
- `warehouses.city`

#### `LowStockRow`

Uses the same fields as `InventoryRow`, filtered by the per-warehouse low-stock definition. `low_stock` is always true in this output.

#### `SalesOrderHeader`

Allowed fields:

- `sales_orders.so_id`
- `sales_orders.customer_id`
- `customers.customer_name`
- `sales_orders.order_date`
- `sales_orders.required_date`
- `sales_orders.status`

Explicitly excluded: `customers.phone`, all invoice and payment fields.

#### `SalesOrderItem`

Allowed fields:

- `sales_order_items.product_id`
- `products.product_name`
- `sales_order_items.ordered_qty`

Explicitly excluded: `sales_order_items.unit_price`, `so_item_id`, line totals, tax, discount, invoice, and payment fields.

#### `SalesOrderDetail`

Contains one `SalesOrderHeader`, a bounded list of `SalesOrderItem` rows, `items_row_count`, and `items_truncated`. It contains no financial fields.

### 5.3 Deterministic ordering and bounded limits

| Tool | Ordering | Limit |
|---|---|---|
| `erp.products.search` | `product_name COLLATE NOCASE ASC, product_id ASC` | Default 20, maximum 50. |
| `erp.products.get` | Single row by `product_id`. | 1. |
| `erp.inventory.get` | `warehouse_id ASC` | Maximum 50, truncated flag. |
| `erp.warehouses.list` | `warehouse_id ASC` | Maximum 50, truncated flag. |
| `erp.inventory.low_stock` | `product_id ASC, warehouse_id ASC` | Default 20, maximum 50. |
| `erp.sales_orders.get` | Header by `so_id`; items by `so_item_id ASC`. | Maximum 100 items, truncated flag. |

All list queries fetch `limit + 1` rows to compute `truncated` and then return at most `limit` rows. No list tool is unbounded.

### 5.4 Wildcard escaping

Product search uses parameterized `LIKE` against name, SKU, material, size, and grade. Before binding, the handler escapes backslash, percent, and underscore:

```text
\  ->  \\
%  ->  \%
_  ->  \_
```

The SQL uses `LIKE ? ESCAPE '\'`. This prevents user input from acting as an unintended wildcard while still allowing normal substring search.

### 5.5 `erp.products.search`

Schema:

```json
{
  "type": "object",
  "properties": {
    "query": {"type": "string"},
    "limit": {"type": "integer"}
  },
  "required": ["query"],
  "additionalProperties": false
}
```

Arguments:

```json
{"query": "M10", "limit": 20}
```

Output:

```json
{
  "items": [
    {
      "product_id": "PRD001",
      "sku": "HEX-M10-SS304",
      "product_name": "Hex Bolt M10",
      "category": "Bolts",
      "material": "Stainless Steel",
      "size": "M10",
      "grade": "SS304",
      "unit": "pieces"
    }
  ],
  "row_count": 1,
  "truncated": false
}
```

Handler validation: trim and require nonblank `query`; maximum query length 200; limit 1-50, default 20.

### 5.6 `erp.products.get`

Schema:

```json
{
  "type": "object",
  "properties": {
    "product_id": {"type": "string"}
  },
  "required": ["product_id"],
  "additionalProperties": false
}
```

Output:

```json
{
  "product": {
    "product_id": "PRD001",
    "sku": "HEX-M10-SS304",
    "product_name": "Hex Bolt M10",
    "category": "Bolts",
    "material": "Stainless Steel",
    "size": "M10",
    "grade": "SS304",
    "unit": "pieces",
    "reorder_level": 500
  }
}
```

Handler validation: trim, require nonblank, maximum ID length 64. Missing product returns `erp_not_found`.

### 5.7 `erp.inventory.get`

Schema:

```json
{
  "type": "object",
  "properties": {
    "product_id": {"type": "string"},
    "warehouse_id": {"type": "string"}
  },
  "required": ["product_id"],
  "additionalProperties": false
}
```

Output:

```json
{
  "items": [
    {
      "product_id": "PRD001",
      "product_name": "Hex Bolt M10",
      "warehouse_id": "WH001",
      "warehouse_name": "Main Warehouse",
      "on_hand_qty": 420,
      "reserved_qty": 70,
      "free_stock": 350,
      "reorder_level": 500,
      "low_stock": true
    }
  ],
  "row_count": 1,
  "truncated": false
}
```

If the product does not exist, return `erp_not_found`. If the product exists but has no inventory rows, return success with an empty list. If a supplied warehouse does not exist, return `erp_not_found`.

### 5.8 `erp.warehouses.list`

Schema:

```json
{
  "type": "object",
  "properties": {},
  "additionalProperties": false
}
```

Output:

```json
{
  "items": [
    {
      "warehouse_id": "WH001",
      "warehouse_name": "Main Warehouse",
      "city": "Chennai"
    }
  ],
  "row_count": 1,
  "truncated": false
}
```

### 5.9 `erp.inventory.low_stock`

Schema:

```json
{
  "type": "object",
  "properties": {
    "warehouse_id": {"type": "string"},
    "limit": {"type": "integer"}
  },
  "additionalProperties": false
}
```

Output uses the same inventory row shape as `erp.inventory.get`, with `low_stock` always true. The definition is per warehouse:

`(on_hand_qty - reserved_qty) <= reorder_level`

No product-level rollup is used. A future product-level reporting view must be explicitly labeled and must not drive replenishment alerts.

### 5.10 `erp.sales_orders.get`

Schema:

```json
{
  "type": "object",
  "properties": {
    "so_id": {"type": "string"}
  },
  "required": ["so_id"],
  "additionalProperties": false
}
```

Output:

```json
{
  "order": {
    "so_id": "SO001",
    "customer_id": "CUS001",
    "customer_name": "Sri Venkateswara Engineering",
    "order_date": "2026-10-02",
    "required_date": "2026-10-05",
    "status": "Partially Dispatched"
  },
  "items": [
    {
      "product_id": "PRD001",
      "product_name": "Hex Bolt M10",
      "ordered_qty": 100
    }
  ],
  "items_row_count": 1,
  "items_truncated": false
}
```

Sales-order output excludes all financial fields, including `unit_price`, line totals, tax, discount, invoice amounts, and payment details.

### 5.11 Error envelope

Handlers return this internal envelope on business failure:

```json
{
  "ok": false,
  "error": {
    "code": "erp_not_found",
    "message": "Product not found",
    "category": "not_found",
    "recoverable": true,
    "retryable": false,
    "details": {
      "resource": "product"
    }
  }
}
```

`ErpToolRunner` converts this into a `FAILED` `ToolExecutionResult` with `ToolExecutionError`. The final output does not expose the envelope.

## 6. Read-Only Security Model

### 6.1 Threats and controls

| Threat | Control |
|---|---|
| INSERT, UPDATE, DELETE | Fixed `SELECT`-only service queries; `mode=ro`; `PRAGMA query_only=ON`; no write methods. |
| DDL operations | Fixed queries only; read-only connection; no schema-changing service methods. |
| Multiple SQL statements | One fixed statement per service method; no generic SQL tool in MVP. |
| Unsafe functions or extension loading | No dynamic SQL; `enable_load_extension(False)`; `PRAGMA trusted_schema=OFF`. |
| Unauthorized table access | Adapter allowlist and fixed queries; no table names from arguments. |
| Arbitrary database paths | Path comes from configuration only; never from tool arguments; validate path and reject agent DB paths. |
| Accidental writes through existing services | Do not use `database.get_connection()` or `fetch_all()`; new read-only adapter only. |
| Sensitive fields returned | Explicit column projections; exclude purchase/selling prices, customer phone, supplier email, and payment details. |
| Expensive queries | Wall-clock progress-handler deadline; row caps; indexed filters; no cross joins. |
| Raw SQL or stack traces leaked | Handlers catch expected failures and return sanitized envelopes; `include_exception_messages` remains off. |

### 6.2 Connection design

The SQLite adapter opens one connection per handler invocation:

```text
sqlite3.connect("file:<configured-path>?mode=ro", uri=True)
PRAGMA query_only = ON
PRAGMA trusted_schema = OFF
connection.enable_load_extension(False)
```

The adapter:

- Uses a wall-clock progress handler based on `time.monotonic()`.
- Uses parameterized queries exclusively.
- Fetches `limit + 1` rows to compute `truncated`.
- Closes the connection in `finally`.
- Never executes SQL supplied by a user or LLM.

`immutable=1` is not recommended for a live ERP database because it assumes the file cannot change.

### 6.3 Safe database path validation and fail-closed behavior

The ERP path is configuration, not a tool argument:

- Configuration key: `ERP_DATABASE_PATH`.
- Default: `backend/data/ifive_erp.db`.
- Resolve the configured path with `Path.resolve()`.
- Require the path to exist and be a regular file.
- Reject directories, empty paths, and unresolved paths.
- Reject the agent database path and any path equal to the configured agent database.
- Never create a database file if the path is missing.
- Never fall back to a default path when a configured path is invalid.
- Open with `mode=ro`; if the file is missing, unreadable, or invalid, fail closed.

Configuration validation should happen when the adapter is created. A later database failure returns a sanitized `erp_database_error`; a configuration failure returns a sanitized `erp_database_unavailable` or startup configuration error. No tool schema includes a database path argument.

### 6.4 Sensitive field policy

MVP tools exclude:

- `products.purchase_price`
- `products.selling_price`
- `customers.phone`
- `suppliers.contact_email`
- `payments` and invoice financial details
- `sales_order_items.unit_price`
- `purchase_order_items.unit_cost`

Pricing or contact fields require a future permission model and should not be added implicitly.

### 6.5 Existing components not to use for ERP tools

- `backend.tools.database.get_connection()` and `fetch_all()`: read-write and generic.
- `backend.tools.sql_executor.execute_readonly_sql()`: generic SQL execution and raw error exposure.
- `backend.tools.sql_security.validate_sql()`: insufficient column/function controls.
- `backend.tools.query_engine` and `sql_generator`: LLM-driven arbitrary SQL.
- `backend.legacy.agent`: broad exception handling and raw error exposure.

The existing SQL query shapes can be adapted, but the new service must own the read-only connection and fixed projections.

### 6.6 Known limitations

- SQLite has no database users or roles. Read-only enforcement is per connection and file permission.
- A process with write access to the file can still modify it outside the tool adapter.
- The existing step-count query limit is not a true time limit.
- The existing SQL security layer is not sufficient for arbitrary LLM-generated SQL.
- Schema drift can break fixed queries; adapter tests and versioning are required.

## 7. Handler and Service Design

### 7.1 Service layer

Create a dedicated `ErpReadService` with methods such as:

- `search_products(query, limit)`
- `get_product(product_id)`
- `get_inventory(product_id, warehouse_id=None)`
- `list_warehouses()`
- `list_low_stock(warehouse_id=None, limit=20)`
- `get_sales_order(so_id)`

The service owns fixed SQL, explicit columns, parameter binding, row mapping, and domain-level errors. Handlers never construct SQL.

### 7.2 Handler flow

Each handler:

1. Receives deep-copied arguments and `ToolExecutionContext`.
2. Performs semantic validation not covered by the Phase 3C schema subset.
3. Calls one service method.
4. Returns `{"ok": true, "data": ...}` or `{"ok": false, "error": ...}`.
5. Never returns raw database rows containing unapproved columns.
6. Never includes SQL, stack traces, database paths, or secrets in error details.

### 7.3 Context and timeout

Handlers use `context.execution_id` for tracing only. `context.metadata` is not trusted for authorization.

The Phase 3C executor timeout is the outer bound. It covers worker-queue waiting plus handler execution, returns `CANCELLED`, and cannot forcibly stop an already-running handler.

The SQLite query deadline is an inner bound:

- It uses a wall-clock progress handler based on `time.monotonic()`.
- The effective deadline is the smaller of the configured ERP query timeout and the remaining executor timeout from `context.timeout_seconds`.
- If the remaining executor budget is already exhausted, the handler returns `erp_query_timeout` without starting a query.
- If the SQLite deadline fires first, the handler returns a sanitized `erp_query_timeout` envelope.
- If the executor timeout fires first, Phase 3C returns `CANCELLED`.
- The executor timeout does not bound preflight validation and does not guarantee total `execute` call latency.

The existing step-count limit is not reused.

### 7.4 Empty results

- Search and list tools return success with an empty `items` list.
- Get-by-ID tools return `erp_not_found`.
- Inventory for an existing product with no rows returns success with an empty list.

### 7.5 Registration

A future registration helper can register definitions and handlers as a pair, but Phase 3D implementation must not register ERP tools in application startup until separately approved.

## 8. Error Handling Model

| Condition | Code | Category | Recoverable | Retryable |
|---|---|---|---|---|
| Phase 3C schema validation | `invalid_arguments` | `VALIDATION` | Yes | No |
| Handler semantic validation | `erp_invalid_arguments` | `VALIDATION` | Yes | No |
| Missing product/order/warehouse | `erp_not_found` | `NOT_FOUND` | Yes | No |
| Ambiguous lookup | `erp_ambiguous_result` | `VALIDATION` | Yes | No |
| Database failure | `erp_database_error` | `INTERNAL` | No | Yes |
| Query deadline exceeded | `erp_query_timeout` | `TIMEOUT` | No | Yes |
| Permission/security rejection | `erp_permission_denied` | `PERMISSION` | No | No |
| Unexpected handler failure | `erp_internal_error` | `INTERNAL` | No | No |
| Phase 3C executor timeout | none | n/a | n/a | n/a |

Phase 3C executor timeouts remain `CANCELLED` with no `ToolExecutionError`, as required by the existing contract.

Error details may include resource type, field names, or a bounded list of candidate summaries. They must not include argument values, raw SQL, database paths, stack traces, or secrets.

## 9. Testing and Verification Strategy

### 9.1 Test matrix

- Tool definitions and schemas:
  - Valid names and descriptions.
  - `type: "object"`, `additionalProperties: false`, required fields.
  - No unsupported schema keywords.
- Registry integration:
  - Registration, duplicate rejection, export definitions.
- Handler registration:
  - Every definition has a handler; missing/duplicate handler behavior.
- Successful execution:
  - Product search, product detail, inventory, warehouses, low stock, sales order.
- Invalid arguments:
  - Missing required fields, wrong types, extra properties, blank query, invalid limit.
- Missing records:
  - Unknown product, order, or warehouse.
- Empty results:
  - Search/list tools return empty items successfully.
- Database errors:
  - Missing database, unreadable file, corrupt database, locked database.
- SQL injection attempts:
  - Quotes, comments, `OR 1=1`, `UNION`, `DROP`, `load_extension`, `ATTACH`, multiple statements.
- Read-only enforcement:
  - Direct INSERT, UPDATE, DELETE, and DDL attempts fail.
  - `PRAGMA query_only` and `mode=ro` behavior verified.
- Output serialization:
  - JSON-compatible, ISO dates, finite numbers, no bytes or Decimal.
- Executor timeout:
  - Slow handler stub returns `CANCELLED` without changing Phase 3C.
- Integrity:
  - Production ERP SHA-256 before and after.
  - `PRAGMA integrity_check`.
  - No default agent database created.

### 9.2 Fixture strategy

Tests must not run destructive or mutation-attempt tests against the production ERP database. All write-rejection, malformed-data, injection, and corruption tests use a temporary fixture database created in a temporary directory. The production ERP database is opened read-only and hashed before and after the test run.

### 9.3 Verification commands for future implementation

```powershell
python -m unittest discover -s backend/tests -t .
Get-FileHash -Algorithm SHA256 backend\data\ifive_erp.db
python -c "from backend.main import app; print(len(app.routes))"
python -c "import backend.legacy.agent; print('legacy import OK')"
```

No Phase 3D tests were run because no Phase 3D implementation exists yet.

## 10. Reusability Considerations

- Define an `ErpReadAdapter` protocol and a SQLite implementation. Other ERP environments can provide different adapters with the same domain methods.
- Keep tool definitions in catalog modules and namespace names as `erp.<domain>.<action>`.
- Keep domain output shapes adapter-neutral.
- Configure ERP paths and adapter selection through environment/configuration, not tool arguments.
- Use tool versions and adapter metadata for future schema changes.
- Keep future write tools in a separate adapter and policy layer with approval requirements.
- Future LLM selection can use `ToolRegistry.export_definitions()` and convert definitions to the LLM tool format.
- Future audit and execution history should use the separate agent database, never the ERP database.
- Multiple catalogs can be registered independently as long as names do not collide.

## 11. Risks, Limitations, and Unresolved Decisions

### Risks and limitations

- SQLite read-only mode is strong at the connection level but not a complete multi-user authorization system.
- Existing read-write helper functions remain in the codebase and must not be used by ERP handlers.
- The existing SQL security layer is insufficient for arbitrary SQL and must not be treated as the Phase 3D boundary.
- Fixed queries can break if the ERP schema changes.
- Phase 3C lacks a typed business-error channel; the envelope plus `ErpToolRunner` adapter is a workaround.
- The executor timeout may leave a running read-only handler active until it finishes.
- Search wildcard handling and case sensitivity need explicit tests.
- No audit persistence exists in the MVP.

### Unresolved decisions

- Whether purchase-order detail should be added to the MVP.
- Whether any pricing or contact fields should be exposed under a future permission model.
- Whether production should use a read-only replica in addition to `mode=ro`.
- Exact future audit schema and retention policy.
- Whether customer search is needed once sales-order detail includes customer names.

## 12. Explicit Implementation Boundaries

Phase 3D design does not:

- Implement ERP handlers.
- Register ERP tools in application startup.
- Modify ERP APIs.
- Modify the SQL query pipeline or security implementation.
- Modify database schema or data.
- Modify Phase 3C implementation or tests.
- Add dependencies.
- Integrate Ollama or any LLM.
- Implement planning or autonomous execution loops.
- Modify frontend files.
- Start Phase 3E.
- Stage, commit, stash, reset, clean, or revert anything.

## 13. Proposed Implementation Sequence for Future Approval

1. Create the Phase 3D design document.
2. Add ERP configuration, read-only connection factory, adapter protocol, and SQLite adapter.
3. Add domain output models and fixed query constants.
4. Add `ErpReadService` with fixed parameterized operations.
5. Add the six tool definitions and handlers.
6. Add `ErpToolRunner` envelope/error adapter.
7. Add a registration helper without wiring it into application startup.
8. Add unit, integration, security, timeout, and integrity tests.
9. Run verification and record Phase 3D design completion in `Project_plan.md` only.
