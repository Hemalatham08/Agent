# RAG Retrieval Quality & Robustness (Phase 6)

This document describes the retrieval-quality work in Phase 6 of the
documentation-only RAG package. RAG remains **standalone** and is **not**
integrated into the active ERP agent.

## Objective

Improve retrieval quality and robustness using evidence-driven evaluation,
without changing ranking, guard safety, or corpus semantics, and without
regressing the golden metrics.

## Scope

Only these files were added or changed in Phase 6:

- `backend/agent/rag/evaluation.py` (new) — deterministic `QualityReport`,
  `CoverageReport`, failure taxonomy, and corpus-derived benchmark.
- `backend/agent/rag/chunking.py` — C1/C3: drop title-only chunks; single-source
  token accounting; O1: include document tags in searchable text; O2: drop
  navigation (`Related topics`) chunks.
- `backend/agent/rag/models.py` — O1: `KnowledgeChunk.tags` field.
- `backend/agent/rag/text.py` — C2: definition-verb stopwords (`mean`,
  `means`, `meaning`, `meant`).
- `backend/agent/rag/__init__.py` — export evaluation API; Phase 7 repaired
  missing `DiagnosedRetrieval` / `FailureKind` exports.
- `backend/tests/test_rag_quality.py` (new) — datasets and quality tests.
- `backend/tests/test_rag_diagnostics.py` — updated chunk-count expectations.
- `docs/rag/QUALITY.md` (this file).

No protected file was modified: `backend/main.py`,
`backend/agent/orchestrator.py`, `backend/agent/erp/**`,
`backend/agent/tools/**`, `frontend/**`, teammate tests, and shared
configuration are untouched. `guard.py` safety logic is untouched.

## Method

Evaluation is **document-level only**: assertions use document recall@k and
coverage bands, never raw BM25 scores or specific chunk IDs. Guard-limited
cases (ambiguous / blocked before retrieval) are tracked separately from
retrieval misses.

### Dev / holdout split

Paraphrase data is split into `PARAPHRASE_DEV` and `PARAPHRASE_HOLDOUT`.
Thresholds and code choices are made on dev; holdout is reported separately
and never tuned against.

## Failure analysis (read-only, pre-change)

Probing 70+ real queries against the shipped corpus (12 docs, 63 chunks
before changes) found:

1. **Guard over-blocking is the dominant failure** — not ranking. Of 58
   paraphrase / hard-negative / list probes, 26% never reached the index
   (11 ambiguous, 4 blocked). Retrieval itself answered 40/40 allowed
   paraphrases (recall@3 = 100%). Guard precision is tracked in a
   false-block ledger and deliberately **not** modified here (guard rules must
   not be weakened for retrieval scores).
2. **Title-only chunks pollute results** — 6 chunks contained only a document
   title (e.g. `"Purchase to Stock Workflow"`). They were returned as hits 24
   times; 15/72 golden hits (20.8%) had snippets under 60 characters.
3. **Hard-negative near-ties** — e.g. `what does item mean?` ranked the
   generic-`mean` FAQ page above the SKU page (rank 5); caused by the generic
   token `mean` (document frequency 4).
4. **Multi-document breadth limited by depth** — a 3-document question cannot
   be fully covered at the default `top_k=3`; covered at `top_k=5`.
5. **Metadata effectiveness** — aliases work (19/20 top-1); document `tags`
   were not indexed at all (tag queries returned zero results); navigation
   (`Related topics`) chunks added noise.
6. **No markdown tables** exist in the shipped corpus; 19 chunks contain list
   markers. Lists split cleanly; oversized tables can split mid-row (future
   proofing only).

## Changes

### C1 (essential): drop title-only chunks

`chunking.py` now drops sections whose only line is the document heading, so
they never become title-only chunks. The title remains in every chunk's
searchable text, so nothing is lost.

- Chunks: 63 → 57.
- Short (<60 char) golden snippets: 15/72 → 3/72 (4.2%).
- All golden metrics unchanged.

### C2 (essential): definition-verb stopwords

`text.py` adds `mean`, `means`, `meaning`, `meant` to `STOPWORDS` (search- and
index-side). This is the single change behind the `what does item mean?`
hard-negative fix (rank 5 → 1).

- Vocab: 381 → 380. Tokens: 2399 → 2391.
- All golden metrics unchanged.

### C3 (essential): single-source token accounting

`chunking.py` now builds the searchable string once (title + section +
summary + tags + aliases + body) and uses it for both `token_count` and
`searchable_text(chunk)`, so the two can never drift. `test_token_count_matches_searchable_text`
locks this in.

### O1 (kept): index document tags

`KnowledgeChunk` gains a `tags` field; `searchable_text` includes tags;
`chunk_document` populates `tags` from the document.

- Golden metrics: identical.
- Tag-probe top-1: 3/8 → 6/8; top-3: 5/8 → 6/8.
- Kept because all gates pass.

### O2 (kept): drop navigation chunks

`chunking.py` drops `Related topics` / `Related documentation` chunks (cross
references with no substantive content; targets are indexed separately).

- Chunks: 57 → 51.
- Short golden snippets: 3/72 → 0/71 (0%).
- All golden metrics unchanged.
- Kept because all gates pass.

## Datasets

All in `backend/tests/test_rag_quality.py`:

- `PARAPHRASE_DEV` (38) — natural paraphrases per document.
- `PARAPHRASE_HOLDOUT` (24) — reported separately, never tuned.
- `HARD_NEGATIVES` (7 strict) — trap doc must not outrank expected doc.
- `MULTI_DOC` (6) — questions spanning multiple documents.
- `LIST_CASES` (10) — enumeration queries requiring correct doc + list content.
- `AMBIGUOUS_LIVE_FACT` (20) — adversarial live-fact queries that must stay
  blocked or ambiguous.
- `FALSE_BLOCK_LEDGER` (12) — conceptual queries the guard currently rejects;
  may only shrink, never grow.

## Acceptance criteria & measured results

| Criterion | Before | After |
|---|---|---|
| Conceptual allow | 24/24 | 24/24 |
| Conceptual answer@3 | 24/24 | 24/24 |
| Conceptual MRR | 1.0000 | 1.0000 |
| Alias top-1 / top-3 | 19/20 / 20/20 | 19/20 / 20/20 |
| Alias end-to-end | 12/20 | 12/20 |
| Live-fact rejection | 12/12 | 12/12 |
| Allowed paraphrase recall@3 | 40/40 | 100% dev (37/37), 100% holdout (18/18) |
| Dev top-1 | 34/40 (85%) | 31/37 (83.8%) |
| Holdout top-1 | — | 17/18 (94.4%) |
| Strict hard-negative traps outranking expected | several | zero |
| Multi-document coverage at top_k=5 | partial | 100% |
| Title-only chunks | 6 | 0 |
| Short snippets (<60 chars) | 15/72 (20.8%) | 0/71 (0%) |
| Live-fact adversarial queries ALLOWED | n/a | 0 |

## Hard-negative ledger

Strict cases where the trap must not outrank the expected document:

- `what does item mean?` — trap `common-questions` → expected `product-sku`.
- `who signs off on an inventory adjustment?` — trap `reporting-overview` → expected `stock-adjustment`.
- `what does allocated mean?` — trap `sales-order-to-dispatch` → expected `dispatch-status`.
- `which table holds reserved quantity?` — trap `free-stock` → expected `core-tables`.
- `what does in transit mean?` — trap `sales-order-to-dispatch` → expected `dispatch-status`.
- `what is shrinkage?` — trap `common-questions` → expected `stock-adjustment`.
- `how are prices stored?` — trap `core-tables` → expected `product-catalogue`
  (guard-blocked; acceptable alternative noted).

Zero strict traps outrank expected documents after C2.

Cases judged **acceptable alternatives** (multiple docs legitimately answer; not strict failures):
- `how are prices stored?` — `product-catalogue` or `core-tables` (guard-blocked live-fact request).

## Multi-document coverage

Evaluated at `top_k=5`, all required documents must appear:

- free stock + stock table columns + sales allocation → `free-stock`, `core-tables`, `sales-order-to-dispatch`
- fulfilment documents + statuses → `sales-order-to-dispatch`, `dispatch-status`
- products + SKUs + catalogue → `product-sku`, `product-catalogue`
- goods receipts + stock storage → `purchase-to-stock`, `core-tables`
- reports + adjustments → `reporting-overview`, `stock-adjustment`
- shared master data → `system-overview`, `product-catalogue`

100% coverage at `top_k=5`. At the default `top_k=3`, depth limits coverage;
this is documented behaviour, not a bug. Default `top_k` is unchanged.

## Ambiguous-query safety

All 20 adversarial live-fact queries remain blocked or ambiguous (zero ALLOWED).
Golden live-fact rejection stays 12/12. Guard logic (`guard.py`) is untouched.

## Corpus coverage

- All 12 documents reachable at top-1 by title, summary, and first sentence.
- 50/51 chunks reachable in top-3 from the query bank (1 orphan: a product-count
  FAQ chunk whose terms are out-of-vocabulary).
- Out-of-vocabulary token types across 70+ queries: 12 (generic verbs plus
  content words such as `grouped`, `keep`, `reuse`, `tied`, `trigger`).
- No markdown tables; list sections split cleanly at item boundaries.

## Determinism

`QualityReport`, `CoverageReport`, `MetricResult`, and `FailureRecord` are
frozen, contain no timestamps or nondeterministic fields, and serialize to
deterministic JSON. Repeated evaluation runs produce identical reports.

## Non-goals (deferred)

- Guard precision changes (the largest remaining improvement; requires a
  separately approved phase with a 100% live-fact-rejection gate).
- Reopening the skipped `AliasTargetTests` / bare-alias guard coverage.
- Field-weighted BM25, `k1`/`b` tuning, adaptive per-document breadth.
- Row-aware table splitting, snippet fallback, synonym expansion.
- Persistent trace storage, telemetry, or web endpoints.
- Active ERP agent / orchestrator integration.

## Phase 7: Release Readiness (this release)

Phase 7 fixed release-evidence and API correctness without changing retrieval
behaviour, safety logic, or corpus content:

- **E1 exports:** `DiagnosedRetrieval` and `FailureKind` are now exported from
  `backend.agent.rag`; `from backend.agent.rag import *` succeeds.
- **E2/E3 evaluation:** `evaluate_quality` uses per-dataset denominators, rates
  stay within [0, 1], `QualityMetric.passed` reflects its `floor`, and the
  public `DocumentationRetriever.retrieve` works directly (no wrapper needed).
- **E4 benchmark:** corpus-derived queries are sanitized to single-line,
  guard-acceptable strings (headings stripped, whitespace collapsed, ≤300 chars);
  all 56 queries execute end-to-end.
- **E5 coverage:** chunk reachability scans top-3 and counts every distinct
  chunk (50/51 reachable, 1 orphan; no title-only chunks).
- **E6 manifest:** `manifest_matches_filesystem` validates document count,
  version/index_version consistency, and recomputes the content-derived index
  version to detect drift.
- **E7 docs:** `index_version` is documented as a corpus-content version
  (derived from `doc_id` + `content_hash` per document), unchanged by chunking.
- **E8 tests:** new `backend/tests/test_rag_release.py` covers exports,
  evaluation accounting, benchmark execution, coverage, manifests, and dataset
  integrity (24 tests).
- **E9 docs:** `QUALITY.md` and `OBSERVABILITY.md` corrected; `docs/rag/README.md`
  added with test and release instructions.

All golden metrics and live-fact rejection remain unchanged.
