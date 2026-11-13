# Entire Project Report: iFive AI ERP Agent

## 1. Project Purpose

This repository is a full-stack ERP demonstration for **ABC Fasteners & Industrial Supplies**. It has two user-facing capabilities:

1. A React dashboard for products, inventory, sales, purchasing, dispatch, quality, and accounting views.
2. A local-AI ERP assistant that uses an Ollama model to select from approved, read-only ERP tools. It does not permit the model to write SQL or modify ERP data.

The ERP source of truth is the SQLite database `backend/data/ifive_erp.db`. Agent operational state, when task persistence is used, is intentionally separate from this ERP database.

## 2. Technology Stack

| Area | Technology |
|---|---|
| Frontend | React 19, TypeScript, Vite 8, Tailwind CSS 4 |
| Frontend libraries | React Router, Recharts, Lucide React |
| Backend | Python, FastAPI, Pydantic, HTTPX |
| ERP storage | SQLite |
| Agent persistence | SQLAlchemy 2 and Alembic |
| Local LLM | Ollama, default model `llama3.2` |
| Backend tests | Python `unittest` |

## 3. Architecture

### Conventional dashboard API

```text
React pages -> frontend/src/services/api.ts -> FastAPI routes in backend/main.py
    -> backend/tools/database.py -> backend/data/ifive_erp.db
```

The conventional routes return products, inventory, orders, dispatch/quality issues, and unpaid-invoice information. This older path uses direct SQLite helper functions.

### AI assistant flow

```text
AI Assistant page -> POST /chat -> AgentService -> AgentOrchestrator -> local Ollama
    -> ToolRegistry -> ToolExecutor -> ErpToolRunner -> ERP handlers
    -> ErpReadService -> SqliteErpReadAdapter -> ERP SQLite database
```

The AI path is deliberately constrained:

- The LLM selects only registered tools with validated JSON arguments.
- ERP queries are fixed, parameterized `SELECT` statements; the LLM never supplies SQL.
- Connections are opened with SQLite read-only mode, `query_only`, disabled extension loading, and query deadlines.
- Results expose selected business fields only. Sensitive price, payment, and contact fields are intentionally excluded from agent tools.
- The orchestration loop is bounded, rejects repeated identical calls, and has deterministic fallback output if the model fails to produce a final answer.
- Dispatch means handoff to a carrier at the warehouse. The system explicitly does **not** claim confirmed customer delivery because the database has no proof-of-delivery data.

## 4. Runtime Entry Points

| Command or URL | Purpose |
|---|---|
| `python -m uvicorn backend.main:app --reload` | Starts FastAPI on its usual Uvicorn port (8000 by default). |
| `npm run dev` from `frontend` | Starts Vite at `http://localhost:5173`. |
| `npm run build` from `frontend` | Type-checks and creates a production frontend build. |
| `npm run lint` from `frontend` | Runs Oxlint. |
| `python -m unittest discover -s backend/tests -t .` | Runs the maintained backend test suite. |
| `demo_erp_tools.py` | CLI demonstration of registered read-only ERP tools. |

The frontend's Vite configuration proxies `/api` to `http://127.0.0.1:8000`. The frontend API client defaults to the same backend URL but can be overridden with `VITE_API_BASE_URL`.

## 5. API Surface

`backend/main.py` defines the FastAPI application, CORS policy for the local Vite server, lifecycle setup/teardown, and these routes:

| Route | Purpose |
|---|---|
| `GET /` | API health/welcome response. |
| `GET /products` | All products. |
| `GET /products/{product_id}` | One product or HTTP 404. |
| `GET /inventory/{product_id}` | Inventory for one product. |
| `GET /inventory/alerts/low-stock` | Low-stock records. |
| `GET /sales/pending` | Pending sales orders. |
| `GET /purchase/pending` | Pending purchase orders. |
| `GET /dispatch/issues` | Dispatch exceptions. |
| `GET /quality/issues` | Quality exceptions. |
| `GET /accounting/unpaid` | Unpaid invoices. |
| `GET /accounting/invoices/{invoice_id}` | One invoice's outstanding amount or HTTP 404. |
| `POST /chat` | AI assistant endpoint. |
| `POST /api/agent/chat` | Alias for the AI assistant endpoint. |

The chat request accepts `message` or `question`, an optional `session_id`, and optional history. A non-empty question is required. The response includes the answer, model, overall status, error code when applicable, and tool-call summaries.

## 6. AI Tool Catalog

The application startup creates `ErpToolPlatform`, registers these nine read-only tools, and supplies them to the local agent:

| Tool | Work performed |
|---|---|
| `erp.products.search` | Finds products by approved product attributes. |
| `erp.products.get` | Retrieves one product's approved master data. |
| `erp.inventory.get` | Retrieves product inventory, optionally for one warehouse. |
| `erp.warehouses.list` | Lists warehouses. |
| `erp.inventory.low_stock` | Lists per-warehouse low-stock entries. |
| `erp.sales_orders.get` | Retrieves a sales order and ordered quantities. |
| `erp.dispatches.get` | Retrieves one dispatch and its picked/dispatched item quantities. |
| `erp.dispatches.list` | Lists dispatches with supported filters. |
| `erp.dispatches.by_sales_order` | Retrieves dispatches associated with a sales order. |

Low stock is defined per warehouse as `on_hand_qty - reserved_qty <= reorder_level`; it is not silently aggregated at product level.

## 7. Repository File Catalog

The following sections account for all authored, configuration, documentation, source, test, static-asset, and tracked binary-data files found in the project. Generated Python bytecode and installed npm packages are grouped in section 8 because they are not authored project logic.

### 7.1 Root files

| File | Work performed / significance |
|---|---|
| `.gitignore` | Excludes local/generated project artifacts, including the default agent persistence directory. |
| `README.md` | Minimal backend startup instruction. |
| `Project_plan.md` | Primary project history: phased design/implementation decisions, safeguards, test history, scope, and deferred work. Some early-phase statements are historical and superseded by later phases. |
| `requirements.txt` | Declares SQLAlchemy and Alembic constraints for agent persistence/migrations. Runtime imports also require FastAPI, Pydantic, HTTPX, and Uvicorn, which are not listed here. |
| `alembic.ini` | Alembic configuration; database URL is resolved by application environment/configuration rather than hardcoded here. |
| `demo_erp_tools.py` | Command-line demonstration that invokes the approved ERP tool platform. |

### 7.2 Backend application and legacy files

| File | Work performed / significance |
|---|---|
| `backend/__init__.py` | Marks the backend as a Python package. |
| `backend/main.py` | FastAPI application entry point; CORS, ERP tool platform lifecycle, conventional ERP endpoints, and chat request/response models/routes. |
| `backend/inspect_schema.py` | Utility for inspecting the ERP SQLite schema. |
| `backend/legacy/__init__.py` | Marks the legacy package. |
| `backend/legacy/agent.py` | Older Ollama/keyword-routing SQL agent retained for compatibility/reference. It is not the secure production tool path. |
| `backend/tools/database.py` | Older direct SQLite connection/query helpers used by the conventional GET endpoints. |
| `backend/tools/schema_context.py` | Extracts ERP schema context for the older text-to-SQL flow. |
| `backend/tools/sql_generator.py` | Generates SQL from natural-language questions in the legacy flow. |
| `backend/tools/sql_security.py` | Applies allowlist-oriented validation to legacy generated SQL. It is defense-in-depth only, not the AI tool security boundary. |
| `backend/tools/sql_executor.py` | Executes validated legacy read-only SQL and applies its legacy result/step limits. |
| `backend/tools/query_engine.py` | Coordinates legacy schema, generation, validation, and SQL execution. |

### 7.3 Agent domain, lifecycle, and persistence files

| File | Work performed / significance |
|---|---|
| `backend/agent/__init__.py` | Agent package marker/public package boundary. |
| `backend/agent/models.py` | Frozen Pydantic domain models for tasks, actions, results, verification, status, and errors. |
| `backend/agent/events.py` | Typed lifecycle-event definitions and event validation. |
| `backend/agent/errors.py` | Typed persistence errors: missing task, duplicate task, concurrency, and storage failures. |
| `backend/agent/runtime/__init__.py` | Runtime package marker. |
| `backend/agent/runtime/state.py` | Task state machine and valid lifecycle transitions. |
| `backend/agent/runtime/context.py` | Runtime execution state/context models. |
| `backend/agent/services/__init__.py` | Re-exports agent service APIs. |
| `backend/agent/services/task_manager.py` | Service layer for task creation, transition, pause/resume, failure/completion, cancellation, and events. |
| `backend/agent/services/agent_service.py` | High-level facade that combines the ERP platform, LLM client, and orchestrator for chat answers. |
| `backend/agent/persistence/__init__.py` | Re-exports persistence APIs. |
| `backend/agent/persistence/config.py` | Resolves `AGENT_DATABASE_URL` and the default separate agent database path. |
| `backend/agent/persistence/database.py` | Creates SQLAlchemy engine/session facilities and enables SQLite foreign keys. |
| `backend/agent/persistence/types.py` | SQLAlchemy type for UTC-aware datetime handling. |
| `backend/agent/persistence/orm.py` | ORM records, tables, constraints, and indexes for tasks/events. |
| `backend/agent/persistence/mappers.py` | Converts between domain models and ORM records. |
| `backend/agent/persistence/repository.py` | Transactional repository with optimistic concurrency and event persistence. |

### 7.4 Generic tool platform files

| File | Work performed / significance |
|---|---|
| `backend/agent/tools/__init__.py` | Re-exports tool-platform public APIs. |
| `backend/agent/tools/contracts.py` | Tool definitions, execution request/context/result/status/error contracts. |
| `backend/agent/tools/errors.py` | Registry, handler, and schema-specific error types. |
| `backend/agent/tools/registry.py` | Thread-safe in-memory registry for tool definitions. |
| `backend/agent/tools/validation.py` | Validates supported JSON-schema-subset tool arguments. |
| `backend/agent/tools/executor.py` | Bounded thread-pool tool execution, handler registration, preflight checks, timeout/cancellation handling, and sanitized execution failures. |

### 7.5 Secure ERP read integration files

| File | Work performed / significance |
|---|---|
| `backend/agent/erp/__init__.py` | Re-exports ERP models, services, and tool APIs. |
| `backend/agent/erp/adapter.py` | Protocol describing low-level ERP read operations. |
| `backend/agent/erp/config.py` | Validates ERP database path and query-timeout configuration from `ERP_DATABASE_PATH` and `ERP_QUERY_TIMEOUT_SECONDS`. |
| `backend/agent/erp/errors.py` | Sanitized ERP access/configuration/timeout/not-found/validation error types. |
| `backend/agent/erp/models.py` | Approved Pydantic output models for products, inventory, warehouses, sales orders, and dispatches. |
| `backend/agent/erp/sqlite_adapter.py` | Per-query SQLite read-only adapter; enforces `SELECT`-only access and wall-clock interruption deadlines. |
| `backend/agent/erp/service.py` | Fixed parameterized ERP queries, semantic validation, row mapping, limits, ordering, and truncation handling. |
| `backend/agent/erp/definitions.py` | Strict schemas and metadata for the nine approved read-only ERP tools. |
| `backend/agent/erp/handlers.py` | Thin handlers that call `ErpReadService` and return validated internal success/error envelopes. |
| `backend/agent/erp/registration.py` | Atomically registers/unregisters ERP definitions and handlers with the generic platform. |
| `backend/agent/erp/runner.py` | Converts ERP handler envelopes to generic tool execution results while preserving typed business errors. |
| `backend/agent/erp/platform.py` | Application-scoped composition root for ERP config, adapter, service, registry, executor, registration, runner, and shutdown. |

### 7.6 Local LLM and orchestration files

| File | Work performed / significance |
|---|---|
| `backend/agent/llm/__init__.py` | LLM package marker/exports. |
| `backend/agent/llm/config.py` | Loads and validates `OLLAMA_*` and maximum-tool-call configuration. |
| `backend/agent/llm/models.py` | Chat messages, model metadata, LLM responses, and tool-selection decision models. |
| `backend/agent/llm/errors.py` | Typed Ollama connection, model, timeout, and response errors. |
| `backend/agent/llm/client.py` | HTTPX client for Ollama health checks, installed model checks, and JSON chat completions. |
| `backend/agent/orchestration/__init__.py` | Orchestration package marker. |
| `backend/agent/orchestration/models.py` | Agent answer result and per-tool-call summary models. |
| `backend/agent/orchestration/prompts.py` | Builds dynamic tool catalog/system prompts and defines safety/capability instructions. |
| `backend/agent/orchestration/orchestrator.py` | Runs bounded LLM/tool loops, normalizes small-model argument mistakes, blocks repetition, feeds tool outcomes to the model, and produces grounded fallback output. |

### 7.7 Migrations and design documentation

| File | Work performed / significance |
|---|---|
| `backend/migrations/env.py` | Environment-aware Alembic migration runner. |
| `backend/migrations/script.py.mako` | Alembic template for future revision files. |
| `backend/migrations/versions/0001_create_agent_task_tables.py` | Creates agent task/event tables, constraints, indexes, and cascading foreign key. |
| `backend/agent/docs/phase_3d_erp_tool_integration_design.md` | Detailed design for the secure read-only ERP tool architecture, field allowlists, error model, risks, and test strategy. Its opening status is historical; later implementation exists. |

### 7.8 Backend tests and test-support files

| File | Work performed / significance |
|---|---|
| `backend/tests/__init__.py` | Marks maintained test suite as a Python package. |
| `backend/tests/support.py` | Temporary agent-persistence database fixtures/helpers. |
| `backend/tests/erp_support.py` | Temporary ERP SQLite schema/data fixtures for safe tests. |
| `backend/tests/test_models.py` | Tests task-domain model invariants. |
| `backend/tests/test_task_state.py` | Tests permitted/rejected lifecycle transitions. |
| `backend/tests/test_serialization.py` | Tests domain serialization. |
| `backend/tests/test_task_repository.py` | Tests transactions, task events, cascade behavior, and concurrency. |
| `backend/tests/test_task_manager.py` | Tests task-manager operations. |
| `backend/tests/test_persistence_restart.py` | Tests durability and configuration over restarts. |
| `backend/tests/test_migrations.py` | Tests Alembic upgrade/downgrade and schema usability. |
| `backend/tests/test_tool_contracts.py` | Tests generic tool contracts. |
| `backend/tests/test_tool_registry.py` | Tests registry lifecycle and thread safety. |
| `backend/tests/test_tool_validation.py` | Tests supported argument/schema validation. |
| `backend/tests/test_tool_executor.py` | Tests handlers, result conversion, timeouts, and shutdown. |
| `backend/tests/test_erp_config.py` | Tests ERP path and timeout configuration validation. |
| `backend/tests/test_erp_adapter.py` | Tests read-only adapter, SQL restrictions, deadlines, and sanitization. |
| `backend/tests/test_erp_service.py` | Tests product, inventory, warehouse, and sales-order service operations. |
| `backend/tests/test_dispatch_service.py` | Tests dispatch detail/list/by-sales-order service behavior. |
| `backend/tests/test_erp_tool_catalog.py` | Tests ERP definitions, handlers, registration, and envelope behavior. |
| `backend/tests/test_erp_tool_runner.py` | Tests envelope-to-generic-result conversion. |
| `backend/tests/test_llm_client.py` | Tests Ollama configuration/client behavior via mocks. |
| `backend/tests/test_agent_orchestrator.py` | Tests tool selection, loop bounds, unknown/repeated calls, and synthesis. |
| `backend/tests/test_business_questions.py` | Tests end-to-end business-question behavior and delivery limitations. |
| `backend/tests/test_chat_api.py` | Tests both chat routes, validation, unavailable-service behavior, and route preservation. |
| `backend/tests/test_dispatch_regression.py` | Regression coverage for dispatch-oriented answers and the dispatch-vs-delivery boundary. |
| `backend/test_agent.py` | Legacy/interactively oriented agent test script. |
| `backend/test_database.py` | Legacy direct database-helper smoke test. |
| `backend/test_local_ai.py` | Local Ollama connectivity test. |
| `backend/test_sql_security.py` | Legacy SQL-security test script. |
| `backend/test_tools.py` | Legacy database-tool smoke test. |
| `backend/tools/test_generated_sql.py` | Legacy generated-SQL behavior test. |
| `backend/tools/test_stock_aggregation.py` | Legacy stock-aggregation semantics test. |

### 7.9 ERP data file

| File | Work performed / significance |
|---|---|
| `backend/data/ifive_erp.db` | Binary SQLite seed ERP database. It contains the application business data and tables including products, inventory, warehouses, sales orders/items, purchase orders/items, dispatches/items, invoices, payments, quality inspections, and related masters. It is queried but should not be manually edited by application code. |

### 7.10 Frontend configuration and static files

| File | Work performed / significance |
|---|---|
| `frontend/README.md` | Frontend stack, commands, page inventory, API notes, and checks. Its statement that chat is pending is outdated because the backend now provides `/chat`. |
| `frontend/package.json` | npm package metadata, scripts, runtime dependencies, and development dependencies. |
| `frontend/package-lock.json` | npm-generated lockfile pinning the dependency tree for reproducible installation. |
| `frontend/vite.config.ts` | Vite React/Tailwind integration, local port, and API proxy configuration. |
| `frontend/tsconfig.json` | TypeScript project-reference root configuration. |
| `frontend/tsconfig.app.json` | TypeScript settings for browser application sources. |
| `frontend/tsconfig.node.json` | TypeScript settings for Vite/Node configuration files. |
| `frontend/.env.example` | Example `VITE_API_BASE_URL` configuration. |
| `frontend/.gitignore` | Ignores frontend local/build artifacts. |
| `frontend/.oxlintrc.json` | Oxlint rules/configuration. |
| `frontend/index.html` | Vite HTML shell containing the React mount node. |
| `frontend/public/favicon.svg` | Browser favicon asset. |
| `frontend/public/icons.svg` | Static SVG icon asset. |

### 7.11 Frontend application, data, types, and utilities

| File | Work performed / significance |
|---|---|
| `frontend/src/main.tsx` | React DOM bootstrap and global-style import. |
| `frontend/src/App.tsx` | Lazy-loaded React Router routes and global application layout. |
| `frontend/src/index.css` | Global CSS/Tailwind theme and shared visual styles. |
| `frontend/src/types/index.ts` | TypeScript contracts for ERP records, dashboard/chart values, and UI data. |
| `frontend/src/data/demo.ts` | Demo ERP records and derived dashboard metrics/chart datasets. |
| `frontend/src/lib/format.ts` | Shared currency, number, date, and percentage formatters. |
| `frontend/src/services/api.ts` | Typed fetch client for conventional ERP APIs and the chat endpoint; centralizes backend URL and HTTP error parsing. |

### 7.12 Frontend layout, shared UI, and dashboard components

| File | Work performed / significance |
|---|---|
| `frontend/src/components/layout/AppLayout.tsx` | Shared sidebar/topbar/outlet page shell. |
| `frontend/src/components/layout/Sidebar.tsx` | Responsive navigation menu. |
| `frontend/src/components/layout/Topbar.tsx` | Route-aware page title area and mobile menu control. |
| `frontend/src/components/ui/Card.tsx` | Reusable card and card-header components. |
| `frontend/src/components/ui/PageHeader.tsx` | Reusable heading/action wrapper. |
| `frontend/src/components/ui/ProgressBar.tsx` | Reusable progress display. |
| `frontend/src/components/ui/StatusBadge.tsx` | Reusable styled status label. |
| `frontend/src/components/dashboard/KpiCard.tsx` | KPI summary-card component. |
| `frontend/src/components/dashboard/SalesChart.tsx` | Recharts sales visualization. |
| `frontend/src/components/dashboard/InventoryChart.tsx` | Recharts inventory visualization. |
| `frontend/src/components/dashboard/ChartState.tsx` | Loading/empty-state rendering for charts. |
| `frontend/src/components/dashboard/AlertsPanel.tsx` | Dashboard alert list. |
| `frontend/src/components/dashboard/RecentSalesTable.tsx` | Recent sales summary table. |
| `frontend/src/components/dashboard/LowStockTable.tsx` | Low-stock summary table. |

### 7.13 Frontend page files

| File | Work performed / significance |
|---|---|
| `frontend/src/pages/Dashboard.tsx` | Dashboard page; renders KPIs, charts, alerts, recent sales, and low-stock information, with demo fallback data. |
| `frontend/src/pages/AIAssistant.tsx` | Stateful conversational UI that posts questions/history to `/chat` and displays responses. |
| `frontend/src/pages/Inventory.tsx` | Inventory overview with filters, pagination, warehouse coverage, and reorder information. |
| `frontend/src/pages/SalesOrders.tsx` | Sales-order table with filters and status presentation. |
| `frontend/src/pages/PurchaseOrders.tsx` | Purchase-order status, receipt, and delay presentation. |
| `frontend/src/pages/Dispatch.tsx` | Dispatch register and dispatch-exception display. |
| `frontend/src/pages/Quality.tsx` | Quality inspection/rejection display. |
| `frontend/src/pages/Accounting.tsx` | Invoice, collection, and outstanding-balance display. |
| `frontend/src/pages/Products.tsx` | Searchable product-catalog page. |

## 8. Generated, Dependency, and Binary Artifact Catalog

These files are present in the workspace but are not individually authored application modules:

| File group | Meaning |
|---|---|
| `frontend/node_modules/**` | Installed npm dependency source, type declarations, distributable bundles, licenses, and package metadata required by the frontend toolchain. Their exact contents are controlled by `frontend/package-lock.json`; they should not be manually documented or edited file-by-file. |
| `frontend/node_modules/.vite/**` when present | Vite-generated dependency optimization cache. |
| `backend/**/__pycache__/**/*.pyc` | CPython-generated bytecode caches corresponding to Python source modules and tests. They may be safely regenerated and are not source of truth. |
| `backend/data/ifive_erp.db` | Binary SQLite data file, documented separately in section 7.9 because it is required runtime business data rather than generated code. |
| `frontend/package-lock.json` | Generated lockfile, documented separately in section 7.10 because it is necessary for reproducible dependency resolution. |

## 9. Security and Operational Boundaries

- The AI tool path is read-only. No tool provides ERP writes, arbitrary SQL, dynamic table names, or a database-path argument.
- Agent tools use explicit column projections and omit product purchase/selling prices, customer phone numbers, invoices/payments, sales-order unit prices, and supplier contact information.
- The older `backend/tools/` SQL generator/security/executor path remains in the codebase for legacy behavior. It is not sufficient for arbitrary LLM SQL and should not be used as the secure agent boundary.
- The task persistence database is separate from the ERP database. Default agent persistence is ignored by Git.
- No authentication or authorization layer is visible in `backend/main.py`. The local CORS policy allows the frontend development origins only.
- Tool execution is in-process. Executor timeouts cancel queued work but cannot force-stop a Python handler that has already started.
- Frontend pages primarily use demo data; `api.ts` is prepared for conventional API calls, while the assistant page uses the chat API.

## 10. Current Scope and Gaps

Implemented:

- Read-only ERP query tools for products, inventory, warehouses, sales orders, and dispatches.
- Local Ollama availability checks, structured tool selection, bounded orchestration, and chat APIs.
- Dashboard/page UI and reusable frontend component system.
- Agent task lifecycle/persistence foundation and Alembic migration.
- Extensive maintained backend unit/integration coverage.

Not implemented or intentionally deferred:

- ERP write tools, approvals, workflow execution, and user authorization.
- Confirmed customer-delivery tracking or proof of delivery.
- Tool-execution audit persistence and autonomous task execution persistence.
- Cloud LLM support, RAG, generic LLM SQL access, and unrestricted SQL querying.
- Frontend automated tests. The repository contains backend tests but no frontend test suite.

## 11. Documentation Consistency Notes

`Project_plan.md` is a chronological implementation record, not just a current-state specification. Earlier sections correctly describe the state at that phase but are superseded by later sections. In particular, early references to a missing chat endpoint, six tools, or absent startup registration no longer reflect the implementation.

`frontend/README.md` likewise says chat is pending; this is stale. `backend/main.py` currently implements both `/chat` and `/api/agent/chat`, and `AIAssistant.tsx` uses the chat client.
