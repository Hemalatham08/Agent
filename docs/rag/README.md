# RAG Documentation

This folder documents the standalone, documentation-only RAG package for the
iFive AI ERP Agent. RAG is **isolated** under `backend/agent/rag/` and is **not**
integrated into the active ERP agent, orchestrator, or ERP data path.

## Documents

| Document | Phase | Description |
|---|---|---|
| `README.md` | — | This index: tests, release instructions, and file map. |
| `OBSERVABILITY.md` | 5 | Diagnostics, traces, guard reporting, corpus health, manifest inspection, performance, determinism. |
| `QUALITY.md` | 6 + 7 | Retrieval quality & robustness: datasets, acceptance criteria, hard-negative ledger, multi-document coverage, corpus coverage, and Phase 7 release-readiness changes. |

## File map

Source (allowed scope for RAG work):

- `backend/agent/rag/` — configuration, errors, models, text, chunking, corpus,
  BM25, guard, retriever, diagnostics, evaluation, definitions, handlers,
  runner, registration, platform.
- `backend/tests/test_rag_*.py` — RAG test suites.
- `docs/rag/` — this documentation.

Protected (never modified by RAG work):

- `backend/main.py`, `backend/agent/orchestration/**`, `backend/agent/erp/**`,
  `backend/agent/tools/**`, `frontend/**`, shared configuration, teammate tests.

## Running the tests

There is no `pytest.ini`, `pyproject.toml`, or CI workflow in the repo. The
unrelated `backend/tests/test_migrations.py` requires `alembic` (not installed)
and fails collection, so tests must be run with explicit file paths:

```powershell
# Full explicit RAG suite (recommended release gate)
python -m pytest backend/tests/test_rag_config.py backend/tests/test_rag_text.py backend/tests/test_rag_chunking.py backend/tests/test_rag_corpus.py backend/tests/test_rag_bm25.py backend/tests/test_rag_guard.py backend/tests/test_rag_retriever.py backend/tests/test_rag_tools.py backend/tests/test_rag_tool_platform.py backend/tests/test_rag_eval.py backend/tests/test_rag_diagnostics.py backend/tests/test_rag_quality.py backend/tests/test_rag_release.py -q

# Individual suites
python -m pytest backend/tests/test_rag_release.py -q
python -m pytest backend/tests/test_rag_quality.py -q
python -m pytest backend/tests/test_rag_diagnostics.py -q
```

Baseline: **610 passed, 3 skipped** (the 3 skipped are `AliasTargetTests`,
pending a separately approved guard-precision phase).

## Release-readiness checklist

Before any RAG release:

- [ ] Full explicit RAG suite passes (see command above).
- [ ] Golden retrieval metrics unchanged: conceptual 24/24 / 24/24 / MRR 1.0000,
  alias top-1 19/20 / top-3 20/20, e2e 12/20.
- [ ] Live-fact rejection: 12/12 golden + 20/20 adversarial blocked/ambiguous.
- [ ] Evaluation rates all within [0, 1]; `evaluate_quality` works with
  `retriever.retrieve` directly (no wrapper).
- [ ] Corpus-derived benchmark: all 56 queries valid; executes end-to-end.
- [ ] Package exports complete: `from backend.agent.rag import *` succeeds;
  `DiagnosedRetrieval` and `FailureKind` exported.
- [ ] Coverage metrics accurate: 50/51 chunks reachable in top-3, 1 orphan,
  0 title-only chunks.
- [ ] Manifest detects document-count, version, and content-version drift.
- [ ] Rebuilds and evaluation reports are deterministic.
- [ ] Docs contain no stale numeric claims (`QUALITY.md`, `OBSERVABILITY.md`).
- [ ] Only allowed paths changed; `guard.py` and protected files untouched.
- [ ] No commits or pushes.

## Versioning

- `index_version` (12 hex chars) is a **corpus-content version**: derived from
  `doc_id` + `content_hash` per document, sorted by `doc_id`. It is unchanged
  by chunking parameters (`max_chunk_chars`), so chunker changes do not
  invalidate it.
- `RAG_TOOL_VERSION = "1.0.0"` in `backend/agent/rag/definitions.py` is the
  tool-layer version.
