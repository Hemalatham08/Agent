# RAG Observability & Diagnostics (Phase 5)

This document describes the structured diagnostics added to the
documentation-only RAG package in Phase 5. The RAG package remains
**standalone** and is **not** integrated into the active ERP agent.

## Goals

Improve debugging and transparency of retrieval behavior without changing
ranking, guard safety, or corpus semantics:

1. Retrieval diagnostics and structured traces.
2. Guard decision and rejection-reason reporting.
3. Search result explanations (per-hit BM25 term contributions).
4. Corpus health reporting.
5. Index statistics.
6. Query expansion diagnostics.
7. Structured, privacy-safe debug output.
8. Evaluation result reporting.

## Scope

Only these files were added or changed:

- `backend/agent/rag/diagnostics.py` (new) — diagnostic models and builders.
- `backend/agent/rag/retriever.py` — `retrieve_with_diagnostics`, optional sink.
- `backend/agent/rag/bm25.py` — shared scoring kernel, `search_detailed`, stats.
- `backend/agent/rag/text.py` — `expansion_trace`.
- `backend/agent/rag/corpus.py` — `inspect_manifest`.
- `backend/agent/rag/__init__.py` — new exports.
- `backend/tests/test_rag_diagnostics.py` (new) — 36 deterministic tests.
- `docs/rag/OBSERVABILITY.md` (this file).

No protected file was modified: `backend/main.py`,
`backend/agent/orchestrator.py`, `backend/agent/erp/**`,
`backend/agent/tools/**`, `frontend/**`, teammate tests, and shared
configuration are untouched.

## Diagnostics are opt-in

The normal `DocumentationRetriever.retrieve()` path allocates nothing
diagnostic and is byte-for-byte equivalent to the pre-Phase-5 implementation.
Diagnostics are requested explicitly:

```python
from backend.agent.rag.retriever import DocumentationRetriever

diagnosed = retriever.retrieve_with_diagnostics(
    "What is free stock?",
    top_k=3,
    include_query_fingerprint=True,          # 12-hex correlation id, opt-in
    include_detailed_scoring=True,           # per-term BM25 contributions, opt-in
)
result = diagnosed.result   # identical to retriever.retrieve(...)
trace = diagnosed.trace
```

`result == retriever.retrieve("What is free stock?", top_k=3)` for every
query. A constructor-supplied `diagnostic_sink` receives one trace per
`retrieve_with_diagnostics` call (never for `retrieve`); a failing sink never
corrupts the result.

## Privacy

Default traces intentionally omit:

- raw query text,
- snippets,
- document bodies,
- guidance text,
- record identifiers.

A short query fingerprint (12 hex characters, SHA-256 truncated) is emitted
only when `include_query_fingerprint=True`. `RetrievalTrace.to_log_fields()`
returns a single-line-safe subset containing only status, index version,
guard verdict/reason, and counts — safe to log without exposing operational
or customer data.

Example log-safe output:

```json
{
  "status": "ok",
  "index_version": "c9dedad29b42",
  "index_searched": true,
  "guard_verdict": "allowed",
  "guard_reason": "conceptual_question",
  "candidate_count": 39,
  "selected_count": 3,
  "total_chars": 382
}
```

## Retrieval trace

`RetrievalTrace` records, per call:

- `status` (`ok`, `no_match`, `blocked`).
- `index_version`, `index_searched` (false for blocked queries).
- `guard` — verdict, reason, live-fact kind, suggested category, signals,
  guidance presence (never guidance text).
- `expansion` — whether query expansion was enabled, original/expanded token
  counts, and the curated source→added term pairs.
- `query_chars`, `query_token_count`, `query_fingerprint` (opt-in).
- `candidate_count`, `best_score`, `threshold`.
- Drop accounting: below min score, below relative floor, duplicate chunk,
  per-document cap, top-k.
- `selected` — per-hit `HitExplanation` (rank, chunk/doc id, category, score,
  snippet length, matched query terms, per-term contributions when detailed
  scoring is on).
- `total_chars`.

## Guard reporting

`GuardTrace` exposes the same verdict/reason/live-fact-kind/signals as
`classify_query`, so callers can inspect why a query was allowed, blocked, or
ambiguous without parsing guidance text. Blocked queries set
`index_searched=False` and never search the BM25 index. Guard logic itself
(`guard.py`) is unchanged; live-fact rejection remains exact.

## Search result explanations

With `include_detailed_scoring=True`, each selected hit carries
`HitExplanation.contributions`, one `TermContribution` per query term with
term frequency, document frequency, IDF, and contribution. Contributions sum
to the hit's BM25 score (verified to within 1e-9). `search_detailed` on
`Bm25Index` shares the same scoring kernel as `search`, so scores, ranking,
tie-breaking, and category filtering are identical.

## Query expansion diagnostics

`expansion_trace(tokens)` returns the curated source→added term pairs, and
`ExpansionTrace` reports original vs expanded token counts. Expansion remains
opt-in (`query_expansion=False` by default) and additive only.

## Index statistics

`build_index_stats(index)` returns `IndexStats`: index version, chunk count,
vocabulary size, total tokens, average length, k1, b, and sorted
`(category, chunk_count)` pairs. Deterministic across fresh builds.

## Corpus health

`build_corpus_health(bundle, knowledge_dir)` returns `CorpusHealthReport`:
document/chunk/alias counts, category and fact-kind counts, duplicate doc IDs,
duplicate content pairs, duplicate alias owners, live-fact violation count,
chunk ownership, document ordering, manifest inspection, index version, and a
`healthy` flag. The shipped corpus (12 docs, 51 chunks, 20 aliases) reports
`healthy=True` with zero live-fact violations and no duplicates.

## Manifest inspection

`inspect_manifest(knowledge_dir)` returns `ManifestInspection` with one of:

- `missing` — no manifest file.
- `malformed` — unreadable, invalid JSON, or invalid shape.
- `stale` — parsed but document count, version, content-derived index version,
  or hashes disagree with the filesystem.
- `current` — parsed and matches the filesystem.

The filesystem is authoritative; a missing or bad manifest safely triggers
regeneration. `read_manifest`/`write_manifest` behavior is unchanged.

## Evaluation reporting

`MetricResult` and `EvaluationReport` provide a stable, deterministic format
for golden-evaluation output (name, value, numerator/denominator, floor,
target, pass flag). Metrics preserve declaration order and serialize to JSON.

## Performance

Measured on the shipped corpus (12 documents, 51 chunks), per-query:

| Mode | Median latency | Overhead vs normal |
|---|---|---|
| Normal `retrieve` | ~0.29 ms | — |
| `retrieve_with_diagnostics` | ~0.70 ms | ~0.41 ms |
| + detailed scoring | ~0.93 ms | ~0.64 ms |

Tracing adds well under 1 ms per query and is opt-in; detailed scoring is
additive and only when requested.

## Determinism

All diagnostic models are frozen, forbid extra fields, and contain no
timestamps or nondeterministic fields. Repeated calls and fresh corpus/index
builds produce equal traces and reports.

## Non-goals (deferred)

- Incremental indexing (Phase 4 documented the full-rebuild tradeoff; the
  12-document corpus rebuilds in ~130 ms).
- Reopening the skipped `AliasTargetTests` / bare-alias guard coverage.
- Persistent trace storage, databases, telemetry backends, or web endpoints.
- Integration into the active ERP agent, prompt layer, or orchestrator.
