"""Frozen domain and tool models for the documentation-only RAG package.

Every model forbids extra fields and is frozen at the attribute level. Nested
values in fields such as ``hits`` and ``section_path`` are immutable tuples,
so models are safe to share across threads after construction.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

DISCLAIMER = (
    "Retrieved documentation is reference material, not live ERP data. "
    "Use ERP SQL tools for actual quantities, counts, totals, prices, and "
    "statuses."
)

Category = Literal[
    "erp_docs",
    "business_definitions",
    "workflows",
    "policies_faqs",
    "schema",
]
FactKind = Literal["overview", "definition", "workflow", "policy", "faq", "schema"]
RetrievalStatus = Literal["ok", "no_match", "blocked"]
LiveFactKind = Literal[
    "quantity",
    "count",
    "money",
    "status",
    "record_lookup",
    "listing",
]

RagDocumentId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        pattern=r"^[a-z][a-z0-9-]{2,63}$",
    ),
]
RagChunkId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        pattern=r"^[a-z][a-z0-9-]{2,63}#[a-z0-9][a-z0-9-]{0,39}#[0-9]{2}$",
    ),
]
RagTitle = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
]
RagVersion = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=r"^\d+\.\d+\.\d+$"),
]
RagSummary = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=300),
]
RagSourcePath = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=512),
]
RagContentHash = Annotated[
    str,
    StringConstraints(pattern=r"^[0-9a-f]{64}$"),
]
RagIndexVersion = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=64),
]
RagQueryText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=300),
]
RagSnippet = Annotated[
    str,
    StringConstraints(min_length=1, max_length=2000),
]
RagChunkText = Annotated[
    str,
    StringConstraints(min_length=1, max_length=5000),
]
RagSectionLabel = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
]
RagGuidance = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=1000),
]
RagDisclaimer = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=1000),
]

_MAX_LABELS = 12
_MAX_LABEL_CHARS = 40
_MAX_SECTION_DEPTH = 8
_MAX_SECTION_CHARS = 120

_DRIVE_PATTERN = re.compile(r"^[A-Za-z]:")


def _require_single_line(value: str, name: str) -> None:
    if "\n" in value or "\r" in value:
        raise ValueError(f"{name} must be a single line")


def _normalize_labels(values: tuple[str, ...], name: str) -> tuple[str, ...]:
    if len(values) > _MAX_LABELS:
        raise ValueError(f"{name} must contain at most {_MAX_LABELS} entries")

    normalized: list[str] = []
    for item in values:
        candidate = item.strip().lower()
        if not candidate:
            raise ValueError(f"{name} entries must not be blank")
        if len(candidate) > _MAX_LABEL_CHARS:
            raise ValueError(
                f"{name} entries must be at most {_MAX_LABEL_CHARS} characters"
            )
        if candidate in normalized:
            raise ValueError(f"{name} entries must be unique")
        normalized.append(candidate)
    return tuple(normalized)


def _validate_source_path(value: str) -> str:
    if "\\" in value:
        raise ValueError("source_path must use '/' separators")
    if value.startswith("/") or _DRIVE_PATTERN.match(value):
        raise ValueError("source_path must be relative")
    parts = value.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError("source_path must not contain empty or relative segments")
    if not value.endswith(".md"):
        raise ValueError("source_path must reference a Markdown file")
    return value


def _normalize_section_path(values: tuple[str, ...]) -> tuple[str, ...]:
    if len(values) > _MAX_SECTION_DEPTH:
        raise ValueError(
            f"section_path must contain at most {_MAX_SECTION_DEPTH} headings"
        )

    normalized: list[str] = []
    for item in values:
        candidate = item.strip()
        if not candidate:
            raise ValueError("section_path entries must not be blank")
        if len(candidate) > _MAX_SECTION_CHARS:
            raise ValueError(
                "section_path entries must be at most "
                f"{_MAX_SECTION_CHARS} characters"
            )
        normalized.append(candidate)
    return tuple(normalized)


class KnowledgeDocument(BaseModel):
    """One reviewed Markdown document from the knowledge corpus."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    doc_id: RagDocumentId
    title: RagTitle
    category: Category
    fact_kind: FactKind
    version: RagVersion
    updated_at: date
    summary: RagSummary
    tags: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    source_path: Annotated[
        RagSourcePath,
        Field(description="Posix-relative path inside the knowledge directory."),
    ]
    content_hash: RagContentHash
    body: Annotated[str, StringConstraints(min_length=40, max_length=20_000)]

    @model_validator(mode="after")
    def validate_document(self) -> KnowledgeDocument:
        _require_single_line(self.title, "title")
        _require_single_line(self.summary, "summary")
        object.__setattr__(self, "tags", _normalize_labels(self.tags, "tags"))
        object.__setattr__(
            self,
            "aliases",
            _normalize_labels(self.aliases, "aliases"),
        )
        _validate_source_path(self.source_path)
        return self


class KnowledgeChunk(BaseModel):
    """One retrievable, heading-scoped slice of a knowledge document."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk_id: RagChunkId
    doc_id: RagDocumentId
    title: RagTitle
    section_path: tuple[str, ...] = ()
    category: Category
    fact_kind: FactKind
    text: RagChunkText
    token_count: int = Field(ge=0)
    source_path: RagSourcePath
    updated_at: date

    @model_validator(mode="after")
    def validate_chunk(self) -> KnowledgeChunk:
        object.__setattr__(
            self,
            "section_path",
            _normalize_section_path(self.section_path),
        )
        if not self.chunk_id.startswith(f"{self.doc_id}#"):
            raise ValueError("chunk_id must start with '<doc_id>#'")
        _validate_source_path(self.source_path)
        return self


class RetrievalQuery(BaseModel):
    """Validated retrieval request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    query: RagQueryText
    category: Category | None = None
    top_k: int = Field(default=3, ge=1, le=5)

    @model_validator(mode="after")
    def validate_query(self) -> RetrievalQuery:
        _require_single_line(self.query, "query")
        return self


class RetrievalHit(BaseModel):
    """One ranked documentation snippet returned to the caller."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk_id: RagChunkId
    doc_id: RagDocumentId
    title: RagTitle
    section: RagSectionLabel
    category: Category
    fact_kind: FactKind
    score: float = Field(ge=0.0)
    snippet: RagSnippet
    source_path: RagSourcePath
    updated_at: date


class RetrievalResult(BaseModel):
    """Outcome of one documentation search.

    ``status`` values are mutually exclusive:

    * ``blocked``: a live ERP fact question; no documentation was retrieved.
    * ``no_match``: retrieval ran but nothing met the thresholds.
    * ``ok``: at least one hit is present.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    query: RagQueryText
    status: RetrievalStatus
    blocked_reason: LiveFactKind | None = None
    guidance: RagGuidance | None = None
    hits: tuple[RetrievalHit, ...] = ()
    total_chars: int = Field(ge=0)
    index_version: RagIndexVersion
    live_data: Literal[False] = False
    disclaimer: RagDisclaimer = DISCLAIMER

    @model_validator(mode="after")
    def validate_result(self) -> RetrievalResult:
        if self.status == "blocked":
            if self.blocked_reason is None:
                raise ValueError("blocked results require blocked_reason")
            if self.hits:
                raise ValueError("blocked results must not contain hits")
            if self.guidance is None:
                raise ValueError("blocked results require guidance")
        elif self.status == "no_match":
            if self.blocked_reason is not None:
                raise ValueError("no_match results must not set blocked_reason")
            if self.hits:
                raise ValueError("no_match results must not contain hits")
        else:  # "ok"
            if self.blocked_reason is not None:
                raise ValueError("successful results must not set blocked_reason")
            if not self.hits:
                raise ValueError("successful results require at least one hit")

        expected_chars = sum(len(hit.snippet) for hit in self.hits)
        if self.total_chars != expected_chars:
            raise ValueError(
                "total_chars must equal the sum of hit snippet lengths"
            )
        return self


class DocumentView(BaseModel):
    """Full (bounded) document body for a follow-up lookup."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    doc_id: RagDocumentId
    title: RagTitle
    category: Category
    fact_kind: FactKind
    version: RagVersion
    updated_at: date
    source_path: RagSourcePath
    body: Annotated[str, StringConstraints(min_length=1, max_length=100_000)]
    truncated: bool = False
    live_data: Literal[False] = False
    disclaimer: RagDisclaimer = DISCLAIMER

    @model_validator(mode="after")
    def validate_view(self) -> DocumentView:
        _validate_source_path(self.source_path)
        return self


class TopicInfo(BaseModel):
    """Compact description used by the topic listing tool."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    doc_id: RagDocumentId
    title: RagTitle
    category: Category
    fact_kind: FactKind
    summary: RagSummary
    version: RagVersion
    updated_at: date


class TopicListResult(BaseModel):
    """Bounded listing of available documentation topics."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    items: tuple[TopicInfo, ...] = ()
    count: int = Field(ge=0)
    live_data: Literal[False] = False
    disclaimer: RagDisclaimer = DISCLAIMER

    @model_validator(mode="after")
    def validate_count(self) -> TopicListResult:
        if self.count != len(self.items):
            raise ValueError("count must equal the number of items")
        return self


class CorpusBundle(BaseModel):
    """Validated corpus assembly produced by the loader."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    documents: tuple[KnowledgeDocument, ...] = ()
    chunks: tuple[KnowledgeChunk, ...] = ()
    index_version: RagIndexVersion

    @model_validator(mode="after")
    def validate_bundle(self) -> CorpusBundle:
        document_ids = [document.doc_id for document in self.documents]
        if len(document_ids) != len(set(document_ids)):
            raise ValueError("document ids must be unique")

        chunk_ids = [chunk.chunk_id for chunk in self.chunks]
        if len(chunk_ids) != len(set(chunk_ids)):
            raise ValueError("chunk ids must be unique")

        known_documents = set(document_ids)
        for chunk in self.chunks:
            if chunk.doc_id not in known_documents:
                raise ValueError(
                    f"chunk {chunk.chunk_id} references an unknown document"
                )

        documents_with_chunks = {chunk.doc_id for chunk in self.chunks}
        missing = known_documents - documents_with_chunks
        if missing:
            raise ValueError(
                "documents without chunks: " + ", ".join(sorted(missing))
            )
        return self


__all__ = [
    "Category",
    "CorpusBundle",
    "DISCLAIMER",
    "DocumentView",
    "FactKind",
    "KnowledgeChunk",
    "KnowledgeDocument",
    "LiveFactKind",
    "RetrievalHit",
    "RetrievalQuery",
    "RetrievalResult",
    "RetrievalStatus",
    "TopicInfo",
    "TopicListResult",
]
