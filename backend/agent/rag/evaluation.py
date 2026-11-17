"""Deterministic RAG retrieval quality reporting.

This module builds stable, comparable reports of retrieval behaviour across
corpus, chunker, and ranking changes. It is intentionally free of file system,
network, timestamp, and randomness so that two runs on the same corpus produce
identical reports.

All failure attribution is document-level only: reports never assert raw BM25
scores or specific chunk IDs, keeping the reports robust to churn in scoring or
chunking while still surfacing real quality regressions.

Guard-limited cases (ambiguous / blocked before retrieval) are tracked
separately from retrieval misses so that guard precision limitations do not
masquerade as ranking regressions, and vice versa.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from backend.agent.rag.guard import GuardVerdict
from backend.agent.rag.models import RetrievalResult

__all__ = [
    "EvalQuery",
    "HardNegativeCase",
    "MultiDocCase",
    "FailureRecord",
    "QualityMetric",
    "QualityReport",
    "CoverageReport",
    "evaluate_quality",
    "build_corpus_benchmark",
    "build_coverage_report",
    "hit_doc_ids",
    "rank_of_doc",
]


def hit_doc_ids(result: RetrievalResult, k: int = 3) -> tuple[str, ...]:
    """Return distinct document ids in hit order, truncated to ``k``.

    Doc-level only: never returns raw scores or chunk IDs.
    """

    ordered: list[str] = []
    seen: set[str] = set()
    for hit in result.hits:
        doc_id = hit.doc_id
        if doc_id in seen:
            continue
        seen.add(doc_id)
        ordered.append(doc_id)
        if len(ordered) >= k:
            break
    return tuple(ordered)


def rank_of_doc(result: RetrievalResult, doc_id: str, k: int = 5) -> int | None:
    """Return the 1-based rank of ``doc_id`` in ``result``, or ``None``."""

    for rank, candidate in enumerate(hit_doc_ids(result, k), start=1):
        if candidate == doc_id:
            return rank
    return None


# ---------------------------------------------------------------------------
# Case dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvalQuery:
    """One evaluation question with its acceptable answering documents.

    ``expected`` is the set of documents that legitimately answer the question.
    Recall@k accepts any entry, which keeps the suite from over-fitting one
    ranking.
    """

    query: str
    expected: tuple[str, ...]
    category: str = ""
    note: str = ""


@dataclass(frozen=True)
class HardNegativeCase:
    """One strict hard-negative query with an expected document and a trap doc.

    The trap document must **not** outrank the expected document. Query wording
    deliberately avoids the terms that make the trap look plausible.
    """

    query: str
    expected: str
    trap: str
    note: str = ""


@dataclass(frozen=True)
class MultiDocCase:
    """One question that legitimately spans several documents."""

    query: str
    required: tuple[str, ...]
    note: str = ""


# ---------------------------------------------------------------------------
# Failure records
# ---------------------------------------------------------------------------


class FailureKind(str, __import__("enum").Enum):
    """Why a quality expectation was not met."""

    GUARD_LIMITED = "guard_limited"
    RETRIEVAL_MISS = "retrieval_miss"
    HARD_NEGATIVE_MISS = "hard_negative_miss"
    HARD_NEGATIVE_TRAP = "hard_negative_trap"
    MULTI_DOC_GAP = "multi_doc_gap"
    SNIPPET_TOO_SHORT = "snippet_too_short"


@dataclass(frozen=True)
class FailureRecord:
    """One documented quality failure."""

    query: str
    kind: FailureKind
    expected: tuple[str, ...] = ()
    got: tuple[str, ...] = ()
    trap: str | None = None
    detail: str = ""

    def to_json(self) -> dict[str, object]:
        return {
            "query": self.query,
            "kind": self.kind.value,
            "expected": list(self.expected),
            "got": list(self.got),
            "trap": self.trap,
            "detail": self.detail,
        }


# ---------------------------------------------------------------------------
# Quality metric
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class QualityMetric:
    """One quality metric with measured value and an optional acceptance bar.

    ``passed`` is derived from ``floor`` when one is supplied: the metric
    passes when ``value >= floor``. When no floor is supplied the metric is
    informational and always reports ``passed=True``.
    """

    name: str
    value: float
    numerator: int | None = None
    denominator: int | None = None
    floor: float | None = None
    passed: bool = True
    informational: bool = False

    def __post_init__(self) -> None:
        if self.floor is not None:
            object.__setattr__(self, "passed", self.value >= self.floor)

    def to_json(self) -> dict[str, object]:
        return {
            "name": self.name,
            "value": self.value,
            "numerator": self.numerator,
            "denominator": self.denominator,
            "floor": self.floor,
            "passed": self.passed,
            "informational": self.informational,
        }


# ---------------------------------------------------------------------------
# Coverage report
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CoverageReport:
    """Aggregate coverage statistics for a corpus and index."""

    document_count: int
    chunk_count: int
    document_reachability_count: int
    document_reachability_total: int
    chunk_reachability_count: int
    chunk_reachability_total: int
    alias_top1_count: int
    alias_top1_total: int
    alias_top3_count: int
    alias_top3_total: int
    zero_result_count: int
    zero_result_total: int
    near_tie_count: int
    near_tie_total: int
    short_snippet_count: int
    short_snippet_total: int
    heading_only_chunk_count: int
    orphan_chunk_count: int
    oov_token_type_count: int
    index_version: str

    def to_json(self) -> dict[str, object]:
        return {
            "document_count": self.document_count,
            "chunk_count": self.chunk_count,
            "document_reachability_rate": _rate(
                self.document_reachability_count, self.document_reachability_total
            ),
            "chunk_reachability_rate": _rate(
                self.chunk_reachability_count, self.chunk_reachability_total
            ),
            "alias_top1_rate": _rate(self.alias_top1_count, self.alias_top1_total),
            "alias_top3_rate": _rate(self.alias_top3_count, self.alias_top3_total),
            "zero_result_rate": _rate(self.zero_result_count, self.zero_result_total),
            "near_tie_rate": _rate(self.near_tie_count, self.near_tie_total),
            "short_snippet_rate": _rate(
                self.short_snippet_count, self.short_snippet_total
            ),
            "heading_only_chunk_count": self.heading_only_chunk_count,
            "orphan_chunk_count": self.orphan_chunk_count,
            "oov_token_type_count": self.oov_token_type_count,
            "index_version": self.index_version,
        }


def _rate(count: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return count / total


# ---------------------------------------------------------------------------
# Quality report
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class QualityReport:
    """Stable summary of one quality evaluation run."""

    index_version: str
    document_count: int
    chunk_count: int
    query_count: int
    guard_limited_count: int
    retrieval_miss_count: int
    hard_negative_trap_count: int
    hard_negative_miss_count: int
    multi_doc_gap_count: int
    short_snippet_count: int
    short_snippet_total: int
    failures: tuple[FailureRecord, ...]
    metrics: tuple[QualityMetric, ...]
    coverage: CoverageReport
    all_required_passed: bool

    def to_json(self) -> dict[str, object]:
        return {
            "index_version": self.index_version,
            "document_count": self.document_count,
            "chunk_count": self.chunk_count,
            "query_count": self.query_count,
            "guard_limited_count": self.guard_limited_count,
            "retrieval_miss_count": self.retrieval_miss_count,
            "hard_negative_trap_count": self.hard_negative_trap_count,
            "hard_negative_miss_count": self.hard_negative_miss_count,
            "multi_doc_gap_count": self.multi_doc_gap_count,
            "short_snippet_count": self.short_snippet_count,
            "short_snippet_total": self.short_snippet_total,
            "failures": [f.to_json() for f in self.failures],
            "metrics": [m.to_json() for m in self.metrics],
            "coverage": self.coverage.to_json(),
            "all_required_passed": self.all_required_passed,
        }


# ---------------------------------------------------------------------------
# Evaluation entry point
# ---------------------------------------------------------------------------


RetrieverRetrieve = Callable[[str], RetrievalResult]


def evaluate_quality(
    *,
    retrieve: RetrieverRetrieve,
    queries: tuple[EvalQuery, ...],
    hard_negatives: tuple[HardNegativeCase, ...] = (),
    multi_doc: tuple[MultiDocCase, ...] = (),
    top_k: int = 3,
    index_version: str = "",
    document_count: int = 0,
    chunk_count: int = 0,
    coverages: CoverageReport | None = None,
) -> QualityReport:
    """Evaluate retrieval quality over one query set.

    ``retrieve`` is called per query; its result must equal the retriever's
    public ``retrieve`` output for the same arguments. Failures are attributed
    per query without exposing raw scores or chunk IDs.

    Guard-limited queries (not ALLOWED) are tracked separately from retrieval
    misses, and counters are kept per dataset so that guard precision
    limitations do not masquerade as ranking regressions, and vice versa.
    ``top_k`` is always passed as a keyword argument so the public
    :meth:`DocumentationRetriever.retrieve` signature is honoured directly.
    """

    # Per-dataset counters so guard-limited cases never inflate miss rates.
    query_guard_limited = 0
    query_retrieval_misses = 0
    hard_negative_guard_limited = 0
    hard_negative_traps = 0
    hard_negative_misses = 0
    multi_doc_guard_limited = 0
    multi_doc_gaps = 0
    short_snippet_count = 0
    short_snippet_total = 0
    failures: list[FailureRecord] = []

    for case in queries:
        result = retrieve(case.query, top_k=top_k)
        if result.status != "ok":
            query_guard_limited += 1
            failures.append(
                FailureRecord(
                    query=case.query,
                    kind=FailureKind.GUARD_LIMITED,
                    expected=case.expected,
                    got=(),
                    detail=f"status={result.status!r}",
                )
            )
            continue

        got = hit_doc_ids(result, top_k)
        matched = set(case.expected) & set(got)
        short_hits = sum(
            1 for hit in result.hits if len(hit.snippet.strip()) < 60
        )
        short_snippet_count += short_hits
        short_snippet_total += len(result.hits)
        if short_hits:
            failures.append(
                FailureRecord(
                    query=case.query,
                    kind=FailureKind.SNIPPET_TOO_SHORT,
                    expected=case.expected,
                    got=got,
                    detail=f"short_snippet_hits={short_hits}",
                )
            )

        if not matched:
            query_retrieval_misses += 1
            failures.append(
                FailureRecord(
                    query=case.query,
                    kind=FailureKind.RETRIEVAL_MISS,
                    expected=case.expected,
                    got=got,
                )
            )

    for case in hard_negatives:
        result = retrieve(case.query, top_k=top_k)
        if result.status != "ok":
            # If the guard blocks a hard negative, that is safe, not a trap.
            hard_negative_guard_limited += 1
            continue
        got = hit_doc_ids(result, top_k)
        if case.expected not in got:
            # Expected doc absent entirely; distinct from a trap.
            hard_negative_misses += 1
            failures.append(
                FailureRecord(
                    query=case.query,
                    kind=FailureKind.HARD_NEGATIVE_MISS,
                    expected=(case.expected,),
                    got=got,
                    trap=case.trap,
                    detail="expected document absent from results",
                )
            )
            continue
        expected_rank = rank_of_doc(result, case.expected, top_k)
        trap_rank = rank_of_doc(result, case.trap, top_k)
        if trap_rank is not None and (
            expected_rank is None or trap_rank < expected_rank
        ):
            hard_negative_traps += 1
            failures.append(
                FailureRecord(
                    query=case.query,
                    kind=FailureKind.HARD_NEGATIVE_TRAP,
                    expected=(case.expected,),
                    got=got,
                    trap=case.trap,
                    detail=(
                        f"expected_rank={expected_rank} "
                        f"trap_rank={trap_rank}"
                    ),
                )
            )

    for case in multi_doc:
        result = retrieve(case.query, top_k=top_k)
        if result.status != "ok":
            multi_doc_guard_limited += 1
            failures.append(
                FailureRecord(
                    query=case.query,
                    kind=FailureKind.GUARD_LIMITED,
                    expected=case.required,
                    got=(),
                    detail=f"status={result.status!r}",
                )
            )
            continue
        got = hit_doc_ids(result, top_k)
        missing = [doc for doc in case.required if doc not in set(got)]
        if missing:
            multi_doc_gaps += 1
            failures.append(
                FailureRecord(
                    query=case.query,
                    kind=FailureKind.MULTI_DOC_GAP,
                    expected=case.required,
                    got=got,
                    detail=f"missing={missing}",
                )
            )

    # Metrics are computed over the ``queries`` dataset only so denominators
    # never bleed across dataset types and rates stay within [0, 1].
    query_count = len(queries)
    answered = query_count - query_guard_limited - query_retrieval_misses
    answer_rate = _clamp(_rate(answered, query_count))
    guard_allow_rate = _clamp(
        _rate(query_count - query_guard_limited, query_count)
    )
    mrr = _clamp(_mrr(retrieve, queries, top_k))

    metrics: list[QualityMetric] = [
        QualityMetric(
            name="guard_allow_rate",
            value=guard_allow_rate,
            numerator=query_count - query_guard_limited,
            denominator=query_count,
            floor=1.0,
        ),
        QualityMetric(
            name="answer_rate",
            value=answer_rate,
            numerator=answered,
            denominator=query_count,
            floor=1.0,
        ),
        QualityMetric(
            name="mean_reciprocal_rank",
            value=mrr,
            floor=1.0,
        ),
        QualityMetric(
            name="hard_negative_trap_rate",
            value=_rate(hard_negative_traps, len(hard_negatives)),
            numerator=hard_negative_traps,
            denominator=len(hard_negatives) or None,
            informational=True,
        ),
        QualityMetric(
            name="hard_negative_miss_rate",
            value=_rate(hard_negative_misses, len(hard_negatives)),
            numerator=hard_negative_misses,
            denominator=len(hard_negatives) or None,
            informational=True,
        ),
        QualityMetric(
            name="multi_doc_coverage_rate",
            value=_rate(
                len(multi_doc) - multi_doc_gaps, len(multi_doc)
            ),
            numerator=len(multi_doc) - multi_doc_gaps,
            denominator=len(multi_doc) or None,
            informational=True,
        ),
        QualityMetric(
            name="short_snippet_rate",
            value=_rate(short_snippet_count, short_snippet_total),
            numerator=short_snippet_count,
            denominator=short_snippet_total or None,
            informational=True,
        ),
    ]

    all_required_passed = (
        query_retrieval_misses == 0
        and hard_negative_traps == 0
        and hard_negative_misses == 0
        and multi_doc_gaps == 0
        and short_snippet_count == 0
        and all(m.passed for m in metrics if not m.informational)
    )

    return QualityReport(
        index_version=index_version,
        document_count=document_count,
        chunk_count=chunk_count,
        query_count=query_count,
        guard_limited_count=query_guard_limited,
        retrieval_miss_count=query_retrieval_misses,
        hard_negative_trap_count=hard_negative_traps,
        hard_negative_miss_count=hard_negative_misses,
        multi_doc_gap_count=multi_doc_gaps,
        short_snippet_count=short_snippet_count,
        short_snippet_total=short_snippet_total,
        failures=tuple(failures),
        metrics=tuple(metrics),
        coverage=coverages
        or CoverageReport(
            document_count=document_count,
            chunk_count=chunk_count,
            document_reachability_count=0,
            document_reachability_total=0,
            chunk_reachability_count=0,
            chunk_reachability_total=0,
            alias_top1_count=0,
            alias_top1_total=0,
            alias_top3_count=0,
            alias_top3_total=0,
            zero_result_count=0,
            zero_result_total=0,
            near_tie_count=0,
            near_tie_total=0,
            short_snippet_count=0,
            short_snippet_total=0,
            heading_only_chunk_count=0,
            orphan_chunk_count=0,
            oov_token_type_count=0,
            index_version=index_version,
        ),
        all_required_passed=all_required_passed,
    )


def _clamp(value: float) -> float:
    """Clamp a rate to the inclusive range [0, 1]."""

    return max(0.0, min(1.0, value))


def _mrr(
    retrieve: RetrieverRetrieve,
    queries: tuple[EvalQuery, ...],
    top_k: int,
) -> float:
    total = 0.0
    for case in queries:
        result = retrieve(case.query, top_k=top_k)
        if result.status != "ok":
            continue
        for rank, doc_id in enumerate(hit_doc_ids(result, top_k), start=1):
            if doc_id in case.expected:
                total += 1.0 / rank
                break
    return total / len(queries) if queries else 0.0


# ---------------------------------------------------------------------------
# Corpus-derived regression benchmark
# ---------------------------------------------------------------------------


def _sanitize_query(query: str, max_chars: int = 300) -> str | None:
    """Return a single-line, guard-safe query string, or ``None`` if empty.

    Strips Markdown heading markers, collapses whitespace (including newlines)
    into single spaces, trims, and truncates to ``max_chars``. The guard
    rejects multi-line queries, so every derived benchmark query must be a
    single line.
    """

    text = query.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
    # Strip leading Markdown heading markers (e.g. "# Title", "## Section").
    text = re.sub(r"^\s*#{1,6}\s+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return None
    if len(text) > max_chars:
        text = text[:max_chars].rstrip()
    return text


def build_corpus_benchmark(
    *,
    documents,
    aliases_by_doc: dict[str, tuple[str, ...]] | None = None,
) -> tuple[EvalQuery, ...]:
    """Derive stable evaluation queries from corpus metadata.

    One question per document from its title, summary, first sentence, and
    aliases. This benchmarks against the corpus itself rather than against a
    hand-tuned golden set, so it cannot be overfitted by construction.

    All derived queries are sanitized to single-line, guard-acceptable strings
    (headings stripped, whitespace collapsed, truncated to 300 characters).
    """

    aliases_by_doc = aliases_by_doc or {}
    queries: list[EvalQuery] = []

    for document in documents:
        expected = (document.doc_id,)

        title_q = _sanitize_query(f"What is {document.title}?")
        if title_q:
            queries.append(
                EvalQuery(title_q, expected, "title", "derived from document title")
            )

        summary_q = _sanitize_query(f"Tell me about {document.summary.lower()}")
        if summary_q:
            queries.append(
                EvalQuery(summary_q, expected, "summary", "derived from document summary")
            )

        body = document.body or ""
        first_sentence = re.split(r"(?<=[.!?])\s+", body.strip())[0].strip()
        if first_sentence and len(first_sentence) > 10:
            first_q = _sanitize_query(f"Explain: {first_sentence.rstrip('.')}")
            if first_q:
                queries.append(
                    EvalQuery(first_q, expected, "first_sentence", "derived from first sentence")
                )

        for alias in aliases_by_doc.get(document.doc_id, ()):
            alias_q = _sanitize_query(f"What does {alias} mean?")
            if alias_q:
                queries.append(
                    EvalQuery(alias_q, expected, "alias", "derived from document alias")
                )
    return tuple(queries)


def build_coverage_report(
    *,
    documents,
    chunks,
    index,
    query_bank: tuple[str, ...],
    aliases_by_doc: dict[str, tuple[str, ...]] | None = None,
    short_snippet_total: int = 0,
    short_snippet_count: int = 0,
) -> CoverageReport:
    """Build aggregate coverage statistics for a corpus and index."""

    aliases_by_doc = aliases_by_doc or {}

    # Document reachability: each document reachable in top-1 by its title.
    doc_reached = 0
    for document in documents:
        ranked = _doc_rank_list(index, document.title, 1)
        if document.doc_id in ranked:
            doc_reached += 1

    # Chunk reachability: each chunk reachable in top-3 from at least one bank
    # query. Every distinct chunk in the top-3 is counted (not just the first
    # chunk per document).
    chunk_reached: set[str] = set()
    zero_result = 0
    zero_total = 0
    near_tie = 0
    near_total = 0
    for query in query_bank:
        results = index.search(query, limit=None)
        zero_total += 1
        if not results:
            zero_result += 1
            continue
        seen_docs: set[str] = set()
        top_scores = []
        for item in results[:3]:
            top_scores.append(item.score)
            chunk_reached.add(item.chunk.chunk_id)
            if item.chunk.doc_id not in seen_docs:
                seen_docs.add(item.chunk.doc_id)
        if len(top_scores) >= 2 and top_scores[0] > 0:
            ratio = top_scores[1] / top_scores[0]
            near_total += 1
            if ratio > 0.90:
                near_tie += 1

    alias_top1 = 0
    alias_top3 = 0
    alias_total = 0
    for document in documents:
        for alias in aliases_by_doc.get(document.doc_id, ()):
            alias_total += 1
            ranked = _doc_rank_list(index, alias, 3)
            if ranked[:1] == [document.doc_id]:
                alias_top1 += 1
            if document.doc_id in ranked:
                alias_top3 += 1

    heading_only = 0
    for chunk in chunks:
        lines = [line for line in chunk.text.strip().split("\n") if line.strip()]
        if len(lines) <= 1:
            heading_only += 1

    reached_chunk_ids = chunk_reached
    orphan = sum(
        1 for chunk in chunks if chunk.chunk_id not in reached_chunk_ids
    )

    # Out-of-vocabulary token types across the query bank.
    from backend.agent.rag.text import tokenize
    from backend.agent.rag.chunking import searchable_text

    vocab: set[str] = set()
    for chunk in chunks:
        vocab.update(tokenize(searchable_text(chunk)))
    oov_types: set[str] = set()
    for query in query_bank:
        for token in tokenize(query):
            if token not in vocab:
                oov_types.add(token)

    return CoverageReport(
        document_count=len(documents),
        chunk_count=len(chunks),
        document_reachability_count=doc_reached,
        document_reachability_total=len(documents),
        chunk_reachability_count=len(reached_chunk_ids),
        chunk_reachability_total=len(chunks),
        alias_top1_count=alias_top1,
        alias_top1_total=alias_total,
        alias_top3_count=alias_top3,
        alias_top3_total=alias_total,
        zero_result_count=zero_result,
        zero_result_total=zero_total,
        near_tie_count=near_tie,
        near_tie_total=near_total,
        short_snippet_count=short_snippet_count,
        short_snippet_total=short_snippet_total,
        heading_only_chunk_count=heading_only,
        orphan_chunk_count=orphan,
        oov_token_type_count=len(oov_types),
        index_version=index.index_version,
    )


# ---------------------------------------------------------------------------
# Helpers (index internals accessed through public surface only)
# ---------------------------------------------------------------------------


def _doc_rank_list(index, query: str, k: int) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for item in index.search(query, limit=None):
        doc_id = item.chunk.doc_id
        if doc_id in seen:
            continue
        seen.add(doc_id)
        ordered.append(doc_id)
        if len(ordered) >= k:
            break
    return ordered
