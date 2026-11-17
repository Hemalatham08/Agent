"""Deterministic golden retrieval evaluation for the documentation RAG corpus.

This suite measures whether the shipped knowledge corpus answers realistic
questions, instead of only checking pipeline mechanics. It is deliberately
read-only: it constructs one ``RagConfig``, one corpus bundle, one BM25 index,
and one retriever at import time and never mutates them.

Determinism contract
--------------------
* The configuration is built explicitly with ``RagConfig(knowledge_dir=...)``
  and never with ``RagConfig.from_env()``, so a stray ``RAG_*`` environment
  variable cannot change the measured baseline.
* The corpus, index, and guard are pure and offline. There is no clock,
  network, database, LLM, or filesystem write in this module.
* Document order comes from the ordered ``hits`` tuple, never from a set.

Measured baseline (shipped corpus, 12 documents, 63 chunks)
-----------------------------------------------------------
==========================  =========
conceptual allow-rate       19/24
conceptual answer-rate @3   19/24
conceptual MRR              0.7708
alias top-1 (index)         12/20
alias top-3 (index)         17/20
alias answer-rate (e2e)      7/20
live-fact rejection         12/12

Measured after Phase 2 guard recall improvements
------------------------------------------------
==========================  =========
conceptual allow-rate       24/24
conceptual answer-rate @3   24/24
conceptual MRR              1.0000
alias top-1 (index)         19/20
alias top-3 (index)         20/20
alias answer-rate (e2e)     12/20
live-fact rejection         12/12
==========================  =========

The five non-allowed conceptual questions are the documented guard misses in
``KNOWN_GUARD_MISSES``. Their desired behaviour is encoded in the skipped
``GuardRecallTargetTests`` class, which becomes the definition of done when the
guard recall rules land.

Threshold policy
----------------
Floors sit one case below the measured baseline, so a vocabulary-neutral corpus
edit or a chunk-boundary shift does not flake the suite, while a real drop of
two or more cases fails loudly. Safety metrics (live-fact rejection) are exact.
No test asserts a raw BM25 score, a chunk id, or an ``index_version`` hash.
"""

from __future__ import annotations

import unittest
from collections import Counter
from dataclasses import dataclass

from backend.agent.rag import (
    BM25_B,
    BM25_K1,
    DEFAULT_KNOWLEDGE_DIR,
    DEFAULT_MAX_HITS_PER_DOC,
    DEFAULT_MAX_SNIPPET_CHARS,
    DEFAULT_MAX_TOTAL_CHARS,
    DEFAULT_MIN_SCORE,
    DEFAULT_TOP_K,
    DISCLAIMER,
    Bm25Index,
    DocumentationRetriever,
    GuardVerdict,
    RagConfig,
    classify_query,
    load_corpus,
)


# ---------------------------------------------------------------------------
# Read-only evaluation context (built once, shared by every test class)
# ---------------------------------------------------------------------------

_CONFIG = RagConfig(knowledge_dir=DEFAULT_KNOWLEDGE_DIR)
_BUNDLE = load_corpus(_CONFIG)
_INDEX = Bm25Index(_BUNDLE)
_RETRIEVER = DocumentationRetriever(_INDEX)


# ---------------------------------------------------------------------------
# Golden case schema
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvalCase:
    """One conceptual question with its acceptable documents.

    ``expected`` is a tuple because some questions are legitimately answered by
    more than one page. The first entry is the preferred document; recall and
    MRR accept any entry, which keeps the suite from over-fitting one ranking.
    """

    query: str
    expected: tuple[str, ...]
    note: str = ""


@dataclass(frozen=True)
class AliasCase:
    """One curated corpus alias and the document that owns it."""

    alias: str
    owner: str


# ---------------------------------------------------------------------------
# Corpus inventory (the golden contract)
# ---------------------------------------------------------------------------

EXPECTED_DOCUMENT_COUNT = 12

EXPECTED_DOC_IDS = (
    "system-overview",
    "product-catalogue",
    "reporting-overview",
    "free-stock",
    "product-sku",
    "dispatch-status",
    "common-questions",
    "data-authority",
    "core-tables",
    "purchase-to-stock",
    "sales-order-to-dispatch",
    "stock-adjustment",
)

EXPECTED_ALIASES: dict[str, tuple[str, ...]] = {
    "system-overview": ("erp overview",),
    "product-catalogue": ("product master", "item master"),
    "reporting-overview": ("reports",),
    "free-stock": ("available stock", "low stock"),
    "product-sku": ("item", "stock keeping unit"),
    "dispatch-status": ("order status", "delivery status"),
    "common-questions": ("faq",),
    "data-authority": ("live data policy", "documentation policy"),
    "core-tables": ("database schema",),
    "purchase-to-stock": ("procurement workflow", "goods receipt"),
    "sales-order-to-dispatch": ("order fulfilment", "delivery workflow"),
    "stock-adjustment": ("cycle count", "stock correction"),
}


# ---------------------------------------------------------------------------
# Conceptual golden set: two natural questions per document
# ---------------------------------------------------------------------------

CONCEPTUAL_CASES: tuple[EvalCase, ...] = (
    EvalCase(
        "What modules does the ERP have?",
        ("system-overview",),
        "module inventory is described in the system overview",
    ),
    EvalCase(
        "What is the iFive ERP system overview?",
        ("system-overview",),
    ),
    EvalCase(
        "What is the product catalogue module?",
        ("product-catalogue",),
    ),
    EvalCase(
        "What does the product catalogue module do?",
        ("product-catalogue",),
    ),
    EvalCase(
        "What does the reporting module show?",
        ("reporting-overview",),
    ),
    EvalCase(
        "What report families exist?",
        ("reporting-overview",),
    ),
    EvalCase(
        "What is free stock?",
        ("free-stock",),
    ),
    EvalCase(
        "What does reserved stock mean?",
        ("free-stock",),
    ),
    EvalCase(
        "What is a SKU?",
        ("product-sku",),
    ),
    EvalCase(
        "What is the difference between a product and a SKU?",
        ("product-sku", "product-catalogue"),
        "either page explains the product/SKU distinction",
    ),
    EvalCase(
        "What does partially dispatched mean?",
        ("dispatch-status",),
    ),
    EvalCase(
        "Which statuses can a sales order have?",
        ("dispatch-status",),
        "known guard miss: marked ambiguous before retrieval",
    ),
    EvalCase(
        "What are the common documentation questions?",
        ("common-questions",),
    ),
    EvalCase(
        "Does the documentation show current stock?",
        ("common-questions", "data-authority"),
        "the FAQ and the policy both answer this",
    ),
    EvalCase(
        "Can documentation be used for live totals?",
        ("data-authority",),
        "known guard miss: marked ambiguous before retrieval",
    ),
    EvalCase(
        "What is the documentation and live data policy?",
        ("data-authority",),
    ),
    EvalCase(
        "What tables store sales orders?",
        ("core-tables",),
        "known guard miss: marked ambiguous before retrieval",
    ),
    EvalCase(
        "What columns does the stock table have?",
        ("core-tables",),
    ),
    EvalCase(
        "What is the goods receipt process?",
        ("purchase-to-stock",),
    ),
    EvalCase(
        "What is the purchase to stock workflow?",
        ("purchase-to-stock",),
    ),
    EvalCase(
        "What happens after a sales order is confirmed?",
        ("sales-order-to-dispatch",),
        "known guard miss: marked ambiguous before retrieval",
    ),
    EvalCase(
        "What is the sales order to dispatch workflow?",
        ("sales-order-to-dispatch",),
    ),
    EvalCase(
        "How does a stock adjustment work?",
        ("stock-adjustment",),
    ),
    EvalCase(
        "Who approves a stock adjustment?",
        ("stock-adjustment",),
        "known guard miss: marked ambiguous before retrieval",
    ),
)


# Questions the guard currently refuses even though the corpus answers them.
# The ledger is directional: it may shrink as the guard improves, but a new
# entry means a guard regression.
KNOWN_GUARD_MISSES = frozenset(
    {
        "Which statuses can a sales order have?",
        "Can documentation be used for live totals?",
        "What tables store sales orders?",
        "What happens after a sales order is confirmed?",
        "Who approves a stock adjustment?",
    }
)


# ---------------------------------------------------------------------------
# Alias golden set (index-level reachability)
# ---------------------------------------------------------------------------

ALIAS_CASES: tuple[AliasCase, ...] = (
    AliasCase("erp overview", "system-overview"),
    AliasCase("product master", "product-catalogue"),
    AliasCase("item master", "product-catalogue"),
    AliasCase("reports", "reporting-overview"),
    AliasCase("available stock", "free-stock"),
    AliasCase("low stock", "free-stock"),
    AliasCase("item", "product-sku"),
    AliasCase("stock keeping unit", "product-sku"),
    AliasCase("order status", "dispatch-status"),
    AliasCase("delivery status", "dispatch-status"),
    AliasCase("faq", "common-questions"),
    AliasCase("live data policy", "data-authority"),
    AliasCase("documentation policy", "data-authority"),
    AliasCase("database schema", "core-tables"),
    AliasCase("procurement workflow", "purchase-to-stock"),
    AliasCase("goods receipt", "purchase-to-stock"),
    AliasCase("order fulfilment", "sales-order-to-dispatch"),
    AliasCase("delivery workflow", "sales-order-to-dispatch"),
    AliasCase("cycle count", "stock-adjustment"),
    AliasCase("stock correction", "stock-adjustment"),
)

# Aliases whose vocabulary is unique enough to require a top-1 result today.
TOP1_ALIASES = frozenset(
    {
        "erp overview",
        "reports",
        "low stock",
        "order status",
        "delivery status",
        "live data policy",
        "documentation policy",
        "procurement workflow",
        "goods receipt",
        "order fulfilment",
        "delivery workflow",
        "stock correction",
    }
)

# Aliases whose owner is outside the index top-3 because aliases are not part
# of ``searchable_text`` yet. The ledger may only shrink.
KNOWN_ALIAS_GAPS = frozenset({"faq", "database schema", "item master"})


# ---------------------------------------------------------------------------
# Live-fact negatives
# ---------------------------------------------------------------------------

# ``expected_kind`` is asserted only where the guard signal is unambiguous;
# ``None`` means "must be blocked or ambiguous, kind not pinned".
LIVE_FACT_NEGATIVES: tuple[tuple[str, str | None], ...] = (
    ("How many products are there?", "count"),
    ("How many open sales orders exist?", "count"),
    ("What is the total sales value this month?", "money"),
    ("What is the price of product PRD001?", None),
    ("What is the status of sales order SO001?", "status"),
    ("Where is dispatch DSP001?", None),
    ("How much stock is left for PRD001?", "quantity"),
    ("Is product PRD001 in stock?", None),
    ("Show me all orders from Acme.", "listing"),
    ("List today's invoices.", "listing"),
    ("What are today's totals?", None),
    ("What is the current stock level of SKU-100?", None),
)


# ---------------------------------------------------------------------------
# Aggregate floors (baseline minus one case)
# ---------------------------------------------------------------------------

CONCEPTUAL_ALLOW_FLOOR = 18
CONCEPTUAL_ANSWER_FLOOR = 18
CONCEPTUAL_MRR_FLOOR = 0.70
ALIAS_TOP1_FLOOR = 11
ALIAS_TOP3_FLOOR = 16
ALIAS_E2E_FLOOR = 6

# ---------------------------------------------------------------------------
# Aggregate targets (post-improvement goals, recorded separately from floors)
# ---------------------------------------------------------------------------

CONCEPTUAL_ALLOW_TARGET = 24
CONCEPTUAL_ANSWER_TARGET = 24
CONCEPTUAL_MRR_TARGET = 1.0
ALIAS_TOP1_TARGET = 17
ALIAS_TOP3_TARGET = 20
ALIAS_E2E_TARGET = 16


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def hit_doc_ids(result, k: int = 3) -> tuple[str, ...]:
    """Return distinct document ids in hit order, truncated to ``k``."""

    ordered: list[str] = []
    seen: set[str] = set()
    for hit in result.hits:
        if hit.doc_id in seen:
            continue
        seen.add(hit.doc_id)
        ordered.append(hit.doc_id)
        if len(ordered) >= k:
            break
    return tuple(ordered)


def alias_doc_ids(alias: str, k: int = 3) -> tuple[str, ...]:
    """Return distinct document ids ranked for ``alias`` by the raw index."""

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


def rank_of(result, expected: tuple[str, ...]) -> int:
    """Return the best 1-based rank of any acceptable document, or 0."""

    for rank, doc_id in enumerate(hit_doc_ids(result, k=5), start=1):
        if doc_id in expected:
            return rank
    return 0


def baseline_conceptual_cases() -> tuple[EvalCase, ...]:
    """Conceptual cases the guard is expected to allow today."""

    return tuple(
        case for case in CONCEPTUAL_CASES if case.query not in KNOWN_GUARD_MISSES
    )


def conceptual_allow_count() -> int:
    return sum(
        1 for case in CONCEPTUAL_CASES if classify_query(case.query).is_allowed
    )


def conceptual_answer_count() -> int:
    answered = 0
    for case in CONCEPTUAL_CASES:
        result = _RETRIEVER.retrieve(case.query, top_k=3)
        if result.status != "ok":
            continue
        if set(case.expected) & set(hit_doc_ids(result, 3)):
            answered += 1
    return answered


def conceptual_mrr() -> float:
    total = 0.0
    for case in CONCEPTUAL_CASES:
        rank = rank_of(_RETRIEVER.retrieve(case.query, top_k=3), case.expected)
        if rank:
            total += 1.0 / rank
    return total / len(CONCEPTUAL_CASES)


def alias_top1_count() -> int:
    return sum(
        1
        for case in ALIAS_CASES
        if alias_doc_ids(case.alias, 1)[:1] == (case.owner,)
    )


def alias_top3_count() -> int:
    return sum(
        1 for case in ALIAS_CASES if case.owner in alias_doc_ids(case.alias, 3)
    )


def alias_end_to_end_count() -> int:
    answered = 0
    for case in ALIAS_CASES:
        result = _RETRIEVER.retrieve(case.alias, top_k=3)
        if result.status == "ok" and case.owner in hit_doc_ids(result, 3):
            answered += 1
    return answered


def all_eval_queries() -> tuple[str, ...]:
    return (
        tuple(case.query for case in CONCEPTUAL_CASES)
        + tuple(case.alias for case in ALIAS_CASES)
        + tuple(query for query, _ in LIVE_FACT_NEGATIVES)
    )


# ---------------------------------------------------------------------------
# Corpus inventory
# ---------------------------------------------------------------------------


class CorpusInventoryTests(unittest.TestCase):
    def test_document_ids_match_the_golden_inventory(self) -> None:
        actual = tuple(document.doc_id for document in _BUNDLE.documents)
        self.assertEqual(
            len(actual),
            EXPECTED_DOCUMENT_COUNT,
            "shipped corpus changed; update EXPECTED_DOC_IDS and the golden cases",
        )
        self.assertEqual(set(actual), set(EXPECTED_DOC_IDS))
        self.assertEqual(len(set(actual)), len(actual))

    def test_alias_inventory_matches_the_golden_map(self) -> None:
        actual = {
            document.doc_id: tuple(document.aliases)
            for document in _BUNDLE.documents
        }
        self.assertEqual(set(actual), set(EXPECTED_ALIASES))
        for doc_id, expected in EXPECTED_ALIASES.items():
            self.assertEqual(
                set(actual[doc_id]),
                set(expected),
                f"alias inventory changed for {doc_id}; update the golden map",
            )

    def test_every_alias_is_owned_by_exactly_one_document(self) -> None:
        owners: dict[str, list[str]] = {}
        for document in _BUNDLE.documents:
            for alias in document.aliases:
                owners.setdefault(alias, []).append(document.doc_id)
        duplicates = {
            alias: doc_ids
            for alias, doc_ids in owners.items()
            if len(doc_ids) != 1
        }
        self.assertEqual(duplicates, {})

    def test_every_document_is_covered_by_a_conceptual_case(self) -> None:
        primary = {case.expected[0] for case in CONCEPTUAL_CASES}
        self.assertEqual(primary, set(EXPECTED_DOC_IDS))

    def test_every_document_owns_an_alias_case(self) -> None:
        owners = {case.owner for case in ALIAS_CASES}
        self.assertEqual(owners, set(EXPECTED_DOC_IDS))

    def test_expected_documents_exist_in_the_bundle(self) -> None:
        known = {document.doc_id for document in _BUNDLE.documents}
        for case in CONCEPTUAL_CASES:
            for doc_id in case.expected:
                self.assertIn(doc_id, known, f"unknown doc in case {case.query!r}")
        for case in ALIAS_CASES:
            self.assertIn(case.owner, known, f"unknown owner for {case.alias!r}")

    def test_alias_count_matches_the_golden_map(self) -> None:
        expected_total = sum(len(values) for values in EXPECTED_ALIASES.values())
        actual_total = sum(len(document.aliases) for document in _BUNDLE.documents)
        self.assertEqual(actual_total, expected_total)
        self.assertEqual(actual_total, len(ALIAS_CASES))


# ---------------------------------------------------------------------------
# Configuration pinning
# ---------------------------------------------------------------------------


class ConfigurationPinningTests(unittest.TestCase):
    def test_eval_config_uses_explicit_defaults(self) -> None:
        self.assertIs(_CONFIG.enabled, False)
        self.assertEqual(_CONFIG.default_top_k, DEFAULT_TOP_K)
        self.assertEqual(_CONFIG.min_score, DEFAULT_MIN_SCORE)
        self.assertEqual(_CONFIG.max_snippet_chars, DEFAULT_MAX_SNIPPET_CHARS)
        self.assertEqual(_CONFIG.max_total_chars, DEFAULT_MAX_TOTAL_CHARS)
        self.assertEqual(_CONFIG.max_hits_per_doc, DEFAULT_MAX_HITS_PER_DOC)
        self.assertEqual(_CONFIG.bm25_k1, BM25_K1)
        self.assertEqual(_CONFIG.bm25_b, BM25_B)

    def test_retriever_wraps_the_evaluated_index(self) -> None:
        self.assertIs(_RETRIEVER.index, _INDEX)
        self.assertGreater(_INDEX.chunk_count, 0)
        self.assertGreater(_INDEX.average_length, 0.0)

    def test_result_index_version_matches_the_bundle(self) -> None:
        result = _RETRIEVER.retrieve("What is free stock?", top_k=3)
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.index_version, _BUNDLE.index_version)


# ---------------------------------------------------------------------------
# Alias coverage
# ---------------------------------------------------------------------------


class AliasCoverageTests(unittest.TestCase):
    def test_canonical_aliases_resolve_top1(self) -> None:
        for case in ALIAS_CASES:
            if case.alias not in TOP1_ALIASES:
                continue
            with self.subTest(alias=case.alias):
                ranked = alias_doc_ids(case.alias, 3)
                self.assertTrue(
                    ranked,
                    f"{case.alias!r} returned no candidates",
                )
                self.assertEqual(
                    ranked[0],
                    case.owner,
                    f"{case.alias!r} ranked {ranked}",
                )

    def test_alias_gap_ledger_does_not_grow(self) -> None:
        gaps = {
            case.alias
            for case in ALIAS_CASES
            if case.owner not in alias_doc_ids(case.alias, 3)
        }
        self.assertLessEqual(
            gaps,
            KNOWN_ALIAS_GAPS,
            f"new alias gaps appeared: {sorted(gaps - KNOWN_ALIAS_GAPS)}",
        )

    def test_alias_top3_floor(self) -> None:
        self.assertGreaterEqual(
            alias_top3_count(),
            ALIAS_TOP3_FLOOR,
            f"alias top-3 dropped: {alias_top3_count()}/{len(ALIAS_CASES)}",
        )

    def test_alias_top1_floor(self) -> None:
        self.assertGreaterEqual(
            alias_top1_count(),
            ALIAS_TOP1_FLOOR,
            f"alias top-1 dropped: {alias_top1_count()}/{len(ALIAS_CASES)}",
        )

    def test_alias_end_to_end_floor(self) -> None:
        self.assertGreaterEqual(
            alias_end_to_end_count(),
            ALIAS_E2E_FLOOR,
            "end-to-end alias answers dropped: "
            f"{alias_end_to_end_count()}/{len(ALIAS_CASES)}",
        )


# ---------------------------------------------------------------------------
# Conceptual retrieval
# ---------------------------------------------------------------------------


class ConceptualRetrievalTests(unittest.TestCase):
    def test_answerable_questions_return_their_documents(self) -> None:
        for case in baseline_conceptual_cases():
            with self.subTest(query=case.query):
                result = _RETRIEVER.retrieve(case.query, top_k=3)
                self.assertEqual(result.status, "ok")
                self.assertIs(result.live_data, False)
                self.assertEqual(result.disclaimer, DISCLAIMER)
                self.assertGreaterEqual(len(result.hits), 1)
                self.assertLessEqual(len(result.hits), DEFAULT_TOP_K)
                self.assertEqual(result.index_version, _BUNDLE.index_version)
                self.assertEqual(
                    result.total_chars,
                    sum(len(hit.snippet) for hit in result.hits),
                )

                ranked = hit_doc_ids(result, 3)
                self.assertTrue(
                    set(case.expected) & set(ranked),
                    f"{case.query!r} -> {ranked}, expected {case.expected}",
                )

    def test_results_respect_the_per_document_cap(self) -> None:
        for case in baseline_conceptual_cases():
            with self.subTest(query=case.query):
                result = _RETRIEVER.retrieve(case.query, top_k=3)
                counts = Counter(hit.doc_id for hit in result.hits)
                if counts:
                    self.assertLessEqual(max(counts.values()), DEFAULT_MAX_HITS_PER_DOC)

    def test_snippets_are_non_empty_and_bounded(self) -> None:
        for case in baseline_conceptual_cases():
            with self.subTest(query=case.query):
                result = _RETRIEVER.retrieve(case.query, top_k=3)
                for hit in result.hits:
                    self.assertTrue(hit.snippet)
                    self.assertLessEqual(
                        len(hit.snippet), DEFAULT_MAX_SNIPPET_CHARS
                    )
                self.assertLessEqual(
                    result.total_chars, DEFAULT_MAX_TOTAL_CHARS
                )


# ---------------------------------------------------------------------------
# Live-fact rejection
# ---------------------------------------------------------------------------


class LiveFactRejectionTests(unittest.TestCase):
    def test_every_live_fact_question_is_rejected(self) -> None:
        for query, expected_kind in LIVE_FACT_NEGATIVES:
            with self.subTest(query=query):
                result = _RETRIEVER.retrieve(query)
                self.assertNotEqual(result.status, "ok")
                self.assertEqual(result.hits, ())
                self.assertIs(result.live_data, False)

                decision = classify_query(query)
                self.assertIsNot(decision.verdict, GuardVerdict.ALLOWED)
                self.assertIsNotNone(decision.live_fact_kind)

                if expected_kind is not None:
                    self.assertIs(decision.verdict, GuardVerdict.BLOCKED)
                    self.assertEqual(
                        decision.live_fact_kind,
                        expected_kind,
                        f"{query!r} classified as {decision.live_fact_kind!r}",
                    )

    def test_blocked_results_carry_a_reason_and_guidance(self) -> None:
        for query, _ in LIVE_FACT_NEGATIVES:
            with self.subTest(query=query):
                result = _RETRIEVER.retrieve(query)
                self.assertEqual(result.status, "blocked")
                self.assertIsNotNone(result.blocked_reason)
                self.assertIsNotNone(result.guidance)
                self.assertLessEqual(len(result.guidance or ""), 1000)


# ---------------------------------------------------------------------------
# Guard ambiguity ledger
# ---------------------------------------------------------------------------


class GuardAmbiguityLedgerTests(unittest.TestCase):
    def test_no_new_conceptual_question_is_refused(self) -> None:
        observed = {
            case.query
            for case in CONCEPTUAL_CASES
            if not classify_query(case.query).is_allowed
        }
        self.assertLessEqual(
            observed,
            KNOWN_GUARD_MISSES,
            f"new guard misses: {sorted(observed - KNOWN_GUARD_MISSES)}",
        )

    def test_known_misses_still_have_corpus_answers(self) -> None:
        # The ledger only makes sense if the corpus really can answer them.
        expected = {case.query: case.expected for case in CONCEPTUAL_CASES}
        for query in KNOWN_GUARD_MISSES:
            self.assertIn(query, expected)
            self.assertTrue(expected[query])


# ---------------------------------------------------------------------------
# Aggregate metrics
# ---------------------------------------------------------------------------


class AggregateMetricTests(unittest.TestCase):
    def test_guard_allow_rate_floor(self) -> None:
        allow = conceptual_allow_count()
        self.assertGreaterEqual(
            allow,
            CONCEPTUAL_ALLOW_FLOOR,
            f"guard allow-rate dropped: {allow}/{len(CONCEPTUAL_CASES)}",
        )

    def test_end_to_end_answer_rate_floor(self) -> None:
        answered = conceptual_answer_count()
        self.assertGreaterEqual(
            answered,
            CONCEPTUAL_ANSWER_FLOOR,
            f"answer-rate dropped: {answered}/{len(CONCEPTUAL_CASES)}",
        )

    def test_mean_reciprocal_rank_floor(self) -> None:
        score = conceptual_mrr()
        self.assertGreaterEqual(
            score,
            CONCEPTUAL_MRR_FLOOR,
            f"MRR dropped to {score:.4f}",
        )

    def test_live_fact_rejection_is_complete(self) -> None:
        rejected = sum(
            1
            for query, _ in LIVE_FACT_NEGATIVES
            if _RETRIEVER.retrieve(query).status != "ok"
        )
        self.assertEqual(
            rejected,
            len(LIVE_FACT_NEGATIVES),
            f"live-fact leak: {rejected}/{len(LIVE_FACT_NEGATIVES)} rejected",
        )


# ---------------------------------------------------------------------------
# Explicit guard recall tests (formerly ambiguous queries)
# ---------------------------------------------------------------------------


class TestGuardRecall(unittest.TestCase):
    """Each previously-ambiguous conceptual question must now be allowed
    and return its documented answer in the top-3 hits."""

    PREVIOUSLY_AMBIGUOUS = (
        ("What happens after a sales order is confirmed?", ("sales-order-to-dispatch",)),
        ("Which statuses can a sales order have?", ("dispatch-status",)),
        ("Can documentation be used for live totals?", ("data-authority",)),
        ("What tables store sales orders?", ("core-tables",)),
        ("Who approves a stock adjustment?", ("stock-adjustment",)),
    )

    def test_previously_ambiguous_queries_are_allowed(self) -> None:
        for query, _ in self.PREVIOUSLY_AMBIGUOUS:
            with self.subTest(query=query):
                decision = classify_query(query)
                self.assertIs(decision.verdict, GuardVerdict.ALLOWED)

    def test_previously_ambiguous_queries_return_docs(self) -> None:
        for query, expected in self.PREVIOUSLY_AMBIGUOUS:
            with self.subTest(query=query):
                result = _RETRIEVER.retrieve(query, top_k=3)
                self.assertEqual(result.status, "ok")
                self.assertTrue(
                    set(expected) & set(hit_doc_ids(result, 3)),
                    f"{query!r} -> {hit_doc_ids(result, 3)}, expected {expected}",
                )


# ---------------------------------------------------------------------------
# Bare alias guard acceptance tests
# ---------------------------------------------------------------------------


class TestGuardBareAlias(unittest.TestCase):
    """Curated documentation-reference aliases must be allowed by the guard
    (reachability is handled by the index layer)."""

    BARE_ALIASES = (
        "item master",
        "product master",
        "database schema",
        "erp overview",
        "procurement workflow",
        "order fulfilment",
        "delivery workflow",
        "live data policy",
        "documentation policy",
    )

    def test_bare_aliases_are_allowed_by_guard(self) -> None:
        for alias in self.BARE_ALIASES:
            with self.subTest(alias=alias):
                decision = classify_query(alias)
                self.assertIs(decision.verdict, GuardVerdict.ALLOWED)
                self.assertIsNone(decision.live_fact_kind)

    def test_bare_aliases_stay_deterministic(self) -> None:
        for alias in self.BARE_ALIASES:
            with self.subTest(alias=alias):
                first = classify_query(alias)
                second = classify_query(alias)
                self.assertEqual(first, second)


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


class DeterminismTests(unittest.TestCase):
    def test_two_fresh_builds_produce_identical_results(self) -> None:
        bundle = load_corpus(_CONFIG)
        index = Bm25Index(bundle)
        retriever = DocumentationRetriever(index)

        self.assertEqual(bundle.index_version, _BUNDLE.index_version)

        for query in all_eval_queries():
            with self.subTest(query=query):
                first = retriever.retrieve(query, top_k=3)
                second = _RETRIEVER.retrieve(query, top_k=3)
                self.assertEqual(first.status, second.status)
                self.assertEqual(
                    hit_doc_ids(first, 5),
                    hit_doc_ids(second, 5),
                )
                self.assertEqual(first.total_chars, second.total_chars)

    def test_repeated_calls_are_stable(self) -> None:
        for query in all_eval_queries():
            with self.subTest(query=query):
                first = _RETRIEVER.retrieve(query, top_k=3)
                second = _RETRIEVER.retrieve(query, top_k=3)
                self.assertEqual(first, second)

    def test_evaluation_is_read_only(self) -> None:
        chunk_count = _INDEX.chunk_count
        document_count = len(_BUNDLE.documents)
        version = _INDEX.index_version

        for query in all_eval_queries():
            _RETRIEVER.retrieve(query, top_k=3)

        self.assertEqual(_INDEX.chunk_count, chunk_count)
        self.assertEqual(len(_BUNDLE.documents), document_count)
        self.assertEqual(_INDEX.index_version, version)


# ---------------------------------------------------------------------------
# Target tier: skipped until the matching improvement lands
# ---------------------------------------------------------------------------


class GuardRecallTargetTests(unittest.TestCase):
    def test_known_guard_misses_become_answerable(self) -> None:
        cases = {
            case.query: case
            for case in CONCEPTUAL_CASES
            if case.query in KNOWN_GUARD_MISSES
        }
        for query, case in cases.items():
            with self.subTest(query=query):
                decision = classify_query(query)
                self.assertIs(decision.verdict, GuardVerdict.ALLOWED)
                result = _RETRIEVER.retrieve(query, top_k=3)
                self.assertEqual(result.status, "ok")
                self.assertTrue(
                    set(case.expected) & set(hit_doc_ids(result, 3))
                )


@unittest.skip("target tier: pending alias indexing (P0-1)")
class AliasTargetTests(unittest.TestCase):
    def test_every_alias_reaches_its_owner_in_top3(self) -> None:
        missing = [
            case.alias
            for case in ALIAS_CASES
            if case.owner not in alias_doc_ids(case.alias, 3)
        ]
        self.assertEqual(missing, [])

    def test_alias_top1_reaches_target(self) -> None:
        self.assertGreaterEqual(alias_top1_count(), 17)

    def test_alias_end_to_end_reaches_target(self) -> None:
        self.assertGreaterEqual(alias_end_to_end_count(), 18)


if __name__ == "__main__":
    unittest.main()
