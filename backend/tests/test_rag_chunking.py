from __future__ import annotations

import unittest
from datetime import date

from backend.agent.rag import (
    DEFAULT_MAX_CHUNK_CHARS,
    DEFAULT_MIN_CHUNK_CHARS,
    MIN_MEANINGFUL_CHARS,
    KnowledgeChunk,
    KnowledgeDocument,
    chunk_document,
    searchable_text,
    tokenize,
)

LONG_TEXT = (
    "The warehouse team confirms the dispatch once every ordered item has been "
    "picked, packed, and checked against the delivery note."
)

SECOND_TEXT = (
    "Free stock is the on-hand quantity minus the reserved quantity, compared "
    "with the reorder level for that product."
)


def make_document(body: str, **overrides: object) -> KnowledgeDocument:
    values: dict[str, object] = {
        "doc_id": "test-document",
        "title": "Test Document",
        "category": "erp_docs",
        "fact_kind": "overview",
        "version": "1.0.0",
        "updated_at": date(2026, 11, 1),
        "summary": "A test document used by the chunking tests.",
        "tags": ("testing",),
        "aliases": (),
        "source_path": "erp_docs/test-document.md",
        "content_hash": "b" * 64,
        "body": body,
    }
    values.update(overrides)
    return KnowledgeDocument(**values)


def make_body(*lines: str) -> str:
    return "\n".join(lines)


def all_text(chunks: tuple[KnowledgeChunk, ...]) -> str:
    return "\n\n".join(chunk.text for chunk in chunks)


class OverviewChunkTests(unittest.TestCase):
    def test_document_without_headings_becomes_overview_chunk(self) -> None:
        body = f"{LONG_TEXT} {SECOND_TEXT}"
        chunks = chunk_document(make_document(body))

        self.assertEqual(len(chunks), 1)
        chunk = chunks[0]
        self.assertEqual(chunk.section_path, ())
        self.assertEqual(chunk.chunk_id, "test-document#overview#01")
        self.assertEqual(chunk.text, body)
        self.assertEqual(chunk.doc_id, "test-document")
        self.assertEqual(chunk.title, "Test Document")
        self.assertEqual(chunk.category, "erp_docs")
        self.assertEqual(chunk.fact_kind, "overview")
        self.assertEqual(chunk.source_path, "erp_docs/test-document.md")
        self.assertEqual(chunk.updated_at, date(2026, 11, 1))
        self.assertGreater(chunk.token_count, 0)

    def test_preamble_before_first_heading_is_overview(self) -> None:
        body = make_body(LONG_TEXT, "", "# Setup", "", SECOND_TEXT)
        chunks = chunk_document(make_document(body), min_chunk_chars=0)

        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0].section_path, ())
        self.assertEqual(chunks[0].chunk_id, "test-document#overview#01")
        self.assertEqual(chunks[1].section_path, ("Setup",))


class HeadingStructureTests(unittest.TestCase):
    def test_single_heading_becomes_section_path(self) -> None:
        body = make_body("# Dispatch", "", LONG_TEXT)
        chunks = chunk_document(make_document(body))

        self.assertEqual(len(chunks), 1)
        chunk = chunks[0]
        self.assertEqual(chunk.section_path, ("Dispatch",))
        self.assertEqual(chunk.chunk_id, "test-document#dispatch#01")
        self.assertEqual(chunk.text, make_body("Dispatch", "", LONG_TEXT))

    def test_heading_terms_are_preserved_in_chunk_text(self) -> None:
        body = make_body("# Reorder Level", "", LONG_TEXT)
        chunk = chunk_document(make_document(body))[0]

        self.assertNotIn("#", chunk.text)
        self.assertIn("Reorder Level", chunk.text)
        self.assertIn("reorder", tokenize(chunk.text))
        self.assertIn("reorder", tokenize(searchable_text(chunk)))

    def test_heading_hierarchy_is_nested(self) -> None:
        body = make_body(
            "# Guide",
            "",
            LONG_TEXT,
            "",
            "## Setup",
            "",
            SECOND_TEXT,
            "",
            "### Details",
            "",
            LONG_TEXT,
        )
        chunks = chunk_document(make_document(body))

        self.assertEqual(
            [chunk.section_path for chunk in chunks],
            [
                ("Guide",),
                ("Guide", "Setup"),
                ("Guide", "Setup", "Details"),
            ],
        )

    def test_level_jump_keeps_actual_hierarchy(self) -> None:
        body = make_body(
            "# Guide",
            "",
            LONG_TEXT,
            "",
            "### Details",
            "",
            SECOND_TEXT,
            "",
            "## Setup",
            "",
            LONG_TEXT,
        )
        chunks = chunk_document(make_document(body))

        self.assertEqual(
            [chunk.section_path for chunk in chunks],
            [
                ("Guide",),
                ("Guide", "Details"),
                ("Guide", "Setup"),
            ],
        )

    def test_multiple_sibling_sections(self) -> None:
        body = make_body(
            "# Guide",
            "",
            LONG_TEXT,
            "",
            "## Setup",
            "",
            SECOND_TEXT,
            "",
            "## Dispatch",
            "",
            LONG_TEXT,
        )
        chunks = chunk_document(make_document(body))

        self.assertEqual(
            [chunk.section_path for chunk in chunks],
            [
                ("Guide",),
                ("Guide", "Setup"),
                ("Guide", "Dispatch"),
            ],
        )

    def test_atx_headings_require_a_space(self) -> None:
        body = make_body(
            "#NotAHeading",
            "",
            LONG_TEXT,
        )
        chunks = chunk_document(make_document(body))

        self.assertEqual(chunks[0].section_path, ())
        self.assertIn("#NotAHeading", chunks[0].text)

    def test_seven_hashes_is_not_a_heading(self) -> None:
        body = make_body(
            "####### Seven Hashes",
            "",
            LONG_TEXT,
        )
        chunks = chunk_document(make_document(body))

        self.assertEqual(chunks[0].section_path, ())
        self.assertIn("####### Seven Hashes", chunks[0].text)

    def test_closing_hashes_are_stripped(self) -> None:
        body = make_body("# Dispatch ##", "", LONG_TEXT)
        chunks = chunk_document(make_document(body))

        self.assertEqual(chunks[0].section_path, ("Dispatch",))
        self.assertEqual(chunks[0].text, make_body("Dispatch", "", LONG_TEXT))
        self.assertNotIn("##", chunks[0].text)

    def test_hash_inside_heading_title_is_kept(self) -> None:
        body = make_body("# C# Scripting", "", LONG_TEXT)
        chunks = chunk_document(make_document(body))

        self.assertEqual(chunks[0].section_path, ("C# Scripting",))


class FencedCodeTests(unittest.TestCase):
    def test_heading_inside_backtick_fence_is_content(self) -> None:
        body = make_body(
            "# Usage",
            "",
            "Run the query below to confirm the connection works.",
            "",
            "```sql",
            "-- # not a heading",
            "SELECT 1 AS value;",
            "```",
            "",
            "The query returns a constant value.",
        )
        chunks = chunk_document(make_document(body))

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].section_path, ("Usage",))
        self.assertIn("# not a heading", chunks[0].text)

    def test_heading_inside_tilde_fence_is_content(self) -> None:
        body = make_body(
            "# Usage",
            "",
            "Run the query below to confirm the connection works.",
            "",
            "~~~text",
            "## still code",
            "~~~",
            "",
            "The query returns a constant value.",
        )
        chunks = chunk_document(make_document(body))

        self.assertEqual([chunk.section_path for chunk in chunks], [("Usage",)])
        self.assertIn("## still code", chunks[0].text)

    def test_heading_after_fence_close_is_parsed(self) -> None:
        body = make_body(
            "# Usage",
            "",
            "Run the query below to confirm the connection works.",
            "",
            "```sql",
            "SELECT 1;",
            "```",
            "",
            "# Dispatch",
            "",
            SECOND_TEXT,
        )
        chunks = chunk_document(make_document(body))

        self.assertEqual(
            [chunk.section_path for chunk in chunks],
            [("Usage",), ("Dispatch",)],
        )

    def test_fence_markers_stay_in_chunk_text(self) -> None:
        body = make_body(
            "# Usage",
            "",
            "Run the query below to confirm the connection works.",
            "",
            "```sql",
            "SELECT 1;",
            "```",
        )
        chunks = chunk_document(make_document(body))

        self.assertIn("```sql", chunks[0].text)


class OversizedSectionTests(unittest.TestCase):
    def test_paragraphs_split_at_paragraph_boundaries(self) -> None:
        paragraphs = [f"Paragraph {index}: {LONG_TEXT}" for index in range(5)]
        body = make_body("# Guide", "", "\n\n".join(paragraphs))
        chunks = chunk_document(
            make_document(body),
            max_chunk_chars=200,
            min_chunk_chars=0,
        )

        self.assertEqual(len(chunks), 5)
        for chunk in chunks:
            self.assertLessEqual(len(chunk.text), 200)
        for paragraph in paragraphs:
            self.assertIn(paragraph, all_text(chunks))

    def test_sentences_split_at_sentence_boundaries(self) -> None:
        sentence = (
            "Each dispatch note records the warehouse, the carrier, and every "
            "item that left the shelf today."
        )
        body = make_body("# Dispatch", "", " ".join([sentence] * 6))
        chunks = chunk_document(
            make_document(body),
            max_chunk_chars=220,
            min_chunk_chars=0,
        )

        self.assertGreater(len(chunks), 2)
        for chunk in chunks:
            self.assertLessEqual(len(chunk.text), 220)
            self.assertTrue(chunk.text.endswith("."), chunk.text)

    def test_hard_split_without_boundaries(self) -> None:
        body = "x" * 300
        chunks = chunk_document(
            make_document(body),
            max_chunk_chars=100,
            min_chunk_chars=0,
        )

        self.assertEqual([len(chunk.text) for chunk in chunks], [100, 100, 100])
        self.assertEqual("".join(chunk.text for chunk in chunks), body)

    def test_long_word_is_split_without_loss(self) -> None:
        word = "a" * 250
        body = make_body("# Token", "", word)
        chunks = chunk_document(
            make_document(body),
            max_chunk_chars=60,
            min_chunk_chars=0,
        )

        for chunk in chunks:
            self.assertLessEqual(len(chunk.text), 60)
        self.assertIn("a" * 50, all_text(chunks))

    def test_oversized_section_keeps_all_meaningful_words(self) -> None:
        body = make_body(
            "# Operations",
            "",
            LONG_TEXT,
            "",
            SECOND_TEXT,
            "",
            LONG_TEXT,
            "",
            SECOND_TEXT,
        )
        chunks = chunk_document(
            make_document(body),
            max_chunk_chars=150,
            min_chunk_chars=0,
        )

        indexed = tokenize(all_text(chunks))
        for word in ("dispatch", "warehouse", "reserved", "reorder", "product"):
            with self.subTest(word=word):
                self.assertIn(word, indexed)

    def test_every_split_stays_under_limit(self) -> None:
        body = make_body(
            "# Guide",
            "",
            LONG_TEXT,
            "",
            SECOND_TEXT,
            "",
            "A short final line.",
        )
        for limit in (60, 90, 120, 180, 240, 400):
            with self.subTest(limit=limit):
                chunks = chunk_document(
                    make_document(body),
                    max_chunk_chars=limit,
                    min_chunk_chars=0,
                )
                self.assertTrue(chunks)
                for chunk in chunks:
                    self.assertLessEqual(len(chunk.text), limit)

    def test_single_long_paragraph_is_split_into_multiple_chunks(self) -> None:
        body = make_body("# Guide", "", " ".join([LONG_TEXT] * 6))
        chunks = chunk_document(
            make_document(body),
            max_chunk_chars=300,
            min_chunk_chars=0,
        )

        self.assertGreater(len(chunks), 2)
        for chunk in chunks:
            self.assertLessEqual(len(chunk.text), 300)


class SmallSectionTests(unittest.TestCase):
    def test_duplicate_small_section_merges_into_next(self) -> None:
        body = make_body(
            "# Guide",
            "",
            "## Setup",
            "",
            "Short setup text.",
            "",
            "## Setup",
            "",
            "The setup section continues with a much longer explanation of how "
            "to configure the system end to end.",
        )
        chunks = chunk_document(make_document(body))

        self.assertEqual(len(chunks), 1)
        self.assertIn("Short setup text.", chunks[0].text)
        self.assertIn("much longer explanation", chunks[0].text)
        self.assertEqual(chunks[0].section_path, ("Guide", "Setup"))

    def test_merged_section_does_not_exceed_maximum(self) -> None:
        body = make_body(
            "# Guide",
            "",
            "## Setup",
            "",
            "Short setup text.",
            "",
            "## Setup",
            "",
            "Another short note that still needs a small amount of room to fit.",
        )
        chunks = chunk_document(
            make_document(body),
            max_chunk_chars=60,
            min_chunk_chars=40,
        )

        for chunk in chunks:
            self.assertLessEqual(len(chunk.text), 60)

    def test_small_group_without_sibling_is_kept(self) -> None:
        body = make_body(
            "# Guide",
            "",
            "## Setup",
            "",
            "Short setup text that is still meaningful.",
            "",
            "## Dispatch",
            "",
            LONG_TEXT,
        )
        chunks = chunk_document(make_document(body))

        self.assertEqual(
            [chunk.section_path for chunk in chunks],
            [("Guide", "Setup"), ("Guide", "Dispatch")],
        )

    def test_merge_disabled_with_zero_minimum(self) -> None:
        body = make_body(
            "# Guide",
            "",
            "## Setup",
            "",
            "Short setup text.",
            "",
            "## Setup",
            "",
            SECOND_TEXT,
        )
        chunks = chunk_document(make_document(body), min_chunk_chars=0)

        self.assertEqual(len(chunks), 2)


class ChunkIdTests(unittest.TestCase):
    def test_ids_are_stable_across_calls(self) -> None:
        body = make_body(
            "# Guide",
            "",
            LONG_TEXT,
            "",
            "## Setup",
            "",
            SECOND_TEXT,
        )
        document = make_document(body)
        first = chunk_document(document)
        second = chunk_document(document)

        self.assertEqual(
            [chunk.chunk_id for chunk in first],
            [chunk.chunk_id for chunk in second],
        )
        self.assertEqual(
            [chunk.text for chunk in first],
            [chunk.text for chunk in second],
        )

    def test_ids_are_unique_for_duplicate_headings(self) -> None:
        body = make_body(
            "# Guide",
            "",
            "## Setup",
            "",
            LONG_TEXT,
            "",
            "## Setup",
            "",
            SECOND_TEXT,
        )
        chunks = chunk_document(make_document(body), min_chunk_chars=0)

        ids = [chunk.chunk_id for chunk in chunks]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(
            ids,
            ["test-document#setup#01", "test-document#setup#02"],
        )

    def test_ids_are_unique_for_many_sections(self) -> None:
        body = make_body(
            "# Guide",
            "",
            LONG_TEXT,
            "",
            "## Setup",
            "",
            SECOND_TEXT,
            "",
            "## Dispatch",
            "",
            LONG_TEXT,
        )
        chunks = chunk_document(make_document(body), min_chunk_chars=0)

        ids = [chunk.chunk_id for chunk in chunks]
        self.assertEqual(len(ids), len(set(ids)))
        for chunk in chunks:
            self.assertTrue(chunk.chunk_id.startswith("test-document#"))
            self.assertTrue(chunk.chunk_id.endswith(("01", "02")))

    def test_section_slug_is_derived_from_leaf_heading(self) -> None:
        body = make_body("# Guide", "", "## Low Stock Level", "", LONG_TEXT)
        chunks = chunk_document(make_document(body), min_chunk_chars=0)

        self.assertEqual(chunks[-1].chunk_id, "test-document#low-stock-level#01")


class ContentPreservationTests(unittest.TestCase):
    def test_all_body_lines_survive_chunking(self) -> None:
        body = make_body(
            "# Guide",
            "",
            LONG_TEXT,
            "",
            "## Setup",
            "",
            SECOND_TEXT,
            "",
            "## Dispatch",
            "",
            "Dispatch closes when the carrier confirms collection at the dock.",
        )
        chunks = chunk_document(
            make_document(body),
            max_chunk_chars=140,
            min_chunk_chars=0,
        )
        indexed = set(tokenize(all_text(chunks)))

        for word in (
            "guide",
            "warehouse",
            "dispatch",
            "carrier",
            "reserved",
            "reorder",
            "collection",
            "dock",
        ):
            with self.subTest(word=word):
                self.assertIn(word, indexed)

    def test_heading_only_document_produces_no_chunks(self) -> None:
        body = "# Heading Only" + "\n" * 40
        self.assertGreaterEqual(len(body), 40)
        self.assertEqual(chunk_document(make_document(body)), ())

    def test_blank_only_body_produces_no_chunks(self) -> None:
        body = " " * 40
        self.assertEqual(chunk_document(make_document(body)), ())

    def test_short_sections_are_dropped_below_threshold(self) -> None:
        body = make_body("# Guide", "", "Tiny.") + "\n" * 40
        self.assertLess(len("Tiny."), MIN_MEANINGFUL_CHARS)
        self.assertEqual(chunk_document(make_document(body)), ())

    def test_threshold_is_twenty_non_whitespace_characters(self) -> None:
        # "Guide" contributes five non-whitespace characters.
        body = make_body("# Guide", "", "12345678901234") + "\n" * 40
        self.assertEqual(chunk_document(make_document(body)), ())

        body = make_body("# Guide", "", "123456789012345") + "\n" * 40
        chunks = chunk_document(make_document(body))
        self.assertEqual(len(chunks), 1)


class TokenCountTests(unittest.TestCase):
    def test_token_count_matches_searchable_text(self) -> None:
        body = make_body("# Dispatch", "", LONG_TEXT)
        chunk = chunk_document(make_document(body))[0]

        expected = len(tokenize(searchable_text(chunk)))
        self.assertEqual(chunk.token_count, expected)

    def test_searchable_text_includes_title_and_section(self) -> None:
        body = make_body("# Dispatch", "", LONG_TEXT)
        chunk = chunk_document(make_document(body))[0]
        text = searchable_text(chunk)

        self.assertTrue(text.startswith("Test Document\nDispatch\n"))
        self.assertIn(LONG_TEXT, text)

    def test_overview_searchable_text_uses_overview_label(self) -> None:
        chunk = chunk_document(make_document(LONG_TEXT))[0]
        self.assertIn("\nOverview\n", searchable_text(chunk))


class DefaultsAndValidationTests(unittest.TestCase):
    def test_documented_defaults(self) -> None:
        self.assertEqual(DEFAULT_MAX_CHUNK_CHARS, 1200)
        self.assertEqual(DEFAULT_MIN_CHUNK_CHARS, 120)
        self.assertEqual(MIN_MEANINGFUL_CHARS, 20)

    def test_default_chunks_respect_default_maximum(self) -> None:
        body = make_body("# Guide", "", " ".join([LONG_TEXT] * 10))
        chunks = chunk_document(make_document(body), min_chunk_chars=0)

        for chunk in chunks:
            self.assertLessEqual(len(chunk.text), DEFAULT_MAX_CHUNK_CHARS)

    def test_returns_tuple_of_chunks(self) -> None:
        chunks = chunk_document(make_document(LONG_TEXT))

        self.assertIsInstance(chunks, tuple)
        for chunk in chunks:
            self.assertIsInstance(chunk, KnowledgeChunk)

    def test_requires_document_instance(self) -> None:
        with self.assertRaises(TypeError):
            chunk_document(LONG_TEXT)  # type: ignore[arg-type]

    def test_rejects_invalid_sizes(self) -> None:
        document = make_document(LONG_TEXT)
        for value in (0, -1, True, 5001, "100"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    chunk_document(document, max_chunk_chars=value)  # type: ignore[arg-type]

    def test_rejects_minimum_above_maximum(self) -> None:
        document = make_document(LONG_TEXT)
        with self.assertRaises(ValueError):
            chunk_document(
                document,
                max_chunk_chars=200,
                min_chunk_chars=201,
            )

    def test_rejects_negative_minimum(self) -> None:
        with self.assertRaises(ValueError):
            chunk_document(make_document(LONG_TEXT), min_chunk_chars=-1)


if __name__ == "__main__":
    unittest.main()
