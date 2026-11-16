from __future__ import annotations

import ast
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from backend.agent.rag.bm25 import Bm25Index
from backend.agent.rag.config import (
    DEFAULT_MAX_DOCUMENT_CHARS,
    DEFAULT_TOP_K,
    MAX_DOCUMENT_CHARS,
    MAX_TOP_K,
)
from backend.agent.rag.corpus import CATEGORIES, load_corpus_from_dir
from backend.agent.rag.definitions import (
    RAG_TOOL_DEFINITIONS,
    RAG_TOOL_DEFINITIONS_BY_NAME,
    RAG_TOOL_NAMES,
    RAG_TOOL_VERSION,
)
from backend.agent.rag.errors import RagConfigurationError
from backend.agent.rag.handlers import RagToolHandlers
from backend.agent.rag.registration import register_rag_tools
from backend.agent.rag.retriever import DocumentationRetriever
from backend.agent.tools.contracts import (
    ToolDefinition,
    ToolExecutionContext,
)
from backend.agent.tools.errors import (
    DuplicateHandlerError,
    DuplicateToolError,
)
from backend.agent.tools.executor import ToolExecutor
from backend.agent.tools.registry import ToolRegistry
from backend.tests.rag_tool_support import (
    LONG_REFERENCE_BODY,
    make_rag_config,
    write_long_document,
    write_tool_corpus,
)


def make_context(tool_name: str) -> ToolExecutionContext:
    return ToolExecutionContext(
        execution_id="exec-rag",
        tool_name=tool_name,
        started_at=datetime(2026, 11, 16, tzinfo=timezone.utc),
    )


def assert_error_envelope(
    testcase: unittest.TestCase,
    envelope: dict,
    *,
    code: str,
    category: str,
) -> dict:
    testcase.assertEqual(set(envelope), {"ok", "error"})
    testcase.assertIs(envelope["ok"], False)
    error = envelope["error"]
    testcase.assertEqual(
        set(error),
        {
            "code",
            "message",
            "category",
            "recoverable",
            "retryable",
            "details",
        },
    )
    testcase.assertEqual(error["code"], code)
    testcase.assertEqual(error["category"], category)
    return error


class RagToolDefinitionTests(unittest.TestCase):
    def test_catalog_has_three_namespaced_tools(self) -> None:
        self.assertEqual(
            RAG_TOOL_NAMES,
            (
                "rag.knowledge.search",
                "rag.knowledge.get",
                "rag.knowledge.topics",
            ),
        )
        self.assertEqual(len(RAG_TOOL_DEFINITIONS), 3)
        for name in RAG_TOOL_NAMES:
            self.assertTrue(name.startswith("rag.knowledge."))

    def test_catalog_maps_are_consistent(self) -> None:
        self.assertEqual(
            tuple(RAG_TOOL_DEFINITIONS_BY_NAME),
            RAG_TOOL_NAMES,
        )
        for name, definition in RAG_TOOL_DEFINITIONS_BY_NAME.items():
            self.assertEqual(definition.name, name)
            self.assertEqual(definition.version, RAG_TOOL_VERSION)

    def test_every_definition_is_read_only_and_documentation_only(self) -> None:
        for definition in RAG_TOOL_DEFINITIONS:
            with self.subTest(tool=definition.name):
                self.assertEqual(definition.version, "1.0.0")
                self.assertIs(definition.metadata["read_only"], True)
                self.assertIs(definition.metadata["documentation_only"], True)
                self.assertIs(definition.metadata["live_data"], False)

    def test_search_schema(self) -> None:
        schema = RAG_TOOL_DEFINITIONS_BY_NAME["rag.knowledge.search"].input_schema

        self.assertEqual(schema["type"], "object")
        self.assertEqual(set(schema["properties"]), {"query", "category", "top_k"})
        self.assertEqual(schema["required"], ["query"])
        self.assertIs(schema["additionalProperties"], False)
        self.assertEqual(schema["properties"]["query"], {"type": "string"})
        self.assertEqual(schema["properties"]["category"]["type"], "string")
        self.assertEqual(
            schema["properties"]["category"]["enum"],
            list(CATEGORIES),
        )
        self.assertEqual(schema["properties"]["top_k"]["type"], "integer")

    def test_get_schema(self) -> None:
        schema = RAG_TOOL_DEFINITIONS_BY_NAME["rag.knowledge.get"].input_schema

        self.assertEqual(set(schema["properties"]), {"doc_id"})
        self.assertEqual(schema["properties"]["doc_id"], {"type": "string"})
        self.assertEqual(schema["required"], ["doc_id"])
        self.assertIs(schema["additionalProperties"], False)

    def test_topics_schema_has_only_an_optional_category(self) -> None:
        schema = RAG_TOOL_DEFINITIONS_BY_NAME[
            "rag.knowledge.topics"
        ].input_schema

        self.assertEqual(set(schema["properties"]), {"category"})
        self.assertEqual(schema["properties"]["category"]["enum"], list(CATEGORIES))
        self.assertNotIn("required", schema)
        self.assertIs(schema["additionalProperties"], False)

    def test_descriptions_document_intended_use_and_live_fact_boundary(self) -> None:
        search = RAG_TOOL_DEFINITIONS_BY_NAME["rag.knowledge.search"].description
        get = RAG_TOOL_DEFINITIONS_BY_NAME["rag.knowledge.get"].description
        topics = RAG_TOOL_DEFINITIONS_BY_NAME["rag.knowledge.topics"].description

        self.assertIn("ERP SQL tools", search)
        self.assertIn("live stock quantities", search)
        self.assertIn("doc_id", get)
        self.assertIn("never returns live ERP records", get)
        self.assertIn("documentation topics", topics)
        self.assertIn("never returns page bodies", topics)

    def test_definitions_round_trip_through_the_registry(self) -> None:
        registry = ToolRegistry()
        for definition in RAG_TOOL_DEFINITIONS:
            registry.register(definition)

        self.assertEqual(
            {definition.name for definition in registry.list_tools()},
            set(RAG_TOOL_NAMES),
        )
        for name in RAG_TOOL_NAMES:
            restored = registry.get(name)
            self.assertEqual(restored, RAG_TOOL_DEFINITIONS_BY_NAME[name])


class _HandlerTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = TemporaryDirectory()
        self.addCleanup(self._temp_dir.cleanup)
        self.root = Path(self._temp_dir.name)
        write_tool_corpus(self.root)
        self.bundle = load_corpus_from_dir(self.root, min_chunk_chars=0)
        self.index = Bm25Index(self.bundle)
        self.retriever = DocumentationRetriever(self.index)
        self.handlers = RagToolHandlers(self.retriever, self.bundle)


class RagToolSearchHandlerTests(_HandlerTestCase):
    def test_mapping_matches_the_catalog(self) -> None:
        self.assertEqual(
            set(self.handlers.as_mapping()),
            set(RAG_TOOL_NAMES),
        )

    def test_search_returns_a_bound_success_envelope(self) -> None:
        envelope = self.handlers.search_knowledge(
            {"query": "  What is free stock?  "},
            make_context("rag.knowledge.search"),
        )

        self.assertEqual(set(envelope), {"ok", "data"})
        self.assertIs(envelope["ok"], True)
        data = envelope["data"]
        self.assertEqual(
            set(data),
            {
                "query",
                "status",
                "blocked_reason",
                "guidance",
                "hits",
                "total_chars",
                "index_version",
                "live_data",
                "disclaimer",
            },
        )
        self.assertEqual(data["query"], "What is free stock?")
        self.assertEqual(data["status"], "ok")
        self.assertIsNone(data["blocked_reason"])
        self.assertIs(data["live_data"], False)
        self.assertEqual(data["index_version"], self.bundle.index_version)
        self.assertTrue(data["hits"])
        self.assertEqual(data["hits"][0]["doc_id"], "free-stock")
        self.assertEqual(
            data["total_chars"],
            sum(len(hit["snippet"]) for hit in data["hits"]),
        )
        for hit in data["hits"]:
            self.assertEqual(
                set(hit),
                {
                    "chunk_id",
                    "doc_id",
                    "title",
                    "section",
                    "category",
                    "fact_kind",
                    "score",
                    "snippet",
                    "source_path",
                    "updated_at",
                },
            )

    def test_search_category_filter_can_return_no_match(self) -> None:
        envelope = self.handlers.search_knowledge(
            {"query": "What is free stock?", "category": "schema"},
            make_context("rag.knowledge.search"),
        )

        data = envelope["data"]
        self.assertEqual(data["status"], "no_match")
        self.assertEqual(data["hits"], [])
        self.assertEqual(data["total_chars"], 0)
        self.assertIsNotNone(data["guidance"])

    def test_search_top_k_is_bounded(self) -> None:
        envelope = self.handlers.search_knowledge(
            {"query": "What is stock or order?", "top_k": 1},
            make_context("rag.knowledge.search"),
        )

        self.assertEqual(envelope["data"]["status"], "ok")
        self.assertLessEqual(len(envelope["data"]["hits"]), 1)

    def test_live_query_is_blocked_with_guidance_and_no_hits(self) -> None:
        envelope = self.handlers.search_knowledge(
            {"query": "How many products do we have?"},
            make_context("rag.knowledge.search"),
        )

        self.assertIs(envelope["ok"], True)
        data = envelope["data"]
        self.assertEqual(data["status"], "blocked")
        self.assertEqual(data["blocked_reason"], "count")
        self.assertEqual(data["hits"], [])
        self.assertEqual(data["total_chars"], 0)
        self.assertTrue(data["guidance"])
        self.assertIs(data["live_data"], False)

    def test_guard_runs_before_bm25(self) -> None:
        with patch.object(
            self.index,
            "search",
            side_effect=AssertionError("BM25 must not run"),
        ):
            envelope = self.handlers.search_knowledge(
                {"query": "How many products do we have?"},
                make_context("rag.knowledge.search"),
            )

        self.assertIs(envelope["ok"], True)
        self.assertEqual(envelope["data"]["status"], "blocked")

    def test_invalid_top_k_is_a_validation_error(self) -> None:
        for top_k in (0, 6, -1):
            with self.subTest(top_k=top_k):
                envelope = self.handlers.search_knowledge(
                    {"query": "What is free stock?", "top_k": top_k},
                    make_context("rag.knowledge.search"),
                )
                error = assert_error_envelope(
                    self,
                    envelope,
                    code="rag_invalid_arguments",
                    category="validation",
                )
                self.assertEqual(error["details"], {"field": "top_k"})
                self.assertIs(error["recoverable"], True)
                self.assertIs(error["retryable"], False)

    def test_invalid_category_is_a_validation_error(self) -> None:
        envelope = self.handlers.search_knowledge(
            {"query": "What is free stock?", "category": "reports"},
            make_context("rag.knowledge.search"),
        )
        error = assert_error_envelope(
            self,
            envelope,
            code="rag_invalid_arguments",
            category="validation",
        )
        self.assertEqual(error["details"], {"field": "category"})

    def test_missing_query_is_a_validation_error(self) -> None:
        envelope = self.handlers.search_knowledge(
            {},
            make_context("rag.knowledge.search"),
        )
        error = assert_error_envelope(
            self,
            envelope,
            code="rag_invalid_arguments",
            category="validation",
        )
        self.assertEqual(error["details"], {"field": "query"})

    def test_wrong_query_type_is_a_validation_error(self) -> None:
        envelope = self.handlers.search_knowledge(
            {"query": 3},
            make_context("rag.knowledge.search"),
        )
        error = assert_error_envelope(
            self,
            envelope,
            code="rag_invalid_arguments",
            category="validation",
        )
        self.assertEqual(error["details"], {"field": "query"})

    def test_unexpected_argument_is_a_validation_error(self) -> None:
        envelope = self.handlers.search_knowledge(
            {"query": "What is free stock?", "sql": "SELECT 1"},
            make_context("rag.knowledge.search"),
        )
        error = assert_error_envelope(
            self,
            envelope,
            code="rag_invalid_arguments",
            category="validation",
        )
        self.assertEqual(error["details"], {"field": "sql"})

    def test_empty_multiline_and_oversized_queries_are_rejected(self) -> None:
        for query in ("", "   ", "first\nsecond", "x" * 301):
            with self.subTest(query=repr(query)):
                envelope = self.handlers.search_knowledge(
                    {"query": query},
                    make_context("rag.knowledge.search"),
                )
                error = assert_error_envelope(
                    self,
                    envelope,
                    code="rag_invalid_arguments",
                    category="validation",
                )
                self.assertEqual(error["details"], {"field": "query"})


class RagToolGetHandlerTests(_HandlerTestCase):
    def test_get_returns_bounded_document_and_metadata(self) -> None:
        envelope = self.handlers.get_document(
            {"doc_id": "free-stock"},
            make_context("rag.knowledge.get"),
        )

        self.assertEqual(set(envelope), {"ok", "data"})
        data = envelope["data"]
        self.assertEqual(
            set(data),
            {
                "doc_id",
                "title",
                "category",
                "fact_kind",
                "version",
                "updated_at",
                "source_path",
                "body",
                "truncated",
                "live_data",
                "disclaimer",
            },
        )
        self.assertEqual(data["doc_id"], "free-stock")
        self.assertEqual(data["title"], "Free Stock and Reserved Stock")
        self.assertEqual(data["category"], "business_definitions")
        self.assertEqual(data["fact_kind"], "definition")
        self.assertEqual(data["version"], "1.0.0")
        self.assertEqual(data["updated_at"], "2026-11-01")
        self.assertEqual(
            data["source_path"],
            "business_definitions/free-stock.md",
        )
        self.assertNotIn("\\", data["source_path"])
        self.assertFalse(data["source_path"].startswith("/"))
        self.assertNotIn("..", data["source_path"])
        self.assertEqual(data["body"], self.bundle.documents[0].body)
        self.assertIs(data["truncated"], False)
        self.assertIs(data["live_data"], False)
        self.assertTrue(data["disclaimer"])

    def test_unknown_doc_id_is_not_found(self) -> None:
        envelope = self.handlers.get_document(
            {"doc_id": "missing-doc"},
            make_context("rag.knowledge.get"),
        )
        error = assert_error_envelope(
            self,
            envelope,
            code="rag_not_found",
            category="not_found",
        )
        self.assertEqual(error["details"], {"resource": "document"})
        self.assertIs(error["recoverable"], True)
        self.assertIs(error["retryable"], False)
        self.assertIn("missing-doc", error["message"])

    def test_path_like_doc_ids_are_rejected_without_leaking_paths(self) -> None:
        for doc_id in (
            "../free-stock",
            "business_definitions/free-stock",
            "free_stock",
            "Free Stock",
            "a",
            "",
        ):
            with self.subTest(doc_id=doc_id):
                envelope = self.handlers.get_document(
                    {"doc_id": doc_id},
                    make_context("rag.knowledge.get"),
                )
                error = assert_error_envelope(
                    self,
                    envelope,
                    code="rag_invalid_arguments",
                    category="validation",
                )
                self.assertEqual(error["details"], {"field": "doc_id"})
                self.assertNotIn("business_definitions", error["message"])

    def test_missing_doc_id_is_a_validation_error(self) -> None:
        envelope = self.handlers.get_document(
            {},
            make_context("rag.knowledge.get"),
        )
        error = assert_error_envelope(
            self,
            envelope,
            code="rag_invalid_arguments",
            category="validation",
        )
        self.assertEqual(error["details"], {"field": "doc_id"})

    def test_unexpected_argument_is_a_validation_error(self) -> None:
        envelope = self.handlers.get_document(
            {"doc_id": "free-stock", "path": "/etc/passwd"},
            make_context("rag.knowledge.get"),
        )
        error = assert_error_envelope(
            self,
            envelope,
            code="rag_invalid_arguments",
            category="validation",
        )
        self.assertEqual(error["details"], {"field": "path"})

    def test_long_document_is_truncated_to_the_configured_bound(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_tool_corpus(root)
            write_long_document(root)
            bundle = load_corpus_from_dir(root, min_chunk_chars=0)
            index = Bm25Index(bundle)
            handlers = RagToolHandlers(
                DocumentationRetriever(index),
                bundle,
                max_document_chars=100,
            )

            envelope = handlers.get_document(
                {"doc_id": "long-reference"},
                make_context("rag.knowledge.get"),
            )

        self.assertIs(envelope["ok"], True)
        data = envelope["data"]
        self.assertIs(data["truncated"], True)
        self.assertLessEqual(len(data["body"]), 100)
        self.assertTrue(data["body"])
        self.assertGreater(len(LONG_REFERENCE_BODY), 100)


class RagToolTopicsHandlerTests(_HandlerTestCase):
    def test_topics_returns_bounded_metadata_for_every_document(self) -> None:
        envelope = self.handlers.list_topics(
            {},
            make_context("rag.knowledge.topics"),
        )

        self.assertEqual(set(envelope), {"ok", "data"})
        data = envelope["data"]
        self.assertEqual(
            set(data),
            {"items", "count", "live_data", "disclaimer"},
        )
        self.assertEqual(data["count"], 5)
        self.assertEqual(len(data["items"]), data["count"])
        self.assertIs(data["live_data"], False)
        self.assertTrue(data["disclaimer"])
        for item in data["items"]:
            self.assertEqual(
                set(item),
                {
                    "doc_id",
                    "title",
                    "category",
                    "fact_kind",
                    "summary",
                    "version",
                    "updated_at",
                },
            )
            self.assertNotIn("body", item)
            self.assertNotIn("source_path", item)

    def test_topics_are_sorted_deterministically(self) -> None:
        first = self.handlers.list_topics(
            {},
            make_context("rag.knowledge.topics"),
        )
        second = self.handlers.list_topics(
            {},
            make_context("rag.knowledge.topics"),
        )

        self.assertEqual(first, second)
        keys = [
            (item["category"], item["doc_id"])
            for item in first["data"]["items"]
        ]
        self.assertEqual(keys, sorted(keys))

    def test_topics_category_filter(self) -> None:
        envelope = self.handlers.list_topics(
            {"category": "schema"},
            make_context("rag.knowledge.topics"),
        )

        data = envelope["data"]
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["items"][0]["doc_id"], "sales-order-schema")
        self.assertEqual(data["items"][0]["category"], "schema")

    def test_unknown_topic_category_is_a_validation_error(self) -> None:
        envelope = self.handlers.list_topics(
            {"category": "reports"},
            make_context("rag.knowledge.topics"),
        )
        error = assert_error_envelope(
            self,
            envelope,
            code="rag_invalid_arguments",
            category="validation",
        )
        self.assertEqual(error["details"], {"field": "category"})

    def test_unexpected_argument_is_a_validation_error(self) -> None:
        envelope = self.handlers.list_topics(
            {"limit": 10},
            make_context("rag.knowledge.topics"),
        )
        error = assert_error_envelope(
            self,
            envelope,
            code="rag_invalid_arguments",
            category="validation",
        )
        self.assertEqual(error["details"], {"field": "limit"})


class RagToolHandlerConstructorTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = TemporaryDirectory()
        self.addCleanup(self._temp_dir.cleanup)
        root = Path(self._temp_dir.name)
        write_tool_corpus(root)
        self.bundle = load_corpus_from_dir(root, min_chunk_chars=0)
        self.retriever = DocumentationRetriever(Bm25Index(self.bundle))

    def test_retriever_and_bundle_types_are_checked(self) -> None:
        with self.assertRaises(RagConfigurationError):
            RagToolHandlers("not a retriever", self.bundle)  # type: ignore[arg-type]
        with self.assertRaises(RagConfigurationError):
            RagToolHandlers(self.retriever, "not a bundle")  # type: ignore[arg-type]

    def test_default_top_k_is_validated(self) -> None:
        for value in (0, MAX_TOP_K + 1, True, "3"):
            with self.subTest(value=repr(value)):
                with self.assertRaises(RagConfigurationError):
                    RagToolHandlers(
                        self.retriever,
                        self.bundle,
                        default_top_k=value,  # type: ignore[arg-type]
                    )

    def test_max_document_chars_is_validated(self) -> None:
        for value in (99, MAX_DOCUMENT_CHARS + 1, True, "6000"):
            with self.subTest(value=repr(value)):
                with self.assertRaises(RagConfigurationError):
                    RagToolHandlers(
                        self.retriever,
                        self.bundle,
                        max_document_chars=value,  # type: ignore[arg-type]
                    )

    def test_documented_defaults_are_accepted(self) -> None:
        handlers = RagToolHandlers(self.retriever, self.bundle)
        self.assertIsInstance(handlers, RagToolHandlers)
        self.assertEqual(DEFAULT_TOP_K, 3)
        self.assertEqual(DEFAULT_MAX_DOCUMENT_CHARS, 6000)


class _IncompleteHandlers(RagToolHandlers):
    def as_mapping(self) -> dict:
        return {"rag.knowledge.search": self.search_knowledge}


class _FailingDefinitionRegistry(ToolRegistry):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def register(self, definition: ToolDefinition) -> None:
        self.calls += 1
        if self.calls == 2:
            raise RuntimeError("definition registration failed")
        super().register(definition)


class _FailingHandlerExecutor(ToolExecutor):
    def __init__(self, registry: ToolRegistry) -> None:
        super().__init__(registry)
        self.handler_calls = 0

    def register_handler(self, tool_name: str, handler) -> None:
        self.handler_calls += 1
        if self.handler_calls == 2:
            raise RuntimeError("handler registration failed")
        super().register_handler(tool_name, handler)


class RagToolRegistrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = TemporaryDirectory()
        self.addCleanup(self._temp_dir.cleanup)
        root = Path(self._temp_dir.name)
        write_tool_corpus(root)
        bundle = load_corpus_from_dir(root, min_chunk_chars=0)
        retriever = DocumentationRetriever(Bm25Index(bundle))
        self.handlers = RagToolHandlers(retriever, bundle)
        self.registry = ToolRegistry()
        self.executor = ToolExecutor(self.registry)
        self.addCleanup(self.executor.shutdown)

    def test_registration_adds_exactly_the_rag_tool_catalog(self) -> None:
        registration = register_rag_tools(
            self.registry,
            self.executor,
            self.handlers,
        )

        self.assertEqual(
            {definition.name for definition in self.registry.list_tools()},
            set(RAG_TOOL_NAMES),
        )
        for name in RAG_TOOL_NAMES:
            self.assertTrue(self.executor.has_handler(name))
        self.assertEqual(registration.tool_names, RAG_TOOL_NAMES)

    def test_duplicate_definition_is_rejected_before_any_handler_registers(
        self,
    ) -> None:
        self.registry.register(RAG_TOOL_DEFINITIONS[0])

        with self.assertRaises(DuplicateToolError):
            register_rag_tools(self.registry, self.executor, self.handlers)

        self.assertEqual(
            {definition.name for definition in self.registry.list_tools()},
            {RAG_TOOL_NAMES[0]},
        )
        for name in RAG_TOOL_NAMES:
            self.assertFalse(self.executor.has_handler(name))

    def test_duplicate_handler_is_rejected_before_any_definition_registers(
        self,
    ) -> None:
        self.executor.register_handler(
            RAG_TOOL_NAMES[0],
            lambda arguments, context: {"ok": True, "data": {}},
        )

        with self.assertRaises(DuplicateHandlerError):
            register_rag_tools(self.registry, self.executor, self.handlers)

        self.assertEqual(self.registry.list_tools(), [])
        self.assertTrue(self.executor.has_handler(RAG_TOOL_NAMES[0]))

    def test_incomplete_handler_catalog_is_rejected(self) -> None:
        incomplete = _IncompleteHandlers(
            self.handlers.retriever,
            self.handlers.bundle,
        )

        with self.assertRaises(ValueError):
            register_rag_tools(self.registry, self.executor, incomplete)

        self.assertEqual(self.registry.list_tools(), [])

    def test_definition_failure_rolls_back_partial_registration(self) -> None:
        registry = _FailingDefinitionRegistry()

        with self.assertRaises(RuntimeError):
            register_rag_tools(registry, self.executor, self.handlers)

        self.assertEqual(registry.list_tools(), [])
        for name in RAG_TOOL_NAMES:
            self.assertFalse(self.executor.has_handler(name))

    def test_handler_failure_rolls_back_definitions_and_handlers(self) -> None:
        executor = _FailingHandlerExecutor(self.registry)
        self.addCleanup(executor.shutdown)

        with self.assertRaises(RuntimeError):
            register_rag_tools(self.registry, executor, self.handlers)

        self.assertEqual(self.registry.list_tools(), [])
        for name in RAG_TOOL_NAMES:
            self.assertFalse(executor.has_handler(name))

    def test_unregister_is_complete_and_idempotent(self) -> None:
        registration = register_rag_tools(
            self.registry,
            self.executor,
            self.handlers,
        )

        registration.unregister()
        registration.unregister()

        self.assertEqual(self.registry.list_tools(), [])
        for name in RAG_TOOL_NAMES:
            self.assertFalse(self.executor.has_handler(name))

    def test_context_manager_unregisters(self) -> None:
        with register_rag_tools(
            self.registry,
            self.executor,
            self.handlers,
        ):
            self.assertEqual(
                {definition.name for definition in self.registry.list_tools()},
                set(RAG_TOOL_NAMES),
            )

        self.assertEqual(self.registry.list_tools(), [])
        for name in RAG_TOOL_NAMES:
            self.assertFalse(self.executor.has_handler(name))

    def test_unrelated_tools_are_preserved(self) -> None:
        other = ToolDefinition(
            name="test.other",
            description="An unrelated test tool.",
            input_schema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        )
        self.registry.register(other)
        self.executor.register_handler(
            "test.other",
            lambda arguments, context: {"ok": True, "data": {"value": 1}},
        )

        registration = register_rag_tools(
            self.registry,
            self.executor,
            self.handlers,
        )
        registration.unregister()

        self.assertEqual(
            [definition.name for definition in self.registry.list_tools()],
            ["test.other"],
        )
        self.assertTrue(self.executor.has_handler("test.other"))


class RagToolImportBoundaryTests(unittest.TestCase):
    _ALLOWED_STDLIB = frozenset(
        {
            "__future__",
            "ast",
            "collections",
            "concurrent",
            "copy",
            "dataclasses",
            "datetime",
            "enum",
            "hashlib",
            "json",
            "math",
            "os",
            "pathlib",
            "re",
            "threading",
            "time",
            "typing",
            "unicodedata",
            "uuid",
        }
    )
    _ALLOWED_THIRD_PARTY = frozenset({"pydantic"})
    _ALLOWED_BACKEND = (
        "backend.agent.models",
        "backend.agent.rag",
        "backend.agent.tools.contracts",
        "backend.agent.tools.errors",
        "backend.agent.tools.executor",
        "backend.agent.tools.registry",
        "backend.agent.tools.validation",
    )
    _FORBIDDEN_PREFIXES = (
        "backend.agent.erp",
        "backend.agent.llm",
        "backend.agent.orchestrator",
        "backend.main",
        "chromadb",
        "faiss",
        "httpx",
        "numpy",
        "openai",
        "rank_bm25",
        "requests",
        "sentence_transformers",
        "sqlalchemy",
        "sqlite3",
        "torch",
    )

    def _check_module(self, path: Path, module: str) -> None:
        if not module:
            return
        for prefix in self._FORBIDDEN_PREFIXES:
            self.assertFalse(
                module == prefix or module.startswith(prefix + "."),
                f"{path.name} imports forbidden module {module}",
            )

        if module == "backend.agent.models":
            return
        if module in self._ALLOWED_BACKEND:
            return
        if module.startswith("backend.agent.rag."):
            return
        if module.startswith(
            (
                "backend.agent.tools.contracts.",
                "backend.agent.tools.errors.",
                "backend.agent.tools.executor.",
                "backend.agent.tools.registry.",
                "backend.agent.tools.validation.",
            )
        ):
            return

        root = module.split(".")[0]
        if root in self._ALLOWED_STDLIB:
            return
        if root in self._ALLOWED_THIRD_PARTY:
            return
        self.fail(f"{path.name} imports unapproved module {module}")

    def test_rag_package_imports_only_approved_dependencies(self) -> None:
        rag_dir = Path(__file__).resolve().parents[1] / "agent" / "rag"
        files = sorted(rag_dir.rglob("*.py"))
        self.assertTrue(files)

        for path in files:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self._check_module(path, alias.name)
                elif isinstance(node, ast.ImportFrom):
                    self.assertEqual(node.level, 0, f"{path.name} uses a relative import")
                    self._check_module(path, node.module or "")

    def test_stage_six_modules_do_not_import_production_agent_layers(self) -> None:
        rag_dir = Path(__file__).resolve().parents[1] / "agent" / "rag"
        stage_six = (
            rag_dir / "definitions.py",
            rag_dir / "handlers.py",
            rag_dir / "runner.py",
            rag_dir / "registration.py",
            rag_dir / "platform.py",
        )

        for path in stage_six:
            text = path.read_text(encoding="utf-8")
            with self.subTest(module=path.name):
                for forbidden in (
                    "backend.agent.erp",
                    "backend.agent.llm",
                    "backend.agent.orchestrator",
                    "backend.main",
                    "sqlite3",
                    "sqlalchemy",
                ):
                    self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
