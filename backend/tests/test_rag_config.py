from __future__ import annotations

import os
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from datetime import date
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from backend.agent.models import ErrorCategory
from backend.agent.rag import (
    DEFAULT_MAX_CHUNK_CHARS,
    DEFAULT_MAX_DOCUMENT_CHARS,
    DEFAULT_MAX_HITS_PER_DOC,
    DEFAULT_MAX_SNIPPET_CHARS,
    DEFAULT_MAX_TOTAL_CHARS,
    DEFAULT_MIN_CHUNK_CHARS,
    DEFAULT_MIN_SCORE,
    DEFAULT_TOP_K,
    DISCLAIMER,
    MAX_CHUNKS,
    MAX_CORPUS_BYTES,
    MAX_DOCS,
    MAX_QUERY_CHARS,
    MAX_TOP_K,
    RELATIVE_SCORE_FLOOR,
    CorpusBundle,
    DocumentView,
    KnowledgeChunk,
    KnowledgeDocument,
    RagConfig,
    RagConfigurationError,
    RagCorpusError,
    RagError,
    RagIndexError,
    RagInternalError,
    RagInvalidArgumentsError,
    RagNotFoundError,
    RetrievalHit,
    RetrievalQuery,
    RetrievalResult,
    TopicInfo,
    TopicListResult,
)
from backend.agent.rag.config import (
    DEFAULT_KNOWLEDGE_DIR,
    RAG_DEFAULT_TOP_K_ENV,
    RAG_ENABLED_ENV,
    RAG_KNOWLEDGE_DIR_ENV,
    RAG_MAX_SNIPPET_CHARS_ENV,
    RAG_MAX_TOTAL_CHARS_ENV,
    RAG_MIN_SCORE_ENV,
)

_VALID_BODY = (
    "Low stock is a per-warehouse condition. Free stock is declared as on-hand "
    "quantity minus reserved quantity and compared with the reorder level."
)


def make_document(**overrides: object) -> KnowledgeDocument:
    values: dict[str, object] = {
        "doc_id": "business-definitions-low-stock",
        "title": "Low Stock and Reorder Level",
        "category": "business_definitions",
        "fact_kind": "definition",
        "version": "1.0.0",
        "updated_at": date(2026, 11, 1),
        "summary": "How free stock is compared with the product reorder level.",
        "tags": ("low stock", "reorder level"),
        "aliases": ("reorder point",),
        "source_path": "business_definitions/low-stock.md",
        "content_hash": "a" * 64,
        "body": _VALID_BODY,
    }
    values.update(overrides)
    return KnowledgeDocument(**values)


def make_chunk(**overrides: object) -> KnowledgeChunk:
    values: dict[str, object] = {
        "chunk_id": "business-definitions-low-stock#definition#01",
        "doc_id": "business-definitions-low-stock",
        "title": "Low Stock and Reorder Level",
        "section_path": ("Low Stock and Reorder Level", "Definition"),
        "category": "business_definitions",
        "fact_kind": "definition",
        "text": "Low stock is a per-warehouse condition.",
        "token_count": 6,
        "source_path": "business_definitions/low-stock.md",
        "updated_at": date(2026, 11, 1),
    }
    values.update(overrides)
    return KnowledgeChunk(**values)


def make_hit(**overrides: object) -> RetrievalHit:
    values: dict[str, object] = {
        "chunk_id": "business-definitions-low-stock#definition#01",
        "doc_id": "business-definitions-low-stock",
        "title": "Low Stock and Reorder Level",
        "section": "Definition",
        "category": "business_definitions",
        "fact_kind": "definition",
        "score": 1.25,
        "snippet": "Low stock is a per-warehouse condition.",
        "source_path": "business_definitions/low-stock.md",
        "updated_at": date(2026, 11, 1),
    }
    values.update(overrides)
    return RetrievalHit(**values)


def make_search_result(**overrides: object) -> RetrievalResult:
    hit = make_hit()
    values: dict[str, object] = {
        "query": "what is low stock",
        "status": "ok",
        "hits": (hit,),
        "total_chars": len(hit.snippet),
        "index_version": "a1b2c3d4e5f6",
    }
    values.update(overrides)
    return RetrievalResult(**values)


class RagConfigTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp_dir.cleanup)
        self.knowledge_dir = Path(self._temp_dir.name)

    def config(self, **overrides: object) -> RagConfig:
        values: dict[str, object] = {"knowledge_dir": self.knowledge_dir}
        values.update(overrides)
        return RagConfig(**values)


class RagConfigValidationTests(RagConfigTestCase):
    def test_defaults(self) -> None:
        config = self.config()

        self.assertEqual(config.knowledge_dir, self.knowledge_dir.resolve())
        self.assertIs(config.enabled, False)
        self.assertEqual(config.default_top_k, DEFAULT_TOP_K)
        self.assertAlmostEqual(config.min_score, DEFAULT_MIN_SCORE)
        self.assertEqual(config.max_snippet_chars, DEFAULT_MAX_SNIPPET_CHARS)
        self.assertEqual(config.max_total_chars, DEFAULT_MAX_TOTAL_CHARS)
        self.assertEqual(config.max_document_chars, DEFAULT_MAX_DOCUMENT_CHARS)
        self.assertEqual(config.max_hits_per_doc, DEFAULT_MAX_HITS_PER_DOC)
        self.assertEqual(config.max_chunk_chars, DEFAULT_MAX_CHUNK_CHARS)
        self.assertEqual(config.min_chunk_chars, DEFAULT_MIN_CHUNK_CHARS)
        self.assertAlmostEqual(config.bm25_k1, 1.2)
        self.assertAlmostEqual(config.bm25_b, 0.75)

    def test_knowledge_dir_is_resolved(self) -> None:
        raw = str(self.knowledge_dir / "." )
        config = self.config(knowledge_dir=raw)
        self.assertEqual(config.knowledge_dir, self.knowledge_dir.resolve())

    def test_rejects_missing_directory(self) -> None:
        missing = self.knowledge_dir / "missing"
        with self.assertRaises(RagConfigurationError):
            self.config(knowledge_dir=missing)

    def test_rejects_file_path(self) -> None:
        file_path = self.knowledge_dir / "notes.md"
        file_path.write_text("x", encoding="utf-8")
        with self.assertRaises(RagConfigurationError):
            self.config(knowledge_dir=file_path)

    def test_rejects_blank_directory(self) -> None:
        with self.assertRaises(RagConfigurationError):
            self.config(knowledge_dir="   ")

    def test_rejects_non_path_directory(self) -> None:
        with self.assertRaises(RagConfigurationError):
            self.config(knowledge_dir=123)

    def test_enabled_must_be_boolean(self) -> None:
        with self.assertRaises(RagConfigurationError):
            self.config(enabled="yes")

    def test_default_top_k_bounds(self) -> None:
        self.assertEqual(self.config(default_top_k=MAX_TOP_K).default_top_k, 5)
        for value in (0, 6, -1):
            with self.subTest(value=value):
                with self.assertRaises(RagConfigurationError):
                    self.config(default_top_k=value)

    def test_default_top_k_rejects_bool(self) -> None:
        with self.assertRaises(RagConfigurationError):
            self.config(default_top_k=True)

    def test_min_score_validation(self) -> None:
        self.assertAlmostEqual(self.config(min_score=0).min_score, 0.0)
        for value in (-0.1, float("nan"), float("inf")):
            with self.subTest(value=value):
                with self.assertRaises(RagConfigurationError):
                    self.config(min_score=value)
        with self.assertRaises(RagConfigurationError):
            self.config(min_score="0.1")

    def test_snippet_char_bounds(self) -> None:
        self.assertEqual(self.config(max_snippet_chars=100).max_snippet_chars, 100)
        for value in (99, 2001, 0):
            with self.subTest(value=value):
                with self.assertRaises(RagConfigurationError):
                    self.config(max_snippet_chars=value)

    def test_total_char_bounds_and_relation(self) -> None:
        self.assertEqual(
            self.config(
                max_snippet_chars=500,
                max_total_chars=500,
            ).max_total_chars,
            500,
        )
        for value in (499, 6001):
            with self.subTest(value=value):
                with self.assertRaises(RagConfigurationError):
                    self.config(max_total_chars=value)
        with self.assertRaises(RagConfigurationError):
            self.config(max_snippet_chars=700, max_total_chars=600)

    def test_document_char_bounds(self) -> None:
        for value in (99, 100_001):
            with self.subTest(value=value):
                with self.assertRaises(RagConfigurationError):
                    self.config(max_document_chars=value)

    def test_hits_per_doc_bounds(self) -> None:
        self.assertEqual(self.config(max_hits_per_doc=1).max_hits_per_doc, 1)
        for value in (0, 11):
            with self.subTest(value=value):
                with self.assertRaises(RagConfigurationError):
                    self.config(max_hits_per_doc=value)

    def test_chunk_char_bounds(self) -> None:
        for value in (199, 5001):
            with self.subTest(value=value):
                with self.assertRaises(RagConfigurationError):
                    self.config(max_chunk_chars=value)
        with self.assertRaises(RagConfigurationError):
            self.config(max_chunk_chars=1000, min_chunk_chars=1001)

    def test_bm25_parameters(self) -> None:
        for value in (0, -1, 5.5, float("nan")):
            with self.subTest(value=value):
                with self.assertRaises(RagConfigurationError):
                    self.config(bm25_k1=value)
        for value in (-0.01, 1.01, float("inf")):
            with self.subTest(value=value):
                with self.assertRaises(RagConfigurationError):
                    self.config(bm25_b=value)

    def test_config_is_frozen(self) -> None:
        config = self.config()
        with self.assertRaises((FrozenInstanceError, ValidationError)):
            config.min_score = 0.5  # type: ignore[misc]

    def test_default_knowledge_dir_points_at_package(self) -> None:
        self.assertEqual(DEFAULT_KNOWLEDGE_DIR.name, "knowledge")
        self.assertEqual(DEFAULT_KNOWLEDGE_DIR.parent.name, "rag")


class RagConfigEnvTests(RagConfigTestCase):
    def from_env(self, **env: str) -> RagConfig:
        values = {RAG_KNOWLEDGE_DIR_ENV: str(self.knowledge_dir)}
        values.update(env)
        with patch.dict(os.environ, values, clear=True):
            return RagConfig.from_env()

    def test_from_env_defaults(self) -> None:
        config = self.from_env()
        self.assertIs(config.enabled, False)
        self.assertEqual(config.default_top_k, DEFAULT_TOP_K)
        self.assertAlmostEqual(config.min_score, DEFAULT_MIN_SCORE)
        self.assertEqual(config.max_snippet_chars, DEFAULT_MAX_SNIPPET_CHARS)
        self.assertEqual(config.max_total_chars, DEFAULT_MAX_TOTAL_CHARS)

    def test_from_env_overrides(self) -> None:
        config = self.from_env(
            **{
                RAG_ENABLED_ENV: "true",
                RAG_DEFAULT_TOP_K_ENV: "5",
                RAG_MIN_SCORE_ENV: "0.4",
                RAG_MAX_SNIPPET_CHARS_ENV: "900",
                RAG_MAX_TOTAL_CHARS_ENV: "1200",
            }
        )
        self.assertIs(config.enabled, True)
        self.assertEqual(config.default_top_k, 5)
        self.assertAlmostEqual(config.min_score, 0.4)
        self.assertEqual(config.max_snippet_chars, 900)
        self.assertEqual(config.max_total_chars, 1200)

    def test_enabled_accepts_documented_forms(self) -> None:
        for raw, expected in (
            ("true", True),
            ("TRUE", True),
            ("1", True),
            ("false", False),
            ("FALSE", False),
            ("0", False),
        ):
            with self.subTest(raw=raw):
                config = self.from_env(**{RAG_ENABLED_ENV: raw})
                self.assertIs(config.enabled, expected)

    def test_enabled_rejects_invalid_value(self) -> None:
        for raw in ("yes", "on", "2", "truthy"):
            with self.subTest(raw=raw):
                with self.assertRaises(RagConfigurationError):
                    self.from_env(**{RAG_ENABLED_ENV: raw})

    def test_blank_values_fall_back_to_defaults(self) -> None:
        config = self.from_env(
            **{
                RAG_ENABLED_ENV: "   ",
                RAG_DEFAULT_TOP_K_ENV: "",
                RAG_MIN_SCORE_ENV: " ",
            }
        )
        self.assertIs(config.enabled, False)
        self.assertEqual(config.default_top_k, DEFAULT_TOP_K)
        self.assertAlmostEqual(config.min_score, DEFAULT_MIN_SCORE)

    def test_invalid_int_env_values(self) -> None:
        for name in (RAG_DEFAULT_TOP_K_ENV, RAG_MAX_SNIPPET_CHARS_ENV, RAG_MAX_TOTAL_CHARS_ENV):
            for raw in ("abc", "1.5"):
                with self.subTest(name=name, raw=raw):
                    with self.assertRaises(RagConfigurationError):
                        self.from_env(**{name: raw})

    def test_out_of_range_int_env_values(self) -> None:
        with self.assertRaises(RagConfigurationError):
            self.from_env(**{RAG_DEFAULT_TOP_K_ENV: "6"})
        with self.assertRaises(RagConfigurationError):
            self.from_env(**{RAG_MAX_SNIPPET_CHARS_ENV: "99"})
        with self.assertRaises(RagConfigurationError):
            self.from_env(**{RAG_MAX_TOTAL_CHARS_ENV: "400"})

    def test_invalid_float_env_values(self) -> None:
        for raw in ("nan", "inf", "-0.5", "abc"):
            with self.subTest(raw=raw):
                with self.assertRaises(RagConfigurationError):
                    self.from_env(**{RAG_MIN_SCORE_ENV: raw})

    def test_relation_checked_after_env_parsing(self) -> None:
        with self.assertRaises(RagConfigurationError):
            self.from_env(
                **{
                    RAG_MAX_SNIPPET_CHARS_ENV: "1500",
                    RAG_MAX_TOTAL_CHARS_ENV: "1200",
                }
            )

    def test_missing_knowledge_dir_env_uses_package_default(self) -> None:
        # Stage 3 ships the reviewed knowledge directory, so the documented
        # default is now a valid corpus location.
        with patch.dict(os.environ, {}, clear=True):
            config = RagConfig.from_env()
        self.assertEqual(config.knowledge_dir, DEFAULT_KNOWLEDGE_DIR.resolve())


class RagConstantsTests(unittest.TestCase):
    def test_documented_limits(self) -> None:
        self.assertEqual(MAX_TOP_K, 5)
        self.assertAlmostEqual(RELATIVE_SCORE_FLOOR, 0.25)
        self.assertEqual(MAX_QUERY_CHARS, 300)
        self.assertEqual(MAX_DOCS, 200)
        self.assertEqual(MAX_CHUNKS, 5000)
        self.assertEqual(MAX_CORPUS_BYTES, 2_000_000)


class RagErrorTests(unittest.TestCase):
    def test_envelope_shape_matches_erp_contract(self) -> None:
        error = RagInvalidArgumentsError("query")
        envelope = error.to_envelope()

        self.assertEqual(set(envelope), {"ok", "error"})
        self.assertIs(envelope["ok"], False)
        payload = envelope["error"]
        self.assertIsInstance(payload, dict)
        self.assertEqual(
            set(payload),
            {
                "code",
                "message",
                "category",
                "recoverable",
                "retryable",
                "details",
            },
        )
        self.assertEqual(payload["code"], "rag_invalid_arguments")
        self.assertEqual(payload["category"], "validation")
        self.assertIs(payload["recoverable"], True)
        self.assertIs(payload["retryable"], False)
        self.assertEqual(payload["details"], {"field": "query"})

    def test_invalid_arguments_custom_message(self) -> None:
        error = RagInvalidArgumentsError("top_k", message="top_k is too large")
        self.assertEqual(error.message, "top_k is too large")
        self.assertIsInstance(error, RagError)

    def test_not_found_defaults(self) -> None:
        error = RagNotFoundError("document")
        self.assertEqual(error.code, "rag_not_found")
        self.assertEqual(error.message, "Document not found")
        self.assertIs(error.category, ErrorCategory.NOT_FOUND)
        self.assertEqual(error.details, {"resource": "document"})

    def test_corpus_error_details_are_optional(self) -> None:
        error = RagCorpusError(path="schema/x.md", line=12, rule="live_fact:L2")
        self.assertEqual(
            error.details,
            {"path": "schema/x.md", "line": 12, "rule": "live_fact:L2"},
        )
        self.assertEqual(RagCorpusError().details, {})

    def test_configuration_error(self) -> None:
        error = RagConfigurationError("bad value")
        self.assertEqual(error.code, "rag_configuration_error")
        self.assertIs(error.category, ErrorCategory.INTERNAL)
        self.assertIs(error.recoverable, False)

    def test_index_and_internal_errors(self) -> None:
        index_error = RagIndexError()
        self.assertEqual(index_error.code, "rag_index_error")
        self.assertIs(index_error.retryable, True)
        self.assertIs(index_error.category, ErrorCategory.INTERNAL)

        internal = RagInternalError()
        self.assertEqual(internal.code, "rag_internal_error")
        self.assertIs(internal.category, ErrorCategory.INTERNAL)
        self.assertIs(internal.retryable, False)

    def test_all_errors_are_rag_errors(self) -> None:
        for factory in (
            lambda: RagConfigurationError(),
            lambda: RagCorpusError(),
            lambda: RagIndexError(),
            lambda: RagInvalidArgumentsError("q"),
            lambda: RagNotFoundError("document"),
            lambda: RagInternalError(),
        ):
            with self.subTest(factory=factory):
                self.assertIsInstance(factory(), RagError)


class KnowledgeDocumentModelTests(unittest.TestCase):
    def test_valid_document(self) -> None:
        document = make_document()
        dumped = document.model_dump(mode="json")
        self.assertEqual(dumped["doc_id"], "business-definitions-low-stock")
        self.assertEqual(dumped["updated_at"], "2026-11-01")
        self.assertEqual(dumped["category"], "business_definitions")
        self.assertEqual(dumped["fact_kind"], "definition")

    def test_tags_and_aliases_are_normalized(self) -> None:
        document = make_document(
            tags=("Low Stock", "  Reorder Level "),
            aliases=("Reorder Point",),
        )
        self.assertEqual(document.tags, ("low stock", "reorder level"))
        self.assertEqual(document.aliases, ("reorder point",))

    def test_extra_fields_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            make_document(unexpected="value")

    def test_document_is_frozen(self) -> None:
        document = make_document()
        with self.assertRaises((FrozenInstanceError, ValidationError)):
            document.title = "Changed"  # type: ignore[misc]

    def test_invalid_doc_id_patterns(self) -> None:
        for value in ("Low-Stock", "ab", "1starts-with-digit", "has space", "x" * 65):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    make_document(doc_id=value)

    def test_multiline_title_and_summary_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            make_document(title="Low Stock\nReorder Level")
        with self.assertRaises(ValidationError):
            make_document(summary="Line one.\nLine two.")

    def test_blank_and_duplicate_tags_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            make_document(tags=("",))
        with self.assertRaises(ValidationError):
            make_document(tags=("low stock", "LOW STOCK"))
        with self.assertRaises(ValidationError):
            make_document(tags=tuple(f"tag {index}" for index in range(13)))
        with self.assertRaises(ValidationError):
            make_document(tags=("x" * 41,))

    def test_source_path_rules(self) -> None:
        for value in (
            "/absolute/path.md",
            "C:/absolute/path.md",
            "business_definitions\\low-stock.md",
            "business_definitions/../low-stock.md",
            "business_definitions/low-stock.txt",
            "business_definitions//low-stock.md",
        ):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    make_document(source_path=value)

    def test_content_hash_and_body_rules(self) -> None:
        for value in ("A" * 64, "a" * 63, "g" * 64):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    make_document(content_hash=value)
        with self.assertRaises(ValidationError):
            make_document(body="too short")
        with self.assertRaises(ValidationError):
            make_document(body="x" * 20_001)

    def test_invalid_enums_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            make_document(category="unknown")
        with self.assertRaises(ValidationError):
            make_document(fact_kind="unknown")
        with self.assertRaises(ValidationError):
            make_document(version="1.0")


class KnowledgeChunkModelTests(unittest.TestCase):
    def test_valid_chunk(self) -> None:
        chunk = make_chunk()
        self.assertEqual(chunk.section_path[1], "Definition")
        self.assertEqual(chunk.token_count, 6)

    def test_chunk_id_must_match_document(self) -> None:
        with self.assertRaises(ValidationError):
            make_chunk(chunk_id="other-document#definition#01")

    def test_invalid_chunk_id_patterns(self) -> None:
        for value in (
            "business-definitions-low-stock#definition",
            "business-definitions-low-stock#definition#1",
            "business-definitions-low-stock#Definition#01",
        ):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    make_chunk(chunk_id=value)

    def test_section_path_rules(self) -> None:
        with self.assertRaises(ValidationError):
            make_chunk(section_path=("Definition", "   "))
        with self.assertRaises(ValidationError):
            make_chunk(section_path=tuple(f"H{index}" for index in range(9)))
        with self.assertRaises(ValidationError):
            make_chunk(section_path=("x" * 121,))

    def test_chunk_text_bounds(self) -> None:
        with self.assertRaises(ValidationError):
            make_chunk(text="")
        with self.assertRaises(ValidationError):
            make_chunk(text="x" * 5001)

    def test_negative_token_count_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            make_chunk(token_count=-1)


class RetrievalModelTests(unittest.TestCase):
    def test_valid_query(self) -> None:
        query = RetrievalQuery(query="what is low stock", category="schema", top_k=5)
        self.assertEqual(query.top_k, 5)
        self.assertEqual(query.category, "schema")

    def test_query_rules(self) -> None:
        with self.assertRaises(ValidationError):
            RetrievalQuery(query="   ")
        with self.assertRaises(ValidationError):
            RetrievalQuery(query="x" * 301)
        with self.assertRaises(ValidationError):
            RetrievalQuery(query="line one\nline two")
        with self.assertRaises(ValidationError):
            RetrievalQuery(query="valid", category="unknown")
        for top_k in (0, 6):
            with self.subTest(top_k=top_k):
                with self.assertRaises(ValidationError):
                    RetrievalQuery(query="valid", top_k=top_k)

    def test_valid_hit_and_result(self) -> None:
        result = make_search_result()
        self.assertEqual(result.status, "ok")
        self.assertIs(result.live_data, False)
        self.assertEqual(result.disclaimer, DISCLAIMER)
        self.assertEqual(result.total_chars, len(result.hits[0].snippet))

    def test_hit_score_must_be_non_negative(self) -> None:
        with self.assertRaises(ValidationError):
            make_hit(score=-0.1)

    def test_blocked_result_requires_guidance_and_no_hits(self) -> None:
        blocked = RetrievalResult(
            query="how many products",
            status="blocked",
            blocked_reason="count",
            guidance="Use erp.products.count.",
            hits=(),
            total_chars=0,
            index_version="a1b2c3d4e5f6",
        )
        self.assertEqual(blocked.blocked_reason, "count")

        with self.assertRaises(ValidationError):
            RetrievalResult(
                query="how many products",
                status="blocked",
                blocked_reason=None,
                guidance="Use erp.products.count.",
                hits=(),
                total_chars=0,
                index_version="a1b2c3d4e5f6",
            )
        with self.assertRaises(ValidationError):
            RetrievalResult(
                query="how many products",
                status="blocked",
                blocked_reason="count",
                guidance="Use erp.products.count.",
                hits=(make_hit(),),
                total_chars=len(make_hit().snippet),
                index_version="a1b2c3d4e5f6",
            )

    def test_no_match_result_rules(self) -> None:
        result = RetrievalResult(
            query="unknown topic",
            status="no_match",
            hits=(),
            total_chars=0,
            index_version="a1b2c3d4e5f6",
        )
        self.assertEqual(result.hits, ())
        with self.assertRaises(ValidationError):
            RetrievalResult(
                query="unknown topic",
                status="no_match",
                hits=(make_hit(),),
                total_chars=len(make_hit().snippet),
                index_version="a1b2c3d4e5f6",
            )

    def test_ok_result_requires_hits(self) -> None:
        with self.assertRaises(ValidationError):
            RetrievalResult(
                query="what is low stock",
                status="ok",
                hits=(),
                total_chars=0,
                index_version="a1b2c3d4e5f6",
            )

    def test_total_chars_must_match_hits(self) -> None:
        with self.assertRaises(ValidationError):
            make_search_result(total_chars=1)

    def test_live_data_must_be_false(self) -> None:
        with self.assertRaises(ValidationError):
            make_search_result(live_data=True)

    def test_document_view(self) -> None:
        view = DocumentView(
            doc_id="business-definitions-low-stock",
            title="Low Stock and Reorder Level",
            category="business_definitions",
            fact_kind="definition",
            version="1.0.0",
            updated_at=date(2026, 11, 1),
            source_path="business_definitions/low-stock.md",
            body="Low stock is a per-warehouse condition.",
        )
        self.assertIs(view.truncated, False)
        self.assertIs(view.live_data, False)
        with self.assertRaises(ValidationError):
            DocumentView(
                doc_id="business-definitions-low-stock",
                title="Low Stock and Reorder Level",
                category="business_definitions",
                fact_kind="definition",
                version="1.0.0",
                updated_at=date(2026, 11, 1),
                source_path="/absolute/low-stock.md",
                body="body",
            )

    def test_topic_list_count_must_match_items(self) -> None:
        topic = TopicInfo(
            doc_id="business-definitions-low-stock",
            title="Low Stock and Reorder Level",
            category="business_definitions",
            fact_kind="definition",
            summary="How free stock is compared with the reorder level.",
            version="1.0.0",
            updated_at=date(2026, 11, 1),
        )
        result = TopicListResult(items=(topic,), count=1)
        self.assertEqual(result.count, 1)
        with self.assertRaises(ValidationError):
            TopicListResult(items=(topic,), count=2)


class CorpusBundleModelTests(unittest.TestCase):
    def test_valid_bundle(self) -> None:
        bundle = CorpusBundle(
            documents=(make_document(),),
            chunks=(make_chunk(),),
            index_version="a1b2c3d4e5f6",
        )
        self.assertEqual(len(bundle.documents), 1)
        self.assertEqual(len(bundle.chunks), 1)

    def test_duplicate_document_ids_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            CorpusBundle(
                documents=(make_document(), make_document()),
                chunks=(make_chunk(),),
                index_version="a1b2c3d4e5f6",
            )

    def test_duplicate_chunk_ids_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            CorpusBundle(
                documents=(make_document(),),
                chunks=(make_chunk(), make_chunk()),
                index_version="a1b2c3d4e5f6",
            )

    def test_unknown_chunk_document_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            CorpusBundle(
                documents=(),
                chunks=(make_chunk(),),
                index_version="a1b2c3d4e5f6",
            )

    def test_document_without_chunks_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            CorpusBundle(
                documents=(make_document(),),
                chunks=(),
                index_version="a1b2c3d4e5f6",
            )


if __name__ == "__main__":
    unittest.main()
