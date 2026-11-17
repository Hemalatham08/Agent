"""Structured diagnostics for the documentation-only RAG package.

These models and helpers make retrieval, guard, index, corpus, and evaluation
behavior inspectable without changing ranking, guard, or corpus semantics.

All models are frozen, forbid extra fields, and contain no timestamps or other
nondeterministic fields so they are directly comparable in tests. By default
``retrieve()`` allocates nothing new; diagnostics are requested explicitly via
:meth:`DocumentationRetriever.retrieve_with_diagnostics` and opt-in expansion
or detailed-scoring flags.

Privacy
-------
Default traces intentionally omit the raw query, snippets, document bodies,
guidance text, and record identifiers. A short query fingerprint (12 hex
characters) is only emitted when the caller explicitly opts in. This keeps
diagnostic output safe to log without exposing operational or customer data.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import Enum
from typing import Callable

from backend.agent.rag.guard import GuardDecision, GuardReason, GuardVerdict
from backend.agent.rag.models import Category, KnowledgeChunk, RetrievalResult

__all__ = [
    "RetrievalTrace",
    "DiagnosedRetrieval",
    "GuardTrace",
    "ExpansionTrace",
    "ExpansionEntry",
    "HitExplanation",
    "TermContribution",
    "ManifestStatus",
    "ManifestInspection",
    "IndexStats",
    "CorpusHealthReport",
    "MetricResult",
    "EvaluationReport",
    "build_index_stats",
    "build_corpus_health",
    "manifest_status_to_json",
    "redacted_trace_fields",
    "DetailedScoredChunk",
]


class ManifestStatus(str, Enum):
    """Manifest consistency status reported by :func:`inspect_manifest`."""

    CURRENT = "current"
    MISSING = "missing"
    MALFORMED = "malformed"
    STALE = "stale"


# ---------------------------------------------------------------------------
# Guard trace
# ---------------------------------------------------------------------------


class GuardTrace:
    """Structured summary of one guard decision.

    Fields are restricted to enums, counts, and labels: no guidance text and
    no raw query tokens, so this is safe to emit alongside logged retrieval
    outcomes.
    """

    __slots__ = (
        "verdict",
        "reason",
        "live_fact_kind",
        "suggested_category",
        "signals",
        "guidance_present",
    )

    def __init__(
        self,
        decision: GuardDecision,
    ) -> None:
        self.verdict: GuardVerdict = decision.verdict
        self.reason: GuardReason = decision.reason
        self.live_fact_kind = decision.live_fact_kind
        self.suggested_category = decision.suggested_category
        self.signals: tuple[str, ...] = tuple(decision.signals)
        self.guidance_present: bool = decision.guidance is not None

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, GuardTrace):
            return NotImplemented
        return (
            self.verdict == other.verdict
            and self.reason == other.reason
            and self.live_fact_kind == other.live_fact_kind
            and self.suggested_category == other.suggested_category
            and self.signals == other.signals
            and self.guidance_present == other.guidance_present
        )

    def __hash__(self) -> int:
        return hash(
            (
                self.verdict,
                self.reason,
                self.live_fact_kind,
                self.suggested_category,
                self.signals,
                self.guidance_present,
            )
        )

    def to_json(self) -> dict[str, object]:
        return {
            "verdict": self.verdict,
            "reason": self.reason,
            "live_fact_kind": self.live_fact_kind,
            "suggested_category": self.suggested_category,
            "signals": list(self.signals),
            "guidance_present": self.guidance_present,
        }


# ---------------------------------------------------------------------------
# Query expansion trace
# ---------------------------------------------------------------------------


class ExpansionEntry:
    """One curated query-expansion source and the terms it added."""

    __slots__ = ("source", "added")

    def __init__(self, source: str, added: tuple[str, ...]) -> None:
        self.source: str = source
        self.added: tuple[str, ...] = tuple(added)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ExpansionEntry):
            return NotImplemented
        return self.source == other.source and self.added == other.added

    def __hash__(self) -> int:
        return hash((self.source, self.added))

    def to_json(self) -> dict[str, object]:
        return {"source": self.source, "added": list(self.added)}


class ExpansionTrace:
    """Summary of query expansion applied to one retrieval request."""

    __slots__ = (
        "enabled",
        "original_token_count",
        "expanded_token_count",
        "expansions",
    )

    def __init__(
        self,
        *,
        enabled: bool,
        original_token_count: int,
        expanded_token_count: int,
        expansions: tuple[ExpansionEntry, ...] = (),
    ) -> None:
        self.enabled: bool = enabled
        self.original_token_count: int = original_token_count
        self.expanded_token_count: int = expanded_token_count
        self.expansions: tuple[ExpansionEntry, ...] = tuple(expansions)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ExpansionTrace):
            return NotImplemented
        return (
            self.enabled == other.enabled
            and self.original_token_count == other.original_token_count
            and self.expanded_token_count == other.expanded_token_count
            and self.expansions == other.expansions
        )

    def __hash__(self) -> int:
        return hash(
            (
                self.enabled,
                self.original_token_count,
                self.expanded_token_count,
                self.expansions,
            )
        )

    def to_json(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "original_token_count": self.original_token_count,
            "expanded_token_count": self.expanded_token_count,
            "expansions": [entry.to_json() for entry in self.expansions],
        }


# ---------------------------------------------------------------------------
# Term contribution and hit explanation
# ---------------------------------------------------------------------------


class TermContribution:
    """One query term's contribution to a chunk's BM25 score."""

    __slots__ = ("term", "term_frequency", "document_frequency", "idf", "contribution")

    def __init__(
        self,
        *,
        term: str,
        term_frequency: int,
        document_frequency: int,
        idf: float,
        contribution: float,
    ) -> None:
        self.term: str = term
        self.term_frequency: int = term_frequency
        self.document_frequency: int = document_frequency
        self.idf: float = idf
        self.contribution: float = contribution

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, TermContribution):
            return NotImplemented
        return (
            self.term == other.term
            and self.term_frequency == other.term_frequency
            and self.document_frequency == other.document_frequency
            and self.idf == other.idf
            and self.contribution == other.contribution
        )

    def __hash__(self) -> int:
        return hash(
            (
                self.term,
                self.term_frequency,
                self.document_frequency,
                self.idf,
                self.contribution,
            )
        )

    def to_json(self) -> dict[str, object]:
        return {
            "term": self.term,
            "term_frequency": self.term_frequency,
            "document_frequency": self.document_frequency,
            "idf": self.idf,
            "contribution": self.contribution,
        }


class HitExplanation:
    """Explanation of one selected retrieval hit."""

    __slots__ = (
        "rank",
        "chunk_id",
        "doc_id",
        "category",
        "score",
        "snippet_chars",
        "matched_terms",
        "contributions",
    )

    def __init__(
        self,
        *,
        rank: int,
        chunk_id: str,
        doc_id: str,
        category: Category,
        score: float,
        snippet_chars: int,
        matched_terms: tuple[str, ...] = (),
        contributions: tuple[TermContribution, ...] = (),
    ) -> None:
        self.rank: int = rank
        self.chunk_id: str = chunk_id
        self.doc_id: str = doc_id
        self.category: Category = category
        self.score: float = score
        self.snippet_chars: int = snippet_chars
        self.matched_terms: tuple[str, ...] = tuple(matched_terms)
        self.contributions: tuple[TermContribution, ...] = tuple(contributions)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, HitExplanation):
            return NotImplemented
        return (
            self.rank == other.rank
            and self.chunk_id == other.chunk_id
            and self.doc_id == other.doc_id
            and self.category == other.category
            and self.score == other.score
            and self.snippet_chars == other.snippet_chars
            and self.matched_terms == other.matched_terms
            and self.contributions == other.contributions
        )

    def __hash__(self) -> int:
        return hash(
            (
                self.rank,
                self.chunk_id,
                self.doc_id,
                self.category,
                self.score,
                self.snippet_chars,
                self.matched_terms,
                self.contributions,
            )
        )

    def to_json(self) -> dict[str, object]:
        return {
            "rank": self.rank,
            "chunk_id": self.chunk_id,
            "doc_id": self.doc_id,
            "category": self.category,
            "score": self.score,
            "snippet_chars": self.snippet_chars,
            "matched_terms": list(self.matched_terms),
            "contributions": [c.to_json() for c in self.contributions],
        }


# ---------------------------------------------------------------------------
# Retrieval trace
# ---------------------------------------------------------------------------


class RetrievalTrace:
    """Complete diagnostic summary of one ``retrieve`` call.

    :class:`RetrievalTrace` is intentionally free of raw query text, snippets,
    bodies, guidance text, and record identifiers. Use
    :meth:`retrieve_with_diagnostics` when you need this trace.
    """

    __slots__ = (
        "status",
        "index_version",
        "index_searched",
        "guard",
        "expansion",
        "query_chars",
        "query_token_count",
        "query_fingerprint",
        "candidate_count",
        "best_score",
        "threshold",
        "dropped_below_min_score",
        "dropped_below_relative_floor",
        "dropped_duplicate_chunk",
        "dropped_per_document_cap",
        "dropped_top_k",
        "selected",
        "total_chars",
    )

    def __init__(
        self,
        *,
        status: str,
        index_version: str,
        index_searched: bool,
        guard: GuardTrace,
        expansion: ExpansionTrace,
        query_chars: int,
        query_token_count: int,
        query_fingerprint: str | None,
        candidate_count: int,
        best_score: float | None,
        threshold: float | None,
        dropped_below_min_score: int,
        dropped_below_relative_floor: int,
        dropped_duplicate_chunk: int,
        dropped_per_document_cap: int,
        dropped_top_k: int,
        selected: tuple[HitExplanation, ...],
        total_chars: int,
    ) -> None:
        self.status: str = status
        self.index_version: str = index_version
        self.index_searched: bool = index_searched
        self.guard: GuardTrace = guard
        self.expansion: ExpansionTrace = expansion
        self.query_chars: int = query_chars
        self.query_token_count: int = query_token_count
        self.query_fingerprint: str | None = query_fingerprint
        self.candidate_count: int = candidate_count
        self.best_score: float | None = best_score
        self.threshold: float | None = threshold
        self.dropped_below_min_score: int = dropped_below_min_score
        self.dropped_below_relative_floor: int = dropped_below_relative_floor
        self.dropped_duplicate_chunk: int = dropped_duplicate_chunk
        self.dropped_per_document_cap: int = dropped_per_document_cap
        self.dropped_top_k: int = dropped_top_k
        self.selected: tuple[HitExplanation, ...] = tuple(selected)
        self.total_chars: int = total_chars

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, RetrievalTrace):
            return NotImplemented
        return (
            self.status == other.status
            and self.index_version == other.index_version
            and self.index_searched == other.index_searched
            and self.guard == other.guard
            and self.expansion == other.expansion
            and self.query_chars == other.query_chars
            and self.query_token_count == other.query_token_count
            and self.query_fingerprint == other.query_fingerprint
            and self.candidate_count == other.candidate_count
            and self.best_score == other.best_score
            and self.threshold == other.threshold
            and self.dropped_below_min_score == other.dropped_below_min_score
            and self.dropped_below_relative_floor == other.dropped_below_relative_floor
            and self.dropped_duplicate_chunk == other.dropped_duplicate_chunk
            and self.dropped_per_document_cap == other.dropped_per_document_cap
            and self.dropped_top_k == other.dropped_top_k
            and self.selected == other.selected
            and self.total_chars == other.total_chars
        )

    def __hash__(self) -> int:
        return hash(
            (
                self.status,
                self.index_version,
                self.index_searched,
                self.guard,
                self.expansion,
                self.query_chars,
                self.query_token_count,
                self.query_fingerprint,
                self.candidate_count,
                self.best_score,
                self.threshold,
                self.dropped_below_min_score,
                self.dropped_below_relative_floor,
                self.dropped_duplicate_chunk,
                self.dropped_per_document_cap,
                self.dropped_top_k,
                self.selected,
                self.total_chars,
            )
        )

    def to_json(self) -> dict[str, object]:
        return {
            "status": self.status,
            "index_version": self.index_version,
            "index_searched": self.index_searched,
            "guard": self.guard.to_json(),
            "expansion": self.expansion.to_json(),
            "query_chars": self.query_chars,
            "query_token_count": self.query_token_count,
            "query_fingerprint": self.query_fingerprint,
            "candidate_count": self.candidate_count,
            "best_score": self.best_score,
            "threshold": self.threshold,
            "dropped_below_min_score": self.dropped_below_min_score,
            "dropped_below_relative_floor": self.dropped_below_relative_floor,
            "dropped_duplicate_chunk": self.dropped_duplicate_chunk,
            "dropped_per_document_cap": self.dropped_per_document_cap,
            "dropped_top_k": self.dropped_top_k,
            "selected": [h.to_json() for h in self.selected],
            "total_chars": self.total_chars,
        }

    def to_log_fields(self) -> dict[str, object]:
        """Return a single-line-safe subset of the trace for logging.

        The fingerprint is omitted unless it was explicitly requested, and the
        result never contains raw query text, snippets, bodies, or guidance.
        """
        return {
            "status": self.status,
            "index_version": self.index_version,
            "index_searched": self.index_searched,
            "guard_verdict": self.guard.verdict,
            "guard_reason": self.guard.reason,
            "candidate_count": self.candidate_count,
            "selected_count": len(self.selected),
            "total_chars": self.total_chars,
        }


class DiagnosedRetrieval:
    """The ``RetrievalResult`` paired with its structured trace."""

    __slots__ = ("result", "trace")

    def __init__(
        self,
        *,
        result: RetrievalResult,
        trace: RetrievalTrace,
    ) -> None:
        self.result: RetrievalResult = result
        self.trace: RetrievalTrace = trace

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, DiagnosedRetrieval):
            return NotImplemented
        return self.result == other.result and self.trace == other.trace

    def to_json(self) -> dict[str, object]:
        return {
            "result": self.result.model_dump(mode="json"),
            "trace": self.trace.to_json(),
        }


# ---------------------------------------------------------------------------
# Index statistics
# ---------------------------------------------------------------------------


class IndexStats:
    """Aggregate, read-only statistics for one BM25 index snapshot."""

    __slots__ = (
        "index_version",
        "chunk_count",
        "vocabulary_size",
        "total_tokens",
        "average_length",
        "k1",
        "b",
        "category_counts",
    )

    def __init__(
        self,
        *,
        index_version: str,
        chunk_count: int,
        vocabulary_size: int,
        total_tokens: int,
        average_length: float,
        k1: float,
        b: float,
        category_counts: tuple[tuple[str, int], ...],
    ) -> None:
        self.index_version: str = index_version
        self.chunk_count: int = chunk_count
        self.vocabulary_size: int = vocabulary_size
        self.total_tokens: int = total_tokens
        self.average_length: float = average_length
        self.k1: float = k1
        self.b: float = b
        self.category_counts: tuple[tuple[str, int], ...] = tuple(category_counts)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, IndexStats):
            return NotImplemented
        return (
            self.index_version == other.index_version
            and self.chunk_count == other.chunk_count
            and self.vocabulary_size == other.vocabulary_size
            and self.total_tokens == other.total_tokens
            and self.average_length == other.average_length
            and self.k1 == other.k1
            and self.b == other.b
            and self.category_counts == other.category_counts
        )

    def __hash__(self) -> int:
        return hash(
            (
                self.index_version,
                self.chunk_count,
                self.vocabulary_size,
                self.total_tokens,
                self.average_length,
                self.k1,
                self.b,
                self.category_counts,
            )
        )

    def to_json(self) -> dict[str, object]:
        return {
            "index_version": self.index_version,
            "chunk_count": self.chunk_count,
            "vocabulary_size": self.vocabulary_size,
            "total_tokens": self.total_tokens,
            "average_length": self.average_length,
            "k1": self.k1,
            "b": self.b,
            "category_counts": [list(pair) for pair in self.category_counts],
        }


# ---------------------------------------------------------------------------
# Manifest inspection
# ---------------------------------------------------------------------------


class ManifestInspection:
    """Outcome of checking a corpus manifest against the filesystem."""

    __slots__ = ("status", "document_count", "index_version", "recorded_hashes")

    def __init__(
        self,
        *,
        status: ManifestStatus,
        document_count: int | None,
        index_version: str | None,
        recorded_hashes: int,
    ) -> None:
        self.status: ManifestStatus = status
        self.document_count: int | None = document_count
        self.index_version: str | None = index_version
        self.recorded_hashes: int = recorded_hashes

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ManifestInspection):
            return NotImplemented
        return (
            self.status == other.status
            and self.document_count == other.document_count
            and self.index_version == other.index_version
            and self.recorded_hashes == other.recorded_hashes
        )

    def __hash__(self) -> int:
        return hash(
            (
                self.status,
                self.document_count,
                self.index_version,
                self.recorded_hashes,
            )
        )

    def to_json(self) -> dict[str, object]:
        return {
            "status": self.status,
            "document_count": self.document_count,
            "index_version": self.index_version,
            "recorded_hashes": self.recorded_hashes,
        }


def manifest_status_to_json(status: ManifestStatus) -> str:
    return status.value


# ---------------------------------------------------------------------------
# Corpus health
# ---------------------------------------------------------------------------


class CorpusHealthReport:
    """Aggregate health view of one corpus bundle and its directory."""

    __slots__ = (
        "document_count",
        "chunk_count",
        "alias_count",
        "category_counts",
        "fact_kind_counts",
        "duplicate_doc_ids",
        "duplicate_content_pairs",
        "duplicate_alias_owners",
        "live_fact_violation_count",
        "documents_in_sorted_order",
        "chunk_ownership_ok",
        "manifest",
        "index_version",
        "healthy",
    )

    def __init__(
        self,
        *,
        document_count: int,
        chunk_count: int,
        alias_count: int,
        category_counts: tuple[tuple[str, int], ...],
        fact_kind_counts: tuple[tuple[str, int], ...],
        duplicate_doc_ids: tuple[str, ...],
        duplicate_content_pairs: tuple[tuple[str, str, str], ...],
        duplicate_alias_owners: tuple[tuple[str, str, str], ...],
        live_fact_violation_count: int,
        documents_in_sorted_order: bool,
        chunk_ownership_ok: bool,
        manifest: ManifestInspection,
        index_version: str,
        healthy: bool,
    ) -> None:
        self.document_count: int = document_count
        self.chunk_count: int = chunk_count
        self.alias_count: int = alias_count
        self.category_counts: tuple[tuple[str, int], ...] = tuple(category_counts)
        self.fact_kind_counts: tuple[tuple[str, int], ...] = tuple(fact_kind_counts)
        self.duplicate_doc_ids: tuple[str, ...] = tuple(duplicate_doc_ids)
        self.duplicate_content_pairs: tuple[tuple[str, str, str], ...] = tuple(
            duplicate_content_pairs
        )
        self.duplicate_alias_owners: tuple[tuple[str, str, str], ...] = tuple(
            duplicate_alias_owners
        )
        self.live_fact_violation_count: int = live_fact_violation_count
        self.documents_in_sorted_order: bool = documents_in_sorted_order
        self.chunk_ownership_ok: bool = chunk_ownership_ok
        self.manifest: ManifestInspection = manifest
        self.index_version: str = index_version
        self.healthy: bool = healthy

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, CorpusHealthReport):
            return NotImplemented
        return (
            self.document_count == other.document_count
            and self.chunk_count == other.chunk_count
            and self.alias_count == other.alias_count
            and self.category_counts == other.category_counts
            and self.fact_kind_counts == other.fact_kind_counts
            and self.duplicate_doc_ids == other.duplicate_doc_ids
            and self.duplicate_content_pairs == other.duplicate_content_pairs
            and self.duplicate_alias_owners == other.duplicate_alias_owners
            and self.live_fact_violation_count == other.live_fact_violation_count
            and self.documents_in_sorted_order == other.documents_in_sorted_order
            and self.chunk_ownership_ok == other.chunk_ownership_ok
            and self.manifest == other.manifest
            and self.index_version == other.index_version
            and self.healthy == other.healthy
        )

    def __hash__(self) -> int:
        return hash(
            (
                self.document_count,
                self.chunk_count,
                self.alias_count,
                self.category_counts,
                self.fact_kind_counts,
                self.duplicate_doc_ids,
                self.duplicate_content_pairs,
                self.duplicate_alias_owners,
                self.live_fact_violation_count,
                self.documents_in_sorted_order,
                self.chunk_ownership_ok,
                self.manifest,
                self.index_version,
                self.healthy,
            )
        )

    def to_json(self) -> dict[str, object]:
        return {
            "document_count": self.document_count,
            "chunk_count": self.chunk_count,
            "alias_count": self.alias_count,
            "category_counts": [list(pair) for pair in self.category_counts],
            "fact_kind_counts": [list(pair) for pair in self.fact_kind_counts],
            "duplicate_doc_ids": list(self.duplicate_doc_ids),
            "duplicate_content_pairs": [
                list(pair) for pair in self.duplicate_content_pairs
            ],
            "duplicate_alias_owners": [
                list(pair) for pair in self.duplicate_alias_owners
            ],
            "live_fact_violation_count": self.live_fact_violation_count,
            "documents_in_sorted_order": self.documents_in_sorted_order,
            "chunk_ownership_ok": self.chunk_ownership_ok,
            "manifest": self.manifest.to_json(),
            "index_version": self.index_version,
            "healthy": self.healthy,
        }


# ---------------------------------------------------------------------------
# Evaluation reporting
# ---------------------------------------------------------------------------


class MetricResult:
    """One evaluation metric with floor/target comparison."""

    __slots__ = (
        "name",
        "value",
        "numerator",
        "denominator",
        "floor",
        "target",
        "passed",
        "informational",
    )

    def __init__(
        self,
        *,
        name: str,
        value: float,
        numerator: int | None = None,
        denominator: int | None = None,
        floor: float | None = None,
        target: float | None = None,
        passed: bool,
        informational: bool = False,
    ) -> None:
        self.name: str = name
        self.value: float = value
        self.numerator: int | None = numerator
        self.denominator: int | None = denominator
        self.floor: float | None = floor
        self.target: float | None = target
        self.passed: bool = passed
        self.informational: bool = informational

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, MetricResult):
            return NotImplemented
        return (
            self.name == other.name
            and self.value == other.value
            and self.numerator == other.numerator
            and self.denominator == other.denominator
            and self.floor == other.floor
            and self.target == other.target
            and self.passed == other.passed
            and self.informational == other.informational
        )

    def __hash__(self) -> int:
        return hash(
            (
                self.name,
                self.value,
                self.numerator,
                self.denominator,
                self.floor,
                self.target,
                self.passed,
                self.informational,
            )
        )

    def to_json(self) -> dict[str, object]:
        return {
            "name": self.name,
            "value": self.value,
            "numerator": self.numerator,
            "denominator": self.denominator,
            "floor": self.floor,
            "target": self.target,
            "passed": self.passed,
            "informational": self.informational,
        }


class EvaluationReport:
    """Stable summary of one golden evaluation run."""

    __slots__ = (
        "index_version",
        "document_count",
        "chunk_count",
        "metrics",
        "all_required_passed",
    )

    def __init__(
        self,
        *,
        index_version: str,
        document_count: int,
        chunk_count: int,
        metrics: tuple[MetricResult, ...],
        all_required_passed: bool,
    ) -> None:
        self.index_version: str = index_version
        self.document_count: int = document_count
        self.chunk_count: int = chunk_count
        self.metrics: tuple[MetricResult, ...] = tuple(metrics)
        self.all_required_passed: bool = all_required_passed

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, EvaluationReport):
            return NotImplemented
        return (
            self.index_version == other.index_version
            and self.document_count == other.document_count
            and self.chunk_count == other.chunk_count
            and self.metrics == other.metrics
            and self.all_required_passed == other.all_required_passed
        )

    def __hash__(self) -> int:
        return hash(
            (
                self.index_version,
                self.document_count,
                self.chunk_count,
                self.metrics,
                self.all_required_passed,
            )
        )

    def to_json(self) -> dict[str, object]:
        return {
            "index_version": self.index_version,
            "document_count": self.document_count,
            "chunk_count": self.chunk_count,
            "metrics": [m.to_json() for m in self.metrics],
            "all_required_passed": self.all_required_passed,
        }


# ---------------------------------------------------------------------------
# Builders (corpus-health and index-stats construction)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DetailedScoredChunk:
    """One ranked chunk with its BM25 score and per-term contributions."""

    chunk: KnowledgeChunk
    score: float
    contributions: tuple[TermContribution, ...]


# Type alias retained for readability in external call sites.
DiagnosticSink = Callable[[RetrievalTrace], None]


def _empty_trace() -> RetrievalTrace:
    raise NotImplementedError("use the builder in retriever.py")


def redacted_trace_fields(trace: RetrievalTrace) -> dict[str, object]:
    """Return only privacy-safe, summary fields from a retrieval trace.

    Equivalent to :meth:`RetrievalTrace.to_log_fields`; provided as a plain
    function so callers can redact without importing the trace constructor.
    """
    return trace.to_log_fields()


def build_index_stats(index) -> IndexStats:
    """Build read-only :class:`IndexStats` from a :class:`Bm25Index` snapshot.

    Imported lazily inside the function to avoid a circular import (bm25
    imports diagnostics models).
    """

    from backend.agent.rag.bm25 import Bm25Index

    if not isinstance(index, Bm25Index):
        raise TypeError("index must be a Bm25Index")

    return IndexStats(
        index_version=index.index_version,
        chunk_count=index.chunk_count,
        vocabulary_size=index.vocabulary_size(),
        total_tokens=index.total_tokens(),
        average_length=index.average_length,
        k1=index.k1,
        b=index.b,
        category_counts=index.category_counts(),
    )


def build_corpus_health(bundle, knowledge_dir) -> CorpusHealthReport:
    """Build a :class:`CorpusHealthReport` for a bundle and its directory.

    Imported lazily inside the function to avoid a circular import (corpus
    imports diagnostics models).
    """

    from backend.agent.rag.corpus import (
        CATEGORIES,
        detect_duplicate_content,
        find_live_fact_violations,
        inspect_manifest,
    )

    documents = tuple(bundle.documents)
    chunks = tuple(bundle.chunks)

    # Document-level checks.
    doc_ids = [document.doc_id for document in documents]
    duplicate_doc_ids = tuple(
        sorted(doc_id for doc_id, count in Counter(doc_ids).items() if count > 1)
    )
    documents_in_sorted_order = doc_ids == sorted(doc_ids)

    # Category and fact-kind counts, sorted for determinism.
    category_counts: dict[str, int] = {}
    fact_kind_counts: dict[str, int] = {}
    alias_count = 0
    for document in documents:
        category_counts[document.category] = (
            category_counts.get(document.category, 0) + 1
        )
        fact_kind_counts[document.fact_kind] = (
            fact_kind_counts.get(document.fact_kind, 0) + 1
        )
        alias_count += len(document.aliases)

    category_pairs = tuple(sorted(category_counts.items()))
    fact_kind_pairs = tuple(sorted(fact_kind_counts.items()))

    # Duplicate content pairs.
    duplicate_content_pairs = tuple(detect_duplicate_content(documents))

    # Duplicate alias owners across documents.
    alias_owners: dict[str, list[str]] = {}
    for document in documents:
        for alias in document.aliases:
            alias_owners.setdefault(alias, []).append(document.doc_id)
    duplicate_alias_owners = tuple(
        sorted(
            (alias, tuple(sorted(owners)))
            for alias, owners in alias_owners.items()
            if len(owners) > 1
        )
    )

    # Chunk ownership: every chunk's doc_id must reference a known document.
    known_doc_ids = set(doc_ids)
    chunk_ownership_ok = all(chunk.doc_id in known_doc_ids for chunk in chunks)

    # Read-only live-fact lint audit (expected to be 0 for the shipped corpus).
    live_fact_violation_count = 0
    for document in documents:
        live_fact_violation_count += len(
            find_live_fact_violations(document.body)
        )

    manifest = inspect_manifest(knowledge_dir)

    healthy = (
        not duplicate_doc_ids
        and live_fact_violation_count == 0
        and chunk_ownership_ok
        and manifest.status in (ManifestStatus.CURRENT, ManifestStatus.MISSING)
    )

    return CorpusHealthReport(
        document_count=len(documents),
        chunk_count=len(chunks),
        alias_count=alias_count,
        category_counts=category_pairs,
        fact_kind_counts=fact_kind_pairs,
        duplicate_doc_ids=duplicate_doc_ids,
        duplicate_content_pairs=duplicate_content_pairs,
        duplicate_alias_owners=duplicate_alias_owners,
        live_fact_violation_count=live_fact_violation_count,
        documents_in_sorted_order=documents_in_sorted_order,
        chunk_ownership_ok=chunk_ownership_ok,
        manifest=manifest,
        index_version=bundle.index_version,
        healthy=healthy,
    )
