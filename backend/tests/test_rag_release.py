"""Phase 7 release-readiness tests for the documentation-only RAG package.

These tests guard the release-evidence layer: public API exports, evaluation
accounting, benchmark execution, coverage metrics, manifest integrity, and
dataset consistency. They never change retrieval behaviour, safety logic, or
corpus content.
"""

from __future__ import annotations

import shutil
import tempfile
from datetime import date
from pathlib import Path
import unittest

from backend.agent.rag import (
    DEFAULT_KNOWLEDGE_DIR,
    DiagnosedRetrieval,
    FailureKind,
    RagConfig,
    classify_query,
    load_corpus,
)
from backend.agent.rag.bm25 import Bm25Index
from backend.agent.rag.corpus import (
    CorpusManifest,
    index_version_for,
    manifest_matches_filesystem,
    read_manifest,
    write_manifest,
)
from backend.agent.rag.evaluation import (
    CoverageReport,
    EvalQuery,
    FailureRecord,
    HardNegativeCase,
    MultiDocCase,
    QualityMetric,
    QualityReport,
    build_corpus_benchmark,
    build_coverage_report,
    evaluate_quality,
    hit_doc_ids,
    rank_of_doc,
)
from backend.agent.rag.models import RetrievalHit, RetrievalResult
from backend.agent.rag.retriever import DocumentationRetriever
from backend.tests import test_rag_quality as q

_HIT = RetrievalHit(
    chunk_id="doc-a#section#01",
    doc_id="doc-a",
    title="Doc A",
    section="Section",
    category="erp_docs",
    fact_kind="overview",
    score=0.5,
    snippet="z" * 80,
    source_path="a.md",
    updated_at=date(2026, 1, 1),
)


def _make_retriever() -> DocumentationRetriever:
    cfg = RagConfig(knowledge_dir=DEFAULT_KNOWLEDGE_DIR)
    return DocumentationRetriever(Bm25Index(load_corpus(cfg)))


class ExportContractTests(unittest.TestCase):
    """The public package export contract is complete and consistent."""

    def test_star_import_succeeds(self) -> None:
        namespace: dict[str, object] = {}
        exec("from backend.agent.rag import *", namespace)  # noqa: S102
        self.assertIn("DiagnosedRetrieval", namespace)
        self.assertIn("FailureKind", namespace)

    def test_all_names_exist(self) -> None:
        import backend.agent.rag as rag

        for name in rag.__all__:
            self.assertTrue(
                hasattr(rag, name),
                f"__all__ names {name!r} but it is not importable",
            )

    def test_no_duplicate_exports(self) -> None:
        import backend.agent.rag as rag

        dupes = [n for n in rag.__all__ if rag.__all__.count(n) > 1]
        self.assertEqual(dupes, [])

    def test_diagnosed_retrieval_and_failure_kind_exported(self) -> None:
        import backend.agent.rag as rag

        self.assertIs(rag.DiagnosedRetrieval, DiagnosedRetrieval)
        self.assertIs(rag.FailureKind, FailureKind)


class EvaluationAccountingTests(unittest.TestCase):
    """Evaluation rates stay within [0, 1] and denominators are per dataset."""

    def _ok_result(self, doc_id: str = "doc-a") -> RetrievalResult:
        hits = (_HIT,) if doc_id == "doc-a" else ()
        return RetrievalResult(
            query="q",
            status="ok",
            total_chars=80,
            index_version="x",
            hits=hits,
        )

    def _retrieve_ok(self, query: str, top_k: int = 3) -> RetrievalResult:
        # Keyword-top_k compatible; always returns doc-a.
        return self._ok_result()

    def test_answer_rate_never_negative(self) -> None:
        report = evaluate_quality(
            retrieve=self._retrieve_ok,
            queries=(EvalQuery("q", ("doc-b",)),),
            top_k=3,
        )
        self.assertEqual(report.query_count, 1)
        self.assertEqual(report.guard_limited_count, 0)
        self.assertEqual(report.retrieval_miss_count, 1)
        self.assertEqual(report.metrics[1].value, 0.0)  # answer_rate
        self.assertGreaterEqual(report.metrics[1].value, 0.0)
        self.assertLessEqual(report.metrics[1].value, 1.0)

    def test_all_rates_within_unit_interval(self) -> None:
        report = evaluate_quality(
            retrieve=self._retrieve_ok,
            queries=(EvalQuery("q", ("doc-a",)),),
            hard_negatives=(
                HardNegativeCase("q2", "doc-a", "doc-trap"),
            ),
            multi_doc=(MultiDocCase("q3", ("doc-a", "doc-b")),),
            top_k=3,
        )
        for m in report.metrics:
            if m.informational:
                continue
            self.assertGreaterEqual(m.value, 0.0, m.name)
            self.assertLessEqual(m.value, 1.0, m.name)

    def test_metric_passed_reflects_floor(self) -> None:
        above = QualityMetric(name="x", value=0.9, floor=0.8)
        below = QualityMetric(name="y", value=0.5, floor=0.8)
        no_floor = QualityMetric(name="z", value=0.1)
        self.assertTrue(above.passed)
        self.assertFalse(below.passed)
        self.assertTrue(no_floor.passed)

    def test_hard_negative_miss_is_distinct_from_trap(self) -> None:
        # Expected doc absent entirely -> HARD_NEGATIVE_MISS, not a trap.
        report = evaluate_quality(
            retrieve=self._retrieve_ok,
            queries=(),
            hard_negatives=(
                HardNegativeCase("q", "doc-b", "doc-trap"),
            ),
            top_k=3,
        )
        self.assertEqual(report.hard_negative_miss_count, 1)
        self.assertEqual(report.hard_negative_trap_count, 0)
        kinds = {f.kind for f in report.failures}
        self.assertIn(FailureKind.HARD_NEGATIVE_MISS, kinds)

    def test_multi_doc_guard_limited_not_counted_as_query_miss(self) -> None:
        report = evaluate_quality(
            retrieve=self._retrieve_ok,
            queries=(),
            multi_doc=(MultiDocCase("q", ("doc-b",)),),
            top_k=3,
        )
        self.assertEqual(report.query_count, 0)
        self.assertEqual(report.multi_doc_gap_count, 1)
        self.assertEqual(report.retrieval_miss_count, 0)

    def test_public_retriever_evaluate_quality_works(self) -> None:
        retriever = _make_retriever()
        allowed = [c for c in q.PARAPHRASE_DEV][:5]
        report = evaluate_quality(
            retrieve=retriever.retrieve,
            queries=tuple(allowed),
            top_k=3,
            index_version="x",
            document_count=12,
            chunk_count=51,
        )
        self.assertEqual(report.query_count, len(allowed))
        for m in report.metrics:
            self.assertGreaterEqual(m.value, 0.0)
            self.assertLessEqual(m.value, 1.0)


class BenchmarkExecutionTests(unittest.TestCase):
    """The corpus-derived benchmark executes end-to-end with valid queries."""

    def test_benchmark_queries_are_valid(self) -> None:
        cfg = RagConfig(knowledge_dir=DEFAULT_KNOWLEDGE_DIR)
        b = load_corpus(cfg)
        aliases = {d.doc_id: d.aliases for d in b.documents}
        bench = build_corpus_benchmark(
            documents=b.documents, aliases_by_doc=aliases
        )
        self.assertEqual(len(bench), 56)
        for case in bench:
            self.assertNotIn("\n", case.query)
            self.assertLessEqual(len(case.query), 300)
            self.assertTrue(case.query.strip())
            self.assertIn(case.expected[0], {d.doc_id for d in b.documents})

    def test_benchmark_executes_end_to_end(self) -> None:
        retriever = _make_retriever()
        cfg = RagConfig(knowledge_dir=DEFAULT_KNOWLEDGE_DIR)
        b = load_corpus(cfg)
        aliases = {d.doc_id: d.aliases for d in b.documents}
        bench = build_corpus_benchmark(
            documents=b.documents, aliases_by_doc=aliases
        )
        report = evaluate_quality(
            retrieve=retriever.retrieve,
            queries=bench,
            top_k=3,
            index_version=b.index_version,
            document_count=len(b.documents),
            chunk_count=len(b.chunks),
        )
        self.assertEqual(report.query_count, 56)
        # Guard-limited cases are tracked separately, never as retrieval misses.
        answered = report.metrics[1].numerator or 0
        self.assertEqual(
            report.guard_limited_count + report.retrieval_miss_count + answered,
            report.query_count,
        )


class CoverageMetricTests(unittest.TestCase):
    """Coverage metrics count every distinct chunk in top-3."""

    def test_chunk_reachability_counts_every_top3_chunk(self) -> None:
        cfg = RagConfig(knowledge_dir=DEFAULT_KNOWLEDGE_DIR)
        b = load_corpus(cfg)
        index = Bm25Index(b)
        aliases = {d.doc_id: d.aliases for d in b.documents}
        report = build_coverage_report(
            documents=b.documents,
            chunks=b.chunks,
            index=index,
            query_bank=tuple(c.query for c in q.PARAPHRASE_DEV),
            aliases_by_doc=aliases,
        )
        # True reachability: scan top-3 over the dev bank.
        reached: set[str] = set()
        for query in (c.query for c in q.PARAPHRASE_DEV):
            for item in index.search(query)[:3]:
                reached.add(item.chunk.chunk_id)
        self.assertEqual(report.chunk_reachability_count, len(reached))
        self.assertEqual(report.chunk_reachability_total, len(b.chunks))
        self.assertEqual(report.heading_only_chunk_count, 0)

    def test_coverage_report_is_deterministic(self) -> None:
        cfg = RagConfig(knowledge_dir=DEFAULT_KNOWLEDGE_DIR)
        b = load_corpus(cfg)
        index = Bm25Index(b)
        aliases = {d.doc_id: d.aliases for d in b.documents}
        bank = tuple(c.query for c in q.PARAPHRASE_DEV)
        first = build_coverage_report(
            documents=b.documents, chunks=b.chunks, index=index,
            query_bank=bank, aliases_by_doc=aliases,
        )
        second = build_coverage_report(
            documents=b.documents, chunks=b.chunks, index=index,
            query_bank=bank, aliases_by_doc=aliases,
        )
        self.assertEqual(first, second)
        self.assertEqual(first.to_json(), second.to_json())


class ManifestIntegrityTests(unittest.TestCase):
    """The manifest detects document-count, version, and content-version drift."""

    def _write_and_read(self) -> tuple[Path, CorpusManifest]:
        cfg = RagConfig(knowledge_dir=DEFAULT_KNOWLEDGE_DIR)
        b = load_corpus(cfg)
        root = Path(tempfile.mkdtemp())
        shutil.copytree(DEFAULT_KNOWLEDGE_DIR, root, dirs_exist_ok=True)
        write_manifest(root, b)
        manifest = read_manifest(root)
        self.assertIsNotNone(manifest)
        return root, manifest

    def test_correct_matches(self) -> None:
        root, manifest = self._write_and_read()
        try:
            self.assertTrue(manifest_matches_filesystem(root, manifest))
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_wrong_document_count_rejected(self) -> None:
        root, manifest = self._write_and_read()
        try:
            bad = CorpusManifest(
                version=manifest.version,
                doc_hashes=manifest.doc_hashes,
                index_version=manifest.index_version,
                document_count=999,
            )
            self.assertFalse(manifest_matches_filesystem(root, bad))
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_wrong_index_version_rejected(self) -> None:
        root, manifest = self._write_and_read()
        try:
            bad = CorpusManifest(
                version="000000000000",
                doc_hashes=manifest.doc_hashes,
                index_version="000000000000",
                document_count=manifest.document_count,
            )
            self.assertFalse(manifest_matches_filesystem(root, bad))
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_version_index_version_mismatch_rejected(self) -> None:
        root, manifest = self._write_and_read()
        try:
            bad = CorpusManifest(
                version="different",
                doc_hashes=manifest.doc_hashes,
                index_version=manifest.index_version,
                document_count=manifest.document_count,
            )
            self.assertFalse(manifest_matches_filesystem(root, bad))
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_index_version_is_content_derived(self) -> None:
        cfg = RagConfig(knowledge_dir=DEFAULT_KNOWLEDGE_DIR)
        b = load_corpus(cfg)
        version = index_version_for(b.documents)
        self.assertEqual(len(version), 12)
        self.assertEqual(version, b.index_version)
        # Different chunking (max_chunk_chars) does not change the version.
        alt = load_corpus(
            RagConfig(
                knowledge_dir=DEFAULT_KNOWLEDGE_DIR, max_chunk_chars=400
            )
        )
        self.assertEqual(alt.index_version, b.index_version)
        self.assertNotEqual(len(alt.chunks), len(b.chunks))


class DatasetIntegrityTests(unittest.TestCase):
    """Phase 6 dataset counts match the docs and dev/holdout stay separate."""

    def test_dataset_counts_match_quality_md(self) -> None:
        self.assertEqual(len(q.PARAPHRASE_DEV), 38)
        self.assertEqual(len(q.PARAPHRASE_HOLDOUT), 24)
        self.assertEqual(len(q.HARD_NEGATIVES), 7)
        self.assertEqual(len(q.MULTI_DOC), 6)
        self.assertEqual(len(q.LIST_CASES), 10)
        self.assertEqual(len(q.AMBIGUOUS_LIVE_FACT), 20)
        self.assertEqual(len(q.FALSE_BLOCK_LEDGER), 12)

    def test_dev_holdout_disjoint(self) -> None:
        dev = {c.query for c in q.PARAPHRASE_DEV}
        holdout = {c.query for c in q.PARAPHRASE_HOLDOUT}
        self.assertEqual(dev & holdout, set())

    def test_false_block_ledger_all_currently_blocked(self) -> None:
        blocked = {
            qry for qry in q.FALSE_BLOCK_LEDGER
            if not classify_query(qry).is_allowed
        }
        self.assertEqual(blocked, set(q.FALSE_BLOCK_LEDGER))

    def test_failure_record_serialises(self) -> None:
        record = FailureRecord(
            query="q",
            kind=FailureKind.HARD_NEGATIVE_TRAP,
            expected=("doc-a",),
            got=("doc-b",),
            trap="doc-trap",
            detail="expected_rank=2 trap_rank=1",
        )
        payload = record.to_json()
        self.assertEqual(payload["kind"], "hard_negative_trap")
        self.assertEqual(payload["trap"], "doc-trap")


class QualityReportDeterminismTests(unittest.TestCase):
    """QualityReport and CoverageReport are deterministic."""

    def test_report_is_deterministic(self) -> None:
        retriever = _make_retriever()
        allowed = [c for c in q.PARAPHRASE_DEV if classify_query(c.query).is_allowed]
        first = evaluate_quality(
            retrieve=retriever.retrieve,
            queries=tuple(allowed[:10]),
            top_k=3,
            index_version="v",
            document_count=12,
            chunk_count=51,
        )
        second = evaluate_quality(
            retrieve=retriever.retrieve,
            queries=tuple(allowed[:10]),
            top_k=3,
            index_version="v",
            document_count=12,
            chunk_count=51,
        )
        self.assertEqual(first, second)
        self.assertEqual(first.to_json(), second.to_json())


if __name__ == "__main__":
    unittest.main()
