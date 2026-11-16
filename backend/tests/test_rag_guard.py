from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError

from backend.agent.rag import (
    CATEGORIES,
    GuardDecision,
    GuardReason,
    GuardVerdict,
    RagInvalidArgumentsError,
    classify_query,
)


def assert_blocked(
    test: unittest.TestCase,
    query: str,
    kind: str,
) -> GuardDecision:
    decision = classify_query(query)
    test.assertIs(decision.verdict, GuardVerdict.BLOCKED)
    test.assertIs(decision.reason, GuardReason.LIVE_FACT_REQUEST)
    test.assertEqual(decision.live_fact_kind, kind)
    test.assertFalse(decision.is_allowed)
    test.assertIsNotNone(decision.guidance)
    test.assertLessEqual(len(decision.guidance or ""), 1000)
    return decision


def assert_allowed(
    test: unittest.TestCase,
    query: str,
) -> GuardDecision:
    decision = classify_query(query)
    test.assertIs(decision.verdict, GuardVerdict.ALLOWED)
    test.assertTrue(decision.is_allowed)
    test.assertIsNone(decision.live_fact_kind)
    test.assertIsNone(decision.guidance)
    return decision


class AllowedDocumentationTests(unittest.TestCase):
    def test_definition_questions_are_allowed(self) -> None:
        cases = {
            "What does free stock mean?": "business_definitions",
            "Explain reserved stock.": "business_definitions",
            "How is free stock calculated?": "business_definitions",
            "What does dispatch status mean?": "business_definitions",
            "What are the sales order statuses?": "business_definitions",
            "Define the term reorder level.": "business_definitions",
            "Explain the difference between on-hand stock and reserved stock.": (
                "business_definitions"
            ),
            "What is the meaning of order status?": "business_definitions",
            "What does order status 'dispatched' mean?": (
                "business_definitions"
            ),
        }
        for query, category in cases.items():
            with self.subTest(query=query):
                decision = assert_allowed(self, query)
                self.assertIs(
                    decision.reason,
                    GuardReason.DOCUMENTATION_INTENT,
                )
                self.assertEqual(decision.suggested_category, category)

    def test_workflow_questions_are_allowed(self) -> None:
        cases = {
            "How does the purchase-to-stock workflow work?": "workflows",
            "Describe the stock adjustment process.": "workflows",
            "What are the steps in the sales order to dispatch process?": (
                "workflows"
            ),
            "Explain the order lifecycle.": "workflows",
            "What is the stock adjustment workflow?": "workflows",
        }
        for query, category in cases.items():
            with self.subTest(query=query):
                decision = assert_allowed(self, query)
                self.assertEqual(decision.suggested_category, category)

    def test_policy_questions_are_allowed(self) -> None:
        cases = {
            "What is the documentation policy for live data?": (
                "policies_faqs"
            ),
            "What is the rule about current stock in documentation?": (
                "policies_faqs"
            ),
            "Is documentation allowed to contain live values?": (
                "policies_faqs"
            ),
            "What is the invoice amount policy?": "policies_faqs",
        }
        for query, category in cases.items():
            with self.subTest(query=query):
                decision = assert_allowed(self, query)
                self.assertEqual(decision.suggested_category, category)

    def test_schema_questions_are_allowed(self) -> None:
        cases = {
            "What is the schema of the products table?": "schema",
            "Explain the columns of the sales order table.": "schema",
            "What is the data model for dispatches?": "schema",
            "Which foreign key links orders to customers?": "schema",
        }
        for query, category in cases.items():
            with self.subTest(query=query):
                decision = assert_allowed(self, query)
                self.assertEqual(decision.suggested_category, category)

    def test_documentation_object_questions_are_allowed(self) -> None:
        cases = (
            "Show me the stock documentation.",
            "Is there documentation about stock?",
            "Show me the documentation topics.",
            "Which guide explains free stock?",
            "Where is the page about dispatch status?",
        )
        for query in cases:
            with self.subTest(query=query):
                decision = assert_allowed(self, query)
                self.assertIs(
                    decision.reason,
                    GuardReason.DOCUMENTATION_INTENT,
                )

    def test_general_non_erp_question_is_allowed(self) -> None:
        decision = classify_query("Hello, how are you?")
        self.assertIs(decision.verdict, GuardVerdict.ALLOWED)
        self.assertIs(decision.reason, GuardReason.GENERAL_QUESTION)
        self.assertIsNone(decision.live_fact_kind)


class ConceptualQuestionsTests(unittest.TestCase):
    def test_conceptual_terms_are_allowed(self) -> None:
        cases = (
            "What is free stock?",
            "What is reserved stock?",
            "What is low stock?",
            "What is dispatch status?",
            "What is order status?",
            "What is a product?",
            "What is a SKU?",
            "What is an invoice?",
            "Tell me about stock.",
        )
        for query in cases:
            with self.subTest(query=query):
                decision = assert_allowed(self, query)
                self.assertIs(
                    decision.reason,
                    GuardReason.CONCEPTUAL_QUESTION,
                )
                self.assertEqual(
                    decision.suggested_category,
                    "business_definitions",
                )

    def test_concept_questions_with_explicit_live_markers_are_blocked(
        self,
    ) -> None:
        cases = {
            "What is the current free stock?": "quantity",
            "What is our reserved stock?": "quantity",
            "What is the free stock level?": "quantity",
        }
        for query, kind in cases.items():
            with self.subTest(query=query):
                assert_blocked(self, query, kind)


class BlockedLiveFactTests(unittest.TestCase):
    def test_quantity_questions_are_blocked(self) -> None:
        cases = (
            "What is the current stock level of product X?",
            "How much stock is available right now?",
            "What is our free stock?",
            "What is the on-hand quantity for product A?",
            "Is product X in stock?",
            "How much inventory do we have?",
        )
        for query in cases:
            with self.subTest(query=query):
                assert_blocked(self, query, "quantity")

    def test_count_questions_are_blocked(self) -> None:
        cases = (
            "How many products do we have?",
            "What is the number of open invoices?",
            "Count the customers.",
            "What is the total number of sales orders?",
        )
        for query in cases:
            with self.subTest(query=query):
                assert_blocked(self, query, "count")

    def test_money_questions_are_blocked(self) -> None:
        cases = (
            "What is the total sales this month?",
            "What is the price of product X?",
            "What is the invoice amount?",
            "How much do we owe supplier A?",
            "What is the outstanding balance?",
            "Show me the revenue total.",
        )
        for query in cases:
            with self.subTest(query=query):
                assert_blocked(self, query, "money")

    def test_record_and_personal_data_questions_are_blocked(self) -> None:
        cases = (
            "Show me invoice INV-1001 amount.",
            "Find customer 12345.",
            "What is the phone number of customer 12345?",
            "Give me the details of product SKU-123.",
        )
        for query in cases:
            with self.subTest(query=query):
                assert_blocked(self, query, "record_lookup")

    def test_listing_questions_are_blocked(self) -> None:
        cases = (
            "List customers in Colombo.",
            "Show me all open orders.",
            "Do we have any products?",
            "Which products are low stock?",
            "Display the current orders.",
        )
        for query in cases:
            with self.subTest(query=query):
                assert_blocked(self, query, "listing")

    def test_status_questions_are_blocked(self) -> None:
        cases = (
            "What is the status of order SO-1001?",
            "What is the current dispatch status?",
            "When will my order be delivered?",
            "Is the invoice paid?",
            "What is the order status?",
            "Where is shipment SHP-77?",
        )
        for query in cases:
            with self.subTest(query=query):
                assert_blocked(self, query, "status")

    def test_blocked_guidance_names_the_erp_tools(self) -> None:
        decision = classify_query("What is the current stock level?")
        self.assertIn("ERP", decision.guidance or "")


class AmbiguousTests(unittest.TestCase):
    def test_mixed_live_and_documentation_questions_are_ambiguous(self) -> None:
        cases = {
            "What is the current stock level and what does free stock mean?": (
                "quantity"
            ),
            "Explain the sales order workflow and show me all open orders.": (
                "listing"
            ),
            "List products and explain SKUs.": "listing",
            "What is the current invoice amount policy?": "money",
            "Describe the dispatch process and give me the status of SO-1001.": (
                "status"
            ),
        }
        for query, kind in cases.items():
            with self.subTest(query=query):
                decision = classify_query(query)
                self.assertIs(decision.verdict, GuardVerdict.AMBIGUOUS)
                self.assertIs(decision.reason, GuardReason.MIXED_INTENT)
                self.assertEqual(decision.live_fact_kind, kind)
                self.assertIsNotNone(decision.guidance)
                self.assertIn("separately", decision.guidance or "")

    def test_domain_without_intent_is_ambiguous(self) -> None:
        cases = (
            "stock",
            "products",
            "order status",
            "inventory",
        )
        for query in cases:
            with self.subTest(query=query):
                decision = classify_query(query)
                self.assertIs(decision.verdict, GuardVerdict.AMBIGUOUS)
                self.assertIs(
                    decision.reason,
                    GuardReason.UNSPECIFIED_DOMAIN,
                )
                self.assertIsNotNone(decision.guidance)

    def test_ambiguous_decision_records_no_suggested_category(self) -> None:
        decision = classify_query("stock")
        self.assertIsNone(decision.suggested_category)


class DecisionStructureTests(unittest.TestCase):
    def test_enums_are_stable_strings(self) -> None:
        self.assertEqual(GuardVerdict.ALLOWED.value, "allowed")
        self.assertEqual(GuardVerdict.BLOCKED.value, "blocked")
        self.assertEqual(GuardVerdict.AMBIGUOUS.value, "ambiguous")
        self.assertEqual(
            GuardReason.DOCUMENTATION_INTENT.value,
            "documentation_intent",
        )
        self.assertEqual(
            GuardReason.CONCEPTUAL_QUESTION.value,
            "conceptual_question",
        )
        self.assertEqual(
            GuardReason.LIVE_FACT_REQUEST.value,
            "live_fact_request",
        )
        self.assertEqual(GuardReason.MIXED_INTENT.value, "mixed_intent")
        self.assertEqual(
            GuardReason.UNSPECIFIED_DOMAIN.value,
            "unspecified_domain",
        )
        self.assertEqual(
            GuardReason.GENERAL_QUESTION.value,
            "general_question",
        )

    def test_decision_is_frozen(self) -> None:
        decision = classify_query("What does free stock mean?")
        with self.assertRaises(FrozenInstanceError):
            decision.verdict = GuardVerdict.BLOCKED  # type: ignore[misc]

    def test_decision_fields_are_typed_and_bounded(self) -> None:
        decision = classify_query(
            "Explain the sales order workflow and show me all open orders."
        )
        self.assertIsInstance(decision.verdict, GuardVerdict)
        self.assertIsInstance(decision.reason, GuardReason)
        self.assertIsInstance(decision.signals, tuple)
        self.assertLessEqual(len(decision.signals), 8)
        self.assertEqual(len(decision.signals), len(set(decision.signals)))
        for signal in decision.signals:
            self.assertIsInstance(signal, str)
            self.assertTrue(signal)
        if decision.suggested_category is not None:
            self.assertIn(decision.suggested_category, CATEGORIES)

    def test_allowed_decision_has_no_guidance(self) -> None:
        decision = classify_query("Explain the purchase workflow.")
        self.assertIsNone(decision.guidance)

    def test_blocked_decision_always_has_a_kind_and_guidance(self) -> None:
        decision = classify_query("How many products are there?")
        self.assertIsNotNone(decision.live_fact_kind)
        self.assertIsNotNone(decision.guidance)
        self.assertIn(decision.live_fact_kind or "", {
            "quantity",
            "count",
            "money",
            "status",
            "record_lookup",
            "listing",
        })


class KnownLimitationTests(unittest.TestCase):
    def test_unqualified_value_policy_question_is_conservatively_mixed(
        self,
    ) -> None:
        # Documented false positive: the temporal value phrase makes this
        # mixed even though the user may want policy documentation. Adding
        # "in documentation" makes the documentation intent explicit.
        decision = classify_query("What is the current stock policy?")
        self.assertIs(decision.verdict, GuardVerdict.AMBIGUOUS)
        self.assertIs(decision.reason, GuardReason.MIXED_INTENT)

        explicit = classify_query(
            "What is the rule about current stock in documentation?"
        )
        self.assertIs(explicit.verdict, GuardVerdict.ALLOWED)


class ValidationTests(unittest.TestCase):
    def test_empty_and_whitespace_queries_are_rejected(self) -> None:
        for query in ("", "   ", "\n\t"):
            with self.subTest(query=repr(query)):
                with self.assertRaises(RagInvalidArgumentsError) as caught:
                    classify_query(query)
                self.assertEqual(caught.exception.code, "rag_invalid_arguments")
                self.assertEqual(
                    caught.exception.details.get("field"),
                    "query",
                )

    def test_multiline_query_is_rejected(self) -> None:
        with self.assertRaises(RagInvalidArgumentsError):
            classify_query("first line\nsecond line")

    def test_too_long_query_is_rejected(self) -> None:
        with self.assertRaises(RagInvalidArgumentsError):
            classify_query("x" * 301)

    def test_non_string_query_is_rejected(self) -> None:
        for query in (None, 3, ("query",), b"bytes"):
            with self.subTest(query=repr(query)):
                with self.assertRaises(RagInvalidArgumentsError):
                    classify_query(query)  # type: ignore[arg-type]


class DeterminismTests(unittest.TestCase):
    def test_repeated_classifications_are_identical(self) -> None:
        queries = (
            "What does free stock mean?",
            "What is the current stock level?",
            "Explain the workflow and show me all orders.",
            "stock",
            "Hello there.",
        )
        for query in queries:
            with self.subTest(query=query):
                first = classify_query(query)
                second = classify_query(query)
                self.assertEqual(first, second)

    def test_classification_is_case_and_punctuation_insensitive(self) -> None:
        first = classify_query("What does free stock mean?")
        second = classify_query("  WHAT DOES 'FREE-STOCK' MEAN!!  ")
        self.assertEqual(first.verdict, second.verdict)
        self.assertEqual(first.reason, second.reason)

    def test_input_query_is_not_mutated(self) -> None:
        query = "  What does free stock mean?  "
        original = query
        classify_query(query)
        self.assertEqual(query, original)


if __name__ == "__main__":
    unittest.main()
