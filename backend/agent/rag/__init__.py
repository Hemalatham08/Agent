"""Isolated documentation-only RAG package.

Stage 1 exposes configuration, sanitized errors, frozen models, and
deterministic text utilities. Stage 2 adds deterministic heading-aware
chunking. Stage 3 adds the Markdown corpus loader and the reviewed knowledge
corpus. Stage 4 adds the deterministic in-memory BM25 index. Stage 5 adds the
live-fact query guard and the bounded, guard-first retriever. Stage 6 adds the
isolated ``rag.knowledge.*`` tool definitions, handlers, runner, registration,
and platform. Nothing in this package touches the ERP database, the LLM client,
the prompt layer, or the orchestrator.
"""

from backend.agent.rag.config import (
    BM25_B,
    BM25_K1,
    DEFAULT_KNOWLEDGE_DIR,
    DEFAULT_MAX_CHUNK_CHARS,
    DEFAULT_MAX_DOCUMENT_CHARS,
    DEFAULT_MAX_HITS_PER_DOC,
    DEFAULT_MAX_SNIPPET_CHARS,
    DEFAULT_MAX_TOTAL_CHARS,
    DEFAULT_MIN_CHUNK_CHARS,
    DEFAULT_MIN_SCORE,
    DEFAULT_TOP_K,
    MAX_CHUNKS,
    MAX_CORPUS_BYTES,
    MAX_DOCS,
    MAX_QUERY_CHARS,
    MAX_TOP_K,
    RELATIVE_SCORE_FLOOR,
    RagConfig,
)
from backend.agent.rag.errors import (
    RagConfigurationError,
    RagCorpusError,
    RagError,
    RagIndexError,
    RagInternalError,
    RagInvalidArgumentsError,
    RagNotFoundError,
)
from backend.agent.rag.models import (
    DISCLAIMER,
    CorpusBundle,
    DocumentView,
    KnowledgeChunk,
    KnowledgeDocument,
    RetrievalHit,
    RetrievalQuery,
    RetrievalResult,
    TopicInfo,
    TopicListResult,
)
from backend.agent.rag.text import STOPWORDS, normalize, slugify, tokenize
from backend.agent.rag.chunking import (
    MIN_MEANINGFUL_CHARS,
    chunk_document,
    searchable_text,
)
from backend.agent.rag.corpus import (
    CATEGORIES,
    LiveFactViolation,
    find_live_fact_violations,
    index_version_for,
    load_corpus,
    load_corpus_from_dir,
)
from backend.agent.rag.bm25 import Bm25Index, ScoredChunk
from backend.agent.rag.guard import (
    GuardDecision,
    GuardReason,
    GuardVerdict,
    classify_query,
)
from backend.agent.rag.retriever import DocumentationRetriever, bounded_snippet
from backend.agent.rag.definitions import (
    RAG_TOOL_DEFINITIONS,
    RAG_TOOL_DEFINITIONS_BY_NAME,
    RAG_TOOL_NAMES,
    RAG_TOOL_VERSION,
)
from backend.agent.rag.handlers import RagToolHandlers
from backend.agent.rag.runner import RagToolRunner
from backend.agent.rag.registration import (
    RagToolRegistration,
    register_rag_tools,
)
from backend.agent.rag.platform import RagToolPlatform

__all__ = [
    "BM25_B",
    "BM25_K1",
    "DEFAULT_KNOWLEDGE_DIR",
    "DEFAULT_MAX_CHUNK_CHARS",
    "DEFAULT_MAX_DOCUMENT_CHARS",
    "DEFAULT_MAX_HITS_PER_DOC",
    "DEFAULT_MAX_SNIPPET_CHARS",
    "DEFAULT_MAX_TOTAL_CHARS",
    "DEFAULT_MIN_CHUNK_CHARS",
    "DEFAULT_MIN_SCORE",
    "DEFAULT_TOP_K",
    "DISCLAIMER",
    "MAX_CHUNKS",
    "MAX_CORPUS_BYTES",
    "MAX_DOCS",
    "MAX_QUERY_CHARS",
    "MAX_TOP_K",
    "MIN_MEANINGFUL_CHARS",
    "RAG_TOOL_DEFINITIONS",
    "RAG_TOOL_DEFINITIONS_BY_NAME",
    "RAG_TOOL_NAMES",
    "RAG_TOOL_VERSION",
    "RELATIVE_SCORE_FLOOR",
    "STOPWORDS",
    "CATEGORIES",
    "CorpusBundle",
    "DocumentView",
    "KnowledgeChunk",
    "KnowledgeDocument",
    "LiveFactViolation",
    "RagConfig",
    "RagConfigurationError",
    "RagCorpusError",
    "RagError",
    "RagIndexError",
    "RagInternalError",
    "RagInvalidArgumentsError",
    "RagNotFoundError",
    "RagToolHandlers",
    "RagToolPlatform",
    "RagToolRegistration",
    "RagToolRunner",
    "RetrievalHit",
    "RetrievalQuery",
    "RetrievalResult",
    "TopicInfo",
    "TopicListResult",
    "Bm25Index",
    "ScoredChunk",
    "DocumentationRetriever",
    "GuardDecision",
    "GuardReason",
    "GuardVerdict",
    "bounded_snippet",
    "chunk_document",
    "classify_query",
    "find_live_fact_violations",
    "index_version_for",
    "load_corpus",
    "load_corpus_from_dir",
    "normalize",
    "register_rag_tools",
    "searchable_text",
    "slugify",
    "tokenize",
]
