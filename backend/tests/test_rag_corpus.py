from __future__ import annotations

import hashlib
import unittest
from collections import Counter
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from backend.agent.rag import (
    CATEGORIES,
    DEFAULT_KNOWLEDGE_DIR,
    RagConfig,
    RagCorpusError,
    chunk_document,
    find_live_fact_violations,
    index_version_for,
    load_corpus,
    load_corpus_from_dir,
)
from backend.agent.rag.config import MAX_CORPUS_BYTES, MAX_DOCS
from backend.agent.rag.corpus import MAX_BODY_CHARS

BODY = (
    "# Reference Topic\n\n"
    "This page explains a documentation concept in enough detail to be "
    "indexed as a meaningful chunk by the corpus loader.\n\n"
    "## Details\n\n"
    "The loader validates metadata, checks for live ERP facts, and then "
    "chunks the body with the deterministic chunker."
)

SAFE_BODY = (
    "# Documentation Page\n\n"
    "This page contains conceptual documentation text that is safe to index "
    "and explains a process without live business values."
)


def front_matter(**overrides: object) -> str:
    values: dict[str, object] = {
        "doc_id": "reference-topic",
        "title": "Reference Topic",
        "category": "erp_docs",
        "fact_kind": "overview",
        "version": "1.0.0",
        "updated_at": "2026-11-01",
        "summary": "A short summary of the reference topic.",
        "tags": "[testing, documentation]",
        "aliases": "[]",
    }
    values.update(overrides)

    lines = ["---"]
    for key, value in values.items():
        if value is None:
            continue
        lines.append(f"{key}: {value}")
    lines.append("---")
    return "\n".join(lines)


class CorpusTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = TemporaryDirectory()
        self.addCleanup(self._temp_dir.cleanup)
        self.root = Path(self._temp_dir.name)

    def write_raw(
        self,
        relative: str,
        raw: str,
        *,
        encoding: str = "utf-8",
        bom: bool = False,
    ) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        data = raw.encode(encoding)
        if bom:
            data = b"\xef\xbb\xbf" + data
        path.write_bytes(data)
        return path

    def write_document(
        self,
        category: str = "erp_docs",
        doc_id: str = "reference-topic",
        *,
        body: str = BODY,
        filename: str | None = None,
        **overrides: object,
    ) -> Path:
        name = filename or f"{doc_id}.md"
        raw = (
            front_matter(doc_id=doc_id, category=category, **overrides)
            + "\n\n"
            + body
        )
        return self.write_raw(f"{category}/{name}", raw)

    def config(self, **overrides: object) -> RagConfig:
        values: dict[str, object] = {
            "knowledge_dir": self.root,
            "min_chunk_chars": 0,
        }
        values.update(overrides)
        return RagConfig(**values)

    def load(self, **overrides: object):
        return load_corpus(self.config(**overrides))

    def assert_corpus_error(self, rule: str, **overrides: object) -> RagCorpusError:
        with self.assertRaises(RagCorpusError) as context:
            self.load(**overrides)
        error = context.exception
        self.assertEqual(error.code, "rag_corpus_error")
        self.assertEqual(error.details.get("rule"), rule)
        return error

    def load_body(
        self,
        body: str,
        *,
        category: str = "erp_docs",
        doc_id: str = "reference-topic",
        **overrides: object,
    ):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root / category
            directory.mkdir()
            raw = (
                front_matter(doc_id=doc_id, category=category, **overrides)
                + "\n\n"
                + body
            )
            (directory / f"{doc_id}.md").write_bytes(raw.encode("utf-8"))
            return load_corpus_from_dir(root, min_chunk_chars=0)

    def assert_body_error(self, rule: str, body: str, **overrides: object):
        with self.assertRaises(RagCorpusError) as context:
            self.load_body(body, **overrides)
        error = context.exception
        self.assertEqual(error.code, "rag_corpus_error")
        self.assertEqual(error.details.get("rule"), rule)
        return error


class ShippedCorpusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bundle = load_corpus_from_dir(DEFAULT_KNOWLEDGE_DIR)

    def test_loads_twelve_documents(self) -> None:
        self.assertEqual(len(self.bundle.documents), 12)

    def test_each_category_is_represented(self) -> None:
        counts = Counter(document.category for document in self.bundle.documents)
        self.assertEqual(
            dict(counts),
            {
                "erp_docs": 3,
                "business_definitions": 3,
                "workflows": 3,
                "policies_faqs": 2,
                "schema": 1,
            },
        )

    def test_document_ids_are_unique_and_chunked(self) -> None:
        document_ids = [document.doc_id for document in self.bundle.documents]
        self.assertEqual(len(document_ids), len(set(document_ids)))

        chunked_ids = {chunk.doc_id for chunk in self.bundle.chunks}
        self.assertEqual(set(document_ids), chunked_ids)

    def test_chunk_ids_are_unique_and_prefixed(self) -> None:
        chunk_ids = [chunk.chunk_id for chunk in self.bundle.chunks]
        self.assertEqual(len(chunk_ids), len(set(chunk_ids)))
        for chunk in self.bundle.chunks:
            self.assertTrue(chunk.chunk_id.startswith(f"{chunk.doc_id}#"))

    def test_chunks_respect_the_default_maximum(self) -> None:
        self.assertTrue(self.bundle.chunks)
        for chunk in self.bundle.chunks:
            self.assertLessEqual(len(chunk.text), 1200)

    def test_source_paths_exist_and_match_category(self) -> None:
        for document in self.bundle.documents:
            path = DEFAULT_KNOWLEDGE_DIR / document.source_path
            self.assertTrue(path.is_file(), document.source_path)
            self.assertEqual(document.source_path.split("/")[0], document.category)
            self.assertEqual(path.stem, document.doc_id)

    def test_documents_are_ordered_by_source_path(self) -> None:
        paths = [document.source_path for document in self.bundle.documents]
        self.assertEqual(paths, sorted(paths))

    def test_index_version_matches_documents(self) -> None:
        self.assertEqual(
            self.bundle.index_version,
            index_version_for(self.bundle.documents),
        )
        self.assertEqual(len(self.bundle.index_version), 12)
        int(self.bundle.index_version, 16)

    def test_content_hashes_are_unique_sha256(self) -> None:
        hashes = [document.content_hash for document in self.bundle.documents]
        self.assertEqual(len(hashes), len(set(hashes)))
        for value in hashes:
            self.assertEqual(len(value), 64)
            int(value, 16)

    def test_all_categories_are_approved(self) -> None:
        for document in self.bundle.documents:
            self.assertIn(document.category, CATEGORIES)

    def test_load_corpus_accepts_a_config(self) -> None:
        bundle = load_corpus(RagConfig(knowledge_dir=DEFAULT_KNOWLEDGE_DIR))
        self.assertEqual(bundle.index_version, self.bundle.index_version)
        self.assertEqual(len(bundle.documents), 12)

    def test_shipped_documents_are_updated(self) -> None:
        for document in self.bundle.documents:
            with self.subTest(document=document.doc_id):
                self.assertEqual(document.version, "1.0.0")
                self.assertEqual(document.updated_at, date(2026, 11, 1))
                self.assertTrue(document.summary)
                self.assertGreaterEqual(len(document.body), 40)


class MetadataParsingTests(CorpusTestCase):
    def test_document_fields_are_parsed(self) -> None:
        self.write_document()

        bundle = self.load()
        self.assertEqual(len(bundle.documents), 1)
        document = bundle.documents[0]
        self.assertEqual(document.doc_id, "reference-topic")
        self.assertEqual(document.title, "Reference Topic")
        self.assertEqual(document.category, "erp_docs")
        self.assertEqual(document.fact_kind, "overview")
        self.assertEqual(document.version, "1.0.0")
        self.assertEqual(document.updated_at, date(2026, 11, 1))
        self.assertEqual(document.summary, "A short summary of the reference topic.")
        self.assertEqual(document.tags, ("testing", "documentation"))
        self.assertEqual(document.aliases, ())
        self.assertEqual(document.source_path, "erp_docs/reference-topic.md")

    def test_flow_and_plain_lists_are_parsed(self) -> None:
        self.write_document(
            tags='["Low Stock", "Reorder Level"]',
            aliases="available stock, low stock",
        )

        document = self.load().documents[0]
        self.assertEqual(document.tags, ("low stock", "reorder level"))
        self.assertEqual(document.aliases, ("available stock", "low stock"))

    def test_quoted_scalars_are_unquoted(self) -> None:
        self.write_document(
            title='"Quoted: Title"',
            summary="'A quoted summary of the topic.'",
        )

        document = self.load().documents[0]
        self.assertEqual(document.title, "Quoted: Title")
        self.assertEqual(document.summary, "A quoted summary of the topic.")

    def test_content_hash_covers_the_normalized_file(self) -> None:
        raw = front_matter() + "\n\n" + BODY
        self.write_raw("erp_docs/reference-topic.md", raw)

        document = self.load().documents[0]
        expected = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        self.assertEqual(document.content_hash, expected)

    def test_crlf_and_lf_produce_the_same_hash(self) -> None:
        raw = front_matter() + "\n\n" + BODY
        self.write_raw("erp_docs/reference-topic.md", raw)
        lf_hash = self.load().documents[0].content_hash

        self.write_raw("erp_docs/reference-topic.md", raw.replace("\n", "\r\n"))
        crlf_hash = self.load().documents[0].content_hash

        self.assertEqual(lf_hash, crlf_hash)

    def test_utf8_bom_is_tolerated(self) -> None:
        raw = front_matter() + "\n\n" + BODY
        self.write_raw("erp_docs/reference-topic.md", raw, bom=True)

        bundle = self.load()
        self.assertEqual(len(bundle.documents), 1)
        self.assertEqual(bundle.documents[0].doc_id, "reference-topic")

    def test_body_is_preserved_verbatim(self) -> None:
        self.write_document(body=BODY)
        document = self.load().documents[0]
        self.assertEqual(document.body, BODY)

    def test_blank_lines_in_front_matter_are_allowed(self) -> None:
        raw = front_matter().replace(
            "title: Reference Topic",
            "title: Reference Topic\n",
        )
        self.write_raw("erp_docs/reference-topic.md", raw + "\n\n" + BODY)

        self.assertEqual(len(self.load().documents), 1)


class MetadataValidationTests(CorpusTestCase):
    def test_missing_required_field(self) -> None:
        self.write_document(title=None)
        error = self.assert_corpus_error("metadata")
        self.assertIn("title", error.message)

    def test_empty_required_field(self) -> None:
        self.write_document(title="   ")
        error = self.assert_corpus_error("metadata")
        self.assertIn("title", error.message)

    def test_unknown_front_matter_field(self) -> None:
        self.write_document(owner="kavinisha")
        error = self.assert_corpus_error("metadata")
        self.assertIn("owner", error.message)

    def test_duplicate_front_matter_field(self) -> None:
        raw = front_matter().replace(
            "doc_id: reference-topic",
            "doc_id: reference-topic\ndoc_id: duplicate",
        )
        self.write_raw("erp_docs/reference-topic.md", raw + "\n\n" + BODY)

        error = self.assert_corpus_error("front_matter")
        self.assertIn("duplicate", error.message)

    def test_malformed_front_matter_line(self) -> None:
        raw = "---\ndoc_id: reference-topic\nthis is not a key value\n---\n\n" + BODY
        self.write_raw("erp_docs/reference-topic.md", raw)

        error = self.assert_corpus_error("front_matter")
        self.assertEqual(error.details.get("line"), 3)

    def test_missing_opening_delimiter(self) -> None:
        raw = "doc_id: reference-topic\n---\n\n" + BODY
        self.write_raw("erp_docs/reference-topic.md", raw)

        error = self.assert_corpus_error("front_matter")
        self.assertEqual(error.details.get("line"), 1)

    def test_unclosed_front_matter(self) -> None:
        raw = "---\ndoc_id: reference-topic\ntitle: Reference Topic"
        self.write_raw("erp_docs/reference-topic.md", raw)

        self.assert_corpus_error("front_matter")

    def test_leading_blank_line_is_rejected(self) -> None:
        raw = "\n" + front_matter() + "\n\n" + BODY
        self.write_raw("erp_docs/reference-topic.md", raw)

        self.assert_corpus_error("front_matter")

    def test_blank_list_entry_is_rejected(self) -> None:
        self.write_document(tags="[testing, ]")
        error = self.assert_corpus_error("metadata")
        self.assertIn("tags", error.message)

    def test_unterminated_list_is_rejected(self) -> None:
        self.write_document(tags="[testing")
        error = self.assert_corpus_error("metadata")
        self.assertIn("tags", error.message)

    def test_invalid_updated_at(self) -> None:
        self.write_document(updated_at="not-a-date")
        error = self.assert_corpus_error("metadata")
        self.assertIn("updated_at", error.message)

    def test_invalid_version(self) -> None:
        self.write_document(version="1.0")
        error = self.assert_corpus_error("metadata")
        self.assertIn("version", error.message)

    def test_invalid_fact_kind(self) -> None:
        self.write_document(fact_kind="unknown")
        error = self.assert_corpus_error("metadata")
        self.assertIn("fact_kind", error.message)

    def test_invalid_doc_id_pattern(self) -> None:
        self.write_document(doc_id="1invalid")
        error = self.assert_corpus_error("metadata")
        self.assertIn("doc_id", error.message)

    def test_unknown_category_value(self) -> None:
        raw = front_matter(category="reports") + "\n\n" + BODY
        self.write_raw("erp_docs/reference-topic.md", raw)

        error = self.assert_corpus_error("category")
        self.assertIn("reports", error.message)
        for category in CATEGORIES:
            self.assertIn(category, error.message)

    def test_category_directory_mismatch(self) -> None:
        raw = front_matter(category="schema") + "\n\n" + BODY
        self.write_raw("erp_docs/reference-topic.md", raw)

        error = self.assert_corpus_error("category_mismatch")
        self.assertIn("schema", error.message)
        self.assertIn("erp_docs", error.message)

    def test_doc_id_must_match_file_stem(self) -> None:
        self.write_document(filename="other-topic.md")

        error = self.assert_corpus_error("doc_id_mismatch")
        self.assertIn("other-topic", error.message)

    def test_duplicate_doc_ids_are_rejected(self) -> None:
        self.write_document("erp_docs", "reference-topic")
        self.write_document("schema", "reference-topic")

        error = self.assert_corpus_error("duplicate_doc_id")
        self.assertIn("reference-topic", error.message)
        self.assertIn("schema/reference-topic.md", error.details.get("path", ""))


class StructureValidationTests(CorpusTestCase):
    def test_unknown_category_directory_is_rejected(self) -> None:
        self.write_raw("misc/notes.md", "not a document")

        error = self.assert_corpus_error("category")
        self.assertIn("misc", error.message)

    def test_document_outside_a_category_is_rejected(self) -> None:
        self.write_raw("stray.md", front_matter() + "\n\n" + BODY)

        error = self.assert_corpus_error("misplaced_document")
        self.assertEqual(error.details.get("path"), "stray.md")

    def test_nested_category_directories_are_rejected(self) -> None:
        self.write_raw("erp_docs/nested/reference-topic.md", "nested")

        error = self.assert_corpus_error("nested_directory")
        self.assertIn("nested", error.details.get("path", ""))

    def test_non_markdown_files_are_ignored(self) -> None:
        self.write_document()
        self.write_raw("erp_docs/notes.txt", "notes")

        self.assertEqual(len(self.load().documents), 1)

    def test_hidden_files_are_ignored(self) -> None:
        self.write_document()
        self.write_raw("erp_docs/.draft.md", "hidden")

        self.assertEqual(len(self.load().documents), 1)


class BoundsTests(CorpusTestCase):
    def test_document_count_limit(self) -> None:
        directory = self.root / "erp_docs"
        directory.mkdir()
        for index in range(MAX_DOCS + 1):
            (directory / f"doc-{index:03d}.md").write_bytes(b"---\n---\n")

        error = self.assert_corpus_error("max_documents")
        self.assertIn(str(MAX_DOCS), error.message)

    def test_document_count_at_limit_is_allowed(self) -> None:
        directory = self.root / "erp_docs"
        directory.mkdir()
        for index in range(MAX_DOCS):
            doc_id = f"doc-{index:03d}"
            raw = front_matter(doc_id=doc_id) + "\n\n" + SAFE_BODY
            (directory / f"{doc_id}.md").write_bytes(raw.encode("utf-8"))

        bundle = self.load()
        self.assertEqual(len(bundle.documents), MAX_DOCS)

    def test_corpus_byte_limit(self) -> None:
        directory = self.root / "erp_docs"
        directory.mkdir()
        (directory / "huge.md").write_bytes(b"x" * (MAX_CORPUS_BYTES + 1))

        error = self.assert_corpus_error("max_corpus_bytes")
        self.assertIn(str(MAX_CORPUS_BYTES), error.message)

    def test_document_body_limit(self) -> None:
        self.write_document(body="a" * (MAX_BODY_CHARS + 1))

        error = self.assert_corpus_error("max_document_chars")
        self.assertIn(str(MAX_BODY_CHARS), error.message)

    def test_document_body_at_limit_is_allowed(self) -> None:
        self.write_document(body="a" * MAX_BODY_CHARS)

        bundle = self.load()
        self.assertEqual(len(bundle.documents), 1)
        self.assertTrue(bundle.chunks)
        for chunk in bundle.chunks:
            self.assertLessEqual(len(chunk.text), 1200)

    def test_invalid_utf8_is_rejected(self) -> None:
        directory = self.root / "erp_docs"
        directory.mkdir()
        (directory / "reference-topic.md").write_bytes(b"---\n\xff\xfe\n---\n")

        self.assert_corpus_error("encoding")


class LiveFactLintTests(unittest.TestCase):
    def test_each_rule_detects_its_pattern(self) -> None:
        cases = {
            "L1": "The stored price is $12.50 today.",
            "L2": "The shelf holds 40 units.",
            "L3": "The catalogue lists 12 products.",
            "L4": "The current stock level is 55.",
            "L5": "Order #1042 was shipped.",
        }
        for rule, line in cases.items():
            with self.subTest(rule=rule):
                violations = find_live_fact_violations(line)
                self.assertEqual(len(violations), 1)
                self.assertEqual(violations[0].rule, rule)
                self.assertEqual(violations[0].line, 1)

    def test_inline_code_is_exempt(self) -> None:
        violations = find_live_fact_violations(
            "Read `on_hand_qty` and `12 units` from the schema."
        )
        self.assertEqual(violations, ())

    def test_fenced_code_is_not_exempt(self) -> None:
        text = "```sql\nSELECT * FROM stock WHERE on_hand_qty = 42;\n```"
        violations = find_live_fact_violations(text)

        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].rule, "L4")
        self.assertEqual(violations[0].line, 2)

    def test_allow_line_marker_exempts_a_line(self) -> None:
        text = "Price example: $12.50 <!-- rag-lint: allow-line -->"
        self.assertEqual(find_live_fact_violations(text), ())

    def test_line_numbers_are_reported_in_order(self) -> None:
        text = "Intro\n\nThe total is 90.\n\nOrder #1234 is late."
        violations = find_live_fact_violations(text)

        self.assertEqual([item.rule for item in violations], ["L4", "L5"])
        self.assertEqual([item.line for item in violations], [3, 5])

    def test_excerpt_is_bounded(self) -> None:
        text = "The total is 90 " + "x" * 200
        violations = find_live_fact_violations(text)

        self.assertEqual(len(violations), 1)
        self.assertLessEqual(len(violations[0].excerpt), 120)

    def test_conceptual_prose_is_clean(self) -> None:
        text = (
            "# Workflow\n\n"
            "Replenishment identifies products whose free stock is at or below\n"
            "the reorder level, then a purchase order is confirmed.\n"
        )
        self.assertEqual(find_live_fact_violations(text), ())

    def test_non_string_is_rejected(self) -> None:
        with self.assertRaises(TypeError):
            find_live_fact_violations(None)  # type: ignore[arg-type]


class LoaderLintTests(CorpusTestCase):
    def test_currency_blocks_the_document(self) -> None:
        error = self.assert_body_error(
            "live_fact:L1",
            "# Example\n\nThe stored price example is $12.50 for reference.",
        )
        self.assertIn("rag-lint: allow-line", error.message)
        self.assertGreater(error.details.get("line", 0), 11)

    def test_quantity_blocks_the_document(self) -> None:
        self.assert_body_error(
            "live_fact:L2",
            "# Example\n\nEach shelf holds 40 units during a normal shift.",
        )

    def test_count_blocks_the_document(self) -> None:
        self.assert_body_error(
            "live_fact:L3",
            "# Example\n\nThe catalogue currently lists 12 products in total.",
        )

    def test_stock_value_blocks_the_document(self) -> None:
        self.assert_body_error(
            "live_fact:L4",
            "# Example\n\nThe current stock level is 55 in this warehouse.",
        )

    def test_record_identifier_blocks_the_document(self) -> None:
        self.assert_body_error(
            "live_fact:L5",
            "# Example\n\nThe dispatch note refers to order #1042 directly.",
        )

    def test_inline_code_does_not_block_the_document(self) -> None:
        bundle = self.load_body(
            "# Schema\n\nRead `on_hand_qty` and `reserved_qty` from the stock "
            "table before computing free stock."
        )
        self.assertEqual(len(bundle.documents), 1)

    def test_fenced_sql_does_not_hide_values(self) -> None:
        self.assert_body_error(
            "live_fact:L4",
            "# Query\n\n```sql\nSELECT * FROM stock WHERE on_hand_qty = 42;\n```",
        )

    def test_allow_line_marker_permits_a_conceptual_example(self) -> None:
        bundle = self.load_body(
            "# Example\n\nA price like $12.50 is illustrative only. "
            "<!-- rag-lint: allow-line -->"
        )
        self.assertEqual(len(bundle.documents), 1)


class ChunkIntegrationTests(CorpusTestCase):
    def test_loader_matches_the_chunker(self) -> None:
        body = (
            "# Guide\n\n"
            "Introductory documentation text that explains the guide itself "
            "in a useful amount of detail.\n\n"
            "## Setup\n\n"
            "Setup documentation text that explains the initial configuration "
            "steps without recording any live business values.\n\n"
            "## Dispatch\n\n"
            "Dispatch documentation text that explains how a consignment "
            "leaves the warehouse and reaches the customer."
        )
        self.write_document(body=body)

        bundle = self.load(max_chunk_chars=400)
        expected = chunk_document(
            bundle.documents[0],
            max_chunk_chars=400,
            min_chunk_chars=0,
        )

        self.assertEqual(
            [chunk.chunk_id for chunk in bundle.chunks],
            [chunk.chunk_id for chunk in expected],
        )
        self.assertEqual(
            [chunk.text for chunk in bundle.chunks],
            [chunk.text for chunk in expected],
        )

    def test_chunks_inherit_document_metadata(self) -> None:
        self.write_document(fact_kind="policy", category="policies_faqs")

        bundle = self.load()
        for chunk in bundle.chunks:
            self.assertEqual(chunk.category, "policies_faqs")
            self.assertEqual(chunk.fact_kind, "policy")
            self.assertEqual(chunk.source_path, "policies_faqs/reference-topic.md")
            self.assertEqual(chunk.updated_at, date(2026, 11, 1))

    def test_multiple_documents_produce_ordered_chunks(self) -> None:
        self.write_document("erp_docs", "alpha-guide")
        self.write_document("schema", "beta-schema", fact_kind="schema")

        bundle = self.load()
        document_order = [document.doc_id for document in bundle.documents]
        chunk_order = []
        for chunk in bundle.chunks:
            if not chunk_order or chunk_order[-1] != chunk.doc_id:
                chunk_order.append(chunk.doc_id)

        self.assertEqual(chunk_order, document_order)

    def test_heading_only_document_is_rejected(self) -> None:
        error = self.assert_body_error(
            "no_chunks",
            "# Heading Only\n\n" + " " * 80,
        )
        self.assertIn("no meaningful chunks", error.message)

    def test_whitespace_only_body_is_rejected(self) -> None:
        self.assert_body_error("metadata", " " * 80)

    def test_too_short_body_is_rejected(self) -> None:
        error = self.assert_body_error("metadata", "# T\n\nshort")
        self.assertIn("40", error.message)

    def test_horizontal_rule_in_body_is_preserved(self) -> None:
        body = BODY + "\n\n---\n\nA closing note after the rule."
        self.write_document(body=body)

        bundle = self.load()
        combined = "\n".join(chunk.text for chunk in bundle.chunks)
        self.assertIn("A closing note after the rule.", combined)


class OrderingAndVersionTests(CorpusTestCase):
    def test_documents_are_sorted_by_source_path(self) -> None:
        self.write_document("schema", "zeta-schema", fact_kind="schema")
        self.write_document("erp_docs", "alpha-guide")
        self.write_document("erp_docs", "middle-guide")

        bundle = self.load()
        self.assertEqual(
            [document.source_path for document in bundle.documents],
            [
                "erp_docs/alpha-guide.md",
                "erp_docs/middle-guide.md",
                "schema/zeta-schema.md",
            ],
        )

    def test_repeated_loads_are_identical(self) -> None:
        self.write_document()

        first = self.load()
        second = self.load()

        self.assertEqual(first.index_version, second.index_version)
        self.assertEqual(
            [chunk.chunk_id for chunk in first.chunks],
            [chunk.chunk_id for chunk in second.chunks],
        )
        self.assertEqual(
            [chunk.text for chunk in first.chunks],
            [chunk.text for chunk in second.chunks],
        )

    def test_index_version_changes_with_content(self) -> None:
        self.write_document()
        first = self.load().index_version

        self.write_document(body=BODY.replace("documentation concept", "updated concept"))
        second = self.load().index_version

        self.assertNotEqual(first, second)
        self.assertEqual(len(second), 12)

    def test_index_version_changes_with_metadata(self) -> None:
        self.write_document()
        first = self.load().index_version

        self.write_document(title="Renamed Topic")
        second = self.load().index_version

        self.assertNotEqual(first, second)

    def test_index_version_ignores_document_order(self) -> None:
        self.write_document("erp_docs", "alpha-guide")
        self.write_document("schema", "beta-schema", fact_kind="schema")
        first = self.load()

        second = self.load()
        self.assertEqual(first.index_version, second.index_version)

    def test_index_version_for_empty_corpus(self) -> None:
        version = index_version_for(())
        self.assertEqual(len(version), 12)
        int(version, 16)
        self.assertEqual(version, index_version_for(()))


class EmptyAndMissingDirectoryTests(CorpusTestCase):
    def test_empty_directory_returns_an_empty_bundle(self) -> None:
        bundle = self.load()

        self.assertEqual(bundle.documents, ())
        self.assertEqual(bundle.chunks, ())
        self.assertEqual(bundle.index_version, index_version_for(()))
        self.assertEqual(bundle.index_version, self.load().index_version)

    def test_empty_category_directories_are_allowed(self) -> None:
        for category in CATEGORIES:
            (self.root / category).mkdir()

        self.assertEqual(self.load().documents, ())

    def test_missing_directory_is_rejected(self) -> None:
        with self.assertRaises(RagCorpusError) as context:
            load_corpus_from_dir(self.root / "missing")
        self.assertEqual(context.exception.details.get("rule"), "missing_directory")

    def test_directory_path_must_be_a_directory(self) -> None:
        path = self.root / "not-a-directory"
        path.write_text("x", encoding="utf-8")

        with self.assertRaises(RagCorpusError) as context:
            load_corpus_from_dir(path)
        self.assertEqual(context.exception.details.get("rule"), "missing_directory")

    def test_load_corpus_requires_a_config(self) -> None:
        with self.assertRaises(TypeError):
            load_corpus(self.root)  # type: ignore[arg-type]


class ErrorContractTests(CorpusTestCase):
    def test_corpus_errors_carry_actionable_details(self) -> None:
        self.write_document(title=None)
        error = self.assert_corpus_error("metadata")

        self.assertEqual(error.details.get("path"), "erp_docs/reference-topic.md")
        self.assertIn("line", error.details)
        self.assertIn("title", error.message)
        self.assertEqual(error.category.value, "internal")
        self.assertFalse(error.recoverable)

    def test_envelope_shape_is_preserved(self) -> None:
        self.write_document(title=None)
        error = self.assert_corpus_error("metadata")
        envelope = error.to_envelope()

        self.assertIs(envelope["ok"], False)
        self.assertEqual(
            set(envelope["error"]),
            {
                "code",
                "message",
                "category",
                "recoverable",
                "retryable",
                "details",
            },
        )

    def test_error_path_is_relative_to_the_corpus(self) -> None:
        self.write_document(body="# Example\n\nA price of $12.50 is shown.")
        error = self.assert_corpus_error("live_fact:L1")

        self.assertEqual(error.details.get("path"), "erp_docs/reference-topic.md")


if __name__ == "__main__":
    unittest.main()
