# Priority 6 — ERP Answer Reliability Audit Report

**Project:** iFive AI ERP Agent  
**Business:** ABC Fasteners & Industrial Supplies  
**Audit Scope:** Read-only ERP agent architecture, orchestration logic, prompt design, tool registration, database mapping, and reliability across 11 key user questions.  
**Date:** November 16, 2026  
**Status:** Audit Complete (No Source Modifications Performed)

---

## 1. Executive Summary

This audit evaluates the reliability, grounding enforcement, and tool-alignment of the iFive AI ERP Agent platform. Through rigorous inspection of `backend/agent/orchestration/orchestrator.py`, `backend/agent/orchestration/prompts.py`, `backend/agent/erp/`, `backend/agent/tools/`, and `backend/tests/`, we assessed how the system handles factual business questions, capability boundaries, data truncation, and LLM synthesis.

### Key Strengths
- **Programmatic Overrides:** For exact structural queries (such as product counts via `erp.products.count` and warehouse listings via `erp.warehouses.list`), the orchestrator bypasses LLM text generation entirely, rendering authoritative answers directly from validated tool outputs.
- **Strict Capability Gating:** Unsupported ERP domains (such as Purchase Orders, Invoices, Accounting, and Payments) are intercepted by `_required_tool_evidence` returning `()`, correctly rejecting ungrounded model generation with an `unsupported_capability` error.
- **Deterministic Fallbacks:** When LLM rounds or tool budgets are exhausted, `_fallback_answer` constructs a structured, truncated JSON payload of successfully retrieved tool results rather than allowing silent failure or fabrication.
- **Robust Schema Normalization:** `normalize_tool_arguments` safely coerces minor LLM formatting errors (e.g. stringified integers, null optionals) without burning tool-call budgets.

### Key Vulnerabilities & Risks
- **Ungrounded Meta-Questions (`requirement = None`):** Broad questions about the ERP as a whole (e.g., "Entire details about the ERP") do not trigger tool evidence enforcement (`requirement` evaluates to `None`), allowing the LLM to generate unverified, potentially fabricated descriptions.
- **Missing Customer-to-Sales-Order Indexing:** There is no registered tool to search sales orders by customer name (e.g., "Sri Venkateswara Engineering"). Consequently, customer-specific order queries lack direct tool pathways.
- **Hallucination of Un-tracked Attributes:** The ERP schema tracks warehouse `city` but not street addresses. Without programmatic field-level validation on synthesis, an LLM can hallucinate detailed street addresses.
- **Absence of Aggregate Analytics Tools:** Complex analytical questions (e.g., "Which warehouse has the lowest stock?") require cross-warehouse inventory aggregation that no single read-only tool currently computes, forcing the LLM to interpret low-stock subsets or estimate.

---

## 2. Question-by-Question Findings

### 1. Give me the list of dispatched items.
- **Correct approved ERP tool(s):** `erp.dispatches.list` followed by `erp.dispatches.get` (or `erp.dispatches.by_sales_order`) to retrieve item-level quantities.
- **Actual registered tool names & handler:** `erp.dispatches.list` (`ErpToolHandlers.list_dispatches`), `erp.dispatches.get` (`ErpToolHandlers.get_dispatch`), `erp.dispatches.by_sales_order` (`ErpToolHandlers.get_dispatches_by_sales_order`).
- **Actual database tables & fields used:** `dispatches` (`dispatch_id`, `so_id`, `dispatch_date`, `carrier`, `tracking_number`, `status`), `dispatch_items` (`dispatch_item_id`, `dispatch_id`, `product_id`, `picked_qty`, `dispatched_qty`, `barcode_verified`), joined with `products` (`product_name`).
- **Tool existence & registration:** Yes, all exist and are registered.
- **Tool output sufficiency:** `erp.dispatches.list` provides dispatch headers/summaries; item-level breakdown requires `erp.dispatches.get` or `erp.dispatches.by_sales_order`.
- **Orchestrator enforcement:** Enforced via `("erp.dispatches.",)` requirement prefix.
- **LLM behavior without execution:** Prevented by `_grounded_answer` checking `_has_required_evidence`.
- **Final answer grounding:** Grounded when both list and get/by_sales_order tools are invoked.
- **Clarification needed:** None.
- **Evaluation:** Correct when multi-step tool retrieval (list + get) is executed and dispatch/delivery semantics are observed.
- **Specific regression tests needed:** Test that list-to-detail dispatch item retrieval accurately presents dispatched quantities while noting the absence of confirmed customer delivery receipts.

### 2. Entire details about the ERP.
- **Correct approved ERP tool(s):** None (no single tool dumps the entire ERP; requires multiple domain tools or is out of scope).
- **Actual registered tool names & handler:** None.
- **Actual database tables & fields used:** None.
- **Tool existence & registration:** No such tool exists.
- **Tool output sufficiency:** N/A.
- **Orchestrator enforcement:** `_required_tool_evidence` returns `None` (non-factual/unrecognized category).
- **LLM behavior without execution:** The LLM is permitted to answer without tool execution because `requirement` is `None`.
- **Final answer grounding:** Ungrounded / model-generated.
- **Clarification needed:** Highly needed (clarify that the ERP is modular and ask which specific domain to inspect).
- **Evaluation:** Potentially fabricated because the LLM can hallucinate table counts, structural schemas, or features not present in the system.
- **Specific regression tests needed:** Test that broad meta-questions about the entire ERP trigger clarification or list available ERP capabilities rather than hallucinating system details.

### 3. Give me the list of all elements in the ERP.
- **Correct approved ERP tool(s):** None (ambiguous term "elements").
- **Actual registered tool names & handler:** None.
- **Actual database tables & fields used:** None.
- **Tool existence & registration:** None.
- **Tool output sufficiency:** N/A.
- **Orchestrator enforcement:** `_required_tool_evidence` returns `None`.
- **LLM behavior without execution:** Permitted without tool execution.
- **Final answer grounding:** Ungrounded.
- **Clarification needed:** Highly needed (clarify what "elements" refers to: products, warehouses, orders, etc.).
- **Evaluation:** Potentially fabricated due to ambiguity and lack of tool grounding enforcement.
- **Specific regression tests needed:** Test that ambiguous requests for "all elements" prompt the user for clarification.

### 4. Compare sales and order.
- **Correct approved ERP tool(s):** `erp.sales_orders.get` (for specific sales orders). No comparative analysis tool exists.
- **Actual registered tool names & handler:** `erp.sales_orders.get` (`ErpToolHandlers.get_sales_order`).
- **Actual database tables & fields used:** `sales_orders`, `sales_order_items`, `customers`.
- **Tool existence & registration:** `erp.sales_orders.get` exists, but no comparison tool exists.
- **Tool output sufficiency:** Insufficient for general comparison unless specific sales order IDs are provided.
- **Orchestrator enforcement:** Enforced via `("erp.sales_orders.",)` requirement.
- **LLM behavior without execution:** If no sales order ID is provided, tool calls fail or are skipped, resulting in a grounding failure error rather than fabrication.
- **Final answer grounding:** Grounding failure prevents unverified claims.
- **Clarification needed:** Yes (needs specific sales order IDs to compare).
- **Evaluation:** Incomplete/Error (correctly blocked from fabricating comparison without tool evidence).
- **Specific regression tests needed:** Test that general sales comparison queries without order IDs prompt for specific sales order identifiers.

### 5. List all warehouses.
- **Correct approved ERP tool(s):** `erp.warehouses.list`.
- **Actual registered tool names & handler:** `erp.warehouses.list` (`ErpToolHandlers.list_warehouses`).
- **Actual database tables & fields used:** `warehouses` (`warehouse_id`, `warehouse_name`, `city`).
- **Tool existence & registration:** Yes, exists and registered.
- **Tool output sufficiency:** Fully sufficient (`warehouse_id`, `warehouse_name`, `city`).
- **Orchestrator enforcement:** Enforced via `(_WAREHOUSE_LIST_TOOL,)`. Programmatically rendered by `_authoritative_warehouse_list`.
- **LLM behavior without execution:** Tool execution strictly required.
- **Final answer grounding:** 100% grounded (rendered directly by Python from tool output).
- **Clarification needed:** None.
- **Evaluation:** Correct.
- **Specific regression tests needed:** `test_question_list_all_warehouses` (already implemented).

### 6. Which warehouse has the lowest stock?
- **Correct approved ERP tool(s):** `erp.inventory.low_stock` (or inventory search). Note: No dedicated aggregate ranking tool exists for lowest total stock across warehouses.
- **Actual registered tool names & handler:** `erp.inventory.low_stock` (`ErpToolHandlers.list_low_stock`).
- **Actual database tables & fields used:** `inventory`, `products`, `warehouses`.
- **Tool existence & registration:** `erp.inventory.low_stock` exists, but warehouse stock aggregation/ranking does not.
- **Tool output sufficiency:** `low_stock` returns items at or below reorder level, not total inventory per warehouse.
- **Orchestrator enforcement:** Enforced via `("erp.inventory.", "erp.warehouses.")`.
- **LLM behavior without execution:** Tool execution required.
- **Final answerグレounding:** Partial / inferred. The LLM must reason over low-stock items or general inventory.
- **Clarification needed:** Yes, or introduction of a dedicated stock-ranking/aggregation tool.
- **Evaluation:** Incomplete or potentially fabricated if the LLM estimates lowest stock without comprehensive inventory aggregation.
- **Specific regression tests needed:** Test warehouse stock ranking queries to ensure they rely on retrieved inventory data and report limitations if aggregate stock is not fully computed.

### 7. What is the address of the main warehouse?
- **Correct approved ERP tool(s):** `erp.warehouses.list`.
- **Actual registered tool names & handler:** `erp.warehouses.list` (`ErpToolHandlers.list_warehouses`).
- **Actual database tables & fields used:** `warehouses` (`warehouse_id`, `warehouse_name`, `city`).
- **Tool existence & registration:** `erp.warehouses.list` exists.
- **Tool output sufficiency:** Returns `city` ("Chennai"), but NOT street addresses.
- **Orchestrator enforcement:** Enforced via inventory/warehouse requirement.
- **LLM behavior without execution:** Tool execution required.
- **Final answer grounding:** Grounded in `city` if stating Chennai, but potentially fabricated if the LLM invents a street address.
- **Clarification needed:** Yes (clarifying that street addresses are not tracked, only city location).
- **Evaluation:** Potentially fabricated if the model hallucinates street details not present in the database schema.
- **Specific regression tests needed:** Test warehouse address query verifies that only city location (`Chennai`) is reported and no street address is invented.

### 8. How much free stock do we have for Hex Bolt M10?
- **Correct approved ERP tool(s):** `erp.products.search` (to find product ID `PRD001`) + `erp.inventory.get` (for `PRD001`).
- **Actual registered tool names & handler:** `erp.products.search`, `erp.inventory.get`.
- **Actual database tables & fields used:** `products`, `inventory`, `warehouses`.
- **Tool existence & registration:** Yes, both exist and are registered.
- **Tool output sufficiency:** Fully sufficient (`on_hand_qty`, `reserved_qty`, `free_stock` computed as `on_hand_qty - reserved_qty`).
- **Orchestrator enforcement:** Enforced via product/inventory requirement.
- **LLM behavior without execution:** Tool execution required.
- **Final answer grounding:** Grounded in actual tool output.
- **Clarification needed:** None.
- **Evaluation:** Correct.
- **Specific regression tests needed:** Test free stock retrieval for Hex Bolt M10 verifies correct calculation across warehouses (`WH001`: 350, `WH002`: 160).

### 9. Which products are below their reorder level?
- **Correct approved ERP tool(s):** `erp.inventory.low_stock`.
- **Actual registered tool names & handler:** `erp.inventory.low_stock` (`ErpToolHandlers.list_low_stock`).
- **Actual database tables & fields used:** `inventory`, `products`, `warehouses`.
- **Tool existence & registration:** Yes, exists and registered.
- **Tool output sufficiency:** Fully sufficient.
- **Orchestrator enforcement:** Enforced via inventory requirement.
- **LLM behavior without execution:** Tool execution required.
- **Final answer grounding:** Grounded in tool output.
- **Clarification needed:** None.
- **Evaluation:** Correct (`test_question_low_stock_products`).
- **Specific regression tests needed:** `test_question_low_stock_products` (already implemented).

### 10. Show me pending sales orders for Sri Venkateswara Engineering.
- **Correct approved ERP tool(s):** `erp.sales_orders.get` (for specific order IDs). Note: No `erp.sales_orders.search` or customer-to-order mapping tool exists.
- **Actual registered tool names & handler:** Only `erp.sales_orders.get` (`so_id`).
- **Actual database tables & fields used:** `sales_orders`, `customers`, `sales_order_items`.
- **Tool existence & registration:** Sales order retrieval exists by ID (`SO001`), but customer name search/listing does not exist.
- **Tool output sufficiency:** Insufficient without knowing the sales order ID (`SO001`).
- **Orchestrator enforcement:** Enforced via `("erp.sales_orders.",)` requirement.
- **LLM behavior without execution:** Blocked from fabrication by grounding failure checks if tools fail or cannot be found.
- **Final answer grounding:** Grounding failure prevents unverified answers.
- **Clarification needed:** Yes (needs sales order ID or a customer sales order search tool).
- **Evaluation:** Incomplete / Tool limitation (correctly fails rather than fabricating without tool output).
- **Specific regression tests needed:** Test sales order queries by customer name when no search tool exists, verifying capability limitation messaging or requesting the sales order ID.

### 11. Which purchase orders are delayed?
- **Correct approved ERP tool(s):** None (Purchase Orders are unsupported/not yet implemented in read-only tools).
- **Actual registered tool names & handler:** None.
- **Actual database tables & fields used:** None.
- **Tool existence & registration:** Not registered.
- **Tool output sufficiency:** N/A.
- **Orchestrator enforcement:** Intercepted by `_UNSUPPORTED_ERP_TERMS` returning `()`.
- **LLM behavior without execution:** Blocked; returns `unsupported_capability` error.
- **Final answer grounding:** Bypasses LLM generation to return capability boundary error.
- **Clarification needed:** None (capability explanation provided).
- **Evaluation:** Correct capability gating.
- **Specific regression tests needed:** Test purchase order queries return `unsupported_capability` error.

---

## 3. Tool and Database Mapping

| Business Domain | Approved Tool Name | Handler Method | SQLite Tables | Key Fields | Grounding Enforcement |
|---|---|---|---|---|---|
| **Products** | `erp.products.search` | `search_products` | `products` | `product_id`, `sku`, `product_name`, `category`, `material`, `size`, `grade`, `unit` | `("erp.products.",)` |
| **Products** | `erp.products.get` | `get_product` | `products` | `product_id`, `reorder_level` | `("erp.products.",)` |
| **Products** | `erp.products.count` | `count_products` | `products` | `product_count` (exact match) | `(_PRODUCT_COUNT_TOOL,)` (Programmatic override) |
| **Inventory** | `erp.inventory.get` | `get_inventory` | `inventory`, `products`, `warehouses` | `on_hand_qty`, `reserved_qty`, `free_stock` | `("erp.inventory.", "erp.warehouses.")` |
| **Warehouses** | `erp.warehouses.list` | `list_warehouses` | `warehouses` | `warehouse_id`, `warehouse_name`, `city` | `(_WAREHOUSE_LIST_TOOL,)` (Programmatic override) |
| **Inventory** | `erp.inventory.low_stock` | `list_low_stock` | `inventory`, `products`, `warehouses` | `free_stock`, `reorder_level`, `low_stock` | `("erp.inventory.", "erp.warehouses.")` |
| **Sales Orders** | `erp.sales_orders.get` | `get_sales_order` | `sales_orders`, `sales_order_items`, `customers` | `so_id`, `customer_id`, `customer_name`, `status` | `("erp.sales_orders.",)` |
| **Dispatches** | `erp.dispatches.get` | `get_dispatch` | `dispatches`, `dispatch_items`, `products` | `dispatch_id`, `so_id`, `carrier`, `tracking_number`, `picked_qty`, `dispatched_qty` | `("erp.dispatches.",)` |
| **Dispatches** | `erp.dispatches.list` | `list_dispatches` | `dispatches` | `dispatch_id`, `so_id`, `status`, `carrier` | `("erp.dispatches.",)` |
| **Dispatches** | `erp.dispatches.by_sales_order` | `get_dispatches_by_sales_order` | `dispatches`, `dispatch_items` | `so_id`, `dispatches` | `("erp.dispatches.",)` |
| **Purchase Orders** | *None* | *None* | *None* (Unsupported) | *None* | `()` (`unsupported_capability`) |

---

## 4. Additional Investigations

1. **Required-Tool Grounding Detection (`_required_tool_evidence`):**
   - Implemented in `backend/agent/orchestration/orchestrator.py`. It inspects lowercase question strings for unsupported ERP terms (returns `()`), warehouse list phrases (returns `_WAREHOUSE_LIST_TOOL`), inventory/warehouse keywords, sales orders, dispatches, product counts, and general products.
   - Verified that questions matching these domains must have corresponding successful tool output; otherwise `_grounded_answer` rejects the final answer.

2. **Unsupported Tools / Domains Execution Results:**
   - When an unsupported domain (like purchase orders) is requested, `_required_tool_evidence` returns `()`. `_has_required_evidence` evaluates to `False`, triggering `_grounding_failure_answer` with status `"error"` and error `"unsupported_capability"`. Unsupported domains cannot produce completed/fabricated answers.

3. **Tool Outputs Passed into Final Synthesis:**
   - Successful tool outputs (`success.output`) are serialized to JSON strings and appended to conversation messages as user-role messages (`Tool {tool_name} output:\n{output_str}`). The LLM reads these messages during final synthesis.

4. **Claims Absent from Tool Outputs:**
   - Yes. Except for warehouse lists and product counts (which have deterministic Python overrides), the LLM generates the final answer text. Even with successful tool execution, the LLM can extrapolate or hallucinate details (such as delivery dates, condition notes, or street addresses) not present in the tool output JSON.

5. **SQL Results vs. Model-Generated Claims:**
   - Raw SQLite results are strictly encapsulated in `{"ok": True, "data": ...}` dictionaries. Model claims reside in natural language text. There is currently no token-level assertion verifying that every claim in `final_answer` maps directly to retrieved database fields, relying instead on system prompt instructions and grounding failure checks.

6. **Origin of "1235 products" Hypothesis:**
   - **Hypothesis/Finding:** "1235 products" does not originate from any actual ERP table or tool in the test database (where 5 fixture products exist). Any such count would be an ungrounded LLM hallucination. The orchestrator prevents this for product count questions by programmatically enforcing `erp.products.count` results via `_authoritative_product_count`.

7. **Source of Warehouse Address and Pending-Order Tracking Details:**
   - **Warehouse Address:** The `warehouses` table and `erp.warehouses.list` tool return `warehouse_id`, `warehouse_name`, and `city`. Street addresses are not tracked in the ERP; any street address reported is an LLM hallucination.
   - **Pending-Order Tracking:** Sales order status comes from `sales_orders.status` (e.g., `"Pending"` or `"Partially Dispatched"`). Dispatch tracking details come from `dispatches.tracking_number` and `dispatches.carrier`.

8. **Dispatch List and Free-Stock Data Alignment:**
   - **Dispatch List:** Directly queries `dispatches` table and matches fixture data (`DSP001`, `DSP002`).
   - **Free-Stock:** Computed directly in SQL via `(i.on_hand_qty - i.reserved_qty) AS free_stock`, ensuring mathematical alignment with underlying inventory table records.

---

## 5. Root Causes Ranked by Severity

1. **Severity 1 — Ungrounded Meta-Questions (`requirement = None`):** Broad questions about the ERP ("Entire details about the ERP", "List all elements") bypass tool evidence checks, leaving them entirely dependent on LLM parametric memory and prone to hallucination.
2. **Severity 2 — Missing Customer-to-Sales-Order Mapping Tools:** Queries asking for pending orders by customer name cannot be resolved efficiently without customer search or sales order list/filter tools, forcing reliance on ID guesswork.
3. **Severity 3 — Lack of Deterministic Renderers for Analytical Queries:** Complex questions (e.g., lowest stock warehouse) lack dedicated aggregation tools or deterministic Python formatters, risking LLM miscalculation or estimation.
4. **Severity 4 — Absence of Field-Level Hallucination Filters:** LLM-synthesized answers lack automated post-processing validation against allowed schema attributes (e.g., permitting fabricated street addresses when only cities exist).

---

## 6. Proposed Fixes Ranked by Priority

1. **Priority 1 — Enforce Capability/Tool Coverage for Meta-Questions:** Update `_required_tool_evidence` or add a meta-query requirement handler so that broad ERP inquiries either trigger a multi-domain summary tool call or provide a structured capability overview rather than returning `None`.
2. **Priority 2 — Implement Customer & Sales Order Search Tooling:** Add `erp.sales_orders.search` (supporting customer name or status filters) to bridge the gap between customer queries and sales order records.
3. **Priority 3 — Expand Programmatic Deterministic Renderers:** Implement Python-side authoritative formatting for inventory summaries and warehouse stock comparisons, mirroring `_authoritative_warehouse_list`.
4. **Priority 4 — Strict Schema Attribute Validation:** Add post-synthesis checks or prompt guardrails ensuring that entity attributes not present in tool outputs (such as street addresses) are explicitly noted as untracked.

---

## 7. Recommended Regression Tests

Add the following unit test cases to `backend/tests/test_business_questions.py`:
1. `test_question_entire_erp_details_prompts_clarification_or_capability`
2. `test_question_warehouse_address_reports_city_only_without_hallucinating_street`
3. `test_question_lowest_stock_warehouse_handles_missing_aggregate_tool_gracefully`
4. `test_question_sales_orders_by_customer_name_handling`

---

## 8. Explicit Distinction Between Verified Findings and Hypotheses

- **Verified Findings:** Database table schemas (`erp_support.py`), SQL query definitions (`service.py`), orchestrator grounding rules and evidence checks (`orchestrator.py`), system prompt instructions (`prompts.py`), and tool definitions (`definitions.py`) are verified facts confirmed via direct code inspection and test suites.
- **Hypotheses:** The potential for LLM hallucination of warehouse street addresses and "1235 products" is a behavioral hypothesis based on known LLM tendencies when faced with incomplete field coverage (`city` vs street address) or ungrounded meta-queries (`requirement = None`).
