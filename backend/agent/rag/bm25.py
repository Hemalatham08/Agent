"""Deterministic in-memory BM25 index over knowledge chunks.

The index is built from an immutable :class:`~backend.agent.rag.models.CorpusBundle`.
Each chunk is one BM25 document; its terms come from
:func:`backend.agent.rag.chunking.searchable_text`, which already contains the
chunk title, section path, and body. No embedding, vector store, database, or
network dependency is involved.

Formula (``k1 = 1.2``, ``b = 0.75``)::

    idf(t) = ln(1 + (N - df(t) + 0.5) / (df(t) + 0.5))
    score(q, d) = sum over t in q of
        idf(t) * (tf(t, d) * (k1 + 1))
        / (tf(t, d) + k1 * (1 - b + b * len(d) / avgdl))

``N`` is the number of indexed chunks and ``avgdl`` the mean chunk length in
tokens. Statistics are always computed over the whole corpus; selecting a
category restricts the candidate chunks but does not recompute IDF, so the
same chunk always receives the same score in every filtered view.

Determinism
-----------
Chunks are indexed in ``chunk_id`` order, postings keep that ascending order,
query terms are deduplicated in first-occurrence order, and results are sorted
by descending score then ascending ``chunk_id``. Repeated searches therefore
return identical values, independent of the order chunks were supplied in.

Concurrency
-----------
Rebuilds construct a fresh immutable snapshot outside the lock and swap it in
atomically under an :class:`~threading.RLock`. A search takes one snapshot and
uses it for the whole query, so concurrent rebuilds can never produce mixed
results.
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass

from backend.agent.rag.chunking import searchable_text
from backend.agent.rag.config import BM25_B, BM25_K1, MAX_BM25_K1
from backend.agent.rag.diagnostics import DetailedScoredChunk, TermContribution
from backend.agent.rag.models import Category, CorpusBundle, KnowledgeChunk
from backend.agent.rag.text import expand_query_terms, tokenize


@dataclass(frozen=True)
class ScoredChunk:
    """One ranked chunk with its BM25 score."""

    chunk: KnowledgeChunk
    score: float


@dataclass(frozen=True)
class _IndexState:
    index_version: str
    chunks: tuple[KnowledgeChunk, ...]
    postings: dict[str, tuple[tuple[int, int], ...]]
    doc_lengths: tuple[int, ...]
    average_length: float
    chunk_positions: dict[str, int]
    documents_by_category: dict[str, tuple[int, ...]]


def _validate_parameter(
    value: object,
    name: str,
    minimum: float,
    maximum: float | None,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be a finite number")
    if number < minimum or (maximum is not None and number > maximum):
        if maximum is None:
            raise ValueError(f"{name} must be at least {minimum}")
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return number


def _validate_k1(value: object) -> float:
    k1 = _validate_parameter(value, "k1", 0.0, MAX_BM25_K1)
    if k1 <= 0.0:
        raise ValueError("k1 must be greater than 0")
    return k1


def _validate_b(value: object) -> float:
    return _validate_parameter(value, "b", 0.0, 1.0)


def _validate_limit(limit: object) -> int | None:
    if limit is None:
        return None
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
        raise ValueError("limit must be a non-negative integer or None")
    return limit


def _idf(document_count: int, document_frequency: int) -> float:
    if document_count == 0:
        return 0.0
    return math.log(
        1.0
        + (document_count - document_frequency + 0.5)
        / (document_frequency + 0.5)
    )


def _require_term(term: object) -> str:
    if not isinstance(term, str):
        raise TypeError("term must be a string")
    tokens = tokenize(term)
    if len(tokens) != 1:
        raise ValueError("term must tokenize to exactly one token")
    return tokens[0]


def _build_state(bundle: CorpusBundle) -> _IndexState:
    if not isinstance(bundle, CorpusBundle):
        raise TypeError("bundle must be a CorpusBundle")

    chunks = tuple(sorted(bundle.chunks, key=lambda chunk: chunk.chunk_id))

    posting_lists: dict[str, list[tuple[int, int]]] = {}
    doc_lengths: list[int] = []
    chunk_positions: dict[str, int] = {}
    category_positions: dict[str, list[int]] = {}

    for index, chunk in enumerate(chunks):
        tokens = tokenize(searchable_text(chunk))
        doc_lengths.append(len(tokens))
        chunk_positions[chunk.chunk_id] = index
        category_positions.setdefault(chunk.category, []).append(index)

        counts: dict[str, int] = {}
        for token in tokens:
            counts[token] = counts.get(token, 0) + 1
        for term, frequency in counts.items():
            posting_lists.setdefault(term, []).append((index, frequency))

    total_length = sum(doc_lengths)
    average_length = total_length / len(chunks) if chunks else 0.0

    return _IndexState(
        index_version=bundle.index_version,
        chunks=chunks,
        postings={
            term: tuple(entries) for term, entries in posting_lists.items()
        },
        doc_lengths=tuple(doc_lengths),
        average_length=average_length,
        chunk_positions=chunk_positions,
        documents_by_category={
            category: tuple(entries)
            for category, entries in category_positions.items()
        },
    )


class Bm25Index:
    """Thread-safe, deterministic BM25 index over corpus chunks."""

    def __init__(
        self,
        bundle: CorpusBundle,
        *,
        k1: float = BM25_K1,
        b: float = BM25_B,
    ) -> None:
        self._k1 = _validate_k1(k1)
        self._b = _validate_b(b)
        self._lock = threading.RLock()
        self._state = _build_state(bundle)

    @property
    def index_version(self) -> str:
        with self._lock:
            return self._state.index_version

    @property
    def chunk_count(self) -> int:
        with self._lock:
            return len(self._state.chunks)

    @property
    def average_length(self) -> float:
        with self._lock:
            return self._state.average_length

    def document_frequency(self, term: str) -> int:
        """Return the number of chunks containing ``term``."""

        key = _require_term(term)
        with self._lock:
            return len(self._state.postings.get(key, ()))

    def idf(self, term: str) -> float:
        """Return the BM25 inverse document frequency of ``term``."""

        key = _require_term(term)
        with self._lock:
            frequency = len(self._state.postings.get(key, ()))
            return _idf(len(self._state.chunks), frequency)

    def term_frequency(self, chunk_id: str, term: str) -> int:
        """Return how often ``term`` occurs in ``chunk_id`` (0 if absent)."""

        if not isinstance(chunk_id, str):
            raise TypeError("chunk_id must be a string")
        key = _require_term(term)
        with self._lock:
            index = self._state.chunk_positions.get(chunk_id)
            if index is None:
                return 0
            for position, frequency in self._state.postings.get(key, ()):
                if position == index:
                    return frequency
            return 0

    def search(
        self,
        query: str,
        *,
        category: Category | None = None,
        limit: int | None = None,
        expand_query: bool = False,
    ) -> tuple[ScoredChunk, ...]:
        """Rank chunks for ``query``.

        ``category`` restricts candidates without changing corpus statistics.
        ``limit`` truncates the ranked list; ``None`` returns every match.
        When ``expand_query`` is true, curated query-term expansions are added
        to the scoring terms (additive only; original tokens are always kept).
        Default ``False`` preserves legacy scoring exactly.
        """

        if not isinstance(query, str):
            raise TypeError("query must be a string")
        limit_value = _validate_limit(limit)

        tokens = tokenize(query)
        if expand_query:
            tokens = expand_query_terms(tokens)
        state = self._snapshot()
        if not tokens or not state.chunks or state.average_length <= 0.0:
            return ()

        allowed: frozenset[int] | None = None
        if category is not None:
            positions = state.documents_by_category.get(category, ())
            if not positions:
                return ()
            allowed = frozenset(positions)

        index_contributions = self._score_terms(state, tokens, allowed)
        scores: dict[int, float] = {}
        for index, contribs in index_contributions.items():
            total = 0.0
            for value in contribs.values():
                total += value
            scores[index] = total

        if not scores:
            return ()

        ranked = sorted(
            ((state.chunks[index], score) for index, score in scores.items()),
            key=lambda item: (-item[1], item[0].chunk_id),
        )
        if limit_value is not None:
            ranked = ranked[:limit_value]
        return tuple(
            ScoredChunk(chunk=chunk, score=score) for chunk, score in ranked
        )

    def search_detailed(
        self,
        query: str,
        *,
        category: Category | None = None,
        limit: int | None = None,
        expand_query: bool = False,
    ) -> tuple[DetailedScoredChunk, ...]:
        """Rank chunks for ``query`` with per-term score contributions.

        Identical to :meth:`search` in scoring, ranking, tie-breaking, and
        category filtering; each returned chunk also carries the per-term
        contribution that produced its total score. Used only by diagnostics
        (opt-in).
        """

        if not isinstance(query, str):
            raise TypeError("query must be a string")
        limit_value = _validate_limit(limit)

        tokens = tokenize(query)
        if expand_query:
            tokens = expand_query_terms(tokens)
        state = self._snapshot()
        if not tokens or not state.chunks or state.average_length <= 0.0:
            return ()

        allowed: frozenset[int] | None = None
        if category is not None:
            positions = state.documents_by_category.get(category, ())
            if not positions:
                return ()
            allowed = frozenset(positions)

        index_contributions = self._score_terms(state, tokens, allowed)
        if not index_contributions:
            return ()

        num_chunks = len(state.chunks)
        detailed: list[DetailedScoredChunk] = []
        for index, contribs in index_contributions.items():
            total = 0.0
            for value in contribs.values():
                total += value
            term_contributions: list[TermContribution] = []
            for term in contribs:
                postings = state.postings.get(term, ())
                document_frequency = len(postings)
                frequency = 0
                for position, freq in postings:
                    if position == index:
                        frequency = freq
                        break
                term_contributions.append(
                    TermContribution(
                        term=term,
                        term_frequency=frequency,
                        document_frequency=document_frequency,
                        idf=_idf(num_chunks, document_frequency),
                        contribution=contribs[term],
                    )
                )
            detailed.append(
                DetailedScoredChunk(
                    chunk=state.chunks[index],
                    score=total,
                    contributions=tuple(term_contributions),
                )
            )

        detailed.sort(key=lambda item: (-item.score, item.chunk.chunk_id))
        if limit_value is not None:
            detailed = detailed[:limit_value]
        return tuple(detailed)

    def _score_terms(
        self,
        state: _IndexState,
        tokens: list[str],
        allowed: frozenset[int] | None,
    ) -> dict[int, dict[str, float]]:
        """Return per-chunk, per-term BM25 contributions.

        The inner dict preserves term order, so summing its values in order
        reproduces :meth:`search` totals bit-for-bit.
        """

        contributions: dict[int, dict[str, float]] = {}
        num_chunks = len(state.chunks)
        for term in dict.fromkeys(tokens):
            postings = state.postings.get(term)
            if not postings:
                continue
            idf = _idf(num_chunks, len(postings))
            for index, frequency in postings:
                if allowed is not None and index not in allowed:
                    continue
                length = state.doc_lengths[index]
                denominator = frequency + self._k1 * (
                    1.0 - self._b + self._b * length / state.average_length
                )
                contribution = idf * (frequency * (self._k1 + 1.0)) / denominator
                per_index = contributions.setdefault(index, {})
                per_index[term] = per_index.get(term, 0.0) + contribution
        return contributions

    @property
    def k1(self) -> float:
        """BM25 ``k1`` parameter."""
        return self._k1

    @property
    def b(self) -> float:
        """BM25 ``b`` parameter."""
        return self._b

    def vocabulary_size(self) -> int:
        """Return the number of distinct indexed terms."""
        with self._lock:
            return len(self._state.postings)

    def total_tokens(self) -> int:
        """Return the total number of indexed tokens across all chunks."""
        with self._lock:
            return sum(self._state.doc_lengths)

    def category_counts(self) -> tuple[tuple[str, int], ...]:
        """Return ``(category, chunk_count)`` pairs, sorted by category."""
        with self._lock:
            return tuple(
                sorted(
                    (category, len(positions))
                    for category, positions in self._state.documents_by_category.items()
                )
            )

    def rebuild(self, bundle: CorpusBundle) -> None:
        """Atomically replace the indexed corpus."""

        state = _build_state(bundle)
        with self._lock:
            self._state = state

    def _snapshot(self) -> _IndexState:
        with self._lock:
            return self._state


__all__ = [
    "BM25_B",
    "BM25_K1",
    "Bm25Index",
    "ScoredChunk",
]
