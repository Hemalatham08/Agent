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

import math

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

        decision = classify_query(query_text)
        query_text = query_text.strip()
        index_version = self._index.index_version

        if decision.verdict is not GuardVerdict.ALLOWED:
            kind = decision.live_fact_kind or "listing"
            guidance = decision.guidance or GUIDANCE_BY_KIND[kind]
            return RetrievalResult(
                query=query_text,
                status="blocked",
                blocked_reason=kind,
                guidance=guidance,
                hits=(),
                total_chars=0,
                index_version=index_version,
            )

        scored = self._index.search(
            query_text,
            category=resolved_category,  # type: ignore[arg-type]
            limit=None,
        )
        if not scored:
            return self._no_match(query_text, index_version)

        best_score = scored[0].score
        if best_score < self._min_score:
            return self._no_match(query_text, index_version)

        threshold = max(
            self._min_score,
            self._relative_score_floor * best_score,
        )
        selected = self._select(scored, threshold, resolved_top_k)

        hits: list[RetrievalHit] = []
        total_chars = 0
        for item in selected:
            remaining = self._max_total_chars - total_chars
            if remaining < _MIN_SNIPPET_BUDGET:
                break
            snippet = bounded_snippet(
                item.chunk.text,
                min(self._max_snippet_chars, remaining),
            )
            if not snippet:
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

        if not hits:
            return self._no_match(query_text, index_version)

        return RetrievalResult(
            query=query_text,
            status="ok",
            hits=tuple(hits),
            total_chars=total_chars,
            index_version=index_version,
        )

    def _select(
        self,
        scored: tuple[ScoredChunk, ...],
        threshold: float,
        top_k: int,
    ) -> list[ScoredChunk]:
        selected: list[ScoredChunk] = []
        seen_chunks: set[str] = set()
        per_document: dict[str, int] = {}

        for item in scored:
            if item.score < threshold:
                break
            chunk_id = item.chunk.chunk_id
            if chunk_id in seen_chunks:
                continue
            doc_id = item.chunk.doc_id
            if per_document.get(doc_id, 0) >= self._max_hits_per_doc:
                continue
            seen_chunks.add(chunk_id)
            per_document[doc_id] = per_document.get(doc_id, 0) + 1
            selected.append(item)
            if len(selected) >= top_k:
                break

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
