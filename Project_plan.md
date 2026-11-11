# Autonomous ERP Agent Platform - Project Plan

## Phase 0 - Audit Findings (Completed)

### Current system
- ERP data: `backend/data/ifive_erp.db` (SQLite, 17 tables).
- Backend: FastAPI in `backend/main.py`; existing GET endpoints; no `POST /chat`.
- AI assistant: `backend/agent.py` (Ollama plus database tools) and the SQL pipeline under `backend/tools/`.
- Frontend: React/Vite; `AIAssistant.tsx` calls `POST /chat`, which does not exist.
- Seed data: 6 products, 12 inventory rows, 2 warehouses, 6 sales orders, 4 purchase orders, 3 dispatches, 6 dispatch items, 5 invoices.

### Key findings
- `backend/agent.py` failed to import from the repo root because it used `from tools.database`; this raised `ModuleNotFoundError`.
- Low-stock contradiction: the API/UI per-warehouse definition (`free_stock <= reorder_level`) returns 6 rows / 5 products, while the SQL prompt aggregate definition (`SUM(on_hand - reserved) < reorder_level`) returns 0 products.
- `backend/main.py` has no `POST /chat`, no CORS, no authentication, and no task persistence.
- `sql_security.py` rejects valid CTEs and accepts `load_extension`; `sql_executor.py` uses a step-count limit rather than a time-based timeout.
- `get_dispatch_issues` conflates quantity mismatches and barcode failures; `get_stock_by_product_name` is exact-match only.
- Legacy `agent.py` contains keyword routing and hardcoded prompt rules; it is preserved as legacy only.
- Frontend dependencies were not installed, so lint/build were not run.

### Inventory semantics decision (documentation only)
- Candidate authoritative definition: per-warehouse availability = `on_hand_qty - reserved_qty`; low stock when availability is `<= reorder_level`.
- A product-level rollup may exist only as an explicitly labeled reporting view; it must never silently drive replenishment alerts.
- No ERP business behavior was changed in Phase 1.

### Persistence decision (implemented in Phase 2)
- Use SQLAlchemy 2.x plus Alembic for agent operational storage.
- Store agent state in a separate agent database via `AGENT_DATABASE_URL`; the default is `backend/agent_data/agent.db`. Never mix agent internals with `backend/data/ifive_erp.db`.
- Alternatives considered: raw `sqlite3`, JSON files, and SQLModel.
- Phase 2 implements task and event persistence; approval and audit repositories remain deferred.

## Phase 1 - Task/State Foundation (Completed)

### Scope
- LLM-independent task models and lifecycle only.
- No planner, LLM calls, ERP tools, API routes, frontend changes, or database persistence.
- No new dependencies; the existing Pydantic 2 installation is used.

### Files created
- `backend/__init__.py`
- `backend/legacy/__init__.py`
- `backend/agent/__init__.py`
- `backend/agent/models.py` - `TaskStatus`, `TaskError`, `Action`, `ToolResult`, `VerificationResult`, `AgentTask`.
- `backend/agent/runtime/__init__.py`
- `backend/agent/runtime/state.py` - allowed-transition map, `TransitionError`, transition functions.
- `backend/agent/runtime/context.py` - `AgentState`, `ExecutionContext`.
- `backend/tests/__init__.py`
- `backend/tests/test_models.py`
- `backend/tests/test_task_state.py`
- `backend/tests/test_serialization.py`

### Files changed
- `backend/agent.py` moved to `backend/legacy/agent.py`; content preserved and only the database import path corrected to `backend.tools.database`.
- `backend/test_agent.py` legacy import updated to `backend.legacy.agent`.
- `Project_plan.md` updated with Phase 0 findings and Phase 1 progress.
- The move was verified with SHA-256 before and after; the hash matched before the one-line import correction.

### State machine
- `CREATED` -> `PLANNING` | `FAILED` | `CANCELLED`
- `PLANNING` -> `PLANNED` | `FAILED` | `CANCELLED`
- `PLANNED` -> `EXECUTING` | `PAUSED` | `FAILED` | `CANCELLED`
- `EXECUTING` -> `WAITING_APPROVAL` | `VERIFYING` | `PAUSED` | `FAILED` | `CANCELLED`
- `WAITING_APPROVAL` -> `EXECUTING` | `PAUSED` | `FAILED` | `CANCELLED`
- `PAUSED` -> exact `paused_from` state | `FAILED` | `CANCELLED`
- `VERIFYING` -> `COMPLETED` | `FAILED` | `CANCELLED`
- `COMPLETED`, `FAILED`, `CANCELLED` -> terminal, no outgoing transitions.

### Invariants
- Models are frozen; state changes occur only through explicit transition functions.
- Terminal states reject every transition, and failed transitions do not mutate the original task.
- `PAUSED` requires a valid `paused_from`; resume restores that exact state and fails safely when `paused_from` is missing or invalid.
- Completion is possible only from `VERIFYING` and requires a valid completion timestamp.
- Failure requires a `TaskError`.
- Transition timestamps must be timezone-aware and must not move backwards.
- Versions increment on every successful transition.
- Non-terminal tasks cannot have `completed_at`; only `FAILED` tasks may carry an error.

### Verification
- Phase 1 suite: `python -m unittest discover -s backend/tests -t . -v` -> 85 tests, OK.
- Baseline checks:
  - `python test_sql_security.py` from `backend` -> 11 passed, 0 failed.
  - `python test_tools.py` from `backend` -> exit 0.
  - `python backend/test_database.py` -> exit 0.
  - `python -m backend.tools.test_stock_aggregation` -> exit 0.
  - `python -m backend.tools.test_generated_sql` -> exit 0.
  - `python -m backend.tools.sql_executor` -> exit 0.
  - `python -m backend.tools.schema_context` -> exit 0.
  - `python backend/inspect_schema.py` -> exit 0.
  - `python test_local_ai.py` from `backend` -> exit 0.
  - `import backend.legacy.agent` -> exit 0.
  - New agent imports -> exit 0.
  - `from backend.main import app` -> 15 routes, exit 0.
- Not run: frontend lint/build (`node_modules` absent) and `backend/test_agent.py` (interactive).

### Guardrails
- No ERP database, ERP business logic, API route, or frontend changes.
- No staging, commit, stash, reset, or clean operations were performed.
- No customer-, product-, or warehouse-specific logic, intent routing, or business values were added to the new package.

## Phase 2 - Task Manager & Persistence (Completed)

### Scope
- Persist `AgentTask` state and lifecycle events in a separate agent database.
- Add repository and Task Manager layers around the Phase 1 state machine.
- Add SQLAlchemy 2.x ORM models and an Alembic migration.
- Deferred: approvals and audit repositories, API, frontend, planner, LLM calls, tool execution, and autonomous loop.

### Dependencies
- Installed and added to `requirements.txt`: `SQLAlchemy>=2.0,<3.0`, `alembic>=1.13,<2.0`.
- Verified installed versions: SQLAlchemy `2.1.8`, Alembic `1.20.1`; Alembic also installed transitive `Mako 1.4.3` and `MarkupSafe 3.0.4`.
- Tests use the existing stdlib `unittest` runner; no pytest dependency was added.

### Files created
- `backend/agent/errors.py` - storage, missing-task, duplicate-task, and concurrency errors.
- `backend/agent/events.py` - `TaskEventType` and validated `TaskEvent`.
- `backend/agent/persistence/config.py` - `AGENT_DATABASE_URL` resolution and default agent DB path.
- `backend/agent/persistence/database.py` - engine/session factory and SQLite foreign-key enforcement.
- `backend/agent/persistence/types.py` - timezone-aware UTC datetime column type.
- `backend/agent/persistence/orm.py` - `AgentTaskRecord`, `AgentTaskEventRecord`, and schema constraints.
- `backend/agent/persistence/mappers.py` - domain/ORM conversions.
- `backend/agent/persistence/repository.py` - `TaskRepository`.
- `backend/agent/persistence/__init__.py` - persistence exports.
- `backend/agent/services/task_manager.py` - `TaskManager`.
- `backend/agent/services/__init__.py` - service exports.
- `backend/tests/support.py` - temporary database and test helpers.
- `backend/tests/test_task_repository.py` - repository, rollback, concurrency, and cascade tests.
- `backend/tests/test_task_manager.py` - manager lifecycle and event validation tests.
- `backend/tests/test_persistence_restart.py` - restart durability and database-config tests.
- `backend/tests/test_migrations.py` - Alembic upgrade/downgrade, schema, and usability tests.
- `alembic.ini` - Alembic configuration without a hardcoded database URL.
- `backend/migrations/env.py` - environment-driven migration runner.
- `backend/migrations/script.py.mako` - migration template.
- `backend/migrations/versions/0001_create_agent_task_tables.py` - initial task/event schema.

### Files changed
- `requirements.txt` - added SQLAlchemy and Alembic constraints.
- `.gitignore` - added `backend/agent_data/`.
- `Project_plan.md` - recorded Phase 2 implementation and verification.

### Persistence model
- `agent_tasks` stores task identity, session, goal, status, lifecycle timestamps, pause source, counters, error JSON, metadata JSON, and an optimistic `version`.
- `agent_task_events` stores ordered lifecycle events with task version, status transition, timestamp, and JSON payload.
- SQLite foreign keys are enabled on every connection; deleting a task cascades to its events.
- Status and event values are stored as lowercase strings with explicit check constraints.
- The ORM attribute `task_metadata` maps to the database column `metadata` because `metadata` is reserved.

### Repository and Task Manager
- `TaskRepository` owns one transaction per operation and supports create/get/list/update-with-event/list-events.
- Create commits the task and `TASK_CREATED` event atomically; duplicate task IDs raise `DuplicateTaskError`.
- Transitions use `WHERE task_id = ? AND version = ?`; stale versions raise `ConcurrencyError` and do not write an event.
- Missing tasks raise `TaskNotFoundError`; event/task reference mismatches are rejected before persistence.
- `TaskManager` exposes create/get/list/transition/pause/resume/fail/complete/cancel/list-events.
- All lifecycle changes continue to use `backend/agent/runtime/state.py`; persistence does not duplicate the state machine.
- Event types distinguish create, generic transition, pause, resume, failure, completion, and cancellation; failure events include the serialized `TaskError`.

### Database and migrations
- Default database: `backend/agent_data/agent.db`, derived from the package path.
- Override: `AGENT_DATABASE_URL`; no hardcoded database URL exists in Alembic configuration.
- Initial migration creates both tables, checks, indexes, unique event ID constraint, and cascade foreign key.
- Alembic `check` reports no new upgrade operations against the ORM metadata.
- Verification did not create the default agent database file.

### Verification
- Full suite: `python -m unittest discover -s backend/tests -t . -v` -> 119 tests, OK (85 Phase 1 + 34 Phase 2).
- Phase 2 suite alone -> 34 tests, OK.
- Migration tests -> SQLite upgrade/downgrade and repository use pass; `alembic check` reports no new operations.
- `python test_sql_security.py` from `backend` -> 11 passed, 0 failed.
- These commands exited 0:
  - `python test_tools.py` from `backend`
  - `python backend/test_database.py`
  - `python -m backend.tools.test_stock_aggregation`
  - `python -m backend.tools.test_generated_sql`
  - `python -m backend.tools.sql_executor`
  - `python -m backend.tools.schema_context`
  - `python backend/inspect_schema.py`
  - `python test_local_ai.py` from `backend`
- `import backend.legacy.agent` and Phase 2 imports exited 0.
- `from backend.main import app` -> 15 routes.
- ERP database SHA-256 remains `23AB19DB0C475894CCE54101D44493E9AE2C9631632EB9AECA575F0F1E449C54`.
- Not run: frontend lint/build (`node_modules` absent) and `backend/test_agent.py` (interactive).

### Guardrails
- No ERP database, ERP schema/business logic, API route, frontend, or legacy agent behavior was changed.
- Pre-existing worktree changes, including modified tracked `.pyc` files, were left in place.
- No staging, commit, stash, reset, or clean operation was performed.
- No customer-, product-, or warehouse-specific logic, intent routing, or business values were added.

### Deferred
- Approval and audit repositories.
- API and frontend integration.
- Planner, LLM integration, tool registry/executor, verification engine, and autonomous loop.

## Phase 3A - Tool Contracts & Data Models (Completed)

### Scope
- Add reusable, typed tool definition and execution contracts.
- Keep tool execution models separate from task models and persistence.
- Deferred: tool registry, executor, policy system, tool persistence, API/frontend integration, planner, LLM calls, and autonomous loop.

### Files created
- `backend/agent/tools/__init__.py` - public tool-contract exports.
- `backend/agent/tools/contracts.py` - tool definition, request, status, error, and result models.
- `backend/tests/test_tool_contracts.py` - 60 focused contract tests.

### Files changed
- `Project_plan.md` - recorded Phase 3A implementation and verification.

### Contracts
- `ToolDefinition` describes a tool with a validated JSON-compatible input schema, optional version, and JSON-compatible metadata.
- `ToolExecutionRequest` carries an execution ID, tool name, JSON-compatible arguments, and metadata.
- `ToolExecutionStatus` covers pending, running, succeeded, failed, and cancelled states.
- `ToolExecutionError` subclasses the existing `TaskError`, defaults to `ErrorCategory.TOOL`, and restricts `details` to JSON-compatible values.
- `ToolExecutionResult` enforces state consistency between status, output, error, timestamps, and duration.
- Existing `Action`, `ToolResult`, `TaskError`, `TaskStatus`, and `ExecutionContext` models were preserved unchanged.
- Frozen Pydantic models are shallowly immutable: attributes cannot be reassigned, but nested dictionaries remain mutable. This limitation is documented in the contracts and covered by tests.

### Validation
- Tool names are lowercase identifiers with optional dot/underscore segments, 1-64 characters.
- Input schemas must declare `type="object"`; properties, required entries, and additional-properties structures are validated structurally.
- Required schema entries must be unique, nonblank, and backed by a `properties` definition.
- Metadata, arguments, output, and error details are JSON-compatible.
- Result validation rejects ambiguous states, including successful results with errors, failed results without errors, and pending/running results carrying terminal data.
- Dictionary defaults use independent `default_factory` containers.

### Verification
- Phase 3A suite: `python -m unittest backend.tests.test_tool_contracts -v` -> 60 tests, OK.
- Full suite: `python -m unittest discover -s backend/tests -t .` -> 179 tests, OK (119 existing + 60 Phase 3A).
- `import backend.legacy.agent` and tool-contract imports exited 0.
- `from backend.main import app` -> 15 routes.
- ERP database SHA-256 remains `23AB19DB0C475894CCE54101D44493E9AE2C9631632EB9AECA575F0F1E449C54`.
- No default agent database was created.
- No dependencies, migrations, persistence schema, API routes, frontend files, or legacy behavior changed.
- Not run: frontend lint/build (`node_modules` absent) and `backend/test_agent.py` (interactive).

### Guardrails
- No registry, executor, policy system, persistence, or autonomous loop was implemented.
- No customer-, product-, warehouse-, intent-routing, or ERP-specific business logic was added.
- Pre-existing worktree changes were left in place.
- No staging, commit, stash, reset, or clean operation was performed.

### Deferred
- Tool registry, executor, policy system, and tool-execution persistence.
- Task-to-tool correlation and historical execution storage.
- Full JSON Schema validation, if needed.
- API/frontend integration, planner, LLM integration, verification engine, and autonomous loop.

## Phase 3B - Dynamic Tool Registry (Completed)

### Scope
- Add an in-memory, thread-safe registry for validated `ToolDefinition` objects.
- Support registration, retrieval, existence checks, listing, unregistering, and serialized export.
- Deferred: tool executor, policies, approval workflow, LLM integration, tool persistence, autonomous loop, and ERP tool registration.

### Files created
- `backend/agent/tools/errors.py` - `ToolRegistryError`, `DuplicateToolError`, and `ToolNotFoundError`.
- `backend/agent/tools/registry.py` - thread-safe `ToolRegistry`.
- `backend/tests/test_tool_registry.py` - 17 focused registry tests.

### Files changed
- `backend/agent/tools/__init__.py` - exported the registry and its errors.
- `Project_plan.md` - recorded Phase 3B implementation and verification.

### Registry API
- `register(definition)` stores a deep copy and rejects duplicate names with `DuplicateToolError`.
- `get(name)` returns a deep copy or raises `ToolNotFoundError`.
- `list_tools()` returns deep copies sorted by tool name.
- `exists(name)` returns a boolean without raising.
- `unregister(name)` removes and returns a deep copy, or raises `ToolNotFoundError`.
- `export_definitions()` returns sorted, JSON-compatible dictionaries from `model_dump(mode="json")`.
- A `threading.RLock` guards all registry operations.
- Registry errors are separate from task/persistence errors and expose `tool_name`.

### Verification
- Phase 3B suite: `python -m unittest backend.tests.test_tool_registry -v` -> 17 tests, OK.
- Full suite: `python -m unittest discover -s backend/tests -t .` -> 196 tests, OK (179 existing + 17 Phase 3B).
- `import backend.legacy.agent` and registry imports exited 0.
- `from backend.main import app` -> 15 routes.
- ERP database SHA-256 remains `23AB19DB0C475894CCE54101D44493E9AE2C9631632EB9AECA575F0F1E449C54`.
- No default agent database was created.
- No dependencies, migrations, persistence changes, API routes, frontend files, or legacy behavior changed.
- Not run: frontend lint/build (`node_modules` absent) and `backend/test_agent.py` (interactive).

### Guardrails
- No tool executor, policy system, approval workflow, LLM integration, autonomous loop, or tool persistence was implemented.
- No ERP tools or business-specific data were registered or hardcoded.
- Pre-existing worktree changes were left in place.
- No staging, commit, stash, reset, or clean operation was performed.

### Deferred
- Tool executor, execution policies, and approval workflow.
- LLM integration and provider-specific tool schema adaptation.
- Tool persistence and task-to-tool execution history.
- ERP tool registration and API/frontend integration.

## Phase 3C - Tool Execution Engine (Completed)

### Scope
- This is the single authoritative Phase 3C record; it supersedes the earlier synchronous v1 description.
- Add bounded, in-process tool execution with handler registration and pre-flight validation.
- Run handlers on a configurable `ThreadPoolExecutor` with configurable default and per-execution timeouts.
- Keep `ToolDefinition` objects in `ToolRegistry` and handlers in `ToolExecutor`.
- Return `ToolExecutionResult` for every tool-level outcome, including pre-flight, handler-phase, and timeout outcomes.

### Files created
- `backend/agent/tools/executor.py` - thread-safe `ToolExecutor`, `ToolHandler`, bounded worker pool, timeout, and shutdown lifecycle.
- `backend/agent/tools/validation.py` - `ToolArgumentIssue` and `validate_arguments()`.
- `backend/tests/test_tool_validation.py` - 25 focused validation tests.
- `backend/tests/test_tool_executor.py` - 47 focused executor and lifecycle tests.

### Files changed
- `backend/agent/tools/contracts.py` - additively added `ToolExecutionContext`.
- `backend/agent/tools/errors.py` - added `ToolHandlerError`, `DuplicateHandlerError`, `HandlerNotFoundError`, and `InvalidToolSchemaError`.
- `backend/agent/tools/__init__.py` - exported the executor, context, validation API, and new errors.
- `Project_plan.md` - recorded the final Phase 3C implementation and verification.

### Public APIs
- `ToolExecutor(registry, *, max_workers=4, default_timeout=None, include_exception_messages=False)`.
- `register_handler(tool_name, handler)` rejects duplicate names with `DuplicateHandlerError`.
- `get_handler(tool_name)` returns a handler or raises `HandlerNotFoundError`.
- `has_handler(tool_name)` returns a boolean without raising.
- `unregister_handler(tool_name)` removes and returns a handler, or raises `HandlerNotFoundError`.
- `execute(request, timeout=_UNSET_TIMEOUT)` returns a terminal `ToolExecutionResult`.
- Omitted `timeout` inherits the executor default; explicit `None` means unlimited; a positive finite number overrides the default.
- `shutdown(wait=True)` stops new work and shuts down the worker pool; repeated calls are safe.
- `ToolHandler = Callable[[dict[str, JsonValue], ToolExecutionContext], Any]`.
- `ToolExecutionContext` exposes `execution_id`, `tool_name`, `started_at`, `timeout_seconds`/`timeout`, and `metadata`.
- `ToolArgumentIssue(path, message, keyword="validation")` is frozen and JSON-serializable.
- `validate_arguments(arguments, schema)` returns an empty list when valid, or a list of issues.
- Malformed schemas raise `InvalidToolSchemaError` instead of becoming unrestricted schemas.

### Execution behavior
- Handler registration and lookup use a `threading.RLock`; concurrent duplicate registration allows exactly one success.
- Handlers receive deep copies of request arguments and metadata through an immutable context.
- The worker pool is bounded by `max_workers`; queued work waits for an available worker.
- Timeout timing includes worker-queue waiting plus handler execution. It does not bound pre-flight validation and does not guarantee total `execute` call latency.
- A queued execution that times out before starting is cancelled with `Future.cancel()` and cannot execute later.
- A handler that has already started when its timeout expires may continue running and may produce side effects.
- Timeouts use the existing `ToolExecutionStatus.CANCELLED` contract: `output=None`, `error=None`, and a valid `finished_at`; timeout reasons are not encoded in an error.
- Success requires JSON-compatible output, including finite numbers and string-keyed objects.
- Failure output is always `None`.
- Pre-flight failures have `started_at=None`, `duration_ms=None`, and a `finished_at` timestamp.
- Handler-phase failures include `started_at`, `finished_at`, and non-negative `duration_ms`.
- Handler exceptions are caught as `Exception` only; `BaseException` subclasses are not swallowed.
- Exception messages are excluded by default. Opt-in inclusion is available through `include_exception_messages=True`.
- Error flags are conservative: only `invalid_arguments` sets `recoverable=True`; all Phase 3C errors leave `retryable=False`.
- `shutdown(wait=False)` returns without waiting for queued or running handlers; `shutdown(wait=True)` waits for them. Work submitted after shutdown raises `RuntimeError`.

### Error codes
- `tool_not_found` - missing registry definition; pre-flight; category `not_found`.
- `handler_not_found` - missing executor handler; pre-flight; category `not_found`.
- `invalid_arguments` - argument validation issues; pre-flight; category `validation`; recoverable, not retryable.
- `invalid_tool_schema` - malformed or unsupported schema structure; pre-flight; category `validation`.
- `handler_error` - handler raised `Exception`; handler-phase timing; category `tool`; generic message by default.
- `invalid_output` - handler returned a non-JSON-compatible value; handler-phase timing; category `tool`.
- Invalid-argument details contain issue path, keyword, and message only; argument values are never included.

### Validation limitations
- Supported subset: `required`, `properties`, `additionalProperties` as a boolean, basic JSON `type` values, and property-level `enum`.
- Nested object schemas are rejected; array item schemas are not validated.
- `additionalProperties` must be boolean. Object-valued additional-property schemas are rejected.
- Unsupported JSON Schema keywords such as `items`, `minLength`, `pattern`, `format`, `minimum`, `maximum`, `oneOf`, `anyOf`, `allOf`, and `$ref` are not enforced.
- This is not full JSON Schema support.
- Invalid schema structures fail with `InvalidToolSchemaError`; they never silently become unrestricted.

### Verification
- Phase 3C suite: `python -m unittest backend.tests.test_tool_validation backend.tests.test_tool_executor -v` -> 72 tests, OK (25 validation + 47 executor).
- Full suite: `python -m unittest discover -s backend/tests -t .` -> 268 tests, OK (196 existing + 72 Phase 3C).
- `import backend.legacy.agent` -> exit 0.
- `from backend.main import app` -> 15 routes.
- ERP database SHA-256 remains `23AB19DB0C475894CCE54101D44493E9AE2C9631632EB9AECA575F0F1E449C54`.
- No default agent database was created.
- No dependencies, migrations, persistence changes, API routes, frontend files, or existing Phase 1/2/3A/3B contract behavior changed.
- Not run: frontend lint/build (`node_modules` absent) and `backend/test_agent.py` (interactive).

### Guardrails
- Handlers execute in-process and are not sandboxed.
- Timeouts are best-effort cooperative boundaries; already-running Python handlers cannot be forcibly stopped safely.
- No ERP handlers, ERP business logic, LLM integration, planner, autonomous loop, approval/policy engine, chat endpoint, frontend integration, or execution persistence was implemented.
- Pre-existing worktree changes and untracked files were left in place.
- No staging, commit, stash, reset, clean, or revert operation was performed.

### Deferred
- Phase 3D and all later phases.
- Tool execution persistence and task-to-tool history.
- Execution policies, approval workflow, and external cancellation.
- ERP tool registration, LLM integration, planner, and API/frontend integration.
- Nested/full JSON Schema validation if later required.

## Phase 3D - Read-Only ERP Tool Integration Design (Design Completed)

### Scope
- Design a read-only ERP tool integration for the existing Phase 3C tool platform.
- The design phase was documentation only; no ERP handlers, services, tool registration, API changes, SQL pipeline changes, database changes, dependencies, LLM integration, or frontend changes were implemented during design.
- Phase 3D.1 foundation and Phase 3D.2 tool catalog, handlers, registration helper, and runner are complete; application-startup registration and later integration remain pending explicit approval.

### Design document
- `backend/agent/docs/phase_3d_erp_tool_integration_design.md`

### Design summary
- Six-tool MVP: `erp.products.search`, `erp.products.get`, `erp.inventory.get`, `erp.warehouses.list`, `erp.inventory.low_stock`, and `erp.sales_orders.get`.
- Dedicated `ErpReadService` and `SqliteErpReadAdapter` using fixed parameterized queries, explicit column projections, deterministic ordering, bounded limits, wildcard escaping, and read-only SQLite connections.
- `ErpToolRunner` translates handler business-error envelopes into the existing `ToolExecutionResult` and `ToolExecutionError` contracts without changing Phase 3C.
- Executor timeout remains the outer bound; the SQLite query deadline is a separate wall-clock inner bound.
- Safe ERP database path validation is configuration-only, fail-closed, and rejects the agent database path.
- Low-stock remains per warehouse: `(on_hand_qty - reserved_qty) <= reorder_level`.
- Sales-order outputs exclude financial fields, including unit prices, line totals, invoices, and payments.
- Destructive security tests must use temporary fixture databases only; the production ERP database is read-only and hash-verified.

### Files created
- `backend/agent/docs/phase_3d_erp_tool_integration_design.md` - approved Phase 3D read-only ERP tool integration design.

### Files changed
- `Project_plan.md` - recorded Phase 3D DESIGN completion and referenced the design document.

### Verification
- Design document exists at `backend/agent/docs/phase_3d_erp_tool_integration_design.md`.
- Documentation-only change: no backend code or tests were modified.
- ERP database SHA-256 remained `23AB19DB0C475894CCE54101D44493E9AE2C9631632EB9AECA575F0F1E449C54`.
- Phase 3C implementation and tests remain untouched.
- No ERP tools were registered, no application startup was changed, and no default agent database was created.
- No staging, commit, stash, reset, clean, or revert operation was performed.

### Guardrails
- No ERP handlers or services, tool registration, API changes, SQL security/query pipeline changes, database schema/data changes, dependency changes, LLM integration, autonomous loop, or frontend changes were made.
- No Phase 3E work was started.
- Pre-existing worktree changes and untracked files were preserved.

### Deferred
- Application-startup ERP tool registration and all later Phase 3D integration work, pending explicit approval.
- Phase 3E and all later phases.
- ERP tool registration in application startup, LLM-driven tool selection, write tools with approval policies, and execution audit persistence.

## Phase 3D.1 - Read-Only ERP Foundation (Completed)

### Scope
- Implemented the secure, reusable read-only ERP database foundation only.
- No tool definitions, handlers, runner, application-startup registration, API routes, frontend changes, LLM integration, planning loops, or Phase 3E work was added.
- Phase 3D.2 was pending explicit approval at the time of Phase 3D.1 completion and was completed in Phase 3D.2.

### Architecture implemented
- `ErpDatabaseConfig` loads `ERP_DATABASE_PATH` or the default `backend/data/ifive_erp.db`, resolves the path, requires an existing regular file, rejects the agent database path, and never creates a missing database.
- `ErpDatabaseConfig` also supports an additive `ERP_QUERY_TIMEOUT_SECONDS` setting with a default of 5 seconds.
- `ErpReadAdapter` is the low-level read protocol (`fetch_all` and `fetch_one`); `ErpReadService` owns fixed SQL, explicit projections, parameter binding, validation, row mapping, and domain errors.
- `SqliteErpReadAdapter` opens one `mode=ro` connection per query, enables `PRAGMA query_only=ON`, sets `PRAGMA trusted_schema=OFF`, disables extension loading, and uses a wall-clock `time.monotonic()` progress-handler deadline.
- `ErpReadService` implements product search, product detail, inventory lookup, warehouse listing, per-warehouse low-stock lookup, and sales-order detail.
- Pydantic output models expose only approved fields. Sales-order outputs exclude unit prices and all invoice/payment data; customer phone and product pricing fields are excluded.
- Product search escapes backslash, percent, and underscore before parameterized `LIKE ... ESCAPE` matching.
- List queries use deterministic ordering, bounded limits, and `limit + 1` fetching to compute truncation flags.

### Files created
- `backend/agent/erp/__init__.py`
- `backend/agent/erp/adapter.py`
- `backend/agent/erp/config.py`
- `backend/agent/erp/errors.py`
- `backend/agent/erp/models.py`
- `backend/agent/erp/service.py`
- `backend/agent/erp/sqlite_adapter.py`
- `backend/tests/erp_support.py`
- `backend/tests/test_erp_config.py`
- `backend/tests/test_erp_adapter.py`
- `backend/tests/test_erp_service.py`

### Files modified
- `Project_plan.md` - recorded Phase 3D.1 completion and current Phase 3D.2 status.

### Test commands and results
- `python -m unittest backend.tests.test_erp_config backend.tests.test_erp_adapter backend.tests.test_erp_service` - 61 tests passed.
- `python -m unittest discover -s backend/tests -t . -p "test_*.py"` - 329 tests passed.
- `python -c "import backend.legacy.agent; print('legacy import OK')"` - legacy import OK.
- `python -c "from backend.main import app; print('routes', len(app.routes))"` - 15 routes.
- `PRAGMA integrity_check` on the production ERP database - `ok`.

### Security checks performed
- Missing, empty, directory, and invalid ERP paths are rejected; the agent database path is rejected.
- A missing ERP database is never created; runtime read failures fail closed as sanitized `erp_database_error`.
- All ERP SQL is fixed and internal; no user/LLM SQL is accepted.
- The adapter rejects non-`SELECT` statements and multiple statements.
- Connections use `mode=ro`, `PRAGMA query_only=ON`, `PRAGMA trusted_schema=OFF`, and disabled extension loading.
- Tests confirm direct INSERT/write attempts and extension loading fail.
- No `SELECT *`, legacy read-write helpers, generic SQL executor, SQL generator, or legacy agent were used.
- Product-search wildcard injection is escaped and covered by tests.
- Output models exclude pricing, contact, invoice, payment, and other unapproved fields.
- Wall-clock query deadlines are covered with a slow recursive query.
- Destructive and write-denial tests use temporary fixture databases only.

### Verification and preservation
- Production ERP SHA-256 before: `23AB19DB0C475894CCE54101D44493E9AE2C9631632EB9AECA575F0F1E449C54`
- Production ERP SHA-256 after: `23AB19DB0C475894CCE54101D44493E9AE2C9631632EB9AECA575F0F1E449C54`
- No default agent database was created.
- Phase 3C implementation and tests were not modified; the existing Phase 3C files remain the same pre-existing untracked files.
- No staging, commit, stash, reset, clean, or revert operation was performed.

### Incomplete work and deviations
- At the time of Phase 3D.1 completion, Phase 3D.2 tool definitions, handlers, and `ErpToolRunner` were not implemented; they were completed in Phase 3D.2.
- No tool registration, startup wiring, API routes, frontend changes, LLM integration, or execution persistence were added.
- The only additive configuration beyond the design is `ERP_QUERY_TIMEOUT_SECONDS`, used to implement the configured wall-clock query deadline.
- No dependency changes were required.

## Phase 3D.2 - ERP Tool Catalog, Handlers, Registration, and Runner (Completed)

### Scope
- Implemented the six read-only ERP tool definitions, handlers, registration helper, and `ErpToolRunner` from the approved Phase 3D design.
- No application-startup registration, API routes, frontend changes, LLM integration, planning loop, execution persistence, write tools, approval workflow, or Phase 3D.3 work was added.
- Phase 3E and all later phases remain pending explicit approval.

### Architecture implemented
- `backend/agent/erp/definitions.py` defines the exact six MVP tools with strict `type: "object"`, `additionalProperties: false`, required-field declarations, version `1.0.0`, and `read_only: true` metadata.
- `backend/agent/erp/handlers.py` provides thin handlers that validate arguments against the Phase 3C supported schema subset, call only `ErpReadService`, pass the execution-context timeout to the service, and return internal success/error envelopes.
- Handler validation rejects missing required fields, wrong types, unknown arguments, SQL arguments, and semantic bounds; service-level errors are converted to sanitized ERP envelopes.
- Unexpected handler/service failures return a sanitized `erp_internal_error` envelope without raw exception text, database paths, SQL, or secrets.
- `backend/agent/erp/registration.py` provides `register_erp_tools()` and `ErpToolRegistration`. Registration registers all six definitions and handlers as a pair, preflights duplicate definitions/handlers, rolls back partial registration on failure, and never overwrites existing registrations.
- `ErpToolRegistration.unregister()` removes only the registered ERP tools and is idempotent; the registration also supports context-manager cleanup.
- `backend/agent/erp/runner.py` provides `ErpToolRunner.execute()`, which calls the Phase 3C executor, returns `FAILED`/`CANCELLED` results unchanged, translates success envelopes to tool data, translates business-error envelopes to typed `ToolExecutionError` results, and preserves execution IDs and timing fields.
- Malformed success/error envelopes fail closed as sanitized `erp_internal_error` `FAILED` results without exposing malformed output.
- Runner timeout behavior preserves Phase 3C semantics: omitted timeout inherits the executor default, explicit `None` means unlimited, and a positive finite value overrides the default. Executor timeouts remain `CANCELLED` with no error.
- ERP tools are not registered in application startup and are not imported by `backend/main.py`.

### Files created
- `backend/agent/erp/definitions.py`
- `backend/agent/erp/handlers.py`
- `backend/agent/erp/registration.py`
- `backend/agent/erp/runner.py`
- `backend/tests/test_erp_tool_catalog.py`
- `backend/tests/test_erp_tool_runner.py`

### Files modified
- `backend/agent/erp/__init__.py` - exported the new Phase 3D.2 catalog, handler, registration, and runner APIs.
- `Project_plan.md` - recorded Phase 3D.2 completion and current deferred scope.

### Test commands and results
- `python -m unittest backend.tests.test_erp_tool_catalog backend.tests.test_erp_tool_runner` - 41 tests passed.
- `python -m unittest discover -s backend/tests -t .` - 370 tests passed.
- `python -m unittest backend.tests.test_tool_contracts backend.tests.test_tool_executor backend.tests.test_tool_registry backend.tests.test_tool_validation` - 149 Phase 3C tests passed.
- `python -c "import backend.legacy.agent; print('legacy import ok')"` - legacy import OK.
- `python -c "from backend.main import app; print('routes', len(app.routes))"` - 15 routes.
- `PRAGMA integrity_check` on the production ERP database - `ok`.

### Security and behavior checks performed
- All six tools execute successfully through the runner against temporary fixture databases.
- Missing products, sales orders, and warehouses return typed `erp_not_found` results.
- Semantic invalid arguments return `erp_invalid_arguments`; Phase 3C schema failures return `invalid_arguments` unchanged.
- SQL arguments are rejected as unknown properties; SQL-injection text is treated as literal search text.
- Empty search/list results return successful empty payloads.
- Outputs are JSON-serializable and exclude pricing, contact, invoice, payment, and other unapproved fields.
- Business-error envelopes preserve typed categories, recoverability, retryability, and sanitized details.
- Malformed envelopes, invalid categories, non-boolean flags, extra envelope fields, and non-JSON details fail closed.
- Slow handlers return `CANCELLED` without an error and without changing Phase 3C behavior.
- Tests use temporary fixture databases only; no destructive operations were run against the production ERP database.

### Verification and preservation
- Production ERP SHA-256 before: `23AB19DB0C475894CCE54101D44493E9AE2C9631632EB9AECA575F0F1E449C54`
- Production ERP SHA-256 after: `23AB19DB0C475894CCE54101D44493E9AE2C9631632EB9AECA575F0F1E449C54`
- No default agent database was created.
- Phase 3C implementation and tests were not modified.
- No ERP tool registration was wired into application startup.
- No dependency changes were required.
- No staging, commit, stash, reset, clean, or revert operation was performed.

### Incomplete work and deviations
- Application-startup ERP tool registration remains intentionally unimplemented.
- Phase 3D.3, Phase 3E, LLM-driven tool selection, write tools, approval workflows, and execution audit persistence were not started.
- No implementation deviation from the approved Phase 3D.2 design was required.


## Phase 3E - Natural Language ERP AI Agent (Completed)

### Scope
- Implement local LLM client abstraction (`OllamaClient`, `LlmConfig`) supporting configurable URL (`OLLAMA_BASE_URL`), model name (`OLLAMA_MODEL`), timeout, and health/availability checks.
- Implement structured reasoning and tool orchestration engine (`AgentOrchestrator`) that connects natural-language user queries to the registered Phase 3D ERP tool catalog.
- Implement bounded orchestration loop with maximum tool calls (`AGENT_MAX_TOOL_CALLS`), repeated identical call detection, argument pre-flight validation, and sanitized error feedback.
- Implement grounded natural-language response generation adhering to strict business boundaries and anti-hallucination rules.
- Explicitly enforce the delivery/dispatch capability boundary: recognize that no dispatch/delivery tools are present in the approved read-only catalog, refrain from substituting unrelated datasets, and report capability requirements clearly.
- Provide a precise proposal for future read-only dispatch tools (`erp.dispatches.get`, `erp.dispatches.list`).
- Implement the chat API endpoint (`POST /api/agent/chat` and alias `POST /chat`) in `backend/main.py` while preserving all 15 existing ERP routes.
- Prevent arbitrary SQL generation, ERP write operations, or direct database access from the LLM.

### Files created
- `backend/agent/llm/__init__.py`
- `backend/agent/llm/config.py` - `LlmConfig` with environment variable loading and validation.
- `backend/agent/llm/errors.py` - `LlmError`, `LlmConnectionError`, `LlmModelNotFoundError`, `LlmTimeoutError`, `LlmResponseError`.
- `backend/agent/llm/models.py` - `ChatMessage`, `ChatRole`, `LLMResponse`, `ModelInfo`, `ToolSelectionDecision`.
- `backend/agent/llm/client.py` - `OllamaClient` with health check, model availability check, and JSON chat completion.
- `backend/agent/orchestration/__init__.py`
- `backend/agent/orchestration/models.py` - `AgentExecutionResult`, `ToolCallSummary`.
- `backend/agent/orchestration/prompts.py` - Dynamic tool catalog formatting, system prompt generation, prompt injection defenses, delivery capability boundary.
- `backend/agent/orchestration/orchestrator.py` - Bounded loop, repeated call detection, argument validation, tool execution through `ErpToolRunner`.
- `backend/agent/services/agent_service.py` - `AgentService` high-level service.
- `backend/tests/test_llm_client.py` - 14 tests for LLM config, client, mock transport, health, timeouts, errors.
- `backend/tests/test_agent_orchestrator.py` - 8 tests for tool selection, execution loop, repeated call blocking, max calls bound, unknown tools.
- `backend/tests/test_business_questions.py` - 5 tests for products, inventory, warehouses, sales orders, delivery capability gap.
- `backend/tests/test_chat_api.py` - 7 tests for `/api/agent/chat`, `/chat`, validation, 503 fallback, route preservation.

### Files modified
- `backend/agent/services/__init__.py` - exported `AgentService`.
- `backend/main.py` - added `AgentService` to application lifespan and registered `/api/agent/chat` and `/chat`.
- `Project_plan.md` - recorded Phase 3E implementation and verification.

### Test commands and results
- `python -m unittest backend.tests.test_llm_client` - 14 tests passed.
- `python -m unittest backend.tests.test_agent_orchestrator` - 8 tests passed.
- `python -m unittest backend.tests.test_business_questions` - 5 tests passed.
- `python -m unittest backend.tests.test_chat_api` - 7 tests passed.
- `python -m unittest discover -s backend/tests -t .` - 404 tests passed (370 existing + 34 Phase 3E).
- `python -m unittest backend.tests.test_tool_contracts backend.tests.test_tool_executor backend.tests.test_tool_registry backend.tests.test_tool_validation` - 149 Phase 3C tests passed.
- `python -m unittest backend.tests.test_erp_config backend.tests.test_erp_adapter backend.tests.test_erp_service backend.tests.test_erp_tool_catalog backend.tests.test_erp_tool_runner` - 102 Phase 3D tests passed.
- `python -c "import backend.legacy.agent; print('legacy import OK')"` - legacy import OK.
- `python -c "from backend.main import app; print(len(app.routes))"` - 17 routes (15 existing + 2 chat routes).
- `PRAGMA integrity_check` on the production ERP database - `ok`.

### Delivery and Dispatch Capability Findings & Proposal
- Inspection of `backend/data/ifive_erp.db` confirms tables `dispatches` and `dispatch_items` exist.
- However, the Phase 3D approved read-only MVP catalog only contains 6 tools (`erp.products.search`, `erp.products.get`, `erp.inventory.get`, `erp.warehouses.list`, `erp.inventory.low_stock`, `erp.sales_orders.get`).
- Sales orders indicate status ('Dispatched', 'Partially Dispatched') but do not prove item-level delivery or carrier confirmation.
- The agent explicitly declines to substitute sales orders or inventory as delivery confirmation.
- Proposal for Phase 3F / future read-only delivery tools:
  1. `erp.dispatches.get`: retrieves dispatch header and picked/dispatched item records by `dispatch_id` or `so_id`.
  2. `erp.dispatches.list`: lists dispatches filtered by status or date range.

### Security and behavior checks performed
- Local Ollama only; no cloud LLMs or API charges.
- Read-only execution; all ERP access flows through fixed parameterized queries via `ErpToolRunner`.
- Untrusted ERP content is handled as passive data; prompt injection within product descriptions or orders cannot redefine instructions.
- Infinite loops prevented via `AGENT_MAX_TOOL_CALLS` and repeated identical tool call detection.
- Production ERP database SHA-256 remained identical before and after test runs.
- No default agent database was created unexpectedly.

### Verification and preservation
- Production ERP SHA-256 before: `23AB19DB0C475894CCE54101D44493E9AE2C9631632EB9AECA575F0F1E449C54`
- Production ERP SHA-256 after: `23AB19DB0C475894CCE54101D44493E9AE2C9631632EB9AECA575F0F1E449C54`
- No staging, commit, stash, reset, clean, or revert operation was performed.
- Pre-existing worktree changes preserved.

### Incomplete work and deviations
- Write tools, approval workflows, task persistence for autonomous agent loops, and execution audit persistence were not started.
- Frontend development is managed separately.

## Phase 3F - Read-Only ERP Dispatch & Delivery Tools (Completed)

### Scope
- Extend the approved read-only ERP tool catalog with three dispatch tools: `erp.dispatches.get`, `erp.dispatches.list`, and `erp.dispatches.by_sales_order`.
- Enable the Phase 3E agent to answer dispatch questions with real `dispatches`/`dispatch_items` data while strictly distinguishing warehouse dispatch from confirmed customer delivery.
- No write tools, delivery-confirmation workflow, shipment creation, inventory adjustments, purchase-order tools, frontend changes, RAG, autonomous tasks, new LLM orchestration, arbitrary SQL, or cloud LLMs.
- Phase 3C execution semantics were not modified; the existing registry/executor/runner pipeline is reused unchanged.

### ERP dispatch schema findings (from `backend/data/ifive_erp.db`)
- `dispatches`: `dispatch_id` TEXT PRIMARY KEY; `so_id` TEXT NOT NULL -> `sales_orders(so_id)`; `dispatch_date` TEXT (nullable, `YYYY-MM-DD`); `carrier` TEXT (nullable); `tracking_number` TEXT (nullable); `status` TEXT NOT NULL with observed values `Dispatched` and `Partially Dispatched`.
- `dispatch_items`: `dispatch_item_id` TEXT PRIMARY KEY; `dispatch_id` TEXT NOT NULL -> `dispatches(dispatch_id)`; `product_id` TEXT NOT NULL -> `products(product_id)`; `picked_qty` INTEGER NOT NULL; `dispatched_qty` INTEGER NOT NULL; `barcode_verified` INTEGER NOT NULL DEFAULT 0 (0/1 boolean).
- Dispatched quantities are stored per item; partial dispatch is possible (DSP001/DI002: picked 100, dispatched 80 with dispatch status `Partially Dispatched`).
- Carrier and tracking numbers exist. Multiple dispatches per sales order are allowed by the schema (non-unique FK); current seed data has one dispatch per dispatched sales order (SO001, SO002, SO004).
- No delivered quantity, delivery receipt, proof-of-delivery, delivery date, or delivery confirmation exists anywhere in the schema. `barcode_verified` is a picking/packing verification, not customer delivery. No `Delivered` status exists in either `dispatches` or `sales_orders`.
- Conclusion: dispatch records represent warehouse dispatch (handover to carrier), NOT confirmed customer delivery. Sales-order status (`Dispatched`/`Partially Dispatched`) must never be used as delivery evidence.

### Implemented tools
1. `erp.dispatches.get` (v1.0.0, read-only) - input `{"dispatch_id": string}` (required); returns dispatch header (dispatch_id, so_id, dispatch_date, status, carrier, tracking_number) plus item-level details (dispatch_item_id, product_id, product_name, picked_qty, dispatched_qty, barcode_verified), `items_row_count`, `items_truncated`.
2. `erp.dispatches.list` (v1.0.0, read-only) - optional `limit` (integer, default 20, max 50), `so_id`, `status`, `carrier` (exact-match filters); returns `DispatchSummary` rows ordered by `dispatch_date DESC, dispatch_id ASC` with `row_count` and `truncated` (limit+1 fetching). No date filters (not required; ISO text dates are returned verbatim).
3. `erp.dispatches.by_sales_order` (v1.0.0, read-only) - input `{"so_id": string}` (required); verifies the sales order exists, returns up to 50 dispatches for that order with item-level dispatched quantities, `dispatches_row_count`, `dispatches_truncated`, and per-dispatch `items_row_count`/`items_truncated`.

### Architecture (unchanged pipeline)
`ErpToolDefinition` -> `ToolRegistry` -> `ErpToolRegistration` -> `ToolExecutor` -> `ErpToolRunner` -> `ErpReadService` -> `SqliteErpReadAdapter` -> ERP SQLite database. All dispatch SQL is fixed, explicitly projected, parameterized, deterministically ordered, and bounded. The `erp.dispatches.list` WHERE clause is composed only from fixed condition fragments; all values are bound parameters.

### Agent integration
- `backend/agent/orchestration/prompts.py` system prompt now documents: dispatch records exist (`erp.dispatches.get/list/by_sales_order`); dispatched quantity vs delivered quantity distinction; the ERP does not establish confirmed customer delivery; never fabricate delivery; never use sales order status alone as delivery evidence; for "delivered items" questions, use dispatch tools and state the dispatch-not-delivery limitation.
- The dynamic tool catalog automatically exposes the new tools to the LLM; no orchestrator code changes were required.

### Files created
- `backend/tests/test_dispatch_service.py` - 48 focused dispatch service tests (detail, list, filters, ordering, limits, truncation, by-sales-order, empty results, unknown IDs, invalid filters, output safety, read-only safety).

### Files modified
- `backend/agent/erp/models.py` - added `DispatchItemDetail`, `DispatchSummary`, `DispatchDetail`, `DispatchListResult`, `SalesOrderDispatchesResult`.
- `backend/agent/erp/service.py` - added `get_dispatch`, `list_dispatches`, `get_dispatches_by_sales_order` with fixed parameterized SQL, validation, and truncation flags; added `_DISPATCH_LIST_SQL`, `_DISPATCHES_BY_SO_SQL`, `_DISPATCH_ITEMS_SQL`, `_DISPATCH_DETAIL_SQL`, `_SALES_ORDER_EXISTS_SQL`.
- `backend/agent/erp/definitions.py` - added the three dispatch tool definitions (strict object schemas, `additionalProperties: false`, version 1.0.0, read-only metadata).
- `backend/agent/erp/handlers.py` - added `get_dispatch`, `list_dispatches`, `get_dispatches_by_sales_order` handlers mapped to `erp.dispatches.*`.
- `backend/agent/erp/__init__.py` - exported the dispatch models.
- `backend/tests/erp_support.py` - fixture schema/data now includes `dispatches` and `dispatch_items` tables with a partial-dispatch case.
- `backend/tests/test_erp_tool_catalog.py` - catalog expects 9 tools; dispatch handler envelope, not-found, invalid-argument, SQL-literal, sanitization, and JSON-serializability tests.
- `backend/tests/test_erp_tool_runner.py` - all-tools success test covers the three dispatch tools.
- `backend/tests/test_business_questions.py` - replaced the Phase 3E capability-gap test with Phase 3F dispatch behavior: delivered-elements question uses dispatch tools; all-dispatches, dispatch-detail, per-sales-order, unknown-dispatch questions; delivery-vs-dispatch safety; system prompt semantics tests.
- `backend/tests/test_chat_api.py` - platform registration exposes dispatch tools as read-only.
- `Project_plan.md` - this record.

### Test commands and results
- Phase 3F focused: `python -m unittest backend.tests.test_dispatch_service` -> 48 tests OK; `backend.tests.test_erp_tool_catalog` -> 35 OK; `backend.tests.test_erp_tool_runner` -> 15 OK; `backend.tests.test_business_questions` -> 13 OK; `backend.tests.test_chat_api` -> 8 OK.
- Full suite: `python -m unittest discover -s backend/tests -t .` -> 470 tests, OK (404 Phase 3E baseline + 66 new/updated Phase 3F tests).
- Phase 3C regression (contracts, executor, registry, validation) -> 149 tests OK.
- Phase 3D regression (config, adapter, service, catalog, runner) -> 111 tests OK.
- Phase 3E regression (llm client, orchestrator, business questions, chat API) -> 43 tests OK.
- Real production-DB tool run: `erp.dispatches.list` returned 3 dispatches; `erp.dispatches.get` DSP001 returned SO001/BlueDart/BD10001 with 2 items (100 and 80 dispatched); `erp.dispatches.by_sales_order` SO001 returned the dispatch with item quantities; combined carrier+status filter returned DSP003.
- `python demo_erp_tools.py` -> completes read-only, no ERP data modified.
- `import backend.legacy.agent` -> OK.
- `from backend.main import app` -> 17 routes (15 ERP + 2 chat, unchanged).
- `git diff --check` -> clean (exit 0).

### Security verification
- All dispatch queries are fixed SELECTs with explicit column projections; no `SELECT *`, no user/LLM SQL, no dynamic SQL text from untrusted values.
- Filters are exact-match (`=`) equality parameters; SQL-injection text is treated as a literal (returns empty result).
- Limits: default 20, maximum 50, minimum 1; invalid limits raise typed `erp_invalid_arguments`; limit+1 fetch computes `truncated`.
- Outputs exclude pricing, contact, invoice, payment, and other unapproved fields (covered by dump-shape tests).
- Read-only enforced at adapter level (mode=ro, `PRAGMA query_only=ON`, non-SELECT rejection, multiple-statement rejection); dispatch-scope tests confirm INSERT/UPDATE/DELETE/DROP rejection and unchanged fixture bytes after reads.
- Unexpected handler/service failures return sanitized `erp_internal_error` envelopes without paths, SQL, or secrets.
- Destructive tests use temporary fixture databases only.

### Environment note
- Mid-verification, Windows Application Control policy began blocking the SQLAlchemy 2.1.8 binary `_cache_key_cy.cp311-win_amd64.pyd` (`DLL load failed ... An Application Control policy has blocked this file`), breaking the persistence-dependent tests. Within the project's `SQLAlchemy>=2.0,<3.0` constraint, SQLAlchemy was reinstalled as 2.1.7 (different wheel binary), which loads normally; all persistence/migration tests then passed. No `requirements.txt` change was required.

### Verification and preservation
- Production ERP SHA-256 before: `23AB19DB0C475894CCE54101D44493E9AE2C9631632EB9AECA575F0F1E449C54`
- Production ERP SHA-256 after: `23AB19DB0C475894CCE54101D44493E9AE2C9631632EB9AECA575F0F1E449C54`
- `PRAGMA integrity_check` on the production ERP database -> `ok`.
- No default agent database was created (`backend/agent_data/` absent).
- A pre-existing trailing blank line at EOF in `backend/main.py` (from uncommitted Phase 3E worktree changes) was removed so `git diff --check` passes; no other behavior change.
- No staging, commit, stash, reset, clean, or revert operation was performed.
- Pre-existing worktree changes preserved.

### Remaining limitations and future work
- Dispatch status must not be treated as proof of customer delivery; the ERP has no delivery confirmation, POD, or delivery-date data. The agent answers "dispatched" and states this limitation explicitly.
- No date-range filters on `erp.dispatches.list` (not required for the approved scope); ISO date strings are returned for the LLM to reason about.
- `erp.dispatches.by_sales_order` caps at 50 dispatches and 100 items per dispatch with truncation flags rather than pagination.
- Delivery-confirmation workflow, shipment creation, write tools, inventory adjustments, purchase-order tools, frontend changes, RAG, autonomous background tasks, and execution audit persistence remain out of scope pending explicit approval.
