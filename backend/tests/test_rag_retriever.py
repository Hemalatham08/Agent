from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from backend.agent.rag import (
    DISCLAIMER,
    Bm25Index,
    CorpusBundle,
    DocumentationRetriever,
    KnowledgeChunk,
    KnowledgeDocument,
    RagConfigurationError,
    RagInvalidArgumentsError,
    RetrievalQuery,
    bounded_snippet,
    load_corpus_from_dir,
    slugify,
    tokenize,
)
from backend.agent.rag.chunking import chunk_document
from backend.agent.rag.retriever import match_centered_snippet


def make_document(
    doc_id: str,
    *,
    category: str = "erp_docs",
    fact_kind: str = "overview",
    title: str = "Doc",
) -> KnowledgeDocument:
    return KnowledgeDocument(
        doc_id=doc_id,
        title=title,
        category=category,
        fact_kind=fact_kind,
        version="1.0.0",
        updated_at=date(2026, 11, 1),
        summary="A test document for the retrieval pipeline.",
        tags=(),
        aliases=(),
        source_path=f"{category}/{doc_id}.md",
        content_hash="a" * 64,
        body="A test document body that is long enough to satisfy the model.",
    )


def make_chunk(
    doc_id: str,
    text: str,
    *,
    title: str = "Doc",
    section: tuple[str, ...] = ("Section",),
    category: str = "erp_docs",
    fact_kind: str = "overview",
    ordinal: int = 1,
) -> KnowledgeChunk:
    section_slug = slugify(section[-1], max_len=40)
    return KnowledgeChunk(
        chunk_id=f"{doc_id}#{section_slug}#{ordinal:02d}",
        doc_id=doc_id,
        title=title,
        section_path=section,
        category=category,
        fact_kind=fact_kind,
        text=text,
        token_count=len(tokenize(text)),
        source_path=f"{category}/{doc_id}.md",
        updated_at=date(2026, 11, 1),
    )


def make_bundle(
    chunks: list[KnowledgeChunk] | tuple[KnowledgeChunk, ...],
    *,
    index_version: str = "test-v1",
) -> CorpusBundle:
    documents: dict[str, KnowledgeDocument] = {}
    for chunk in chunks:
        documents.setdefault(
            chunk.doc_id,
            make_document(
                chunk.doc_id,
                category=chunk.category,
                fact_kind=chunk.fact_kind,
                title=chunk.title,
            ),
        )
    return CorpusBundle(
        documents=tuple(documents[key] for key in sorted(documents)),
        chunks=tuple(chunks),
        index_version=index_version,
    )


def make_index(
    chunks: list[KnowledgeChunk] | tuple[KnowledgeChunk, ...],
    *,
    index_version: str = "test-v1",
) -> Bm25Index:
    return Bm25Index(make_bundle(chunks, index_version=index_version))


def corpus_chunks() -> list[KnowledgeChunk]:
    return [
        make_chunk(
            "free-stock",
            "Free stock is on-hand stock minus reserved stock. It is the "
            "quantity that can still be promised to new demand.",
            title="Free Stock",
            section=("Free stock",),
            category="business_definitions",
            fact_kind="definition",
        ),
        make_chunk(
            "purchase-workflow",
            "The purchase to stock workflow begins with a purchase order and "
            "ends with a receipt into the warehouse.",
            title="Purchase to Stock Workflow",
            section=("Workflow",),
            category="workflows",
            fact_kind="workflow",
        ),
        make_chunk(
            "documentation-policy",
            "Documentation explains concepts and policies. Live stock "
            "quantities, totals, and statuses must be read with the ERP tools.",
            title="Documentation Policy",
            section=("Rule",),
            category="policies_faqs",
            fact_kind="policy",
        ),
        make_chunk(
            "products-schema",
            "The products table stores product identifiers, names, and units. "
            "The schema defines columns and keys for the catalogue.",
            title="Products Table Schema",
            section=("Schema",),
            category="schema",
            fact_kind="schema",
        ),
    ]


def stock_category_chunks() -> list[KnowledgeChunk]:
    return [
        make_chunk(
            "definition-doc",
            "Stock means the goods held in a warehouse. The definition is "
            "conceptual and does not report a current value.",
            title="Stock Definition",
            section=("Definition",),
            category="business_definitions",
            fact_kind="definition",
        ),
        make_chunk(
            "workflow-doc",
            "Stock adjustment is a workflow of counted corrections. The "
            "process describes steps, not a current quantity.",
            title="Stock Adjustment Workflow",
            section=("Workflow",),
            category="workflows",
            fact_kind="workflow",
        ),
        make_chunk(
            "schema-doc",
            "Stock appears in the inventory table schema. The data model "
            "defines the columns and keys used to store it.",
            title="Inventory Schema",
            section=("Schema",),
            category="schema",
            fact_kind="schema",
        ),
    ]


def varying_score_chunks() -> list[KnowledgeChunk]:
    filler = "filler " * 60
    return [
        make_chunk(
            "score-a",
            "alpha alpha alpha " + filler,
            title="Alpha A",
        ),
        make_chunk(
            "score-b",
            "alpha " + filler + filler,
            title="Alpha B",
        ),
        make_chunk(
            "score-c",
            "alpha " + filler * 3,
            title="Alpha C",
        ),
    ]


def long_snippet_chunks() -> list[KnowledgeChunk]:
    chunks: list[KnowledgeChunk] = []
    for number in range(1, 6):
        text = ("alpha " * 3) + ("filler " * 180)
        chunks.append(
            make_chunk(
                f"long-{number}",
                text,
                title=f"Long Document {number}",
                ordinal=1,
            )
        )
    return chunks


def per_document_chunks() -> list[KnowledgeChunk]:
    chunks = [
        make_chunk(
            "doc-a",
            "alpha alpha alpha " + ("filler " * 20),
            title="Document A",
            section=("Alpha",),
            ordinal=number,
        )
        for number in range(1, 5)
    ]
    chunks.append(
        make_chunk(
            "doc-b",
            "alpha alpha alpha " + ("filler " * 20),
            title="Document B",
            section=("Alpha",),
            ordinal=1,
        )
    )
    return chunks


class AllowedRetrievalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.bundle = make_bundle(corpus_chunks(), index_version="corpus-1")
        self.index = Bm25Index(self.bundle)
        self.retriever = DocumentationRetriever(self.index)

    def test_definition_question_returns_the_definition(self) -> None:
        result = self.retriever.retrieve("What does free stock mean?")

        self.assertEqual(result.status, "ok")
        self.assertGreaterEqual(len(result.hits), 1)
        self.assertEqual(result.hits[0].doc_id, "free-stock")
        self.assertEqual(result.hits[0].category, "business_definitions")
        self.assertGreater(result.hits[0].score, 0.0)

    def test_workflow_question_returns_the_workflow(self) -> None:
        result = self.retriever.retrieve(
            "How does the purchase to stock workflow work?"
        )

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.hits[0].doc_id, "purchase-workflow")
        self.assertEqual(result.hits[0].category, "workflows")

    def test_schema_question_returns_the_schema(self) -> None:
        result = self.retriever.retrieve(
            "What is the products table schema?"
        )

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.hits[0].doc_id, "products-schema")
        self.assertEqual(result.hits[0].category, "schema")

    def test_policy_question_returns_the_policy(self) -> None:
        result = self.retriever.retrieve(
            "What is the documentation policy for live data?"
        )

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.hits[0].doc_id, "documentation-policy")
        self.assertEqual(result.hits[0].category, "policies_faqs")

    def test_hit_metadata_is_complete(self) -> None:
        result = self.retriever.retrieve("What does free stock mean?")
        hit = result.hits[0]

        self.assertTrue(hit.chunk_id.startswith("free-stock#"))
        self.assertEqual(hit.doc_id, "free-stock")
        self.assertEqual(hit.title, "Free Stock")
        self.assertEqual(hit.section, "Free stock")
        self.assertEqual(hit.category, "business_definitions")
        self.assertEqual(hit.fact_kind, "definition")
        self.assertEqual(
            hit.source_path,
            "business_definitions/free-stock.md",
        )
        self.assertEqual(hit.updated_at, date(2026, 11, 1))
        self.assertGreater(hit.score, 0.0)
        self.assertTrue(hit.snippet)

    def test_total_chars_is_the_sum_of_snippet_lengths(self) -> None:
        result = self.retriever.retrieve("What does free stock mean?")

        self.assertEqual(
            result.total_chars,
            sum(len(hit.snippet) for hit in result.hits),
        )

    def test_default_top_k_is_three(self) -> None:
        result = self.retriever.retrieve("What does stock mean?")
        self.assertLessEqual(len(result.hits), 3)

    def test_retrieval_query_model_is_supported(self) -> None:
        request = RetrievalQuery(
            query="What does free stock mean?",
            category="business_definitions",
            top_k=2,
        )
        result = self.retriever.retrieve(request)

        self.assertEqual(result.query, request.query)
        self.assertLessEqual(len(result.hits), 2)
        for hit in result.hits:
            self.assertEqual(hit.category, "business_definitions")

    def test_category_override_is_applied(self) -> None:
        result = self.retriever.retrieve(
            "What is the products table schema?",
            category="schema",
        )

        self.assertEqual(result.status, "ok")
        for hit in result.hits:
            self.assertEqual(hit.category, "schema")

    def test_category_filter_with_no_matching_chunks_is_no_match(self) -> None:
        result = self.retriever.retrieve(
            "What does free stock mean?",
            category="schema",
        )

        self.assertEqual(result.status, "no_match")
        self.assertEqual(result.hits, ())

    def test_index_version_is_preserved(self) -> None:
        result = self.retriever.retrieve("What does free stock mean?")
        self.assertEqual(result.index_version, "corpus-1")

    def test_flags_and_disclaimer_are_present(self) -> None:
        result = self.retriever.retrieve("What does free stock mean?")

        self.assertIs(result.live_data, False)
        self.assertEqual(result.disclaimer, DISCLAIMER)
        self.assertIsNone(result.blocked_reason)


class GuardFirstTests(unittest.TestCase):
    def setUp(self) -> None:
        self.index = make_index(corpus_chunks())
        self.retriever = DocumentationRetriever(self.index)

    def test_blocked_query_returns_no_hits(self) -> None:
        result = self.retriever.retrieve(
            "What is the current stock level of product X?"
        )

        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.blocked_reason, "quantity")
        self.assertEqual(result.hits, ())
        self.assertEqual(result.total_chars, 0)
        self.assertIsNotNone(result.guidance)
        self.assertIs(result.live_data, False)
        self.assertEqual(result.disclaimer, DISCLAIMER)

    def test_ambiguous_query_returns_no_hits(self) -> None:
        result = self.retriever.retrieve(
            "Explain the sales order workflow and show me all open orders."
        )

        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.blocked_reason, "listing")
        self.assertEqual(result.hits, ())
        self.assertIsNotNone(result.guidance)

    def test_guard_runs_before_bm25(self) -> None:
        with patch.object(
            self.index,
            "search",
            side_effect=AssertionError("BM25 must not run"),
        ):
            result = self.retriever.retrieve(
                "How many products do we have?"
            )

        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.blocked_reason, "count")

    def test_ambiguous_guard_also_runs_before_bm25(self) -> None:
        with patch.object(
            self.index,
            "search",
            side_effect=AssertionError("BM25 must not run"),
        ):
            result = self.retriever.retrieve("stock")

        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.hits, ())

    def test_blocked_result_keeps_index_version(self) -> None:
        result = self.retriever.retrieve("What is the price of product X?")
        self.assertEqual(result.index_version, "test-v1")

    def test_blocked_reason_is_a_live_fact_kind(self) -> None:
        result = self.retriever.retrieve(
            "What is the status of order SO-1001?"
        )
        self.assertIn(
            result.blocked_reason,
            {
                "quantity",
                "count",
                "money",
                "status",
                "record_lookup",
                "listing",
            },
        )


class ThresholdTests(unittest.TestCase):
    def test_min_score_above_every_score_returns_no_match(self) -> None:
        retriever = DocumentationRetriever(
            make_index(corpus_chunks()),
            min_score=100.0,
        )
        result = retriever.retrieve("What does free stock mean?")

        self.assertEqual(result.status, "no_match")
        self.assertEqual(result.hits, ())
        self.assertEqual(result.total_chars, 0)
        self.assertIsNotNone(result.guidance)

    def test_relative_floor_of_one_keeps_only_the_best_score(self) -> None:
        index = make_index(varying_score_chunks())
        retriever = DocumentationRetriever(
            index,
            relative_score_floor=1.0,
        )
        result = retriever.retrieve("alpha")

        self.assertEqual(result.status, "ok")
        best = result.hits[0].score
        for hit in result.hits:
            self.assertAlmostEqual(hit.score, best, places=12)

    def test_relative_floor_of_zero_keeps_lower_scores(self) -> None:
        index = make_index(varying_score_chunks())
        restrictive = DocumentationRetriever(
            index,
            relative_score_floor=1.0,
        ).retrieve("alpha")
        permissive = DocumentationRetriever(
            index,
            relative_score_floor=0.0,
        ).retrieve("alpha")

        self.assertGreaterEqual(
            len(permissive.hits),
            len(restrictive.hits),
        )

    def test_relative_threshold_matches_the_documented_formula(self) -> None:
        index = make_index(varying_score_chunks())
        retriever = DocumentationRetriever(index)
        result = retriever.retrieve("alpha")

        best = index.search("alpha")[0].score
        threshold = max(0.10, 0.25 * best)
        for hit in result.hits:
            self.assertGreaterEqual(hit.score, threshold)

    def test_min_score_dominates_a_low_relative_floor(self) -> None:
        index = make_index(varying_score_chunks())
        retriever = DocumentationRetriever(
            index,
            min_score=0.5,
            relative_score_floor=0.0,
        )
        result = retriever.retrieve("alpha")

        for hit in result.hits:
            self.assertGreaterEqual(hit.score, 0.5)

    def test_top_k_limits_the_number_of_hits(self) -> None:
        retriever = DocumentationRetriever(make_index(long_snippet_chunks()))
        for top_k in (1, 2, 5):
            with self.subTest(top_k=top_k):
                result = retriever.retrieve("alpha", top_k=top_k)
                self.assertLessEqual(len(result.hits), top_k)

    def test_invalid_top_k_is_a_typed_error(self) -> None:
        retriever = DocumentationRetriever(make_index(corpus_chunks()))
        for top_k in (0, 6, -1, True, "3", 1.5):
            with self.subTest(top_k=repr(top_k)):
                with self.assertRaises(RagInvalidArgumentsError) as caught:
                    retriever.retrieve(
                        "What does free stock mean?",
                        top_k=top_k,  # type: ignore[arg-type]
                    )
                self.assertEqual(
                    caught.exception.details.get("field"),
                    "top_k",
                )

    def test_invalid_category_is_a_typed_error(self) -> None:
        retriever = DocumentationRetriever(make_index(corpus_chunks()))
        for category in ("", "unknown", 3):
            with self.subTest(category=repr(category)):
                with self.assertRaises(RagInvalidArgumentsError) as caught:
                    retriever.retrieve(
                        "What does free stock mean?",
                        category=category,  # type: ignore[arg-type]
                    )
                self.assertEqual(
                    caught.exception.details.get("field"),
                    "category",
                )


class PerDocumentAndDedupTests(unittest.TestCase):
    def test_at_most_two_chunks_per_document_by_default(self) -> None:
        retriever = DocumentationRetriever(make_index(per_document_chunks()))
        result = retriever.retrieve("alpha", top_k=5)

        counts: dict[str, int] = {}
        for hit in result.hits:
            counts[hit.doc_id] = counts.get(hit.doc_id, 0) + 1
        self.assertTrue(counts)
        for count in counts.values():
            self.assertLessEqual(count, 2)

    def test_custom_per_document_cap_is_applied(self) -> None:
        retriever = DocumentationRetriever(
            make_index(per_document_chunks()),
            max_hits_per_doc=1,
        )
        result = retriever.retrieve("alpha", top_k=5)

        counts: dict[str, int] = {}
        for hit in result.hits:
            counts[hit.doc_id] = counts.get(hit.doc_id, 0) + 1
        for count in counts.values():
            self.assertLessEqual(count, 1)

    def test_duplicate_chunk_ids_are_deduplicated(self) -> None:
        index = make_index(per_document_chunks())
        retriever = DocumentationRetriever(index)
        original = index.search("alpha")
        duplicated = (original[0], original[0], *original[1:])

        with patch.object(index, "search", return_value=duplicated):
            result = retriever.retrieve("alpha", top_k=5)

        chunk_ids = [hit.chunk_id for hit in result.hits]
        self.assertEqual(len(chunk_ids), len(set(chunk_ids)))

    def test_hit_order_is_deterministic_and_non_increasing(self) -> None:
        retriever = DocumentationRetriever(make_index(per_document_chunks()))
        result = retriever.retrieve("alpha", top_k=5)

        scores = [hit.score for hit in result.hits]
        self.assertEqual(scores, sorted(scores, reverse=True))


class SnippetTests(unittest.TestCase):
    def test_short_text_is_unchanged(self) -> None:
        self.assertEqual(bounded_snippet("Short text.", 700), "Short text.")

    def test_long_text_is_bounded(self) -> None:
        snippet = bounded_snippet("x" * 2000, 700)
        self.assertLessEqual(len(snippet), 700)
        self.assertTrue(snippet.endswith("..."))

    def test_sentence_boundary_is_preferred(self) -> None:
        text = "First sentence. Second sentence. " + "tail " * 200
        snippet = bounded_snippet(text, 60)

        self.assertLessEqual(len(snippet), 60)
        self.assertTrue(snippet.startswith("First sentence."))

    def test_invalid_snippet_arguments_are_rejected(self) -> None:
        with self.assertRaises(TypeError):
            bounded_snippet(None, 700)  # type: ignore[arg-type]
        for limit in (0, -1, True, "700", 1.5):
            with self.subTest(limit=repr(limit)):
                with self.assertRaises(ValueError):
                    bounded_snippet("text", limit)  # type: ignore[arg-type]

    def test_each_snippet_is_at_most_700_characters(self) -> None:
        retriever = DocumentationRetriever(make_index(long_snippet_chunks()))
        result = retriever.retrieve("alpha", top_k=5)

        for hit in result.hits:
            self.assertLessEqual(len(hit.snippet), 700)

    def test_total_snippet_budget_is_at_most_3000_characters(self) -> None:
        retriever = DocumentationRetriever(make_index(long_snippet_chunks()))
        result = retriever.retrieve("alpha", top_k=5)

        self.assertLessEqual(result.total_chars, 3000)
        self.assertEqual(
            result.total_chars,
            sum(len(hit.snippet) for hit in result.hits),
        )

    def test_total_budget_uses_the_full_allowance(self) -> None:
        retriever = DocumentationRetriever(make_index(long_snippet_chunks()))
        result = retriever.retrieve("alpha", top_k=5)

        self.assertEqual(len(result.hits), 5)
        self.assertGreaterEqual(result.total_chars, 2900)
        self.assertLessEqual(result.total_chars, 3000)

    def test_snippet_budget_can_be_lowered(self) -> None:
        retriever = DocumentationRetriever(
            make_index(long_snippet_chunks()),
            max_snippet_chars=200,
            max_total_chars=500,
        )
        result = retriever.retrieve("alpha", top_k=5)

        self.assertLessEqual(result.total_chars, 500)
        for hit in result.hits:
            self.assertLessEqual(len(hit.snippet), 200)


class MatchCenteredSnippetTests(unittest.TestCase):
    """Tests for match_centered_snippet: sentence-span scoring,
    match-centered windowing, expansion, limits, and fallback."""

    def test_sentence_with_match_is_centered(self) -> None:
        text = (
            "Intro sentence that is irrelevant. "
            "The target sentence contains the query term alpha here. "
            "Another trailing sentence with no matches at all."
        )
        snippet = match_centered_snippet(text, ["alpha"], 200)
        self.assertIn("alpha", snippet)
        self.assertLessEqual(len(snippet), 200)

    def test_match_at_end_of_chunk_is_centered(self) -> None:
        text = (
            "Leading filler text with no matches. "
            "More filler. "
            "The final sentence has the alpha term at the end."
        )
        snippet = match_centered_snippet(text, ["alpha"], 200)
        self.assertIn("alpha", snippet)
        self.assertLessEqual(len(snippet), 200)

    def test_zero_match_falls_back_to_head(self) -> None:
        text = (
            "First sentence with no query terms. "
            "Second sentence also lacks them. "
            "Third sentence still no matches."
        )
        snippet = match_centered_snippet(text, ["zzznomatch"], 200)
        # Should fall back to bounded_snippet (head of chunk)
        self.assertTrue(snippet.startswith("First sentence"))

    def test_multiple_matching_sentences_are_included(self) -> None:
        text = (
            "Intro filler. "
            "Sentence one has alpha and beta. "
            "Connector sentence without terms. "
            "Sentence two has beta and gamma. "
            "Trailing filler."
        )
        snippet = match_centered_snippet(text, ["alpha", "beta", "gamma"], 500)
        self.assertIn("alpha", snippet)
        self.assertIn("beta", snippet)
        self.assertIn("gamma", snippet)

    def test_ties_resolve_to_earliest_sentence(self) -> None:
        text = (
            "First sentence with alpha term here. "
            "Middle filler sentence. "
            "Third sentence with alpha term here too."
        )
        snippet = match_centered_snippet(text, ["alpha"], 200)
        # Best score tie between sentence 0 and sentence 2; earliest wins
        self.assertTrue(snippet.startswith("First sentence"))

    def test_empty_text_returns_empty(self) -> None:
        self.assertEqual(match_centered_snippet("", ["alpha"], 100), "")

    def test_empty_query_tokens_falls_back_to_head(self) -> None:
        text = "First sentence. Second sentence with alpha. Third sentence."
        snippet = match_centered_snippet(text, [], 100)
        self.assertTrue(snippet.startswith("First sentence"))

    def test_limit_is_respected(self) -> None:
        text = (
            "Alpha sentence one. " + "filler " * 100 + " Alpha sentence two."
        )
        snippet = match_centered_snippet(text, ["alpha"], 50)
        self.assertLessEqual(len(snippet), 50)

    def test_short_text_is_returned_as_is(self) -> None:
        text = "Short text with alpha."
        snippet = match_centered_snippet(text, ["alpha"], 700)
        self.assertEqual(snippet, text)

    def test_invalid_limit_is_rejected(self) -> None:
        for limit in (0, -1, True, "100", 1.5):
            with self.subTest(limit=repr(limit)):
                with self.assertRaises(ValueError):
                    match_centered_snippet("text", ["alpha"], limit)  # type: ignore[arg-type]

    def test_invalid_text_is_rejected(self) -> None:
        with self.assertRaises(TypeError):
            match_centered_snippet(None, ["alpha"], 100)  # type: ignore[arg-type]

    def test_list_items_are_preserved(self) -> None:
        text = (
            "Intro paragraph. "
            "- Item one with alpha keyword. "
            "- Item two with beta keyword. "
            "- Item three with no keywords. "
            "Outro paragraph."
        )
        snippet = match_centered_snippet(text, ["alpha", "beta"], 300)
        self.assertIn("alpha", snippet)
        self.assertIn("beta", snippet)

    def test_retriever_uses_match_centered_snippets(self) -> None:
        """End-to-end: retriever snippets contain query terms when possible."""
        body = (
            "Preamble about the system. "
            "The free stock calculation is on_hand_qty minus reserved_qty. "
            "This formula is used across all warehouse modules. "
            "Reserved stock is committed to open sales orders. "
            "Free stock may be negative when reservations exceed on-hand."
        )
        doc = KnowledgeDocument(
            doc_id="free-stock-detail",
            title="Free Stock Detail",
            category="business_definitions",
            fact_kind="definition",
            version="1.0.0",
            updated_at=date(2026, 11, 1),
            summary="Free stock calculation details.",
            tags=(),
            aliases=(),
            source_path="business_definitions/free-stock-detail.md",
            content_hash="b" * 64,
            body=body,
        )
        index = make_index(chunk_document(doc))
        retriever = DocumentationRetriever(index, max_snippet_chars=200)
        result = retriever.retrieve("free stock calculation", top_k=3)

        self.assertEqual(result.status, "ok")
        # At least one hit should contain the query terms in its snippet
        found_term = any(
            "calculation" in hit.snippet or "formula" in hit.snippet
            for hit in result.hits
        )
        self.assertTrue(found_term, f"No snippet contained query terms: {[h.snippet for h in result.hits]}")


class CategoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.index = make_index(stock_category_chunks())
        self.retriever = DocumentationRetriever(self.index)

    def test_unfiltered_search_spans_categories(self) -> None:
        result = self.retriever.retrieve("What is stock?", top_k=5)
        categories = {hit.category for hit in result.hits}
        self.assertGreater(len(categories), 1)

    def test_filtered_search_returns_one_category(self) -> None:
        for category in (
            "business_definitions",
            "workflows",
            "schema",
        ):
            with self.subTest(category=category):
                result = self.retriever.retrieve(
                    "What is stock?",
                    category=category,
                )
                self.assertEqual(result.status, "ok")
                for hit in result.hits:
                    self.assertEqual(hit.category, category)


class EmptyAndNoMatchTests(unittest.TestCase):
    def test_empty_corpus_returns_no_match(self) -> None:
        index = Bm25Index(
            CorpusBundle(
                documents=(),
                chunks=(),
                index_version="empty-v1",
            )
        )
        result = DocumentationRetriever(index).retrieve(
            "What does free stock mean?"
        )

        self.assertEqual(result.status, "no_match")
        self.assertEqual(result.hits, ())
        self.assertEqual(result.total_chars, 0)
        self.assertEqual(result.index_version, "empty-v1")

    def test_unknown_terms_return_no_match(self) -> None:
        retriever = DocumentationRetriever(make_index(corpus_chunks()))
        result = retriever.retrieve("What is zzzunknown?")

        self.assertEqual(result.status, "no_match")
        self.assertEqual(result.hits, ())
        self.assertIsNotNone(result.guidance)

    def test_empty_query_is_a_typed_error(self) -> None:
        retriever = DocumentationRetriever(make_index(corpus_chunks()))
        for query in ("", "   ", "\n\t"):
            with self.subTest(query=repr(query)):
                with self.assertRaises(RagInvalidArgumentsError):
                    retriever.retrieve(query)

    def test_multiline_query_is_a_typed_error(self) -> None:
        retriever = DocumentationRetriever(make_index(corpus_chunks()))
        with self.assertRaises(RagInvalidArgumentsError):
            retriever.retrieve("first\nsecond")

    def test_too_long_query_is_a_typed_error(self) -> None:
        retriever = DocumentationRetriever(make_index(corpus_chunks()))
        with self.assertRaises(RagInvalidArgumentsError):
            retriever.retrieve("x" * 301)

    def test_non_string_request_is_a_typed_error(self) -> None:
        retriever = DocumentationRetriever(make_index(corpus_chunks()))
        for request in (None, 3, ("query",)):
            with self.subTest(request=repr(request)):
                with self.assertRaises(RagInvalidArgumentsError):
                    retriever.retrieve(request)  # type: ignore[arg-type]


class FlagsAndModelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.retriever = DocumentationRetriever(make_index(corpus_chunks()))

    def test_ok_result_flags(self) -> None:
        result = self.retriever.retrieve("What does free stock mean?")
        self.assertIs(result.live_data, False)
        self.assertEqual(result.disclaimer, DISCLAIMER)
        self.assertEqual(result.status, "ok")

    def test_no_match_flags(self) -> None:
        result = self.retriever.retrieve("What is zzzunknown?")
        self.assertIs(result.live_data, False)
        self.assertEqual(result.disclaimer, DISCLAIMER)
        self.assertEqual(result.status, "no_match")

    def test_blocked_flags(self) -> None:
        result = self.retriever.retrieve("How many products are there?")
        self.assertIs(result.live_data, False)
        self.assertEqual(result.disclaimer, DISCLAIMER)
        self.assertEqual(result.status, "blocked")
        self.assertIsNotNone(result.guidance)

    def test_result_query_is_the_trimmed_query(self) -> None:
        result = self.retriever.retrieve("  What does free stock mean?  ")
        self.assertEqual(result.query, "What does free stock mean?")


class DeterminismTests(unittest.TestCase):
    def test_repeated_retrieval_is_identical(self) -> None:
        retriever = DocumentationRetriever(make_index(corpus_chunks()))
        first = retriever.retrieve("What does free stock mean?")
        second = retriever.retrieve("What does free stock mean?")
        self.assertEqual(first, second)

    def test_input_order_does_not_change_results(self) -> None:
        chunks = corpus_chunks()
        forward = DocumentationRetriever(make_index(chunks)).retrieve(
            "What does free stock mean?"
        )
        backward = DocumentationRetriever(
            make_index(list(reversed(chunks)))
        ).retrieve("What does free stock mean?")

        self.assertEqual(
            [(hit.chunk_id, hit.score, hit.snippet) for hit in forward.hits],
            [(hit.chunk_id, hit.score, hit.snippet) for hit in backward.hits],
        )

    def test_hit_chunk_ids_are_unique(self) -> None:
        retriever = DocumentationRetriever(make_index(per_document_chunks()))
        result = retriever.retrieve("alpha", top_k=5)
        chunk_ids = [hit.chunk_id for hit in result.hits]
        self.assertEqual(len(chunk_ids), len(set(chunk_ids)))

    def test_query_is_not_mutated(self) -> None:
        retriever = DocumentationRetriever(make_index(corpus_chunks()))
        query = "  What does free stock mean?  "
        original = query
        retriever.retrieve(query)
        self.assertEqual(query, original)


class ImmutabilityTests(unittest.TestCase):
    def test_bundle_and_chunks_are_not_mutated(self) -> None:
        chunks = corpus_chunks()
        bundle = make_bundle(chunks, index_version="immutable-v1")
        index = Bm25Index(bundle)
        retriever = DocumentationRetriever(index)
        original_chunks = bundle.chunks
        original_documents = bundle.documents

        retriever.retrieve("What does free stock mean?")
        retriever.retrieve("What is the current stock level?")
        retriever.retrieve("alpha", top_k=1)

        self.assertEqual(bundle.chunks, original_chunks)
        self.assertEqual(bundle.documents, original_documents)
        self.assertEqual(bundle.index_version, "immutable-v1")
        self.assertEqual(index.index_version, "immutable-v1")
        self.assertEqual(index.chunk_count, len(chunks))

    def test_hits_do_not_expose_mutable_chunk_state(self) -> None:
        retriever = DocumentationRetriever(make_index(corpus_chunks()))
        result = retriever.retrieve("What does free stock mean?")

        with self.assertRaises(ValidationError):
            result.hits[0].snippet = "changed"  # type: ignore[misc]


class ConstructorValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.index = make_index(corpus_chunks())

    def test_index_must_be_a_bm25_index(self) -> None:
        with self.assertRaises(RagInvalidArgumentsError):
            DocumentationRetriever("not an index")  # type: ignore[arg-type]

    def test_invalid_thresholds_are_typed_errors(self) -> None:
        cases = (
            ({"min_score": -1}, "min_score"),
            ({"min_score": float("nan")}, "min_score"),
            ({"min_score": "0.1"}, "min_score"),
            ({"relative_score_floor": -0.1}, "relative_score_floor"),
            ({"relative_score_floor": 1.1}, "relative_score_floor"),
            ({"max_hits_per_doc": 0}, "max_hits_per_doc"),
            ({"max_hits_per_doc": 11}, "max_hits_per_doc"),
            ({"max_snippet_chars": 0}, "max_snippet_chars"),
            ({"max_snippet_chars": 2001}, "max_snippet_chars"),
            ({"max_total_chars": 0}, "max_total_chars"),
            ({"max_total_chars": 6001}, "max_total_chars"),
        )
        for kwargs, _name in cases:
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(RagConfigurationError):
                    DocumentationRetriever(self.index, **kwargs)  # type: ignore[arg-type]


class TempCorpusIntegrationTests(unittest.TestCase):
    def _write_document(
        self,
        root: Path,
        category: str,
        stem: str,
        *,
        title: str,
        fact_kind: str,
        body: str,
    ) -> None:
        directory = root / category
        directory.mkdir(parents=True, exist_ok=True)
        content = (
            "---\n"
            f"doc_id: {stem}\n"
            f"title: {title}\n"
            f"category: {category}\n"
            f"fact_kind: {fact_kind}\n"
            "version: 1.0.0\n"
            "updated_at: 2026-11-01\n"
            f"summary: Reviewed documentation for {title}.\n"
            "tags: [test]\n"
            "aliases: []\n"
            "---\n\n"
            f"{body}\n"
        )
        (directory / f"{stem}.md").write_text(content, encoding="utf-8")

    def test_temp_corpus_retrieval_and_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._write_document(
                root,
                "business_definitions",
                "free-stock",
                title="Free Stock",
                fact_kind="definition",
                body=(
                    "# Free Stock\n\n"
                    "## Definition\n\n"
                    "Free stock is the quantity that can still be promised "
                    "to new demand. It is on-hand stock minus reserved stock."
                ),
            )
            self._write_document(
                root,
                "workflows",
                "stock-adjustment",
                title="Stock Adjustment Workflow",
                fact_kind="workflow",
                body=(
                    "# Stock Adjustment Workflow\n\n"
                    "## Steps\n\n"
                    "A stock adjustment starts with a counted correction and "
                    "ends with an approved adjustment record."
                ),
            )

            bundle = load_corpus_from_dir(root)
            index = Bm25Index(bundle)
            retriever = DocumentationRetriever(index)

            result = retriever.retrieve("What does free stock mean?")
            self.assertEqual(result.status, "ok")
            self.assertEqual(result.hits[0].doc_id, "free-stock")
            self.assertEqual(result.index_version, bundle.index_version)
            self.assertIs(result.live_data, False)

            blocked = retriever.retrieve(
                "What is the current stock level?"
            )
            self.assertEqual(blocked.status, "blocked")
            self.assertEqual(blocked.hits, ())

            workflow = retriever.retrieve(
                "Describe the stock adjustment workflow."
            )
            self.assertEqual(workflow.status, "ok")
            self.assertEqual(
                workflow.hits[0].doc_id,
                "stock-adjustment",
            )


if __name__ == "__main__":
    unittest.main()
