# Phase 1 — Baseline Speed & Reliability Audit

**Project:** iFive AI ERP Agent  
**Audit date:** 2026-11-16  
**Repository:** `D:\Agent\Agent`  
**Branch / commit:** `main` / `dd34191`  
**Python:** 3.11.9  
**Mode:** Read-only inspection and analysis

## 1. Scope and Method

This audit inspected the active FastAPI + Agent + Ollama + SQLite ERP path only. No frontend, model configuration, database schema, ERP data, or application source was modified.

The only file created by this audit is this report.

Requested paths map to the active implementation as follows:

| Requested path | Actual active path |
|---|---|
| `backend/agent/orchestrator.py` | `backend/agent/orchestration/orchestrator.py` |
| `backend/agent/prompts.py` | `backend/agent/orchestration/prompts.py` |
| `backend/agent/service.py` | `backend/agent/services/agent_service.py` |
| `backend/agent/llm/client.py` | same |
| `backend/agent/llm/config.py` | same |
| `backend/agent/erp/` | same |
| `backend/main.py` | same |
| `backend/tests/` | same |

`backend/legacy/agent.py` is retained but is not used by the active FastAPI agent path.

---

## 2. Current Architecture and Request Flow

1. **Application startup**
   - `backend/main.py:26-51` creates one `ErpToolPlatform` and one `AgentService` for the process.
   - `ErpToolPlatform` owns the tool registry, executor, read service, and runner.

2. **HTTP entry point**
   - `backend/main.py:178-214` exposes `POST /api/agent/chat` and `POST /chat`.
   - `chat_endpoint` is a synchronous `def`, so FastAPI executes it in its threadpool.
   - It validates only that the message/question is non-empty (`backend/main.py:181-183`).
   - It ignores the optional `history` field (`backend/main.py:160`) and passes only the current text (`backend/main.py:194`).

3. **Agent service**
   - `backend/agent/services/agent_service.py:24-40` builds the LLM client and orchestrator.
   - `backend/agent/services/agent_service.py:42-48` delegates directly to `AgentOrchestrator.process_question`.

4. **Orchestrator**
   - `backend/agent/orchestration/orchestrator.py:366-610` implements the question flow:
     - classify grounding requirement via `_required_tool_evidence()` (`orchestrator.py:371`, helper at `63-86`);
     - call `OllamaClient.validate_availability()` (`orchestrator.py:383-385`);
     - build the system prompt and tool catalog (`orchestrator.py:411-418`);
     - enter the bounded decision loop (`orchestrator.py:427-431`);
     - call Ollama (`orchestrator.py:435`);
     - parse a JSON decision (`orchestrator.py:456-475`);
     - return a final answer (`orchestrator.py:477-496`) or execute a tool (`orchestrator.py:499-587`);
     - synthesize after budget exhaustion (`orchestrator.py:602-610`, method at `612-711`).

5. **Tool execution**
   - `AgentOrchestrator` → `ErpToolRunner.execute()` (`backend/agent/erp/runner.py:30-80`)
   - → `ToolExecutor.execute()` (`backend/agent/tools/executor.py:138-288`)
   - → ERP handler (`backend/agent/erp/handlers.py:212-238`)
   - → `ErpReadService` fixed parameterized queries (`backend/agent/erp/service.py`)
   - → read-only SQLite adapter (`backend/agent/erp/sqlite_adapter.py:66-115`).

6. **Response**
   - `backend/main.py:196-214` maps only the answer, tool-call summaries, status, model name, and error into `ChatResponse`.
   - Tool result payloads are not returned directly; they only survive if included in the answer or fallback text.

---

## 3. Current Ollama Call Count Per Question

The orchestrator uses one LLM call to select a tool and then another LLM call to synthesize the final answer.

| Question type | Ollama `/api/chat` calls | Notes |
|---|---:|---|
| Greeting / non-ERP question | 1 | One decision call returns `final_answer`. |
| Product count | 2 | Count tool succeeds, then a second call is made even though the answer is deterministic. |
| Product listing / search | 2 | One tool call plus final-answer synthesis. |
| Product detail by ID | 2 | One tool call plus final-answer synthesis. |
| Inventory lookup by product ID | 2 | One tool call plus final-answer synthesis. |
| Inventory lookup by product name | 2–3 | May require product search, inventory lookup, then final answer. |
| Warehouse list | 2 | One tool call plus final-answer synthesis. |
| Low-stock list | 2 | One tool call plus final-answer synthesis. |
| Sales-order detail | 2 | One tool call plus final-answer synthesis. |
| Dispatch list / detail / by sales order | 2 | One tool call plus final-answer synthesis. |
| Question requiring `N` tool executions | `N + 1` | One decision per tool call plus one final answer. |
| Invalid JSON / unknown tool / duplicate call / unknown action | +1 per correction | Each corrective round is another LLM call. |
| Budget/round exhaustion | Up to `15 + 1` | `max_llm_rounds = max_tool_calls * 3` at `orchestrator.py:364`; synthesis adds one more call at `orchestrator.py:646`. |

Additionally, every question performs an HTTP `GET /api/tags` through `validate_availability()` (`orchestrator.py:383-385` → `backend/agent/llm/client.py:89-108`). This is not an inference call, but it is an extra network round trip and can block for the full LLM timeout.

---

## 4. Current Timeout and Token Settings

### 4.1 Ollama configuration

| Setting | Current value | Location |
|---|---|---|
| Base URL | `http://localhost:11434` | `backend/agent/llm/config.py:7` |
| Model | `llama3.2` | `backend/agent/llm/config.py:8` |
| LLM timeout | `30.0` seconds (scalar) | `backend/agent/llm/config.py:9` |
| Environment override | `OLLAMA_TIMEOUT_SECONDS` | `backend/agent/llm/config.py:58-64` |
| Max tool calls | `5` | `backend/agent/llm/config.py:10` |
| HTTP client timeout | `httpx.Client(timeout=config.timeout_seconds)` | `backend/agent/llm/client.py:22` |
| Per-request timeout | scalar `timeout=req_timeout` | `backend/agent/llm/client.py:131-134` |
| Availability check timeout | same 30-second scalar | `client.py:89-108` |

### 4.2 Generation options

`OllamaClient.chat()` builds this payload at `backend/agent/llm/client.py:120-129`:

- `model`
- `messages`
- `stream: False`
- `format: "json"` when requested
- `options: {"temperature": 0.0}`

Current findings:

- **`num_predict` is not specified.**
- **`num_ctx` is not specified.**
- **`keep_alive` is not specified.**
- `temperature=0.0` is set by the orchestrator at `orchestrator.py:435` and `646`.
- Generation can continue until the model emits EOS or reaches the model's default context limit.

### 4.3 Orchestration limits

| Limit | Current value | Location |
|---|---|---|
| Max tool executions | `5` | `backend/agent/llm/config.py:10`, `orchestrator.py:360` |
| Max LLM rounds | `max_tool_calls * 3 = 15` | `orchestrator.py:361-364` |
| Tool executor default timeout | `None` | `backend/agent/erp/platform.py:49` |
| ERP SQLite query timeout | `5.0` seconds | `backend/agent/erp/config.py:17` |
| Fallback output truncation | `1200` characters per tool | `orchestrator.py:43`, `724-728` |

The tool executor has no default timeout (`platform.py:49`), but ERP queries are bounded by the read service deadline (`service.py:792-843`) and SQLite progress handler (`sqlite_adapter.py:108-112`).

---

## 5. Where Unnecessary LLM Calls Occur

### 5.1 Universal second call for ERP data questions

Every ERP data question pays for a second LLM call:

1. First call selects `action="call_tool"` at `orchestrator.py:435`.
2. Tool result is appended at `orchestrator.py:562-570`.
3. Loop continues and calls the LLM again to produce `action="final_answer"`.

There is no post-tool short-circuit even when the tool output already contains the complete answer.

### 5.2 Product count

`_required_tool_evidence()` maps product-count questions to `erp.products.count` (`orchestrator.py:79-84`).

`_grounded_answer()` already produces the authoritative deterministic answer from the tool output (`orchestrator.py:179-188`). The second LLM call is therefore unnecessary, and a timeout on that second call can discard a successful count (`orchestrator.py:436-444`).

### 5.3 Simple single-tool queries

The following currently need a second LLM call even though the answer is directly present in the tool result:

- product listing/search: `backend/agent/erp/service.py:399-467`
- product detail: `service.py:469-488`
- inventory lookup: `service.py:505-550`
- warehouse list: `service.py:552-571`
- low stock: `service.py:573-611`
- sales-order detail: `service.py:613-648`
- dispatch list/detail/by-order: `service.py:650-790`

### 5.4 Correction rounds

Each of the following adds another LLM round:

- invalid JSON: `orchestrator.py:456-475`
- unrecognized tool: `orchestrator.py:504-516`
- repeated identical call: `orchestrator.py:522-537`
- unknown action: `orchestrator.py:589-600`

Because pre-flight validation failures do not consume the tool budget (`orchestrator.py:547-548`), a model can consume up to 15 LLM rounds on invalid calls alone. This behavior is explicitly covered by `backend/tests/test_dispatch_regression.py:603-641`.

### 5.5 Budget-exhaustion synthesis

After the loop, `_synthesize_final_answer()` always calls the model once at `orchestrator.py:646`. For product count, the deterministic answer at `orchestrator.py:670-684` is only reached after that extra call.

### 5.6 Availability check

`validate_availability()` performs `GET /api/tags` on every question (`orchestrator.py:383-385`). This is a minor cost compared with inference, but it can consume the full 30-second timeout before any model call if Ollama is slow or unresponsive.

---

## 6. Where ERP Data Can Be Lost After Successful Tool Execution

### 6.1 Primary data-loss path

1. A tool succeeds.
2. `successful_outputs.append((tool_name, result.output))` executes at `orchestrator.py:562-563`.
3. The output is added to the message history at `orchestrator.py:564-570`.
4. The loop calls the LLM again at `orchestrator.py:435`.
5. If that call raises `LlmTimeoutError`:
   - `orchestrator.py:436-444` returns a generic timeout message.
   - `successful_outputs` is not used.
6. If that call raises another `LlmError`:
   - `orchestrator.py:445-453` returns a generic error message.
   - `successful_outputs` is not used.

`ToolCallSummary` only carries tool name, arguments, status, duration, and error (`backend/agent/orchestration/models.py:7-16`). It does not carry the ERP output. Therefore the successful data is completely absent from the API response.

This directly explains the reported loss of successful ERP results after a subsequent final-answer/synthesis timeout.

### 6.2 Where preservation already exists

- `_synthesize_final_answer()` catches failures at `orchestrator.py:651-652`.
- Product count is preserved deterministically at `orchestrator.py:670-684`.
- Required evidence is checked at `orchestrator.py:686-703`.
- `_fallback_answer()` renders `successful_outputs` at `orchestrator.py:713-743`.
- Dispatch/delivery caveat is included at `orchestrator.py:741-742`.

This preservation only applies on the budget-exhaustion/synthesis path, not on the normal post-tool LLM call.

### 6.3 Grounding can also suppress data

If the final answer lacks the required tool family, `_grounded_answer()` returns a generic error at `orchestrator.py:175-177` and `126-156`. This is intentional grounding, but it means successful but irrelevant tool data is not shown. The primary fix should target timeout/error preservation, not bypassing grounding.

### 6.4 Recommended preservation behavior

On LLM timeout or LLM error after at least one successful tool execution:

- use only `ToolExecutionStatus.SUCCEEDED` outputs;
- render only values from the verified `result.output`;
- never use partial model text or truncated JSON;
- preserve the dispatch/delivery caveat;
- preserve the authoritative product-count override;
- return an explicit partial/incomplete status and error code;
- keep tool summaries in the response;
- do not query the ERP directly from the orchestrator and do not introduce SQL.

---

## 7. Where Incorrect Tool Selection or Grounding Can Occur

### 7.1 LLM-based tool selection is inherently probabilistic

The model chooses among ten tools exposed in `backend/agent/erp/definitions.py:10-175`. Common ambiguity points:

- `erp.products.search` vs `erp.products.get` vs `erp.products.count`
- `erp.dispatches.list` vs `erp.dispatches.get` vs `erp.dispatches.by_sales_order`
- `erp.inventory.get` vs `erp.inventory.low_stock`
- `erp.warehouses.list` vs inventory-by-warehouse

The prompt attempts to disambiguate at `backend/agent/orchestration/prompts.py:22-48`, and tool descriptions repeat constraints at `definitions.py:12-16`, `56-58`, `112-174`. Incorrect choices are corrected through feedback (`orchestrator.py:307-335`, `504-537`), but each correction costs another LLM call.

### 7.2 Grounding classification uses a limited keyword heuristic

`_required_tool_evidence()` at `orchestrator.py:63-86` only recognizes specific terms:

- inventory, stock, warehouse
- sales order
- dispatch, shipment, delivered
- product, sku
- product count phrases

Examples that can bypass grounding entirely:

| Question | Classification | Risk |
|---|---|---|
| “What did we ship yesterday?” | `None` | No approved tool evidence required; model could answer from memory. |
| “Show SO001.” | `None` | Sales-order ID alone is not recognized. |
| “What is in the catalog?” | `None` | “Catalog” is not recognized as product intent. |
| “How much of PRD001 do we have?” | `None` | No stock/inventory term. |
| “List the items.” | `None` | “Item” is not recognized. |

When `_required_tool_evidence()` returns `None`, `_grounded_answer()` returns the model text unchanged at `orchestrator.py:172-173`. No tool is required, so hallucination prevention is weak for those phrasings.

### 7.3 Keyword order can create false negatives

`_required_tool_evidence()` checks inventory/stock before sales order:

- `orchestrator.py:72-76` checks inventory/stock/warehouse first.
- `orchestrator.py:75-76` checks “sales order” afterward.

Therefore a question such as “Show stock for sales order SO001” is classified as an inventory question. If the model correctly calls a sales-order tool, the result may be rejected as missing required inventory evidence.

### 7.4 Unsupported terms are broad

`_UNSUPPORTED_ERP_TERMS` at `orchestrator.py:45-60` includes broad words such as `supplier`, `price`, `invoice`, `payment`, and `quality`. Any question containing one of these terms is rejected as an unsupported capability even if part of the question could be answered by an approved read-only tool. This is a deliberate safety boundary, but it can produce false unsupported responses.

### 7.5 Argument normalization can silently change query scope

`normalize_tool_arguments()` at `orchestrator.py:262-304` drops values that cannot be coerced to the declared schema type. This prevents validation failures, but it can change semantics:

- an invalid `warehouse_id` value is dropped, so the handler may query all warehouses instead of the requested one;
- `limit="all"` is dropped, so the handler uses its default limit, possibly returning a truncated list;
- optional filters that fail type coercion are silently ignored.

The executor still rejects undeclared properties, but optional values are not surfaced as errors. This can produce a successful tool result that does not match the user's intended scope.

### 7.6 Grounding is family-level, not field-level

For non-count answers, `_grounded_answer()` only verifies that some tool in the required family succeeded (`orchestrator.py:103-111`, `175-190`). It then returns the model's answer unchanged at `orchestrator.py:190`.

Example: a successful `erp.warehouses.list` call establishes that the warehouse family is present, but the model could still invent an additional warehouse name and the answer would be accepted.

Only product count has field-level authoritative replacement (`orchestrator.py:179-188`). Other answers rely on the model's truthfulness. Deterministic renderers would reduce this risk.

### 7.7 Dispatch-specific selection risk

The prompt says a delivered-items question should use exactly one unfiltered `erp.dispatches.list` call (`prompts.py:30-35`). The model may instead:

- filter by status `delivered`, which returns zero rows because that status does not exist (`definitions.py:137-141`, `prompts.py:25`);
- call `erp.dispatches.get` without a real `dispatch_id`;
- call `erp.dispatches.by_sales_order` with an invented sales-order ID.

Feedback is emitted for these cases (`orchestrator.py:325-329`), and regression tests exist in `backend/tests/test_dispatch_regression.py`.

---

## 8. Prompt, Context, and Token Pressure

### 8.1 Prompt size

- System prompt template: `backend/agent/orchestration/prompts.py:6-66`.
- Catalog formatter: `prompts.py:69-94`.
- Ten tool definitions: `backend/agent/erp/definitions.py:10-175`.

The full prompt is roughly 6.8 KB before the catalog, plus the catalog and tool schemas. It is re-sent on every orchestration round.

### 8.2 Excessive output instructions

`prompts.py:61` asks for a “Comprehensive, grounded natural language answer” inside the decision JSON. This encourages long output even when the model is only selecting a tool.

`prompts.py:54-65` requires `thought`, `action`, `tool_name`, `arguments`, and `final_answer` in every decision. There is no rule that `final_answer` must be null when `action == "call_tool"`.

`format="json"` (`client.py:128-129`) enforces JSON syntax, not schema or maximum length. `ToolSelectionDecision` ignores extra fields (`backend/agent/llm/models.py:42-50`).

### 8.3 Tool output context growth

Successful output is serialized without a size cap at `orchestrator.py:564` and appended at `orchestrator.py:565-570`.

`_MAX_FALLBACK_OUTPUT_CHARS` only applies to the final fallback rendering (`orchestrator.py:43`, `724-728`); it does not cap model context.

Large payloads are possible:

- up to 50 products (`service.py:41`, `399-467`);
- up to 50 dispatches with up to 100 items each for `by_sales_order` (`service.py:232-233`, `740-790`).

This is the largest context-pressure risk and can cause slow prompt processing, context truncation, or request failure.

### 8.4 Conversation history and question length

- `ChatRequest.history` exists (`backend/main.py:160`) but is not used (`backend/main.py:194`).
- The user message has no maximum length (`backend/main.py:156-160`, `181-183`).

History is not currently a source of pressure, but unbounded messages are.

### 8.5 Recommended safe token limits

These are starting points to measure, not changes to apply without approval:

| Phase | Suggested `num_predict` | Rationale |
|---|---:|---|
| Tool decision | 160–192 | JSON envelope, brief thought, tool name, small arguments. Require `final_answer: null` on tool calls. |
| Final answer from tool data | 320–384 | Concise grounded answer; prefer deterministic rendering for large lists. |
| Budget-exhaustion synthesis | 384–512 | Only when deterministic fallback is not applicable. |

Values below roughly 128 risk truncating the JSON envelope itself.

### 8.6 JSON truncation handling

If `num_predict` is reached mid-response, Ollama may stop with incomplete JSON. `_clean_json_text()` (`orchestrator.py:193-214`) only strips fences and trims to the first/last brace; it cannot repair missing braces or truncated strings.

Safe handling should include:

- capture `done_reason` from the Ollama response;
- treat `done_reason == "length"` as truncation;
- do not trust a truncated `final_answer`, even if the JSON happens to parse;
- allow at most one corrective retry for malformed JSON;
- then use verified tool output or deterministic fallback.

The client currently parses only `total_duration`, `prompt_eval_count`, and `eval_count` (`client.py:151-164`). It does not parse `done_reason`, `load_duration`, `prompt_eval_duration`, or `eval_duration`.

---

## 9. Existing Deterministic ERP Answer Paths

### 9.1 Product count

- `_authoritative_product_count()` at `orchestrator.py:114-123`.
- `_grounded_answer()` returns the fixed count answer at `orchestrator.py:179-188`.
- `_synthesize_final_answer()` also applies the count override at `orchestrator.py:670-684`.

This is the strongest existing deterministic path. It still pays for an unnecessary second LLM call in the normal loop.

### 9.2 Budget-exhaustion fallback

- `_fallback_answer()` at `orchestrator.py:713-743`.
- It renders successful outputs as JSON, truncates each to 1200 characters, lists failed calls, and adds the dispatch/delivery note.
- It returns status `incomplete` at `orchestrator.py:705-711`.

This preserves data only when the budget/round limit is exhausted, not when the normal post-tool LLM call fails.

### 9.3 Dispatch/delivery caveat

- `_DELIVERY_SEMANTICS_NOTE` at `orchestrator.py:38-42`.
- Applied in fallback at `orchestrator.py:741-742`.
- Also explained in the system prompt at `prompts.py:22-36`.

### 9.4 What is missing

There are no deterministic renderers for:

- product listing/search;
- product detail;
- inventory lookup;
- warehouse list;
- low stock;
- sales-order detail;
- dispatch list/detail/by-order.

Adding them would remove the second LLM call for safe single-tool questions while preserving the LLM as the planner.

---

## 10. Timeout and Error-Handling Flow

### 10.1 Timeout path

- `validate_availability()`: `orchestrator.py:383-409`.
  - A `LlmTimeoutError` from `/api/tags` is caught by the generic `except Exception` at `403-408` and reported as `llm_initialization_error`, not a timeout-specific error.
- Normal decision/final-answer call: `orchestrator.py:435-453`.
  - `LlmTimeoutError` returns a generic timeout message and loses successful outputs.
- Budget-exhaustion synthesis: `orchestrator.py:646-652`.
  - The broad `except Exception` swallows timeout and parse failures; fallback may preserve data.

### 10.2 Delays are not distinguished

The current scalar 30-second timeout does not distinguish:

- **model load / cold start:** Ollama `load_duration`;
- **prompt processing / first token:** `prompt_eval_duration`, `prompt_eval_count`;
- **generation:** `eval_duration`, `eval_count`;
- **overall request:** `total_duration`.

`stream=False` (`client.py:123`) means there is no first-token event and no progress signal.

### 10.3 Recommended timeout strategy

Future, after approval:

1. Add phase-specific timeouts:
   - connect: 2–5 seconds;
   - decision: 30–45 seconds warm;
   - final answer: 30–45 seconds;
   - availability check: 2–5 seconds.
2. Add a per-question wall-clock deadline:
   - pass remaining time into `client.chat(timeout=...)`;
   - cap tool execution by the remaining budget;
   - stop and return verified partial data when the deadline expires.
3. Capture Ollama timing fields and `done_reason`.
4. Retry at most once for transient cold-start/model-load failures.
5. Do not retry synthesis repeatedly after timeout or truncation.
6. Cache or shorten Ollama availability checks without caching business data.

### 10.4 Streaming assessment

Streaming would not reduce CPU inference time.

- The decision phase needs a complete JSON object, so partial streaming does not help final parsing.
- Final-answer streaming would require API and frontend changes, which are prohibited in this phase.
- Internal streaming could improve first-token/idle-timeout detection later, but it is a lower priority than call reduction, token caps, and deterministic fallback.

**Recommendation:** defer streaming.

---

## 11. Tests and Coverage

### 11.1 Existing coverage

| Test file | Coverage |
|---|---|
| `backend/tests/test_llm_client.py` | Config defaults, URL normalization, health, model listing, chat success, connection errors, timeout errors, HTTP errors. |
| `backend/tests/test_agent_orchestrator.py` | Greetings, direct answers, product count grounding, missing evidence, failed evidence, unsupported domains, product listing, budget exhaustion, repeated calls, unknown tools, max calls, Ollama unavailable. |
| `backend/tests/test_business_questions.py` | Warehouses, low stock, product details, sales orders, dispatch/delivery semantics, prompt guarantees. |
| `backend/tests/test_dispatch_regression.py` | Dispatch argument normalization, handler envelopes, scripted Ollama flows, fallback preservation, budget counting, JSON failure handling, prompt guidance. |
| `backend/tests/test_chat_api.py` | API response contract, empty input, Ollama unavailable, uninitialized service, legacy ERP routes, dispatch tool registration. |
| `backend/tests/test_erp_*.py`, `test_tool_*.py`, `test_sql_security.py`, `backend/test_sql_security.py` | ERP service, runner, catalog, config, adapter, tool registry/executor/validation, SQL security, dispatch service. |
| `backend/tests/test_task_*.py`, `test_models.py`, `test_migrations.py`, `test_serialization.py`, `test_persistence_restart.py` | Task/state/persistence layers, not the active chat path. |

### 11.2 Coverage gaps

There are no tests for:

- successful tool result followed by LLM timeout or `LlmError`;
- exact `/api/chat` call counts for simple questions;
- `num_predict` payload values;
- `done_reason == "length"` truncation;
- global per-question deadlines;
- phase-specific connect/read timeouts;
- deterministic renderers for product/inventory/warehouse/sales-order/dispatch outputs;
- grounding for phrasings such as “catalog,” “SO001,” “shipped,” or “items”;
- silent argument dropping for optional filters;
- field-level hallucination inside a successfully used tool family;
- prompt size/prompt token regression.

### 11.3 Existing test expectations that may need review

Some tests assert exact model-generated text:

- `test_multiple_sequential_tool_calls` expects “350 free stock”.
- `test_delivery_answer_must_not_fabricate_delivery` expects “proof-of-delivery”.
- Several prompt tests assert exact phrases such as “between 1 and 50,” “NEVER invent or guess identifiers,” and “does not establish confirmed customer delivery.”

Deterministic rendering or prompt compaction must either preserve these phrases or update tests with project-owner approval.

### 11.4 Baseline test command

Existing project convention:

```powershell
python -m unittest discover -s backend/tests -t . -v
```

Do not run this as part of this read-only audit if it would create or modify project state. It is the recommended baseline command for the implementation phase.

---

## 12. ERP Grounding and Hallucination Prevention

### 12.1 Controls that work well

- Strict tool allowlist and schema validation:
  - `backend/agent/tools/registry.py`
  - `backend/agent/tools/validation.py`
  - `backend/agent/tools/executor.py:154-199`
  - `backend/agent/erp/handlers.py:212-238`
- Read-only, parameterized SQL:
  - `backend/agent/erp/service.py`
  - `backend/agent/erp/sqlite_adapter.py:99-115`
  - SQL validation at `sqlite_adapter.py:128-151`
- Result envelope validation:
  - `backend/agent/erp/runner.py:30-80`
- Required evidence families:
  - `orchestrator.py:63-111`
- Product-count authoritative replacement:
  - `orchestrator.py:114-123`, `179-188`
- Unsupported capability rejection:
  - `orchestrator.py:126-156`, `45-60`
- Prompt-injection defense:
  - `prompts.py:50-52`
- Dispatch/delivery semantic distinction:
  - `prompts.py:22-36`, `orchestrator.py:38-42`

### 12.2 Gaps

1. **Grounding classification is keyword-based and incomplete.**
   - Unknown phrasings return `None`, disabling the requirement for tool evidence.
2. **Grounding is family-level, not field-level.**
   - Once a tool family succeeds, the model's answer text is accepted unchanged for non-count tools (`orchestrator.py:190`).
3. **Optional argument dropping can change scope silently.**
   - `normalize_tool_arguments()` at `orchestrator.py:262-304`.
4. **No deterministic rendering for most verified results.**
   - This leaves more answer construction to the model than necessary.

Deterministic renderers would improve both speed and field-level grounding because they can format only verified fields. They must remain post-tool presentation helpers, not replacements for tool selection, validation, or read-only SQL controls.

---

## 13. Recommended Optimization Order

### Priority 1 — Preserve successful results after LLM timeout/error

- **Impact:** very high
- **Risk:** low
- **Change area:** `orchestrator.py:436-453`
- **Behavior:** if a tool succeeded and the subsequent LLM call fails, return verified data through a deterministic fallback or partial-answer path instead of only a generic error.
- **Risk controls:** use only `SUCCEEDED` outputs; preserve grounding and dispatch caveat; keep existing response shape.

### Priority 2 — Add LLM timing and truncation instrumentation

- **Impact:** high
- **Risk:** low–medium
- **Change area:** `backend/agent/llm/client.py:110-166`, `backend/agent/llm/models.py`
- **Behavior:** parse `done_reason`, `load_duration`, `prompt_eval_duration`, `eval_duration`; add optional per-call `num_predict`.
- **Risk controls:** preserve existing defaults and tests; do not change model or model configuration.

### Priority 3 — Short-circuit product count

- **Impact:** high
- **Risk:** low
- **Change area:** `orchestrator.py:179-188`, `498-587`, `670-684`
- **Behavior:** after a successful `erp.products.count`, return the deterministic count immediately and skip the extra LLM call.
- **Risk controls:** preserve existing answer wording and authoritative override; add call-count tests.

### Priority 4 — Add a per-question deadline and phase-specific timeouts

- **Impact:** high
- **Risk:** medium
- **Change area:** `orchestrator.py:366-610`, `client.py:131-138`, `config.py`
- **Behavior:** bound total question time; distinguish decision/final/availability timeouts; use remaining time for tool execution.
- **Risk controls:** return verified partial data; do not retry synthesis repeatedly; verify behavior on CPU-only Ollama.

### Priority 5 — Add deterministic renderers for safe single-tool queries

- **Impact:** high for simple queries
- **Risk:** medium
- **Change area:** new module under `backend/agent/orchestration/` plus `orchestrator.py:498-587`
- **Start with:** product listing/search, warehouse list, low stock, inventory, sales order, dispatch.
- **Risk controls:** conservative simple-question predicate; fall back to LLM for ambiguity, comparisons, calculations, or multi-tool needs; preserve truncation flags and dispatch caveat.

### Priority 6 — Reduce prompt and context pressure

- **Impact:** medium–high
- **Risk:** low–medium
- **Change area:** `prompts.py`, `orchestrator.py:564-570`
- **Behavior:** compact catalog, remove avoidable duplication, require concise output, cap/compact tool output sent to the model while preserving full verified output.
- **Risk controls:** keep all security/grounding phrases required by tests; never hide truncation; measure prompt token counts before changing `num_ctx`.

### Priority 7 — Cap corrective rounds separately

- **Impact:** medium
- **Risk:** low
- **Change area:** `orchestrator.py:361-364`, `456-475`, `504-537`
- **Behavior:** limit parse/validation correction attempts independently of tool executions.
- **Risk controls:** fall back to verified data after the cap; preserve existing budget tests.

### Priority 8 — Strengthen field-level grounding

- **Impact:** medium–high for correctness
- **Risk:** medium–high
- **Change area:** `orchestrator.py:103-190` and new renderers
- **Behavior:** verify that material claims come from tool output; prefer deterministic rendering for known tools.
- **Risk controls:** avoid false rejections; do not introduce model-authored SQL; keep read-only service and allowlist unchanged.

### Priority 9 — Optional database micro-optimizations

- **Impact:** low relative to LLM latency
- **Risk:** low
- **Change area:** `backend/agent/erp/service.py:740-790`
- **Behavior:** reduce the N+1 query pattern for `erp.dispatches.by_sales_order`; consider connection reuse.
- **Risk controls:** preserve parameterized SQL, read-only access, deadlines, and existing result contracts.

---

## 14. Risks of Each Proposed Change

| Proposed change | Main risks | Mitigations |
|---|---|---|
| Preserve results on LLM failure | Returning partial data as if complete; changing status semantics; frontend expectations | Use explicit `incomplete`/partial status; include verified data only; keep existing `ChatResponse` fields; add API tests. |
| `num_predict` limits | Truncated JSON; truncated final answer; over-aggressive limits | Capture `done_reason`; treat length stop as failure; one corrective retry; deterministic fallback; benchmark limits. |
| Timing instrumentation | Added response fields; logging sensitive data | Keep fields optional/internal; do not log full ERP records; preserve existing response contract. |
| Product-count short-circuit | Bypassing a needed synthesis step; changing answer wording | Count already has a deterministic authoritative path; preserve exact wording; test call counts and output. |
| Global deadline | Premature failures on slow CPU; partial answers; concurrent requests contending for CPU | Choose conservative budget; return verified partial data; measure p50/p95; consider request serialization later. |
| Deterministic renderers | Misclassifying a complex question; incomplete formatting; changing test expectations | Conservative single-tool predicate; fall back to LLM; preserve `truncated` and caveats; test each renderer. |
| Prompt compaction | Removing security rules; changing model behavior; breaking prompt regression tests | Keep required phrases; review diff against tests; run prompt-security tests. |
| Corrective-round cap | Fewer recovery attempts for malformed output | Cap only repeated invalid output; preserve one corrective attempt; use verified fallback after cap. |
| Field-level grounding | False rejection of valid answers; implementation complexity | Validate only against verified output fields; prefer renderers for known tools; keep model fallback when evidence is ambiguous. |
| Database micro-optimization | Changing query semantics; regressions under deadlines | Preserve SQL parameterization and read-only controls; run ERP service/security tests. |

---

## 15. Benchmarking Plan

### 15.1 Deterministic call-count benchmark

Use the existing fixture database (`backend/tests/erp_support.py`) and `httpx.MockTransport`:

- record the number of `/api/chat` requests;
- record request `options.num_predict`;
- record final answer/status;
- verify output against fixture data.

Fixed question set:

1. greeting
2. “How many products do we have?”
3. “List all products.”
4. “Which products are low in stock?”
5. “What is the inventory for PRD001?”
6. “List all warehouses.”
7. “Show sales order SO001.”
8. “Show dispatch DSP001.”
9. “Give me the list of elements that are delivered.”
10. an unsupported-domain question

### 15.2 Real local latency benchmark

Run the existing backend against local Ollama and execute each question 5–10 times. Report cold and warm runs separately.

Record:

- wall-clock latency;
- number of `/api/chat` calls;
- `total_duration`;
- `load_duration`;
- `prompt_eval_duration`;
- `prompt_eval_count`;
- `eval_duration`;
- `eval_count`;
- `done_reason`;
- tool `duration_ms`;
- final status/error.

Report p50 and p95. Track JSON parse failures, corrective rounds, and timeout counts.

### 15.3 Expected outcomes

- Simple queries: 2 LLM calls → 1 where deterministic rendering is safe.
- Product count: second call eliminated.
- Worst-case latency: bounded by a per-question deadline instead of up to 15 × 30 seconds plus synthesis.
- Generated tokens: reduced by phase-specific `num_predict`.
- Prompt processing: reduced by compact catalog and capped tool-output context.
- Reliability: no successful tool result lost after a later LLM timeout/error.

---

## 16. Files That Would Be Modified in a Future Implementation Phase

### Application files

- `backend/agent/orchestration/orchestrator.py`
- `backend/agent/orchestration/prompts.py`
- `backend/agent/llm/client.py`
- `backend/agent/llm/config.py`
- `backend/agent/llm/models.py`
- `backend/agent/services/agent_service.py`
- `backend/main.py` only if diagnostic response fields are intentionally exposed; otherwise keep the public API unchanged.

### Proposed new files

- `backend/agent/orchestration/deterministic_answers.py` (or equivalent renderer module)
- `backend/tests/test_orchestrator_performance.py` (or equivalent)

### Test files likely to change

- `backend/tests/test_llm_client.py`
- `backend/tests/test_agent_orchestrator.py`
- `backend/tests/test_business_questions.py`
- `backend/tests/test_chat_api.py`
- `backend/tests/test_dispatch_regression.py`

### Files that should not change in this optimization

- `backend/agent/erp/service.py`
- `backend/agent/erp/sqlite_adapter.py`
- `backend/agent/erp/handlers.py`
- `backend/agent/erp/runner.py`
- `backend/agent/tools/registry.py`
- `backend/agent/tools/executor.py`
- `backend/agent/tools/validation.py`
- `backend/legacy/agent.py`
- all frontend files
- model configuration
- database files/schema

---

## 17. Conclusion

The current system is secure in its ERP access path but slow and fragile in orchestration:

- Every ERP data question requires at least two Ollama calls.
- Product count already has a deterministic answer but still pays for a second call.
- `num_predict` is unset, so generation length is unbounded.
- A 30-second scalar timeout is used for all phases and cannot distinguish model load, prompt processing, and generation.
- Successful tool results are preserved only on the budget-exhaustion path; a timeout or error on the normal post-tool LLM call discards the verified data.
- Grounding is family-level for most tools, not field-level; keyword classification misses common phrasings.
- The prompt and tool-output context have duplication and no size caps.

The safest first steps are:

1. preserve verified tool results on LLM failure;
2. add timing/truncation instrumentation and per-phase token limits;
3. short-circuit product count;
4. add a per-question deadline;
5. add conservative deterministic renderers for simple single-tool queries.

No frontend, model configuration, database schema, or ERP data changes are required for these steps.
