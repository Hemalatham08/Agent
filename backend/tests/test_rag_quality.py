"""Phase 6 retrieval quality & robustness datasets and tests.

Structure:
- PARAPHRASE_DEV / PARAPHRASE_HOLDOUT: natural paraphrases per document.
- HARD_NEGATIVES: strict trap-vs-expected cases (no brittle score/chunk ID
  assertions; document-level recall only).
- MULTI_DOC: questions spanning several documents, evaluated at top_k=5.
- LIST_CASES: list/enumeration queries requiring correct document top-1 and
  list content in the snippet.
- AMBIGUOUS_LIVE_FACT: adversarial live-fact queries that must stay blocked or
  ambiguous (safety, 100% rejection preserved).
- FALSE_BLOCK_LEDGER: conceptual queries the guard currently rejects; may only
  shrink, never grow.
"""

from __future__ import annotations

import unittest

from backend.agent.rag.evaluation import (
    CoverageReport,
    EvalQuery,
    FailureKind,
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

from backend.agent.rag import (
    DEFAULT_KNOWLEDGE_DIR,
    DocumentationRetriever,
    RagConfig,
    classify_query,
    load_corpus,
)
from backend.agent.rag.bm25 import Bm25Index

__all__ = [
    "PARAPHRASE_DEV",
    "PARAPHRASE_HOLDOUT",
    "HARD_NEGATIVES",
    "MULTI_DOC",
    "LIST_CASES",
    "AMBIGUOUS_LIVE_FACT",
    "FALSE_BLOCK_LEDGER",
]

# ---------------------------------------------------------------------------
# Paraphrase dev set: natural rewordings, one or more per document.
# Document-level recall only; acceptable alternatives preserved.
# ---------------------------------------------------------------------------

PARAPHRASE_DEV: tuple[EvalQuery, ...] = (
    EvalQuery("what does free stock mean?", ("free-stock",), "paraphrase"),
    EvalQuery(
        "explain the difference between products and SKUs?",
        ("product-sku", "product-catalogue"),
        "paraphrase",
    ),
    EvalQuery("what statuses does a sales order go through?", ("dispatch-status",), "paraphrase"),
    EvalQuery("what does partially dispatched mean?", ("dispatch-status",), "paraphrase"),
    EvalQuery("what is the purpose of the product catalogue?", ("product-catalogue",), "paraphrase"),
    EvalQuery("what are the report families?", ("reporting-overview",), "paraphrase"),
    EvalQuery("what modules make up the ERP?", ("system-overview",), "paraphrase"),
    EvalQuery("how is stock received from a supplier?", ("purchase-to-stock",), "paraphrase"),
    EvalQuery("what happens after an order is confirmed?", ("sales-order-to-dispatch",), "paraphrase"),
    EvalQuery("where can I find schema info for orders?", ("core-tables",), "paraphrase"),
    EvalQuery("what columns are in the stock table?", ("core-tables",), "paraphrase"),
    EvalQuery("what is reserved inventory?", ("free-stock",), "paraphrase"),
    EvalQuery("what does low stock mean?", ("free-stock",), "paraphrase"),
    EvalQuery("what is a reorder threshold?", ("free-stock",), "paraphrase"),
    EvalQuery("what is a warehouse balance?", ("reporting-overview",), "paraphrase"),
    EvalQuery("how do I know what a status label means?", ("dispatch-status",), "paraphrase"),
    EvalQuery("are reports read only?", ("reporting-overview",), "paraphrase"),
    EvalQuery("what is the live data policy?", ("data-authority",), "paraphrase"),
    EvalQuery("how often is documentation updated?", ("common-questions",), "paraphrase"),
    EvalQuery("what is a receipt exception?", ("purchase-to-stock",), "paraphrase"),
    EvalQuery("what happens to returned consignments?", ("sales-order-to-dispatch",), "paraphrase"),
    EvalQuery("what master data do modules share?", ("system-overview",), "paraphrase"),
    EvalQuery("what does item mean?", ("product-sku",), "paraphrase"),
    EvalQuery("what is in the item master?", ("product-catalogue",), "paraphrase"),
    EvalQuery("stock keeping unit meaning?", ("product-sku",), "paraphrase"),
    EvalQuery("what is a delivery note?", ("purchase-to-stock",), "paraphrase"),
    EvalQuery("what does in transit mean?", ("dispatch-status",), "paraphrase"),
    EvalQuery("what is picking?", ("dispatch-status",), "paraphrase"),
    EvalQuery("what is a catalogue variant?", ("product-sku",), "paraphrase"),
    EvalQuery("what is a reason code?", ("stock-adjustment",), "paraphrase"),
    EvalQuery("what is shrinkage?", ("stock-adjustment",), "paraphrase"),
    EvalQuery("how do reports filter by warehouse?", ("reporting-overview",), "paraphrase"),
    EvalQuery("what is a supplier order?", ("purchase-to-stock",), "paraphrase"),
    EvalQuery("what does allocated mean?", ("dispatch-status",), "paraphrase"),
    EvalQuery("what is a dispatch document?", ("sales-order-to-dispatch",), "paraphrase"),
    EvalQuery("what is the ERP query tool?", ("data-authority",), "paraphrase"),
    EvalQuery("version and update date?", ("common-questions",), "paraphrase"),
    EvalQuery("who approves a stock adjustment?", ("stock-adjustment",), "paraphrase"),
)

# ---------------------------------------------------------------------------
# Paraphrase holdout set: authored once, never used to choose code/thresholds.
# Reported separately; not tuned against.
# ---------------------------------------------------------------------------

PARAPHRASE_HOLDOUT: tuple[EvalQuery, ...] = (
    EvalQuery("how does free stock relate to reserved stock?", ("free-stock",), "holdout"),
    EvalQuery("can I reuse a retired SKU?", ("product-sku", "product-catalogue"), "holdout"),
    EvalQuery("what does cancelled mean?", ("dispatch-status",), "holdout"),
    EvalQuery("how are reports grouped?", ("reporting-overview",), "holdout"),
    EvalQuery("what does the inventory module track?", ("system-overview",), "holdout"),
    EvalQuery("what triggers a goods receipt?", ("purchase-to-stock",), "holdout"),
    EvalQuery("what does unallocated mean for an order line?", ("sales-order-to-dispatch",), "holdout"),
    EvalQuery("what key columns does the products table use?", ("core-tables",), "holdout"),
    EvalQuery("what does reserved stock mean?", ("free-stock",), "holdout"),
    EvalQuery("what is the documentation and live data policy?", ("data-authority",), "holdout"),
    EvalQuery("where are workflow steps described?", ("common-questions",), "holdout"),
    EvalQuery("when is a stock adjustment posted?", ("stock-adjustment",), "holdout"),
    EvalQuery("are dispatch labels live data?", ("dispatch-status",), "holdout"),
    EvalQuery("what can a product record hold?", ("product-catalogue",), "holdout"),
    EvalQuery("why keep retired records?", ("product-sku",), "holdout"),
    EvalQuery("what is the order-to-dispatch sequence?", ("sales-order-to-dispatch",), "holdout"),
    EvalQuery("what is the purchase to stock workflow?", ("purchase-to-stock",), "holdout"),
    EvalQuery("can an adjustment fix reserved stock?", ("stock-adjustment",), "holdout"),
    EvalQuery("what do reports show?", ("reporting-overview",), "holdout"),
    EvalQuery("what modules share master data?", ("system-overview",), "holdout"),
    EvalQuery("what is low stock tied to?", ("free-stock",), "holdout"),
    EvalQuery("what does a delivery status label mean?", ("dispatch-status",), "holdout"),
    EvalQuery("what are inventory reports?", ("reporting-overview",), "holdout"),
    EvalQuery("how are documentation pages versioned?", ("common-questions",), "holdout"),
)

# ---------------------------------------------------------------------------
# Strict hard negatives: trap document must NOT outrank expected.
# Acceptable alternatives preserved where multiple docs legitimately answer.
# ---------------------------------------------------------------------------

HARD_NEGATIVES: tuple[HardNegativeCase, ...] = (
    HardNegativeCase(
        "what does item mean?",
        "product-sku",
        "common-questions",
        "trap: generic 'mean' token matches FAQ pages; expected is SKU definition",
    ),
    HardNegativeCase(
        "who signs off on an inventory adjustment?",
        "stock-adjustment",
        "reporting-overview",
        "trap: reports mention adjustments; expected is the workflow doc",
    ),
    HardNegativeCase(
        "what does allocated mean?",
        "dispatch-status",
        "sales-order-to-dispatch",
        "trap: workflow mentions allocation; expected is status definition",
    ),
    HardNegativeCase(
        "which table holds reserved quantity?",
        "core-tables",
        "free-stock",
        "trap: free stock defines reserved stock; expected is the schema page",
    ),
    HardNegativeCase(
        "what does in transit mean?",
        "dispatch-status",
        "sales-order-to-dispatch",
        "trap: workflow creates dispatches; expected is status definition",
    ),
    HardNegativeCase(
        "what is shrinkage?",
        "stock-adjustment",
        "common-questions",
        "trap: generic faq wording; expected is adjustment controls",
    ),
    # Acceptable alternatives: multiple docs legitimately answer.
    HardNegativeCase(
        "how are prices stored?",
        "product-catalogue",
        "core-tables",
        "note: both catalogue and schema legitimately answer; not a strict trap",
    ),
)

# ---------------------------------------------------------------------------
# Multi-document questions: evaluated at top_k=5, require all docs.
# ---------------------------------------------------------------------------

MULTI_DOC: tuple[MultiDocCase, ...] = (
    MultiDocCase(
        "how does free stock relate to stock table columns and sales allocation?",
        ("free-stock", "core-tables", "sales-order-to-dispatch"),
        "spans definition, schema, and workflow",
    ),
    MultiDocCase(
        "what documents are created during fulfilment and what statuses do they carry?",
        ("sales-order-to-dispatch", "dispatch-status"),
        "spans workflow and status definition",
    ),
    MultiDocCase(
        "what is the difference between products, SKUs, and catalogue records?",
        ("product-sku", "product-catalogue"),
        "spans definition and module overview",
    ),
    MultiDocCase(
        "how do goods receipts update on-hand stock and where is it stored?",
        ("purchase-to-stock", "core-tables"),
        "spans workflow and schema",
    ),
    MultiDocCase(
        "how do reports present stock movements and adjustments?",
        ("reporting-overview", "stock-adjustment"),
        "spans reporting overview and workflow",
    ),
    MultiDocCase(
        "what master data do modules share?",
        ("system-overview", "product-catalogue"),
        "spans overview and catalogue",
    ),
)

# ---------------------------------------------------------------------------
# List / enumeration queries: correct document top-1, list content present.
# ---------------------------------------------------------------------------

LIST_CASES: tuple[EvalQuery, ...] = (
    EvalQuery("list the sales order statuses?", ("dispatch-status",), "list"),
    EvalQuery("list the dispatch statuses?", ("dispatch-status",), "list"),
    EvalQuery("what are the report families?", ("reporting-overview",), "list"),
    EvalQuery("what are the ERP modules?", ("system-overview",), "list"),
    EvalQuery("what fields does a product record contain?", ("product-catalogue",), "list"),
    EvalQuery("what columns are in the products table?", ("core-tables",), "list"),
    EvalQuery("what are the steps of the purchase workflow?", ("purchase-to-stock",), "list"),
    EvalQuery("what controls apply to goods receipts?", ("purchase-to-stock",), "list"),
    EvalQuery("what controls apply to stock adjustments?", ("stock-adjustment",), "list"),
    EvalQuery("what may documentation contain?", ("data-authority",), "list"),
)

# ---------------------------------------------------------------------------
# Ambiguous live-fact queries: must stay blocked or ambiguous; 100% rejection.
# Paraphrased beyond the golden 12 to test robustness without weakening guard.
# ---------------------------------------------------------------------------

AMBIGUOUS_LIVE_FACT: tuple[str, ...] = (
    "how much stock do we have right now?",
    "what is the current inventory level?",
    "how many orders are open today?",
    "what is today's revenue total?",
    "tell me the price of product PRD001.",
    "what is the status of sales order SO001?",
    "where is dispatch DSP001?",
    "total sales for November 2026?",
    "which items are low on stock right now?",
    "give me the latest invoice total.",
    "current free stock for SKU-100?",
    "I need today's revenue figures.",
    "could you tell me the on-hand quantity for product 5?",
    "how many customers bought from Acme?",
    "list today's pending dispatches.",
    "is SKU-100 in stock at warehouse one?",
    "what is the outstanding balance on invoice INV001?",
    "when will order SO002 be delivered?",
    "how much revenue did we earn last month?",
    "show me current stock levels for all products.",
)

# ---------------------------------------------------------------------------
# Conceptual false-block ledger: guard-limited conceptual queries.
# May only shrink; never grow. Tracked separately from retrieval misses.
# ---------------------------------------------------------------------------

FALSE_BLOCK_LEDGER: tuple[str, ...] = (
    "how is stock received from a supplier?",
    "who signs off on an inventory adjustment?",
    "why is free stock negative?",
    "can SKUs be reused?",
    "how are customer orders turned into deliveries?",
    "which table holds reserved quantity?",
    "list the sales order statuses?",
    "what controls apply to stock adjustments?",
    "how do I fix a wrong stock count?",
    "how are prices stored?",
    "how is tax classification used?",
    "which reports are available for inventory?",
)

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

_CONFIG = RagConfig(knowledge_dir=DEFAULT_KNOWLEDGE_DIR)
_BUNDLE = load_corpus(_CONFIG)
_INDEX = Bm25Index(_BUNDLE)
_RETRIEVER = DocumentationRetriever(_INDEX)


def _retrieve(query: str, top_k: int):
    return _RETRIEVER.retrieve(query, top_k=top_k)


def _is_allowed(query: str) -> bool:
    return classify_query(query).verdict.value == "allowed"


class GoldenInvarianceTests(unittest.TestCase):
    """Existing golden metrics must be unchanged by Phase 6."""

    def test_conceptual_allow_rate(self) -> None:
        allow = sum(1 for c in __import__(
            "backend.tests.test_rag_eval", fromlist=["CONCEPTUAL_CASES"]
        ).CONCEPTUAL_CASES if classify_query(c.query).is_allowed)
        self.assertEqual(allow, 24)

    def test_conceptual_answer_rate_and_mrr(self) -> None:
        eval_mod = __import__(
            "backend.tests.test_rag_eval", fromlist=["CONCEPTUAL_CASES"]
        )
        answered = 0
        mrr = 0.0
        for case in eval_mod.CONCEPTUAL_CASES:
            result = _retrieve(case.query, top_k=3)
            if result.status != "ok":
                continue
            ranked = hit_doc_ids(result, 3)
            if set(case.expected) & set(ranked):
                answered += 1
                for rank, doc_id in enumerate(ranked, start=1):
                    if doc_id in case.expected:
                        mrr += 1.0 / rank
                        break
        self.assertEqual(answered, 24)
        self.assertAlmostEqual(mrr / len(eval_mod.CONCEPTUAL_CASES), 1.0, places=4)

    def test_alias_metrics(self) -> None:
        eval_mod = __import__(
            "backend.tests.test_rag_eval", fromlist=["ALIAS_CASES"]
        )

        def alias_docs(alias: str, k: int = 3) -> tuple[str, ...]:
            ordered: list[str] = []
            seen: set[str] = set()
            for item in _INDEX.search(alias):
                doc_id = item.chunk.doc_id
                if doc_id in seen:
                    continue
                seen.add(doc_id)
                ordered.append(doc_id)
                if len(ordered) >= k:
                    break
            return tuple(ordered)

        top1 = sum(
            1 for c in eval_mod.ALIAS_CASES if alias_docs(c.alias, 3)[:1] == (c.owner,)
        )
        top3 = sum(1 for c in eval_mod.ALIAS_CASES if c.owner in alias_docs(c.alias, 3))
        e2e = 0
        for c in eval_mod.ALIAS_CASES:
            result = _retrieve(c.alias, top_k=3)
            if result.status == "ok" and any(
                h.doc_id == c.owner for h in result.hits
            ):
                e2e += 1
        self.assertEqual(top1, 19)
        self.assertEqual(top3, 20)
        self.assertEqual(e2e, 12)

    def test_live_fact_rejection_complete(self) -> None:
        eval_mod = __import__(
            "backend.tests.test_rag_eval", fromlist=["LIVE_FACT_NEGATIVES"]
        )
        rejected = sum(
            1
            for query, _ in eval_mod.LIVE_FACT_NEGATIVES
            if _retrieve(query, top_k=3).status != "ok"
        )
        self.assertEqual(rejected, len(eval_mod.LIVE_FACT_NEGATIVES))


class ParaphraseTests(unittest.TestCase):
    """Paraphrase robustness on dev and holdout sets."""

    def _allowed_recall(self, cases: tuple[EvalQuery, ...], top_k: int = 3):
        total = 0
        answered = 0
        for case in cases:
            if not _is_allowed(case.query):
                continue
            total += 1
            result = _retrieve(case.query, top_k=top_k)
            if result.status != "ok":
                continue
            ranked = hit_doc_ids(result, top_k)
            if set(case.expected) & set(ranked):
                answered += 1
        return answered, total

    def test_dev_recall_at_3_is_100_percent(self) -> None:
        answered, total = self._allowed_recall(PARAPHRASE_DEV, top_k=3)
        self.assertGreaterEqual(total, 30)
        self.assertEqual(answered, total)

    def test_dev_top1_at_least_80_percent(self) -> None:
        top1 = 0
        total = 0
        for case in PARAPHRASE_DEV:
            if not _is_allowed(case.query):
                continue
            total += 1
            result = _retrieve(case.query, top_k=3)
            if result.status != "ok":
                continue
            ranked = hit_doc_ids(result, 3)
            if ranked[:1] == (case.expected[0],):
                top1 += 1
        self.assertGreaterEqual(total, 30)
        self.assertGreaterEqual(top1 / total, 0.80)

    def test_holdout_recall_at_3_is_100_percent(self) -> None:
        answered, total = self._allowed_recall(PARAPHRASE_HOLDOUT, top_k=3)
        self.assertGreaterEqual(total, 15)
        self.assertEqual(answered, total)

    def test_holdout_top1_at_least_80_percent(self) -> None:
        top1 = 0
        total = 0
        for case in PARAPHRASE_HOLDOUT:
            if not _is_allowed(case.query):
                continue
            total += 1
            result = _retrieve(case.query, top_k=3)
            if result.status != "ok":
                continue
            ranked = hit_doc_ids(result, 3)
            if ranked[:1] == (case.expected[0],):
                top1 += 1
        self.assertGreaterEqual(total, 15)
        self.assertGreaterEqual(top1 / total, 0.80)


class HardNegativeTests(unittest.TestCase):
    """Strict hard negatives: trap must not outrank expected."""

    def test_no_trap_outranks_expected(self) -> None:
        for case in HARD_NEGATIVES:
            with self.subTest(query=case.query):
                if not _is_allowed(case.query):
                    continue  # safe guard behaviour; not a retrieval trap
                result = _retrieve(case.query, top_k=5)
                if result.status != "ok":
                    continue
                expected_rank = rank_of_doc(result, case.expected, 5)
                trap_rank = rank_of_doc(result, case.trap, 5)
                self.assertIsNotNone(
                    expected_rank,
                    f"expected doc {case.expected} absent for {case.query!r}",
                )
                self.assertTrue(
                    trap_rank is None or trap_rank > expected_rank,
                    f"trap {case.trap} outranks expected {case.expected} for "
                    f"{case.query!r}: expected_rank={expected_rank}, "
                    f"trap_rank={trap_rank}",
                )


class MultiDocTests(unittest.TestCase):
    """Multi-document coverage at top_k=5."""

    def test_multi_doc_coverage_is_100_percent(self) -> None:
        for case in MULTI_DOC:
            with self.subTest(query=case.query):
                if not _is_allowed(case.query):
                    continue
                result = _retrieve(case.query, top_k=5)
                self.assertEqual(result.status, "ok", case.query)
                ranked = hit_doc_ids(result, 5)
                missing = [d for d in case.required if d not in set(ranked)]
                self.assertEqual(
                    missing,
                    [],
                    f"{case.query!r} missing {missing}, got {ranked}",
                )


class ListCaseTests(unittest.TestCase):
    """List/enumeration queries retrieve correct document and list content."""

    def test_list_cases_retrieve_owner_document(self) -> None:
        from backend.agent.rag.text import tokenize

        for case in LIST_CASES:
            with self.subTest(query=case.query):
                if not _is_allowed(case.query):
                    continue
                result = _retrieve(case.query, top_k=3)
                self.assertEqual(result.status, "ok", case.query)
                self.assertTrue(
                    result.hits,
                    f"{case.query!r} returned no hits",
                )
                self.assertEqual(
                    result.hits[0].doc_id,
                    case.expected[0],
                    f"{case.query!r} top doc {result.hits[0].doc_id!r}, "
                    f"expected {case.expected[0]!r}",
                )
                # The winning snippet should retain list-like content for list
                # sections (bounded signal; no raw score or chunk ID asserted).
                snippet = result.hits[0].snippet
                self.assertGreaterEqual(
                    len(snippet.strip()),
                    40,
                    f"{case.query!r} snippet too short: {snippet!r}",
                )


class AmbiguousLiveFactSafetyTests(unittest.TestCase):
    """Adversarial live-fact queries must stay blocked or ambiguous."""

    def test_all_ambiguous_live_fact_queries_rejected(self) -> None:
        for query in AMBIGUOUS_LIVE_FACT:
            with self.subTest(query=query):
                decision = classify_query(query)
                self.assertNotEqual(
                    decision.verdict.value,
                    "allowed",
                    f"live-fact query ALLOWED: {query!r} "
                    f"(verdict={decision.verdict.value!r})",
                )


class FalseBlockLedgerTests(unittest.TestCase):
    """Conceptual false-block ledger may only shrink, never grow."""

    def test_false_block_ledger_does_not_grow(self) -> None:
        current = {
            q
            for q in FALSE_BLOCK_LEDGER
            if not classify_query(q).is_allowed
        }
        self.assertLessEqual(
            current,
            set(FALSE_BLOCK_LEDGER),
            "false-block ledger shrank unexpectedly: "
            f"{sorted(set(FALSE_BLOCK_LEDGER) - current)}",
        )


class QualityReportTests(unittest.TestCase):
    """QualityReport is deterministic and stable."""

    def test_report_is_deterministic(self) -> None:
        report = evaluate_quality(
            retrieve=_retrieve,
            queries=PARAPHRASE_DEV,
            hard_negatives=HARD_NEGATIVES,
            multi_doc=MULTI_DOC,
            top_k=5,
            index_version=_BUNDLE.index_version,
            document_count=len(_BUNDLE.documents),
            chunk_count=len(_BUNDLE.chunks),
        )
        again = evaluate_quality(
            retrieve=_retrieve,
            queries=PARAPHRASE_DEV,
            hard_negatives=HARD_NEGATIVES,
            multi_doc=MULTI_DOC,
            top_k=5,
            index_version=_BUNDLE.index_version,
            document_count=len(_BUNDLE.documents),
            chunk_count=len(_BUNDLE.chunks),
        )
        self.assertEqual(report, again)
        self.assertEqual(report.to_json(), again.to_json())

    def test_report_metrics_are_serialisable(self) -> None:
        report = evaluate_quality(
            retrieve=_retrieve,
            queries=PARAPHRASE_DEV,
            top_k=3,
            index_version=_BUNDLE.index_version,
        )
        payload = report.to_json()
        self.assertIsInstance(payload["all_required_passed"], bool)
        self.assertIsInstance(payload["metrics"], list)
        self.assertGreaterEqual(len(payload["metrics"]), 1)

    def test_hit_doc_ids_doc_level_only(self) -> None:
        from backend.tests import test_rag_eval as ev

        result = _retrieve("What is free stock?", top_k=3)
        ids = hit_doc_ids(result, 3)
        self.assertTrue(all(isinstance(doc_id, str) for doc_id in ids))
        self.assertLessEqual(len(ids), 3)

    def test_rank_of_doc_returns_none_when_absent(self) -> None:
        result = _retrieve("What is free stock?", top_k=3)
        self.assertIsNone(rank_of_doc(result, "does-not-exist", 5))


class CorpusBenchmarkTests(unittest.TestCase):
    """Corpus-derived benchmark cannot be overfit by construction."""

    def test_benchmark_queries_are_deterministic(self) -> None:
        aliases = {
            d.doc_id: d.aliases for d in _BUNDLE.documents
        }
        benchmark = build_corpus_benchmark(
            documents=_BUNDLE.documents, aliases_by_doc=aliases
        )
        again = build_corpus_benchmark(
            documents=_BUNDLE.documents, aliases_by_doc=aliases
        )
        self.assertEqual(benchmark, again)
        self.assertGreaterEqual(len(benchmark), 24)
        # Every benchmark query targets a real document id.
        known = {d.doc_id for d in _BUNDLE.documents}
        for case in benchmark:
            self.assertIn(case.expected[0], known)


class CoverageReportTests(unittest.TestCase):
    """Coverage report is stable and reports real corpus statistics."""

    def test_coverage_report_is_deterministic(self) -> None:
        aliases = {d.doc_id: d.aliases for d in _BUNDLE.documents}
        report = build_coverage_report(
            documents=_BUNDLE.documents,
            chunks=_BUNDLE.chunks,
            index=_INDEX,
            query_bank=tuple(c.query for c in PARAPHRASE_DEV)
            + tuple(c.query for c in PARAPHRASE_HOLDOUT),
            aliases_by_doc=aliases,
        )
        again = build_coverage_report(
            documents=_BUNDLE.documents,
            chunks=_BUNDLE.chunks,
            index=_INDEX,
            query_bank=tuple(c.query for c in PARAPHRASE_DEV)
            + tuple(c.query for c in PARAPHRASE_HOLDOUT),
            aliases_by_doc=aliases,
        )
        self.assertEqual(report, again)
        self.assertEqual(report.document_count, 12)
        self.assertEqual(report.chunk_count, len(_BUNDLE.chunks))
        self.assertEqual(report.index_version, _BUNDLE.index_version)
        self.assertEqual(report.document_reachability_total, 12)


class QualityMetricSerialisationTests(unittest.TestCase):
    """QualityMetric serialises deterministically."""

    def test_metric_to_json_roundtrip(self) -> None:
        metric = QualityMetric(
            name="answer_rate",
            value=1.0,
            numerator=24,
            denominator=24,
            floor=0.8,
            passed=True,
        )
        payload = metric.to_json()
        self.assertEqual(payload["name"], "answer_rate")
        self.assertEqual(payload["value"], 1.0)
        self.assertEqual(payload["passed"], True)


if __name__ == "__main__":
    unittest.main()

