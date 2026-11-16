"""Read-only handlers implementing the three ``rag.knowledge.*`` tools.

The handlers adapt the Stage 5 guard-first retriever and the Stage 3 corpus
bundle to the existing tool contract. They never read the filesystem at call
time, never query the ERP database, and never accept a path from a caller:

* ``rag.knowledge.search`` delegates to
  :class:`~backend.agent.rag.retriever.DocumentationRetriever`, which runs the
  live-fact guard before BM25.
* ``rag.knowledge.get`` looks up a document by ID in the already-loaded corpus,
  so arbitrary paths and unrelated files are unreachable.
* ``rag.knowledge.topics`` returns only compact corpus metadata.

Handlers return the same ``{"ok": True, "data": ...}`` /
``{"ok": False, "error": ...}`` envelopes as the ERP handlers. A live-fact
block is a **successful** response whose ``data.status`` is ``"blocked"``: it
carries the guard's reason and guidance so the caller can explain the block
instead of receiving a silently empty result.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any, Callable

from pydantic import JsonValue, TypeAdapter, ValidationError

from backend.agent.rag.config import (
    DEFAULT_MAX_DOCUMENT_CHARS,
    DEFAULT_TOP_K,
    MAX_DOCUMENT_CHARS,
    MAX_TOP_K,
    MIN_DOCUMENT_CHARS,
)
from backend.agent.rag.corpus import CATEGORIES
from backend.agent.rag.definitions import RAG_TOOL_DEFINITIONS_BY_NAME
from backend.agent.rag.errors import (
    RagConfigurationError,
    RagError,
    RagInternalError,
    RagInvalidArgumentsError,
    RagNotFoundError,
)
from backend.agent.rag.models import (
    CorpusBundle,
    DocumentView,
    KnowledgeDocument,
    TopicInfo,
    TopicListResult,
)
from backend.agent.rag.retriever import DocumentationRetriever, bounded_snippet
from backend.agent.tools.contracts import ToolExecutionContext
from backend.agent.tools.validation import validate_arguments

_Handler = Callable[[dict[str, JsonValue], ToolExecutionContext], Any]
_Operation = Callable[[Mapping[str, JsonValue]], Any]
_JSON_VALUE_ADAPTER = TypeAdapter(JsonValue)

_DOC_ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]{2,63}$")


def _success(data: Any) -> dict[str, JsonValue]:
    if hasattr(data, "model_dump"):
        data = data.model_dump(mode="json")
    try:
        _JSON_VALUE_ADAPTER.validate_python(data, strict=True)
        json.dumps(data, allow_nan=False)
    except (TypeError, ValueError, ValidationError) as exc:
        raise RagInternalError() from exc
    return {"ok": True, "data": data}


class RagToolHandlers:
    """Thin handlers that adapt RAG tools to a retriever and corpus bundle."""

    def __init__(
        self,
        retriever: DocumentationRetriever,
        bundle: CorpusBundle,
        *,
        default_top_k: int = DEFAULT_TOP_K,
        max_document_chars: int = DEFAULT_MAX_DOCUMENT_CHARS,
    ) -> None:
        if not isinstance(retriever, DocumentationRetriever):
            raise RagConfigurationError(
                "retriever must be a DocumentationRetriever"
            )
        if not isinstance(bundle, CorpusBundle):
            raise RagConfigurationError("bundle must be a CorpusBundle")
        if (
            isinstance(default_top_k, bool)
            or not isinstance(default_top_k, int)
            or default_top_k < 1
            or default_top_k > MAX_TOP_K
        ):
            raise RagConfigurationError(
                f"default_top_k must be an integer between 1 and {MAX_TOP_K}"
            )
        if (
            isinstance(max_document_chars, bool)
            or not isinstance(max_document_chars, int)
            or max_document_chars < MIN_DOCUMENT_CHARS
            or max_document_chars > MAX_DOCUMENT_CHARS
        ):
            raise RagConfigurationError(
                "max_document_chars must be an integer between "
                f"{MIN_DOCUMENT_CHARS} and {MAX_DOCUMENT_CHARS}"
            )

        self._retriever = retriever
        self._bundle = bundle
        self._documents = {
            document.doc_id: document for document in bundle.documents
        }
        self._default_top_k = default_top_k
        self._max_document_chars = max_document_chars

    @property
    def retriever(self) -> DocumentationRetriever:
        return self._retriever

    @property
    def bundle(self) -> CorpusBundle:
        return self._bundle

    def as_mapping(self) -> dict[str, _Handler]:
        return {
            "rag.knowledge.search": self.search_knowledge,
            "rag.knowledge.get": self.get_document,
            "rag.knowledge.topics": self.list_topics,
        }

    def search_knowledge(
        self,
        arguments: dict[str, JsonValue],
        context: ToolExecutionContext,
    ) -> dict[str, JsonValue]:
        def operation(args: Mapping[str, JsonValue]) -> Any:
            query = args["query"]
            category = args.get("category")
            top_k = args.get("top_k", self._default_top_k)
            return self._retriever.retrieve(
                query,  # type: ignore[arg-type]
                category=category,  # type: ignore[arg-type]
                top_k=top_k,  # type: ignore[arg-type]
            )

        return self._handle("rag.knowledge.search", arguments, operation)

    def get_document(
        self,
        arguments: dict[str, JsonValue],
        context: ToolExecutionContext,
    ) -> dict[str, JsonValue]:
        def operation(args: Mapping[str, JsonValue]) -> Any:
            doc_id = self._normalize_doc_id(args["doc_id"])
            document = self._document_for(doc_id)
            if len(document.body) <= self._max_document_chars:
                body = document.body
                truncated = False
            else:
                body = bounded_snippet(document.body, self._max_document_chars)
                truncated = True

            return DocumentView(
                doc_id=document.doc_id,
                title=document.title,
                category=document.category,
                fact_kind=document.fact_kind,
                version=document.version,
                updated_at=document.updated_at,
                source_path=document.source_path,
                body=body,
                truncated=truncated,
            )

        return self._handle("rag.knowledge.get", arguments, operation)

    def list_topics(
        self,
        arguments: dict[str, JsonValue],
        context: ToolExecutionContext,
    ) -> dict[str, JsonValue]:
        def operation(args: Mapping[str, JsonValue]) -> Any:
            category = args.get("category")
            if category is not None and (
                not isinstance(category, str) or category not in CATEGORIES
            ):
                raise RagInvalidArgumentsError(
                    "category",
                    "category must be one of: " + ", ".join(CATEGORIES),
                )

            documents = [
                document
                for document in self._bundle.documents
                if category is None or document.category == category
            ]
            documents.sort(key=lambda item: (item.category, item.doc_id))
            items = tuple(
                TopicInfo(
                    doc_id=document.doc_id,
                    title=document.title,
                    category=document.category,
                    fact_kind=document.fact_kind,
                    summary=document.summary,
                    version=document.version,
                    updated_at=document.updated_at,
                )
                for document in documents
            )
            return TopicListResult(items=items, count=len(items))

        return self._handle("rag.knowledge.topics", arguments, operation)

    def _handle(
        self,
        tool_name: str,
        arguments: object,
        operation: _Operation,
    ) -> dict[str, JsonValue]:
        try:
            validated = self._validate_arguments(tool_name, arguments)
            return _success(operation(validated))
        except RagError as exc:
            return exc.to_envelope()
        except Exception:
            return RagInternalError().to_envelope()

    @staticmethod
    def _validate_arguments(
        tool_name: str,
        arguments: object,
    ) -> dict[str, JsonValue]:
        if not isinstance(arguments, Mapping):
            raise RagInvalidArgumentsError("arguments")

        definition = RAG_TOOL_DEFINITIONS_BY_NAME[tool_name]
        issues = validate_arguments(arguments, definition.input_schema)
        if issues:
            raise RagInvalidArgumentsError(issues[0].path)
        return dict(arguments)

    @staticmethod
    def _normalize_doc_id(value: object) -> str:
        if not isinstance(value, str):
            raise RagInvalidArgumentsError("doc_id", "doc_id must be a string")
        doc_id = value.strip()
        if not _DOC_ID_PATTERN.fullmatch(doc_id):
            raise RagInvalidArgumentsError(
                "doc_id",
                "doc_id must be a lowercase documentation identifier",
            )
        return doc_id

    def _document_for(self, doc_id: str) -> KnowledgeDocument:
        document = self._documents.get(doc_id)
        if document is None:
            raise RagNotFoundError(
                "document",
                f"Documentation page not found: {doc_id}",
            )
        return document


__all__ = ["RagToolHandlers"]
