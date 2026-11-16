from __future__ import annotations

import math
import threading
import unittest
from datetime import date

from backend.agent.rag import (
    BM25_B,
    BM25_K1,
    Bm25Index,
    CorpusBundle,
    KnowledgeChunk,
    KnowledgeDocument,
    ScoredChunk,
    slugify,
    tokenize,
)
from backend.agent.rag.chunking import searchable_text


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
        summary="A test document for the BM25 index.",
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
    index_version: str = "corpus-v1",
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


def expected_score(
    *,
    tf: int,
    df: int,
    n: int,
    dl: int,
    avgdl: float,
    k1: float = 1.2,
    b: float = 0.75,
) -> float:
    """Independent BM25 implementation used to check the index."""

    idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
    return idf * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / avgdl))


def stats_chunks() -> list[KnowledgeChunk]:
    return [
        make_chunk("doc-a", "alpha alpha beta"),
        make_chunk("doc-b", "beta gamma"),
    ]


def ranking_chunks() -> list[KnowledgeChunk]:
    return [
        make_chunk("rank-a", "alpha alpha alpha filler"),
        make_chunk("rank-b", "alpha alpha filler filler"),
        make_chunk("rank-c", "alpha filler filler filler"),
    ]


class ConstructionTests(unittest.TestCase):
    def test_approved_parameters(self) -> None:
        self.assertAlmostEqual(BM25_K1, 1.2)
        self.assertAlmostEqual(BM25_B, 0.75)

    def test_chunk_count_and_average_length(self) -> None:
        chunks = stats_chunks()
        index = Bm25Index(make_bundle(chunks))

        self.assertEqual(index.chunk_count, 2)
        lengths = [len(tokenize(searchable_text(chunk))) for chunk in chunks]
        self.assertEqual(lengths, [5, 4])
        self.assertAlmostEqual(index.average_length, 4.5)

    def test_index_version_is_preserved(self) -> None:
        index = Bm25Index(make_bundle(stats_chunks(), index_version="v-123"))
        self.assertEqual(index.index_version, "v-123")

    def test_search_returns_scored_chunks(self) -> None:
        index = Bm25Index(make_bundle(stats_chunks()))
        results = index.search("alpha")

        self.assertIsInstance(results, tuple)
        for result in results:
            self.assertIsInstance(result, ScoredChunk)
            self.assertIsInstance(result.chunk, KnowledgeChunk)
            self.assertIsInstance(result.score, float)
            self.assertGreater(result.score, 0.0)

    def test_result_metadata_is_available(self) -> None:
        chunk = make_chunk(
            "meta-doc",
            "alpha beta",
            title="Metadata Doc",
            section=("Guide", "Overview"),
            category="schema",
            fact_kind="schema",
        )
        index = Bm25Index(make_bundle([chunk]))
        result = index.search("alpha")[0]

        self.assertIs(result.chunk, chunk)
        self.assertEqual(result.chunk.chunk_id, chunk.chunk_id)
        self.assertEqual(result.chunk.doc_id, "meta-doc")
        self.assertEqual(result.chunk.title, "Metadata Doc")
        self.assertEqual(result.chunk.section_path, ("Guide", "Overview"))
        self.assertEqual(result.chunk.category, "schema")
        self.assertEqual(result.chunk.fact_kind, "schema")
        self.assertEqual(result.chunk.source_path, "schema/meta-doc.md")
        self.assertEqual(result.chunk.updated_at, date(2026, 11, 1))

    def test_title_terms_are_indexed(self) -> None:
        chunk = make_chunk("title-doc", "one two three", title="Dispatch Guide")
        index = Bm25Index(make_bundle([chunk]))

        self.assertEqual(index.document_frequency("dispatch"), 1)
        self.assertEqual(len(index.search("dispatch")), 1)

    def test_section_path_terms_are_indexed(self) -> None:
        chunk = make_chunk(
            "section-doc",
            "one two three",
            section=("Guide", "Fulfilment"),
        )
        index = Bm25Index(make_bundle([chunk]))

        self.assertEqual(index.document_frequency("fulfilment"), 1)
        self.assertEqual(len(index.search("fulfilment")), 1)

    def test_input_order_does_not_change_statistics(self) -> None:
        chunks = stats_chunks()
        forward = Bm25Index(make_bundle(chunks))
        backward = Bm25Index(make_bundle(list(reversed(chunks))))

        self.assertEqual(forward.chunk_count, backward.chunk_count)
        self.assertAlmostEqual(forward.average_length, backward.average_length)
        self.assertEqual(
            [(item.chunk.chunk_id, item.score) for item in forward.search("beta")],
            [(item.chunk.chunk_id, item.score) for item in backward.search("beta")],
        )


class StatisticsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.index = Bm25Index(make_bundle(stats_chunks()))

    def test_term_frequency(self) -> None:
        self.assertEqual(self.index.term_frequency("doc-a#section#01", "alpha"), 2)
        self.assertEqual(self.index.term_frequency("doc-a#section#01", "beta"), 1)
        self.assertEqual(self.index.term_frequency("doc-b#section#01", "beta"), 1)
        self.assertEqual(self.index.term_frequency("doc-b#section#01", "alpha"), 0)

    def test_document_frequency(self) -> None:
        self.assertEqual(self.index.document_frequency("alpha"), 1)
        self.assertEqual(self.index.document_frequency("beta"), 2)
        self.assertEqual(self.index.document_frequency("gamma"), 1)

    def test_unknown_term_statistics(self) -> None:
        self.assertEqual(self.index.document_frequency("delta"), 0)
        self.assertEqual(self.index.term_frequency("doc-a#section#01", "delta"), 0)

    def test_idf_matches_the_formula(self) -> None:
        self.assertAlmostEqual(self.index.idf("alpha"), math.log(2), places=12)
        self.assertAlmostEqual(self.index.idf("beta"), math.log(1.2), places=12)
        self.assertAlmostEqual(self.index.idf("delta"), math.log(6), places=12)

    def test_term_lookup_normalizes_plurals(self) -> None:
        self.assertEqual(self.index.document_frequency("sections"), 2)
        self.assertEqual(self.index.idf("sections"), self.index.idf("section"))

    def test_term_lookup_requires_one_token(self) -> None:
        for value in ("alpha beta", "", "the"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.index.document_frequency(value)

    def test_term_lookup_requires_a_string(self) -> None:
        for value in (None, 3, ("alpha",)):
            with self.subTest(value=value):
                with self.assertRaises(TypeError):
                    self.index.document_frequency(value)

    def test_unknown_chunk_id_has_no_term_frequency(self) -> None:
        self.assertEqual(self.index.term_frequency("missing#section#01", "alpha"), 0)

    def test_chunk_id_must_be_a_string(self) -> None:
        with self.assertRaises(TypeError):
            self.index.term_frequency(None, "alpha")  # type: ignore[arg-type]


class EmptyIndexStatisticsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.index = Bm25Index(
            CorpusBundle(documents=(), chunks=(), index_version="empty-v1")
        )

    def test_empty_index_properties(self) -> None:
        self.assertEqual(self.index.chunk_count, 0)
        self.assertEqual(self.index.average_length, 0.0)
        self.assertEqual(self.index.index_version, "empty-v1")

    def test_empty_index_statistics(self) -> None:
        self.assertEqual(self.index.document_frequency("alpha"), 0)
        self.assertEqual(self.index.term_frequency("doc-a#section#01", "alpha"), 0)
        self.assertEqual(self.index.idf("alpha"), 0.0)


class ScoringTests(unittest.TestCase):
    def setUp(self) -> None:
        self.index = Bm25Index(make_bundle(stats_chunks()))

    def test_single_term_score_matches_formula(self) -> None:
        result = self.index.search("alpha")[0]

        self.assertEqual(result.chunk.doc_id, "doc-a")
        self.assertAlmostEqual(
            result.score,
            expected_score(tf=2, df=1, n=2, dl=5, avgdl=4.5),
            places=12,
        )

    def test_second_term_score_matches_formula(self) -> None:
        results = {item.chunk.doc_id: item for item in self.index.search("beta")}

        self.assertAlmostEqual(
            results["doc-a"].score,
            expected_score(tf=1, df=2, n=2, dl=5, avgdl=4.5),
            places=12,
        )
        self.assertAlmostEqual(
            results["doc-b"].score,
            expected_score(tf=1, df=2, n=2, dl=4, avgdl=4.5),
            places=12,
        )

    def test_scores_sum_across_query_terms(self) -> None:
        alpha = self.index.search("alpha")[0].score
        beta = next(
            item for item in self.index.search("beta") if item.chunk.doc_id == "doc-a"
        ).score
        combined = next(
            item
            for item in self.index.search("alpha beta")
            if item.chunk.doc_id == "doc-a"
        )

        self.assertAlmostEqual(combined.score, alpha + beta, places=12)

    def test_duplicate_query_terms_are_deduplicated(self) -> None:
        once = self.index.search("alpha")
        twice = self.index.search("alpha alpha")

        self.assertEqual(
            [item.chunk.chunk_id for item in once],
            [item.chunk.chunk_id for item in twice],
        )
        for first, second in zip(once, twice):
            self.assertEqual(first.score, second.score)

    def test_custom_parameters_are_applied(self) -> None:
        index = Bm25Index(make_bundle(stats_chunks()), k1=2.0, b=0.0)
        result = index.search("alpha")[0]

        self.assertAlmostEqual(
            result.score,
            expected_score(tf=2, df=1, n=2, dl=5, avgdl=4.5, k1=2.0, b=0.0),
            places=12,
        )

    def test_invalid_parameters_are_rejected(self) -> None:
        bundle = make_bundle(stats_chunks())
        for value in (0, -1, True, "1.2", float("nan"), float("inf"), 5.5):
            with self.subTest(k1=value):
                with self.assertRaises(ValueError):
                    Bm25Index(bundle, k1=value)  # type: ignore[arg-type]
        for value in (-0.1, 1.1, True, "0.5", float("inf")):
            with self.subTest(b=value):
                with self.assertRaises(ValueError):
                    Bm25Index(bundle, b=value)  # type: ignore[arg-type]


class RankingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.index = Bm25Index(make_bundle(ranking_chunks()))

    def test_term_frequency_orders_results(self) -> None:
        results = self.index.search("alpha")

        self.assertEqual(
            [item.chunk.doc_id for item in results],
            ["rank-a", "rank-b", "rank-c"],
        )

    def test_ranking_scores_match_the_formula(self) -> None:
        results = self.index.search("alpha")

        for result, tf in zip(results, (3, 2, 1), strict=True):
            self.assertAlmostEqual(
                result.score,
                expected_score(tf=tf, df=3, n=3, dl=6, avgdl=6.0),
                places=12,
            )

    def test_ties_break_on_chunk_id(self) -> None:
        chunks = [
            make_chunk("tie-b", "alpha alpha"),
            make_chunk("tie-a", "alpha alpha"),
        ]
        results = Bm25Index(make_bundle(chunks)).search("alpha")

        self.assertEqual(
            [item.chunk.chunk_id for item in results],
            ["tie-a#section#01", "tie-b#section#01"],
        )
        self.assertEqual(results[0].score, results[1].score)

    def test_tie_break_is_independent_of_input_order(self) -> None:
        chunks = [
            make_chunk("tie-a", "alpha alpha"),
            make_chunk("tie-b", "alpha alpha"),
        ]
        forward = Bm25Index(make_bundle(chunks)).search("alpha")
        backward = Bm25Index(make_bundle(list(reversed(chunks)))).search("alpha")

        self.assertEqual(
            [item.chunk.chunk_id for item in forward],
            [item.chunk.chunk_id for item in backward],
        )

    def test_repeated_searches_are_identical(self) -> None:
        first = self.index.search("alpha")
        second = self.index.search("alpha")

        self.assertEqual(
            [(item.chunk.chunk_id, item.score) for item in first],
            [(item.chunk.chunk_id, item.score) for item in second],
        )

    def test_limit_truncates_results(self) -> None:
        results = self.index.search("alpha", limit=2)
        self.assertEqual(
            [item.chunk.doc_id for item in results],
            ["rank-a", "rank-b"],
        )

    def test_limit_none_returns_every_match(self) -> None:
        self.assertEqual(len(self.index.search("alpha")), 3)
        self.assertEqual(len(self.index.search("alpha", limit=None)), 3)
        self.assertEqual(len(self.index.search("alpha", limit=10)), 3)

    def test_zero_limit_returns_nothing(self) -> None:
        self.assertEqual(self.index.search("alpha", limit=0), ())

    def test_invalid_limit_is_rejected(self) -> None:
        for value in (-1, True, "2", 1.5):
            with self.subTest(limit=value):
                with self.assertRaises(ValueError):
                    self.index.search("alpha", limit=value)  # type: ignore[arg-type]


class CategoryTests(unittest.TestCase):
    def setUp(self) -> None:
        chunks = [
            make_chunk(
                "schema-doc",
                "alpha alpha",
                category="schema",
                fact_kind="schema",
            ),
            make_chunk("erp-doc-a", "alpha"),
            make_chunk("erp-doc-b", "alpha"),
        ]
        self.bundle = make_bundle(chunks)
        self.index = Bm25Index(self.bundle)

    def test_category_filter_restricts_candidates(self) -> None:
        results = self.index.search("alpha", category="schema")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].chunk.category, "schema")
        self.assertEqual(results[0].chunk.doc_id, "schema-doc")

    def test_category_filter_keeps_ranking(self) -> None:
        results = self.index.search("alpha", category="erp_docs")

        self.assertEqual(
            [item.chunk.doc_id for item in results],
            ["erp-doc-a", "erp-doc-b"],
        )

    def test_category_filter_does_not_change_scores(self) -> None:
        unfiltered = self.index.search("alpha")
        filtered = self.index.search("alpha", category="schema")

        original = next(
            item for item in unfiltered if item.chunk.doc_id == "schema-doc"
        )
        self.assertEqual(filtered[0].score, original.score)

    def test_category_filter_with_limit(self) -> None:
        results = self.index.search("alpha", category="erp_docs", limit=1)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].chunk.doc_id, "erp-doc-a")

    def test_unknown_or_empty_category_returns_nothing(self) -> None:
        self.assertEqual(self.index.search("alpha", category="workflows"), ())
        self.assertEqual(self.index.search("missing", category="schema"), ())


class EmptyQueryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.index = Bm25Index(make_bundle(stats_chunks()))

    def test_empty_query(self) -> None:
        self.assertEqual(self.index.search(""), ())

    def test_whitespace_query(self) -> None:
        self.assertEqual(self.index.search("   \n\t "), ())

    def test_stopword_only_query(self) -> None:
        self.assertEqual(self.index.search("the and of what is"), ())

    def test_unknown_term_query(self) -> None:
        self.assertEqual(self.index.search("delta"), ())
        self.assertEqual(self.index.search("alphabet"), ())

    def test_number_only_query(self) -> None:
        self.assertEqual(self.index.search("1234 5678"), ())

    def test_non_string_query_is_rejected(self) -> None:
        for value in (None, 3, ("alpha",)):
            with self.subTest(value=value):
                with self.assertRaises(TypeError):
                    self.index.search(value)  # type: ignore[arg-type]

    def test_empty_index_search(self) -> None:
        index = Bm25Index(
            CorpusBundle(documents=(), chunks=(), index_version="empty-v1")
        )
        self.assertEqual(index.search("alpha"), ())
        self.assertEqual(index.search(""), ())


class RebuildTests(unittest.TestCase):
    def setUp(self) -> None:
        self.bundle_a = make_bundle(
            [make_chunk("doc-a", "alpha alpha")],
            index_version="version-a",
        )
        self.bundle_b = make_bundle(
            [make_chunk("doc-b", "gamma gamma")],
            index_version="version-b",
        )

    def test_rebuild_swaps_content_and_version(self) -> None:
        index = Bm25Index(self.bundle_a)
        self.assertEqual(index.index_version, "version-a")
        self.assertEqual(len(index.search("alpha")), 1)

        index.rebuild(self.bundle_b)

        self.assertEqual(index.index_version, "version-b")
        self.assertEqual(index.search("alpha"), ())
        self.assertEqual(len(index.search("gamma")), 1)
        self.assertEqual(index.chunk_count, 1)

    def test_rebuild_to_empty_corpus(self) -> None:
        index = Bm25Index(self.bundle_a)
        empty = CorpusBundle(documents=(), chunks=(), index_version="empty")

        index.rebuild(empty)

        self.assertEqual(index.index_version, "empty")
        self.assertEqual(index.chunk_count, 0)
        self.assertEqual(index.average_length, 0.0)
        self.assertEqual(index.search("alpha"), ())

    def test_rebuild_rejects_non_bundle_and_keeps_state(self) -> None:
        index = Bm25Index(self.bundle_a)

        with self.assertRaises(TypeError):
            index.rebuild("not a bundle")  # type: ignore[arg-type]

        self.assertEqual(index.index_version, "version-a")
        self.assertEqual(len(index.search("alpha")), 1)

    def test_concurrent_reads_and_rebuilds(self) -> None:
        bundle_a = make_bundle(
            [make_chunk("doc-a", "alpha alpha")],
            index_version="version-a",
        )
        bundle_b = make_bundle(
            [make_chunk("doc-b", "alpha alpha")],
            index_version="version-b",
        )
        index = Bm25Index(bundle_a)
        errors: list[object] = []
        barrier = threading.Barrier(6)

        def reader() -> None:
            barrier.wait()
            for _ in range(40):
                try:
                    results = index.search("alpha")
                    document_ids = {item.chunk.doc_id for item in results}
                    if document_ids not in ({"doc-a"}, {"doc-b"}):
                        errors.append(document_ids)
                except Exception as exc:  # pragma: no cover - failure path
                    errors.append(exc)

        def writer() -> None:
            barrier.wait()
            for step in range(40):
                try:
                    index.rebuild(bundle_a if step % 2 == 0 else bundle_b)
                except Exception as exc:  # pragma: no cover - failure path
                    errors.append(exc)

        threads = [threading.Thread(target=reader) for _ in range(4)]
        threads.extend(threading.Thread(target=writer) for _ in range(2))
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(errors, [])
        self.assertIn(index.index_version, {"version-a", "version-b"})


class ImmutabilityTests(unittest.TestCase):
    def test_bundle_is_not_mutated(self) -> None:
        chunks = ranking_chunks()
        bundle = make_bundle(chunks, index_version="immutable-v1")
        original_chunks = bundle.chunks
        original_documents = bundle.documents

        index = Bm25Index(bundle)
        index.search("alpha")
        index.rebuild(make_bundle(stats_chunks(), index_version="other"))

        self.assertEqual(bundle.chunks, original_chunks)
        self.assertEqual(bundle.documents, original_documents)
        self.assertEqual(bundle.index_version, "immutable-v1")

    def test_input_chunk_order_is_preserved(self) -> None:
        chunks = list(reversed(ranking_chunks()))
        bundle = make_bundle(chunks)

        Bm25Index(bundle).search("alpha")

        self.assertEqual(
            [chunk.doc_id for chunk in bundle.chunks],
            [chunk.doc_id for chunk in chunks],
        )

    def test_results_reference_original_chunks(self) -> None:
        chunk = make_chunk("meta-doc", "alpha")
        bundle = make_bundle([chunk])

        result = Bm25Index(bundle).search("alpha")[0]

        self.assertIs(result.chunk, chunk)


if __name__ == "__main__":
    unittest.main()
