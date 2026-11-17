"""Guard-first documentation retrieval with bounded, deterministic output.

Pipeline
--------
1. Validate the request.
2. Run :func:`backend.agent.rag.guard.classify_query` **before** touching the
   BM25 index. Blocked and ambiguous questions return a structured ``blocked``
   result with guidance and no hits.
3. Search the index, applying ``min_score`` and the relative floor
   ``0.25 * best_score``.
4. Keep at most two chunks per document, deduplicate chunk IDs, and truncate
   to ``top_k`` (maximum five).
5. Build snippets capped at 700 characters each and 3000 characters in total.

The result always carries ``live_data=False`` and the shared documentation
disclaimer. Nothing in this module mutates the index, corpus, or chunks, and no
filesystem, network, database, or LLM access occurs.
"""

from __future__ import annotations

import hashlib
import math
import re

from backend.agent.rag.bm25 import Bm25Index, ScoredChunk
from backend.agent.rag.config import (
    DEFAULT_MAX_HITS_PER_DOC,
    DEFAULT_MAX_SNIPPET_CHARS,
    DEFAULT_MAX_TOTAL_CHARS,
    DEFAULT_MIN_SCORE,
    DEFAULT_TOP_K,
    MAX_HITS_PER_DOC,
    MAX_SNIPPET_CHARS,
    MAX_TOP_K,
    MAX_TOTAL_CHARS,
    RELATIVE_SCORE_FLOOR,
)
from backend.agent.rag.corpus import CATEGORIES
from backend.agent.rag.diagnostics import (
    DiagnosedRetrieval,
    DetailedScoredChunk,
    ExpansionTrace,
    GuardTrace,
    HitExplanation,
    RetrievalTrace,
    TermContribution,
    build_index_stats,
    build_corpus_health,
    redacted_trace_fields,
)
from backend.agent.rag.errors import (
    RagConfigurationError,
    RagInvalidArgumentsError,
)
from backend.agent.rag.guard import (
    GUIDANCE_BY_KIND,
    GuardVerdict,
    classify_query,
)
from backend.agent.rag.models import (
    RetrievalHit,
    RetrievalQuery,
    RetrievalResult,
)
from backend.agent.rag.text import expansion_trace, tokenize

NO_MATCH_GUIDANCE = (
    "No reviewed documentation matched this question closely enough. Rephrase "
    "it as a definition, workflow, policy, or schema question."
)

_MIN_SNIPPET_BUDGET = 20
_MAX_SECTION_LABEL = 500


def _configuration_number(
    value: object,
    name: str,
    minimum: float,
    maximum: float | None = None,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RagConfigurationError(f"{name} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise RagConfigurationError(f"{name} must be a finite number")
    if number < minimum or (maximum is not None and number > maximum):
        if maximum is None:
            raise RagConfigurationError(f"{name} must be at least {minimum}")
        raise RagConfigurationError(
            f"{name} must be between {minimum} and {maximum}"
        )
    return number


def _configuration_int(value: object, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RagConfigurationError(
            f"{name} must be an integer between {minimum} and {maximum}"
        )
    if value < minimum or value > maximum:
        raise RagConfigurationError(
            f"{name} must be an integer between {minimum} and {maximum}"
        )
    return value


def _preferred_snippet_cut(head: str) -> int:
    minimum = max(1, len(head) // 2)
    for marker in ("\n\n", ". ", "? ", "! ", ".\n"):
        index = head.rfind(marker)
        if index >= minimum:
            return index + len(marker)
    index = max(head.rfind(" "), head.rfind("\n"), head.rfind("\t"))
    if index >= minimum:
        return index
    return len(head)


def _split_into_sentences(text: str) -> list[str]:
    """Split text into sentence spans, preserving order.

    Splits first on double newlines (paragraphs), then on sentence-ending
    punctuation followed by whitespace. Lists, tables, and headings are
    treated as sentence-like spans so they are never silently discarded.
    """

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    sentences: list[str] = []
    for para in paragraphs:
        parts = re.split(r"(?<=[.!?])\s+", para)
        for part in parts:
            part = part.strip()
            if part:
                sentences.append(part)
    return sentences


def match_centered_snippet(
    text: str, query_tokens: list[str], limit: int
) -> str:
    """Return a snippet of at most ``limit`` characters centered on matches.

    Unlike :func:`bounded_snippet`, which always starts at the head of the
    chunk, this function:

    1. Splits ``text`` into sentence spans.
    2. Scores each span by how many query tokens it contains.
    3. Selects the highest-scoring span (ties resolved to the earliest index).
    4. Expands the window to include adjacent matching spans, then fills the
       remaining budget with neighboring spans.
    5. Falls back to :func:`bounded_snippet` when no span contains a query
       term.

    The result is deterministic and always clamps to ``limit`` characters.
    """

    if not isinstance(text, str):
        raise TypeError("text must be a string")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("limit must be a positive integer")

    text = text.strip()
    if not text:
        return ""
    if len(text) <= limit:
        return text
    if not query_tokens:
        return bounded_snippet(text, limit)

    sentences = _split_into_sentences(text)
    if not sentences:
        return bounded_snippet(text, limit)

    # Score each sentence by query-token overlap.
    qt = set(query_tokens)
    scores = [len(qt & set(tokenize(s))) for s in sentences]

    # No match anywhere: fall back to head-of-chunk behavior.
    if max(scores) == 0:
        return bounded_snippet(text, limit)

    # Best sentence: highest score, ties resolved to earliest index.
    best_idx = max(range(len(scores)), key=lambda i: (scores[i], -i))

    # Build a contiguous window of matching sentences around the best one.
    window_indices: set[int] = {best_idx}
    changed = True
    while changed:
        changed = False
        for idx in list(window_indices):
            for neighbor in (idx - 1, idx + 1):
                if (
                    0 <= neighbor < len(sentences)
                    and neighbor not in window_indices
                    and scores[neighbor] > 0
                ):
                    window_indices.add(neighbor)
                    changed = True

    # Expand outward to fill the remaining budget, preferring matching
    # neighbors, then filling right, then left (deterministic order).
    left = min(window_indices) - 1
    right = max(window_indices) + 1

    def build(indices: set[int]) -> str:
        return " ".join(sentences[i] for i in sorted(indices))

    while left >= 0 or right < len(sentences):
        if len(build(window_indices)) >= limit - 3:
            break
        added = False
        if right < len(sentences) and scores[right] > 0:
            window_indices.add(right)
            right += 1
            added = True
        elif left >= 0 and scores[left] > 0:
            window_indices.add(left)
            left -= 1
            added = True
        elif right < len(sentences):
            window_indices.add(right)
            right += 1
            added = True
        elif left >= 0:
            window_indices.add(left)
            left -= 1
            added = True
        if not added:
            break

    result = build(window_indices)
    return bounded_snippet(result, limit)


def bounded_snippet(text: str, limit: int) -> str:
    """Return ``text`` shortened to at most ``limit`` characters.

    The cut prefers a paragraph boundary, then a sentence boundary, then
    whitespace, and falls back to a hard cut. An ellipsis is appended only when
    the result does not already end with sentence punctuation.
    """

    if not isinstance(text, str):
        raise TypeError("text must be a string")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("limit must be a positive integer")

    snippet = text.strip()
    if not snippet:
        return ""
    if len(snippet) <= limit:
        return snippet
    if limit <= 3:
        return snippet[:limit].strip()

    budget = limit - 3
    head = snippet[:budget]
    head = head[: _preferred_snippet_cut(head)].rstrip()
    if not head:
        head = snippet[:budget].rstrip()
    if not head:
        return snippet[:limit].strip()
    if head.endswith((".", "!", "?")):
        return head[:limit]
    return (head + "...")[:limit]


def _section_label(section_path: tuple[str, ...]) -> str:
    label = " > ".join(section_path) or "Overview"
    if len(label) > _MAX_SECTION_LABEL:
        label = label[: _MAX_SECTION_LABEL - 3].rstrip() + "..."
    return label


class DocumentationRetriever:
    """Thread-safe, immutable-configuration retrieval facade.

    The wrapped :class:`~backend.agent.rag.bm25.Bm25Index` may be rebuilt by
    another thread; each call reads the index version once and performs one
    search.
    """

    def __init__(
        self,
        index: Bm25Index,
        *,
        min_score: float = DEFAULT_MIN_SCORE,
        relative_score_floor: float = RELATIVE_SCORE_FLOOR,
        max_hits_per_doc: int = DEFAULT_MAX_HITS_PER_DOC,
        max_snippet_chars: int = DEFAULT_MAX_SNIPPET_CHARS,
        max_total_chars: int = DEFAULT_MAX_TOTAL_CHARS,
        query_expansion: bool = False,
        diagnostic_sink: object = None,
    ) -> None:
        if not isinstance(index, Bm25Index):
            raise RagInvalidArgumentsError(
                "index",
                "index must be a Bm25Index",
            )
        self._index = index
        self._min_score = _configuration_number(min_score, "min_score", 0.0)
        self._relative_score_floor = _configuration_number(
            relative_score_floor,
            "relative_score_floor",
            0.0,
            1.0,
        )
        self._max_hits_per_doc = _configuration_int(
            max_hits_per_doc,
            "max_hits_per_doc",
            1,
            MAX_HITS_PER_DOC,
        )
        self._max_snippet_chars = _configuration_int(
            max_snippet_chars,
            "max_snippet_chars",
            1,
            MAX_SNIPPET_CHARS,
        )
        self._max_total_chars = _configuration_int(
            max_total_chars,
            "max_total_chars",
            1,
            MAX_TOTAL_CHARS,
        )
        self._query_expansion = bool(query_expansion)
        if diagnostic_sink is not None and not callable(diagnostic_sink):
            raise RagInvalidArgumentsError(
                "diagnostic_sink", "diagnostic_sink must be callable or None"
            )
        self._diagnostic_sink = diagnostic_sink

    @property
    def index(self) -> Bm25Index:
        return self._index

    def retrieve(
        self,
        request: RetrievalQuery | str,
        *,
        category: str | None = None,
        top_k: int | None = None,
    ) -> RetrievalResult:
        """Run the guard, then retrieve bounded documentation snippets.

        ``category`` and ``top_k`` override the corresponding fields when a
        :class:`~backend.agent.rag.models.RetrievalQuery` is supplied. Invalid
        arguments raise :class:`RagInvalidArgumentsError`; blocked and
        ambiguous questions never search the index.
        """

        result, _trace = self._retrieve_core(
            request,
            category,
            top_k,
            include_diagnostics=False,
        )
        return result

    def retrieve_with_diagnostics(
        self,
        request: RetrievalQuery | str,
        *,
        category: str | None = None,
        top_k: int | None = None,
        include_query_fingerprint: bool = False,
        include_detailed_scoring: bool = False,
    ) -> DiagnosedRetrieval:
        """Run the guard and retrieval, returning the result plus a trace.

        The returned ``result`` is identical to :meth:`retrieve` for the same
        arguments. The ``trace`` contains guard, expansion, selection, and
        per-hit explanation details. No raw query text, snippet, body, or
        guidance text is included unless a query fingerprint is explicitly
        requested. Detailed per-term score contributions require
        ``include_detailed_scoring=True``.

        A diagnostic sink, if configured in the constructor, is invoked with
        the trace; a failing sink never corrupts the result.
        """

        result, trace = self._retrieve_core(
            request,
            category,
            top_k,
            include_diagnostics=True,
            include_query_fingerprint=include_query_fingerprint,
            include_detailed_scoring=include_detailed_scoring,
        )
        assert trace is not None
        if self._diagnostic_sink is not None:
            # A diagnostic sink must never corrupt a retrieval result.
            try:
                self._diagnostic_sink(trace)
            except Exception:
                pass
        return DiagnosedRetrieval(result=result, trace=trace)

    def _retrieve_core(
        self,
        request: RetrievalQuery | str,
        category: str | None,
        top_k: int | None,
        *,
        include_diagnostics: bool,
        include_query_fingerprint: bool = False,
        include_detailed_scoring: bool = False,
    ) -> tuple[RetrievalResult, RetrievalTrace | None]:
        """Shared retrieval core used by ``retrieve`` and diagnostics.

        ``retrieve`` passes ``include_diagnostics=False`` so the normal path
        allocates nothing diagnostic and is byte-for-byte equivalent to the
        pre-Phase-5 implementation.
        """

        # --- argument validation (identical to the public retrieve contract) ---
        if isinstance(request, RetrievalQuery):
            query_text = request.query
            resolved_category = (
                request.category if category is None else category
            )
            resolved_top_k = (
                request.top_k if top_k is None else top_k
            )
        elif isinstance(request, str):
            query_text = request
            resolved_category = category
            resolved_top_k = DEFAULT_TOP_K if top_k is None else top_k
        else:
            raise RagInvalidArgumentsError(
                "query",
                "query must be a string or RetrievalQuery",
            )

        if resolved_category is not None:
            if (
                not isinstance(resolved_category, str)
                or resolved_category not in CATEGORIES
            ):
                raise RagInvalidArgumentsError(
                    "category",
                    "category must be one of: " + ", ".join(CATEGORIES),
                )

        if (
            isinstance(resolved_top_k, bool)
            or not isinstance(resolved_top_k, int)
            or resolved_top_k < 1
            or resolved_top_k > MAX_TOP_K
        ):
            raise RagInvalidArgumentsError(
                "top_k",
                f"top_k must be an integer between 1 and {MAX_TOP_K}",
            )

        # --- diagnostics inputs (query tokens are needed for snippets even
        # on the normal path, so they are always computed) ---
        query_text_stripped = query_text.strip()
        query_tokens = tokenize(query_text_stripped)
        query_chars = len(query_text_stripped)
        query_fingerprint: str | None = None
        if include_query_fingerprint:
            query_fingerprint = hashlib.sha256(
                query_text_stripped.encode("utf-8")
            ).hexdigest()[:12]

        decision = classify_query(query_text_stripped)
        index_version = self._index.index_version

        # --- diagnostics accumulators ---
        index_searched = False
        guard = GuardTrace(decision)
        expansion = ExpansionTrace(
            enabled=self._query_expansion,
            original_token_count=len(query_tokens) if query_tokens is not None else 0,
            expanded_token_count=len(query_tokens) if query_tokens is not None else 0,
        )
        candidate_count = 0
        best_score: float | None = None
        threshold: float | None = None
        dropped_below_min_score = 0
        dropped_below_relative_floor = 0
        dropped_duplicate_chunk = 0
        dropped_per_document_cap = 0
        dropped_top_k = 0
        selected_explanations: list[HitExplanation] = []

        # --- guard branch: never searches the index ---
        if decision.verdict is not GuardVerdict.ALLOWED:
            kind = decision.live_fact_kind or "listing"
            guidance = decision.guidance or GUIDANCE_BY_KIND[kind]
            result = RetrievalResult(
                query=query_text_stripped,
                status="blocked",
                blocked_reason=kind,
                guidance=guidance,
                hits=(),
                total_chars=0,
                index_version=index_version,
            )
        else:
            index_searched = True

            # Expansion trace terms (diagnostics only).
            if include_diagnostics and self._query_expansion:
                expanded_tokens = expand_query_terms(query_tokens)
                expanded_pairs = expansion_trace(query_tokens)
                expansion = ExpansionTrace(
                    enabled=True,
                    original_token_count=len(query_tokens),
                    expanded_token_count=len(expanded_tokens),
                    expansions=tuple(
                        ExpansionEntry(source=source, added=added)
                        for source, added in expanded_pairs
                    ),
                )

            scored = self._index.search(
                query_text_stripped,
                category=resolved_category,  # type: ignore[arg-type]
                limit=None,
                expand_query=self._query_expansion,
            )
            candidate_count = len(scored)

            if not scored:
                result = self._no_match(query_text_stripped, index_version)
            else:
                best_score = scored[0].score
                threshold = max(
                    self._min_score,
                    self._relative_score_floor * best_score,
                )
                if best_score < self._min_score:
                    dropped_below_min_score = candidate_count
                    result = self._no_match(query_text_stripped, index_version)
                else:
                    selected_list, stats = self._select_with_stats(
                        scored, threshold, resolved_top_k
                    )
                    dropped_below_min_score = stats["dropped_below_min_score"]
                    dropped_below_relative_floor = stats[
                        "dropped_below_relative_floor"
                    ]
                    dropped_duplicate_chunk = stats["dropped_duplicate_chunk"]
                    dropped_per_document_cap = stats["dropped_per_document_cap"]
                    dropped_top_k = stats["dropped_top_k"]

                    # Detailed scoring (opt-in): search_detailed mirrors search
                    # exactly but also returns per-term contributions.
                    detailed_map: dict[str, DetailedScoredChunk] = {}
                    if include_diagnostics and include_detailed_scoring:
                        detailed_results = self._index.search_detailed(
                            query_text_stripped,
                            category=resolved_category,  # type: ignore[arg-type]
                            limit=None,
                            expand_query=self._query_expansion,
                        )
                        detailed_map = {
                            item.chunk.chunk_id: item
                            for item in detailed_results
                        }

                    hits: list[RetrievalHit] = []
                    total_chars = 0
                    for rank, item in enumerate(selected_list, start=1):
                        remaining = self._max_total_chars - total_chars
                        if remaining < _MIN_SNIPPET_BUDGET:
                            dropped_top_k += len(selected_list) - rank + 1
                            break
                        snippet = match_centered_snippet(
                            item.chunk.text,
                            query_tokens,
                            min(self._max_snippet_chars, remaining),
                        )
                        if not snippet:
                            dropped_top_k += len(selected_list) - rank + 1
                            break
                        chunk = item.chunk
                        hits.append(
                            RetrievalHit(
                                chunk_id=chunk.chunk_id,
                                doc_id=chunk.doc_id,
                                title=chunk.title,
                                section=_section_label(chunk.section_path),
                                category=chunk.category,
                                fact_kind=chunk.fact_kind,
                                score=item.score,
                                snippet=snippet,
                                source_path=chunk.source_path,
                                updated_at=chunk.updated_at,
                            )
                        )
                        total_chars += len(snippet)

                        if include_diagnostics:
                            chunk_tokens = set(tokenize(chunk.text))
                            matched_terms = tuple(
                                t for t in query_tokens if t in chunk_tokens
                            )
                            contributions: tuple[TermContribution, ...] = ()
                            if (
                                include_detailed_scoring
                                and chunk.chunk_id in detailed_map
                            ):
                                contributions = detailed_map[
                                    chunk.chunk_id
                                ].contributions
                            selected_explanations.append(
                                HitExplanation(
                                    rank=rank,
                                    chunk_id=chunk.chunk_id,
                                    doc_id=chunk.doc_id,
                                    category=chunk.category,
                                    score=item.score,
                                    snippet_chars=len(snippet),
                                    matched_terms=matched_terms,
                                    contributions=contributions,
                                )
                            )

                    if not hits:
                        result = self._no_match(query_text_stripped, index_version)
                    else:
                        result = RetrievalResult(
                            query=query_text_stripped,
                            status="ok",
                            hits=tuple(hits),
                            total_chars=total_chars,
                            index_version=index_version,
                        )

        # --- build the trace (diagnostics only) ---
        trace: RetrievalTrace | None = None
        if include_diagnostics:
            assert query_tokens is not None
            trace = RetrievalTrace(
                status=result.status,
                index_version=index_version,
                index_searched=index_searched,
                guard=guard,
                expansion=expansion,
                query_chars=query_chars,
                query_token_count=len(query_tokens),
                query_fingerprint=query_fingerprint,
                candidate_count=candidate_count,
                best_score=best_score,
                threshold=threshold,
                dropped_below_min_score=dropped_below_min_score,
                dropped_below_relative_floor=dropped_below_relative_floor,
                dropped_duplicate_chunk=dropped_duplicate_chunk,
                dropped_per_document_cap=dropped_per_document_cap,
                dropped_top_k=dropped_top_k,
                selected=tuple(selected_explanations),
                total_chars=result.total_chars,
            )

        return result, trace

    def _select_with_stats(
        self,
        scored: tuple[ScoredChunk, ...],
        threshold: float,
        top_k: int,
    ) -> tuple[list[ScoredChunk], dict[str, int]]:
        """Select hits like :meth:`_select` while counting every drop.

        The selected list is identical to :meth:`_select`; the returned stats
        dictionary is diagnostic-only.
        """

        selected: list[ScoredChunk] = []
        seen_chunks: set[str] = set()
        per_document: dict[str, int] = {}
        dropped_below_min_score = 0
        dropped_below_relative_floor = 0
        dropped_duplicate_chunk = 0
        dropped_per_document_cap = 0
        dropped_top_k = 0

        for item in scored:
            if len(selected) >= top_k:
                dropped_top_k += 1
                continue
            if item.score < self._min_score:
                dropped_below_min_score += 1
                continue
            if item.score < threshold:
                dropped_below_relative_floor += 1
                continue
            chunk_id = item.chunk.chunk_id
            if chunk_id in seen_chunks:
                dropped_duplicate_chunk += 1
                continue
            doc_id = item.chunk.doc_id
            if per_document.get(doc_id, 0) >= self._max_hits_per_doc:
                dropped_per_document_cap += 1
                continue
            seen_chunks.add(chunk_id)
            per_document[doc_id] = per_document.get(doc_id, 0) + 1
            selected.append(item)

        return selected, {
            "dropped_below_min_score": dropped_below_min_score,
            "dropped_below_relative_floor": dropped_below_relative_floor,
            "dropped_duplicate_chunk": dropped_duplicate_chunk,
            "dropped_per_document_cap": dropped_per_document_cap,
            "dropped_top_k": dropped_top_k,
        }

    def _select(
        self,
        scored: tuple[ScoredChunk, ...],
        threshold: float,
        top_k: int,
    ) -> list[ScoredChunk]:
        selected, _stats = self._select_with_stats(scored, threshold, top_k)
        return selected

    @staticmethod
    def _no_match(query: str, index_version: str) -> RetrievalResult:
        return RetrievalResult(
            query=query,
            status="no_match",
            guidance=NO_MATCH_GUIDANCE,
            hits=(),
            total_chars=0,
            index_version=index_version,
        )


__all__ = [
    "DocumentationRetriever",
    "NO_MATCH_GUIDANCE",
    "bounded_snippet",
]
