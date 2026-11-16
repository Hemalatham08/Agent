from __future__ import annotations

import unittest

from backend.agent.rag import STOPWORDS, normalize, slugify, tokenize


class NormalizeTests(unittest.TestCase):
    def test_underscores_become_separators(self) -> None:
        self.assertEqual(normalize("on_hand_qty"), "on hand qty")

    def test_slashes_dots_and_hyphens_become_separators(self) -> None:
        self.assertEqual(normalize("Café / Bar-Baz.v2"), "cafe bar baz v2")

    def test_case_is_folded(self) -> None:
        self.assertEqual(normalize("Low STOCK"), "low stock")

    def test_punctuation_is_removed(self) -> None:
        self.assertEqual(normalize("what is a SKU?"), "what is a sku")
        self.assertEqual(normalize("e.g. item"), "e g item")
        self.assertEqual(normalize("(alpha) [beta] {gamma}"), "alpha beta gamma")

    def test_accents_are_folded_to_ascii(self) -> None:
        self.assertEqual(normalize("Résumé naïve"), "resume naive")

    def test_apostrophes_split_tokens(self) -> None:
        self.assertEqual(normalize("don't"), "don t")

    def test_empty_and_whitespace(self) -> None:
        self.assertEqual(normalize(""), "")
        self.assertEqual(normalize("   \n\t "), "")

    def test_non_string_rejected(self) -> None:
        with self.assertRaises(TypeError):
            normalize(None)  # type: ignore[arg-type]

    def test_repeated_calls_are_identical(self) -> None:
        text = "Dispatch_Status and On-Hand Qty"
        self.assertEqual(normalize(text), normalize(text))


class TokenizeTests(unittest.TestCase):
    def test_stopwords_removed(self) -> None:
        self.assertEqual(tokenize("the and of to a"), [])

    def test_one_character_tokens_removed(self) -> None:
        self.assertEqual(tokenize("a i x 1"), [])

    def test_pure_numbers_removed(self) -> None:
        self.assertEqual(tokenize("2024 5 10 1000"), [])

    def test_punctuation_and_underscores(self) -> None:
        self.assertEqual(
            tokenize("products, dispatches; invoices."),
            ["product", "dispatch", "invoice"],
        )
        self.assertEqual(tokenize("on_hand_qty"), ["hand", "qty"])

    def test_plural_normalization(self) -> None:
        self.assertEqual(tokenize("orders"), ["order"])
        self.assertEqual(tokenize("categories"), ["category"])
        self.assertEqual(tokenize("dispatches"), ["dispatch"])
        self.assertEqual(tokenize("invoices"), ["invoice"])
        self.assertEqual(tokenize("sales"), ["sale"])

    def test_singular_words_are_not_stripped(self) -> None:
        self.assertEqual(
            tokenize("status business class analysis"),
            ["status", "business", "class", "analysis"],
        )

    def test_mixed_text(self) -> None:
        self.assertEqual(
            tokenize("The orders are in the warehouse"),
            ["order", "warehouse"],
        )

    def test_empty_and_stopword_only(self) -> None:
        self.assertEqual(tokenize(""), [])
        self.assertEqual(tokenize("   "), [])
        self.assertEqual(tokenize("what is it"), [])

    def test_non_string_rejected(self) -> None:
        with self.assertRaises(TypeError):
            tokenize(None)  # type: ignore[arg-type]

    def test_determinism(self) -> None:
        text = "Low stock levels for warehouses and dispatches"
        first = tokenize(text)
        second = tokenize(text)
        self.assertEqual(first, second)
        self.assertEqual(first, tokenize(text.upper()))

    def test_preserves_order_and_duplicates(self) -> None:
        self.assertEqual(tokenize("stock stock level"), ["stock", "stock", "level"])


class StopwordTests(unittest.TestCase):
    def test_stopwords_is_immutable_set(self) -> None:
        self.assertIsInstance(STOPWORDS, frozenset)

    def test_expected_words(self) -> None:
        for word in ("the", "and", "how", "is", "what", "with"):
            with self.subTest(word=word):
                self.assertIn(word, STOPWORDS)

    def test_domain_terms_are_not_stopwords(self) -> None:
        for word in ("stock", "product", "dispatch", "warehouse", "invoice"):
            with self.subTest(word=word):
                self.assertNotIn(word, STOPWORDS)


class SlugifyTests(unittest.TestCase):
    def test_basic_slug(self) -> None:
        self.assertEqual(slugify("Low Stock and Reorder Level"), "low-stock-and-reorder-level")

    def test_punctuation_collapses(self) -> None:
        self.assertEqual(slugify("Low Stock!"), "low-stock")
        self.assertEqual(slugify("A/B Test"), "a-b-test")
        self.assertEqual(slugify("on_hand_qty"), "on-hand-qty")

    def test_accents_folded(self) -> None:
        self.assertEqual(slugify("Café Operations"), "cafe-operations")

    def test_empty_returns_overview(self) -> None:
        self.assertEqual(slugify(""), "overview")
        self.assertEqual(slugify("   "), "overview")
        self.assertEqual(slugify("!!!"), "overview")
        self.assertEqual(slugify("---"), "overview")

    def test_max_length_truncates_without_trailing_hyphen(self) -> None:
        self.assertEqual(slugify("abcdefghij", max_len=5), "abcde")
        self.assertEqual(slugify("abc def", max_len=4), "abc")
        self.assertEqual(slugify("ab cd ef", max_len=5), "ab-cd")

    def test_single_character_limit(self) -> None:
        self.assertEqual(slugify("a b c", max_len=1), "a")

    def test_invalid_max_length(self) -> None:
        for value in (0, -1, True, "5"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    slugify("text", max_len=value)  # type: ignore[arg-type]

    def test_non_string_rejected(self) -> None:
        with self.assertRaises(TypeError):
            slugify(None)  # type: ignore[arg-type]

    def test_deterministic(self) -> None:
        text = "Dispatch & Delivery Status"
        self.assertEqual(slugify(text), slugify(text))


if __name__ == "__main__":
    unittest.main()
