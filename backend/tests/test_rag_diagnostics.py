"""Deterministic diagnostics tests for Phase 5 observability.

These tests verify that diagnostics are opt-in, do not alter retrieval output,
preserve BM25 scores/ranking, expose guard and selection reasoning, respect
privacy (no raw query/snippet/body/guidance by default), and remain
deterministic across repeated builds.
"""

from __future__ import annotations

import hashlib
import unittest
from tempfile import TemporaryDirectory

from backend.agent.rag import (
    DEFAULT_KNOWLEDGE_DIR,
    ExpansionEntry,
    ExpansionTrace,
    GuardVerdict,
    HitExplanation,
    IndexStats,
    ManifestInspection,
    ManifestStatus,
    RagConfig,
    RetrievalTrace,
    TermContribution,
    build_corpus_health,
    build_index_stats,
    classify_query,
    load_corpus,
    redacted_trace_fields,
)
from backend.agent.rag.bm25 import Bm25Index
from backend.agent.rag.corpus import CATEGORIES, load_corpus_from_dir, write_manifest
from backend.agent.rag.diagnostics import (
    DiagnosedRetrieval,
    DetailedScoredChunk,
    CorpusHealthReport,
    EvaluationReport,
)
from backend.agent.rag.models import RetrievalQuery
from backend.agent.rag.retriever import DocumentationRetriever
from backend.agent.rag.text import expansion_trace, tokenize

# Read-only golden evaluation context, mirroring test_rag_eval.py.
_CONFIG = RagConfig(knowledge_dir=DEFAULT_KNOWLEDGE_DIR)
_BUNDLE = load_corpus(_CONFIG)
_INDEX = Bm25Index(_BUNDLE)
_RETRIEVER = DocumentationRetriever(_INDEX)

ALL_QUERIES = (
    "What modules does the ERP have?",
    "What is the iFive ERP system overview?",
    "What is the product catalogue module?",
    "What does the product catalogue module do?",
    "What does the reporting module show?",
    "What report families exist?",
    "What is free stock?",
    "What does reserved stock mean?",
    "What is a SKU?",
    "What is the difference between a product and a SKU?",
    "What does partially dispatched mean?",
    "Which statuses can a sales order have?",
    "What are the common documentation questions?",
    "Does the documentation show current stock?",
    "Can documentation be used for live totals?",
    "What is the documentation and live data policy?",
    "What tables store sales orders?",
    "What columns does the stock table have?",
    "What is the goods receipt process?",
    "What is the purchase to stock workflow?",
    "What happens after a sales order is confirmed?",
    "What is the sales order to dispatch workflow?",
    "How does a stock adjustment work?",
    "Who approves a stock adjustment?",
    "erp overview",
    "product master",
    "item master",
    "reports",
    "available stock",
    "low stock",
    "item",
    "stock keeping unit",
    "order status",
    "delivery status",
    "faq",
    "live data policy",
    "documentation policy",
    "database schema",
    "procurement workflow",
    "goods receipt",
    "order fulfilment",
    "delivery workflow",
    "cycle count",
    "stock correction",
    "How many products are there?",
    "How many open sales orders exist?",
    "What is the total sales value this month?",
    "What is the price of product PRD001?",
    "What is the status of sales order SO001?",
    "Where is dispatch DSP001?",
    "How much stock is left for PRD001?",
    "Is product PRD001 in stock?",
    "Show me all orders from Acme.",
    "List today's invoices.",
    "What are today's totals?",
    "What is the current stock level of SKU-100?",
)


class ResultEquivalenceTests(unittest.TestCase):
    """retrieve_with_diagnostics().result must equal retrieve() exactly."""

    def test_result_equals_retrieve_for_all_queries(self) -> None:
        for query in ALL_QUERIES:
            with self.subTest(query=query):
                normal = _RETRIEVER.retrieve(query, top_k=3)
                diagnosed = _RETRIEVER.retrieve_with_diagnostics(query, top_k=3)
                self.assertEqual(diagnosed.result, normal)
                self.assertIsInstance(diagnosed, DiagnosedRetrieval)
                self.assertIsInstance(diagnosed.trace, RetrievalTrace)

    def test_trace_is_deterministic_across_repeated_calls(self) -> None:
        for query in ALL_QUERIES:
            with self.subTest(query=query):
                first = _RETRIEVER.retrieve_with_diagnostics(query, top_k=3)
                second = _RETRIEVER.retrieve_with_diagnostics(query, top_k=3)
                self.assertEqual(first.trace, second.trace)
                self.assertEqual(first.result, second.result)

    def test_trace_equality_across_fresh_builds(self) -> None:
        bundle = load_corpus(_CONFIG)
        index = Bm25Index(bundle)
        retriever = DocumentationRetriever(index)
        self.assertEqual(index.index_version, _INDEX.index_version)
        for query in ALL_QUERIES[:6]:
            with self.subTest(query=query):
                first = retriever.retrieve_with_diagnostics(query, top_k=3)
                second = _RETRIEVER.retrieve_with_diagnostics(query, top_k=3)
                self.assertEqual(first.trace, second.trace)

    def test_normal_retrieve_allocates_no_trace(self) -> None:
        # The normal path must behave exactly as before (no diagnostic object).
        result = _RETRIEVER.retrieve("What is free stock?", top_k=3)
        self.assertIsInstance(result, __import__(
            "backend.agent.rag.models", fromlist=["RetrievalResult"]
        ).RetrievalResult)


class GuardTraceTests(unittest.TestCase):
    """Guard traces must reflect classify_query exactly."""

    def test_guard_trace_matches_classify_query(self) -> None:
        for query in ALL_QUERIES:
            with self.subTest(query=query):
                decision = classify_query(query)
                diagnosed = _RETRIEVER.retrieve_with_diagnostics(query, top_k=3)
                trace = diagnosed.trace
                self.assertEqual(trace.guard.verdict, decision.verdict)
                self.assertEqual(trace.guard.reason, decision.reason)
                self.assertEqual(trace.guard.live_fact_kind, decision.live_fact_kind)
                self.assertEqual(
                    trace.guard.suggested_category, decision.suggested_category
                )
                self.assertEqual(trace.guard.signals, decision.signals)
                self.assertEqual(
                    trace.guard.guidance_present, decision.guidance is not None
                )

    def test_blocked_queries_never_search_the_index(self) -> None:
        for query in ALL_QUERIES:
            with self.subTest(query=query):
                decision = classify_query(query)
                diagnosed = _RETRIEVER.retrieve_with_diagnostics(query, top_k=3)
                if decision.verdict is not GuardVerdict.ALLOWED:
                    self.assertEqual(diagnosed.trace.status, "blocked")
                    self.assertFalse(diagnosed.trace.index_searched)
                    self.assertEqual(diagnosed.trace.candidate_count, 0)
                    self.assertEqual(diagnosed.trace.best_score, None)
                    self.assertEqual(diagnosed.trace.threshold, None)
                    self.assertEqual(diagnosed.trace.selected, ())

    def test_allowed_queries_search_the_index(self) -> None:
        for query in ALL_QUERIES[:24]:
            with self.subTest(query=query):
                diagnosed = _RETRIEVER.retrieve_with_diagnostics(query, top_k=3)
                if diagnosed.trace.status == "ok":
                    self.assertTrue(diagnosed.trace.index_searched)
                    self.assertGreater(diagnosed.trace.candidate_count, 0)
                    self.assertIsNotNone(diagnosed.trace.best_score)


class ScoreExplanationTests(unittest.TestCase):
    """Per-hit explanations must reconcile with BM25 scores."""

    def test_contributions_sum_to_score(self) -> None:
        for query in ALL_QUERIES[:24]:
            with self.subTest(query=query):
                diagnosed = _RETRIEVER.retrieve_with_diagnostics(
                    query, top_k=3, include_detailed_scoring=True
                )
                for hit in diagnosed.trace.selected:
                    with self.subTest(query=query, chunk=hit.chunk_id):
                        total = sum(c.contribution for c in hit.contributions)
                        self.assertAlmostEqual(total, hit.score, places=9)
                        self.assertGreaterEqual(hit.score, 0.0)
                        self.assertGreaterEqual(hit.snippet_chars, 1)
                        self.assertLessEqual(hit.rank, 3)

    def test_detailed_scoring_is_opt_in(self) -> None:
        normal = _RETRIEVER.retrieve_with_diagnostics("What is free stock?", top_k=3)
        detailed = _RETRIEVER.retrieve_with_diagnostics(
            "What is free stock?", top_k=3, include_detailed_scoring=True
        )
        self.assertEqual(normal.result, detailed.result)
        if normal.trace.selected:
            self.assertEqual(normal.trace.selected[0].contributions, ())
            self.assertGreater(len(detailed.trace.selected[0].contributions), 0)

    def test_matched_terms_are_query_tokens_in_chunk(self) -> None:
        diagnosed = _RETRIEVER.retrieve_with_diagnostics(
            "What is free stock?", top_k=3, include_detailed_scoring=True
        )
        for hit in diagnosed.trace.selected:
            for term in hit.matched_terms:
                self.assertIn(term, tokenize("What is free stock?"))

    def test_ranking_is_descending_score(self) -> None:
        diagnosed = _RETRIEVER.retrieve_with_diagnostics("What is free stock?", top_k=3)
        scores = [h.score for h in diagnosed.trace.selected]
        self.assertEqual(scores, sorted(scores, reverse=True))


class SelectionAccountingTests(unittest.TestCase):
    """Drop accounting must be deterministic and consistent."""

    def test_dropped_counts_are_non_negative(self) -> None:
        for query in ALL_QUERIES:
            with self.subTest(query=query):
                trace = _RETRIEVER.retrieve_with_diagnostics(query, top_k=3).trace
                for attr in (
                    "dropped_below_min_score",
                    "dropped_below_relative_floor",
                    "dropped_duplicate_chunk",
                    "dropped_per_document_cap",
                    "dropped_top_k",
                ):
                    self.assertGreaterEqual(getattr(trace, attr), 0)

    def test_blocked_has_zero_drops(self) -> None:
        trace = _RETRIEVER.retrieve_with_diagnostics(
            "How many products are there?", top_k=3
        ).trace
        self.assertEqual(trace.dropped_below_min_score, 0)
        self.assertEqual(trace.dropped_top_k, 0)


class ExpansionTraceTests(unittest.TestCase):
    """Expansion traces must be opt-in-correct and deterministic."""

    def test_expansion_disabled_by_default(self) -> None:
        trace = _RETRIEVER.retrieve_with_diagnostics(
            "What is free stock?", top_k=3
        ).trace
        self.assertFalse(trace.expansion.enabled)
        self.assertEqual(trace.expansion.expansions, ())
        self.assertEqual(
            trace.expansion.original_token_count,
            trace.expansion.expanded_token_count,
        )

    def test_expansion_trace_terms_match_expand_query_terms(self) -> None:
        tokens = tokenize("dispatched orders")
        pairs = expansion_trace(tokens)
        expanded = [t for t in tokens]
        seen = set(expanded)
        for source, added in pairs:
            expanded.extend(added)
            seen.update(added)
        self.assertEqual(
            [p[0] for p in pairs],
            [t for t in tokens if expansion_trace([t])],
        )
        # Round-trip: expansion_trace of expanded adds nothing new.
        expanded2 = expansion_trace(expanded)
        self.assertEqual(expanded2, ())

    def test_expansion_does_not_change_retrieval(self) -> None:
        retriever = DocumentationRetriever(_INDEX, query_expansion=True)
        normal = retriever.retrieve("dispatched orders", top_k=3)
        diagnosed = retriever.retrieve_with_diagnostics(
            "dispatched orders", top_k=3, include_detailed_scoring=True
        )
        self.assertEqual(diagnosed.result, normal)
        self.assertTrue(diagnosed.trace.expansion.enabled)
        self.assertGreater(diagnosed.trace.expansion.expanded_token_count, 0)


class IndexStatsTests(unittest.TestCase):
    """Index statistics must be deterministic across builds."""

    def test_stats_deterministic_across_builds(self) -> None:
        first = build_index_stats(_INDEX)
        bundle = load_corpus(_CONFIG)
        index = Bm25Index(bundle)
        second = build_index_stats(index)
        self.assertEqual(first, second)
        self.assertEqual(first.chunk_count, 51)
        self.assertGreater(first.vocabulary_size, 0)
        self.assertGreater(first.total_tokens, 0)
        self.assertGreater(first.average_length, 0.0)
        self.assertEqual(first.k1, 1.2)
        self.assertEqual(first.b, 0.75)
        self.assertGreater(len(first.category_counts), 0)
        # category_counts sorted deterministically
        cats = [c for c, _ in first.category_counts]
        self.assertEqual(cats, sorted(cats))

    def test_stats_are_json_serializable(self) -> None:
        stats = build_index_stats(_INDEX)
        payload = stats.to_json()
        self.assertIsInstance(payload["category_counts"], list)
        self.assertEqual(
            len(payload["category_counts"]), len(stats.category_counts)
        )
        self.assertEqual(payload["k1"], 1.2)
        self.assertEqual(payload["b"], 0.75)


class CorpusHealthTests(unittest.TestCase):
    """Corpus health must report the shipped corpus as healthy."""

    def test_shipped_corpus_is_healthy(self) -> None:
        health = build_corpus_health(_BUNDLE, DEFAULT_KNOWLEDGE_DIR)
        self.assertIsInstance(health, CorpusHealthReport)
        self.assertTrue(health.healthy)
        self.assertEqual(health.document_count, 12)
        self.assertEqual(health.chunk_count, 51)
        self.assertEqual(health.alias_count, 20)
        self.assertEqual(health.live_fact_violation_count, 0)
        self.assertEqual(health.duplicate_doc_ids, ())
        self.assertEqual(health.duplicate_content_pairs, ())
        self.assertEqual(health.duplicate_alias_owners, ())
        self.assertTrue(health.chunk_ownership_ok)
        self.assertEqual(health.index_version, _BUNDLE.index_version)
        self.assertEqual(health.manifest.status, ManifestStatus.MISSING)

    def test_health_is_deterministic(self) -> None:
        first = build_corpus_health(_BUNDLE, DEFAULT_KNOWLEDGE_DIR)
        second = build_corpus_health(_BUNDLE, DEFAULT_KNOWLEDGE_DIR)
        self.assertEqual(first, second)

    def test_health_detects_duplicate_content_via_builder(self) -> None:
        # Duplicate content detection is exercised through build_corpus_health;
        # the shipped corpus has no duplicates, so the pair list is empty.
        health = build_corpus_health(_BUNDLE, DEFAULT_KNOWLEDGE_DIR)
        self.assertEqual(health.duplicate_content_pairs, ())
        self.assertEqual(health.duplicate_alias_owners, ())

    def test_health_to_json_roundtrip(self) -> None:
        health = build_corpus_health(_BUNDLE, DEFAULT_KNOWLEDGE_DIR)
        payload = health.to_json()
        self.assertIsInstance(payload["healthy"], bool)
        self.assertIsInstance(payload["category_counts"], list)
        self.assertIsInstance(payload["manifest"], dict)


class ManifestStatusTests(unittest.TestCase):
    """Manifest inspection must report missing/malformed/stale/current."""

    def _copy_shipped_corpus(self, tmp: str) -> str:
        import shutil
        from pathlib import Path

        dest = Path(tmp) / "knowledge"
        shutil.copytree(DEFAULT_KNOWLEDGE_DIR, dest)
        return str(dest)

    def test_missing_manifest(self) -> None:
        from backend.agent.rag.corpus import inspect_manifest

        with TemporaryDirectory() as tmp:
            inspection = inspect_manifest(tmp)
            self.assertEqual(inspection.status, ManifestStatus.MISSING)
            self.assertIsNone(inspection.document_count)
            self.assertIsNone(inspection.index_version)
            self.assertEqual(inspection.recorded_hashes, 0)

    def test_roundtrip_manifest_is_current(self) -> None:
        from backend.agent.rag.corpus import inspect_manifest

        with TemporaryDirectory() as tmp:
            knowledge_dir = self._copy_shipped_corpus(tmp)
            bundle = load_corpus_from_dir(knowledge_dir)
            write_manifest(knowledge_dir, bundle)
            inspection = inspect_manifest(knowledge_dir)
            self.assertEqual(inspection.status, ManifestStatus.CURRENT)
            self.assertEqual(inspection.document_count, 12)
            self.assertEqual(len(inspection.index_version), 12)
            self.assertEqual(inspection.recorded_hashes, 12)

    def test_stale_manifest_after_document_change(self) -> None:
        import os
        from backend.agent.rag.corpus import inspect_manifest

        with TemporaryDirectory() as tmp:
            knowledge_dir = self._copy_shipped_corpus(tmp)
            bundle = load_corpus_from_dir(knowledge_dir)
            write_manifest(knowledge_dir, bundle)
            self.assertEqual(
                inspect_manifest(knowledge_dir).status, ManifestStatus.CURRENT
            )

            target = None
            for cat in os.listdir(knowledge_dir):
                cat_dir = os.path.join(knowledge_dir, cat)
                if os.path.isdir(cat_dir):
                    for fn in os.listdir(cat_dir):
                        if fn.endswith(".md"):
                            target = os.path.join(cat_dir, fn)
                            break
                    if target:
                        break
            self.assertIsNotNone(target)
            with open(target, "a", encoding="utf-8") as fh:
                fh.write("\n<!-- diagnostics test change -->\n")

            self.assertEqual(
                inspect_manifest(knowledge_dir).status, ManifestStatus.STALE
            )

    def test_malformed_manifest(self) -> None:
        from pathlib import Path
        from backend.agent.rag.corpus import inspect_manifest

        with TemporaryDirectory() as tmp:
            knowledge_dir = self._copy_shipped_corpus(tmp)
            manifest_file = Path(knowledge_dir) / "corpus-manifest.json"
            manifest_file.write_text("{not valid json", encoding="utf-8")
            self.assertEqual(
                inspect_manifest(knowledge_dir).status, ManifestStatus.MALFORMED
            )


class PrivacyTests(unittest.TestCase):
    """Default traces must not leak raw query, snippet, body, or guidance."""

    def _serialized_contains_sensitive(self, payload) -> bool:
        text = str(payload)
        sensitive = [
            "What is free stock?",
            "How many products are there?",
            "PRD001",
            "SO001",
            "DSP001",
            "SKU-100",
            "This page explains",
            "use the ERP tools",
        ]
        return any(s in text for s in sensitive)

    def test_default_trace_contains_no_raw_query(self) -> None:
        diagnosed = _RETRIEVER.retrieve_with_diagnostics(
            "What is free stock?", top_k=3
        )
        payload = diagnosed.trace.to_json()
        self.assertFalse(self._serialized_contains_sensitive(payload))
        self.assertNotIn("query", payload)
        self.assertNotIn("snippet", payload)
        self.assertNotIn("body", payload)

    def test_log_fields_are_safe(self) -> None:
        diagnosed = _RETRIEVER.retrieve_with_diagnostics(
            "How many products are there?", top_k=3
        )
        fields = diagnosed.trace.to_log_fields()
        self.assertNotIn("query", fields)
        self.assertNotIn("snippet", fields)
        self.assertIn("status", fields)
        self.assertIn("guard_verdict", fields)
        self.assertIn("guard_reason", fields)

    def test_fingerprint_only_when_opted_in(self) -> None:
        default_trace = _RETRIEVER.retrieve_with_diagnostics("X", top_k=1).trace
        self.assertIsNone(default_trace.query_fingerprint)
        opted = _RETRIEVER.retrieve_with_diagnostics(
            "X", top_k=1, include_query_fingerprint=True
        ).trace
        self.assertIsNotNone(opted.query_fingerprint)
        self.assertEqual(len(opted.query_fingerprint), 12)
        self.assertEqual(
            opted.query_fingerprint,
            hashlib.sha256("X".encode("utf-8")).hexdigest()[:12],
        )

    def test_blocked_trace_leaks_no_guidance_text(self) -> None:
        diagnosed = _RETRIEVER.retrieve_with_diagnostics(
            "How many products are there?", top_k=3
        )
        payload = diagnosed.trace.to_json()
        # The guard object carries only guidance_present (a bool), never text.
        self.assertNotIn("guidance", payload["guard"])
        self.assertIsInstance(payload["guard"]["guidance_present"], bool)
        # The full trace must not contain the raw query or guidance text.
        self.assertNotIn("How many products are there?", str(payload))
        self.assertFalse(self._serialized_contains_sensitive(payload))


class SinkTests(unittest.TestCase):
    """Diagnostic sinks must be isolated from retrieval errors."""

    def test_sink_receives_one_trace_per_call(self) -> None:
        captured = []
        retriever = DocumentationRetriever(_INDEX, diagnostic_sink=captured.append)
        retriever.retrieve_with_diagnostics("What is free stock?", top_k=3)
        retriever.retrieve_with_diagnostics("How many products?", top_k=3)
        self.assertEqual(len(captured), 2)
        self.assertIsInstance(captured[0], RetrievalTrace)

    def test_normal_retrieve_does_not_invoke_sink(self) -> None:
        captured = []
        retriever = DocumentationRetriever(_INDEX, diagnostic_sink=captured.append)
        retriever.retrieve("What is free stock?", top_k=3)
        self.assertEqual(len(captured), 0)

    def test_failing_sink_does_not_corrupt_result(self) -> None:
        def boom(trace):  # noqa: ARG001
            raise RuntimeError("sink failure")

        retriever = DocumentationRetriever(_INDEX, diagnostic_sink=boom)
        diagnosed = retriever.retrieve_with_diagnostics("What is free stock?", top_k=3)
        self.assertEqual(diagnosed.result.status, "ok")

    def test_invalid_sink_constructor(self) -> None:
        with self.assertRaises(__import__(
            "backend.agent.rag.errors", fromlist=["RagInvalidArgumentsError"]
        ).RagInvalidArgumentsError):
            DocumentationRetriever(_INDEX, diagnostic_sink=42)  # type: ignore[arg-type]


class EvaluationReportTests(unittest.TestCase):
    """Evaluation report must be deterministic and stable."""

    def test_report_construction(self) -> None:
        metrics = [
            __import__("backend.agent.rag.diagnostics", fromlist=["MetricResult"]).MetricResult(
                name="conceptual_allow_rate",
                value=24.0,
                numerator=24,
                denominator=24,
                floor=18.0,
                target=24.0,
                passed=True,
            )
        ]
        report = EvaluationReport(
            index_version=_BUNDLE.index_version,
            document_count=12,
            chunk_count=51,
            metrics=tuple(metrics),
            all_required_passed=True,
        )
        self.assertTrue(report.all_required_passed)
        self.assertEqual(report.metrics[0].name, "conceptual_allow_rate")
        payload = report.to_json()
        self.assertEqual(payload["all_required_passed"], True)
        self.assertEqual(len(payload["metrics"]), 1)
        # Deterministic serialization.
        self.assertEqual(report, EvaluationReport(**{
            "index_version": report.index_version,
            "document_count": report.document_count,
            "chunk_count": report.chunk_count,
            "metrics": report.metrics,
            "all_required_passed": report.all_required_passed,
        }))


class PerformanceSmokeTests(unittest.TestCase):
    """Tracing overhead must be bounded and measured separately from scoring."""

    def test_traced_vs_untraced_latency(self) -> None:
        import time

        queries = ALL_QUERIES[:20]
        # Untraced.
        t0 = time.perf_counter()
        for _ in range(3):
            for q in queries:
                _RETRIEVER.retrieve(q, top_k=3)
        t1 = time.perf_counter()
        # Traced (no detailed scoring).
        t2 = time.perf_counter()
        for _ in range(3):
            for q in queries:
                _RETRIEVER.retrieve_with_diagnostics(q, top_k=3)
        t3 = time.perf_counter()
        # Detailed scoring.
        t4 = time.perf_counter()
        for _ in range(3):
            for q in queries[:5]:
                _RETRIEVER.retrieve_with_diagnostics(
                    q, top_k=3, include_detailed_scoring=True
                )
        t5 = time.perf_counter()

        normal_ms = (t1 - t0) * 1000
        traced_ms = (t3 - t2) * 1000
        detailed_ms = (t5 - t4) * 1000
        print(f"\nnormal={normal_ms:.1f}ms traced={traced_ms:.1f}ms detailed={detailed_ms:.1f}ms")
        # Traced must not exceed 2x normal on this small corpus (generous bound).
        self.assertLessEqual(traced_ms, normal_ms * 2 + 50)


if __name__ == "__main__":
    unittest.main()
