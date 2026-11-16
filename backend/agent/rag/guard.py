"""Deterministic, offline guard against live-ERP questions reaching RAG.

The guard is a **heuristic classifier**, not a semantic safety mechanism. It
looks for explicit signals that a question asks for a current business value
(quantity, count, money, status, record, or listing) and for signals that it
asks about documentation (definition, workflow, policy, schema). It never
claims complete coverage: paraphrases, multilingual text, and unusual phrasing
can evade it.

Classification order
--------------------
1. A hard live-fact signal (record identifier, count question, ``how much``,
   presence question, listing verb, temporal or possessive value request,
   status/tracking phrase, total/sum request, measurement-of-entity) is
   detected.
2. A genuine documentation marker (meaning, explain, workflow, policy, schema,
   documentation) makes a hard live request **ambiguous** instead of blocked.
   The retriever treats ambiguous conservatively: no documentation is returned.
3. Otherwise a hard live request is **blocked**.
4. With no hard signal, a documentation marker allows the question.
5. A bare "value-like" phrase (``invoice amount``, ``stock level``) is blocked.
6. A definition frame such as ``what is free stock`` is allowed as a
   conceptual question; a domain term with no intent at all is ambiguous.

Known limitations and risks
---------------------------
* False positives: policy or workflow questions that mention a live noun and a
  temporal word (``current stock policy``) are classified as mixed and blocked
  conservatively. The caller should rephrase or ask a more specific question.
* False negatives: a question can ask for live data without any listed signal
  (for example a bare record identifier without a prefix, or an indirect
  paraphrase). The orchestrator's ERP evidence requirement remains the final
  grounding layer, so RAG output can never satisfy an ERP-evidence obligation.
* Non-English text, slang, and deliberate obfuscation are not handled.
* The guard examines surface patterns only; it does not understand the
  business meaning of a question.

The implementation is pure Python, deterministic, and touches no filesystem,
network, database, LLM, or orchestrator code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from backend.agent.rag.config import MAX_QUERY_CHARS
from backend.agent.rag.errors import RagInvalidArgumentsError
from backend.agent.rag.models import Category, LiveFactKind


class GuardVerdict(str, Enum):
    """Outcome of the live-fact guard."""

    ALLOWED = "allowed"
    BLOCKED = "blocked"
    AMBIGUOUS = "ambiguous"


class GuardReason(str, Enum):
    """Stable, machine-readable reason for a guard verdict."""

    DOCUMENTATION_INTENT = "documentation_intent"
    CONCEPTUAL_QUESTION = "conceptual_question"
    LIVE_FACT_REQUEST = "live_fact_request"
    MIXED_INTENT = "mixed_intent"
    UNSPECIFIED_DOMAIN = "unspecified_domain"
    GENERAL_QUESTION = "general_question"


@dataclass(frozen=True)
class GuardDecision:
    """Structured guard outcome.

    ``live_fact_kind`` is set whenever a live-fact signal was detected, even if
    the verdict is ambiguous. ``suggested_category`` is advisory only; the
    retriever never applies it implicitly.
    """

    verdict: GuardVerdict
    reason: GuardReason
    live_fact_kind: LiveFactKind | None = None
    suggested_category: Category | None = None
    guidance: str | None = None
    signals: tuple[str, ...] = ()

    @property
    def is_allowed(self) -> bool:
        return self.verdict is GuardVerdict.ALLOWED


GUIDANCE_BY_KIND: dict[LiveFactKind, str] = {
    "quantity": (
        "This question asks for a current quantity or stock level. Use the ERP "
        "inventory tools to read live values; documentation only explains the "
        "concepts."
    ),
    "count": (
        "This question asks for a current record count. Use the ERP tools to "
        "count live records; documentation only explains what the entities "
        "mean."
    ),
    "money": (
        "This question asks for a live amount, total, or price. Use the ERP "
        "tools for financial values; documentation only explains the terms."
    ),
    "status": (
        "This question asks for the current status of a specific record. Use "
        "the ERP tools to read live status; documentation only explains what "
        "each status label means."
    ),
    "record_lookup": (
        "This question looks up a specific record or personal data. Use the "
        "ERP tools for live records; documentation never contains customer or "
        "operational records."
    ),
    "listing": (
        "This question asks for a live list of records. Use the ERP tools to "
        "query current records; documentation only explains concepts, "
        "workflows, policies, and schema."
    ),
}

MIXED_INTENT_GUIDANCE = (
    "This question mixes a documentation request with a request for live ERP "
    "data. Ask about the definition, workflow, policy, or schema separately, "
    "and use the ERP tools for the live values."
)

UNSPECIFIED_DOMAIN_GUIDANCE = (
    "This question mentions an ERP domain but does not say whether it asks for "
    "a definition or a live value. Rephrase it as a definition, workflow, "
    "policy, or schema question, or use the ERP tools for a live value."
)

_MAX_SIGNALS = 8
_NON_ALNUM = re.compile(r"[^a-z0-9]+")

# Business entities, measurements, and money terms. These are deliberately
# narrow enough that ordinary prose does not trip them.
_ENTITY = re.compile(
    r"\b(?:products?|skus?|orders?|sales orders?|purchase orders?|invoices?|"
    r"customers?|suppliers?|dispatches?|shipments?|deliver(?:y|ies)|items?|"
    r"records?|users?|employees?|stock items?|inventory items?)\b"
)
_PLURAL_ENTITY = re.compile(
    r"\b(?:products|skus|orders|sales orders|purchase orders|invoices|"
    r"customers|suppliers|dispatches|shipments|deliveries|items|records|"
    r"users|employees)\b"
)
_MEASUREMENT = re.compile(
    r"\b(?:stock|inventory|quantit(?:y|ies)|qty|on hand|free stock|"
    r"reserved stock|available stock|reorder level|low stock|stock levels?|"
    r"balance|amounts?|totals?|count)\b"
)
_MONEY = re.compile(
    r"\b(?:revenue|profit|margin|prices?|costs?|invoice amounts?|"
    r"invoice totals?|amount due|outstanding balance|balance due|payments?|"
    r"tax|total sales|sales totals?|sales revenue|total revenue|"
    r"revenue total|sales figures?|sales numbers?)\b"
)
_DOMAIN = re.compile(
    r"\b(?:stock|inventory|quantit(?:y|ies)|qty|on hand|free stock|"
    r"reserved stock|available stock|reorder level|low stock|stock levels?|"
    r"balance|amounts?|totals?|count|sales|revenue|profit|margin|prices?|"
    r"costs?|invoice amounts?|invoice totals?|amount due|outstanding balance|"
    r"balance due|payments?|tax|products?|skus?|orders?|sales orders?|"
    r"purchase orders?|invoices?|customers?|suppliers?|dispatches?|"
    r"shipments?|deliver(?:y|ies)|items?|records?|users?|employees?|"
    r"status|statuses|state|stage)\b"
)

_RECORD_ID = re.compile(
    r"\b(?:so|inv|po|dsp|ord|sku|prod|cust|sup|emp|pay)\s?\d{2,}\b"
    r"|\b(?:order|invoice|dispatch|delivery|receipt|customer|supplier|product|"
    r"sku|purchase order|sales order)\s+(?:no|number|num|id)?\s*[a-z0-9]*\d{2,}\b"
)

_STATUS_WORD = re.compile(r"\b(?:status|statuses|state|stage)\b")
_TRACKING_WORD = re.compile(
    r"\b(?:track|tracking|delivered|dispatched|shipped|paid|overdue|arrived)\b"
)
_STATUS_OF = re.compile(
    r"\b(?:status|statuses|state|stage)\s+(?:of|for)\s+"
    r"(?:the\s+|our\s+|my\s+|this\s+|that\s+)?"
    r"(?:orders?|invoices?|dispatches?|shipments?|deliver(?:y|ies)|payments?|"
    r"customers?|products?|stock|inventory|free stock|reserved stock)\b"
)
_ARTICLE_STATUS = re.compile(
    r"\b(?:the|our|my|this|that)\s+(?:orders?|invoices?|dispatches?|shipments?|"
    r"deliver(?:y|ies)|payments?)\s+(?:status|state|stage)\b"
)
_STATUS_TEMPORAL = re.compile(
    r"\b(?:current|currently|now|latest|today|live|actual)\b(?:\s+\w+){0,2}\s+"
    r"(?:status|state|stage)\b"
)
_TRACKING = re.compile(
    r"\b(?:where is|where are|when will|when did)\b.{0,50}\b(?:orders?|"
    r"invoices?|dispatches?|shipments?|deliver(?:y|ies)|payments?)\b"
    r"|\b(?:has|have)\b.{0,30}\b(?:orders?|invoices?|dispatches?|shipments?|"
    r"deliver(?:y|ies)|payments?)\b.{0,20}\b(?:been|shipped|delivered|"
    r"dispatched|paid|arrived)\b"
)
_IN_STOCK = re.compile(
    r"\b(?:is|are)\b.{0,40}\b(?:in stock|out of stock|available|unavailable)\b"
)

_COUNT_QUERY = re.compile(
    r"\b(?:how many|number of|count of|count the|total number of|"
    r"total count of)\b"
)
_HOW_MUCH = re.compile(r"\bhow much\b")
_MONEY_VERB = re.compile(
    r"\b(?:owe|owed|cost|costs|paid|pay|spend|spent|earn|earned|sell|sold|"
    r"outstanding)\b"
)

_MONEY_OF_DOMAIN = re.compile(
    r"\b(?:prices?|costs?|value|amount|balance|total|revenue|profit|margin)\b"
    r"\s+(?:of|for)\s+(?:the\s+|our\s+|my\s+)?"
    r"(?:products?|skus?|orders?|invoices?|customers?|suppliers?|stock|"
    r"inventory|items?|purchase orders?|sales orders?)\b"
)
_TOTAL_TARGET = re.compile(
    r"\b(?:total|sum|average|avg|min|max|aggregate)\b(?:\s+\w+){0,2}\s+"
    r"(?:stock|inventory|quantit(?:y|ies)|qty|sales|revenue|prices?|costs?|"
    r"amounts?|balances?|profit|margin|invoices?|count)\b"
)
_SALES_PERIOD = re.compile(
    r"\b(?:sales|revenue|profit|orders|invoices)\b.{0,20}\b(?:this|last|"
    r"current|today|week|month|year|quarter)\b"
    r"|\b(?:this|last|current|today|yesterday)\b(?:\s+\w+){0,2}\s+"
    r"(?:sales|revenue|profit)\b"
)
_TEMPORAL_TARGET = re.compile(
    r"\b(?:current|currently|now|right now|today|tonight|latest|live|present|"
    r"actual|as of|open|pending|recent)\b(?:\s+\w+){0,2}\s+"
    r"(?:stock|inventory|quantit(?:y|ies)|qty|on hand|free stock|reserved stock|"
    r"available stock|reorder level|low stock|stock levels?|balance|amounts?|"
    r"totals?|prices?|costs?|revenue|profit|margin|invoice amounts?|"
    r"invoice totals?|sales totals?|total sales|products|skus|orders|invoices|"
    r"customers|suppliers|dispatches|shipments|deliveries|items|records|users|"
    r"employees)\b"
)
_POSSESSIVE_MONEY = re.compile(
    r"\b(?:our|my|your)\b(?:\s+\w+){0,2}\s+(?:revenue|profit|prices?|costs?|"
    r"amounts?|balances?|totals?|invoice amounts?|invoice totals?|payments?)\b"
)
_POSSESSIVE_DOMAIN = re.compile(
    r"\b(?:our|my|your)\b(?:\s+\w+){0,2}\s+(?:stock|inventory|"
    r"quantit(?:y|ies)|qty|on hand|free stock|reserved stock|available stock|"
    r"reorder level|low stock|stock levels?|products|skus|orders|invoices|"
    r"customers|suppliers|dispatches|shipments|deliveries|items|records|"
    r"users|employees)\b"
)
_MEASUREMENT_OF_ENTITY = re.compile(
    r"\b(?:stock|inventory|quantit(?:y|ies)|qty|on hand|free stock|"
    r"reserved stock|available stock|balance|amount|total)\b\s+(?:of|for)\s+"
    r"(?:the\s+|our\s+|my\s+)?(?:products?|skus?|orders?|invoices?|"
    r"customers?|suppliers?|items?|purchase orders?|sales orders?)\b"
)
_MEASUREMENT_COMPOUND = re.compile(
    r"\b(?:stock|inventory|quantit(?:y|ies)|qty|on hand|free stock|"
    r"reserved stock|available stock|reorder level|low stock)\s+"
    r"(?:levels?|quantit(?:y|ies)|amounts?|values?|counts?|balances?|totals?)\b"
)
_PRESENCE = re.compile(
    r"\b(?:do we have|do we currently have|have we got|is there|are there|"
    r"do you have)\b"
)
_LIST_VERB = re.compile(
    r"\b(?:list|show|display|give me|enumerate|dump|export|which)\b"
)

_DOC_PATTERNS: tuple[tuple[Category, str, re.Pattern[str]], ...] = (
    (
        "schema",
        "schema_terms",
        re.compile(
            r"\b(?:schemas?|table structure|data model|entity relationship|"
            r"primary key|foreign key|database tables?|table definitions?|"
            r"column definitions?|columns?|fields?)\b"
        ),
    ),
    (
        "workflows",
        "workflow_terms",
        re.compile(
            r"\b(?:workflows?|process(?:es)?|procedures?|steps?|lifecycle|"
            r"sequence of (?:steps|events)|how (?:does|do) .{0,60} work)\b"
        ),
    ),
    (
        "policies_faqs",
        "policy_terms",
        re.compile(
            r"\b(?:polic(?:y|ies)|rules?|faqs?|frequently asked|guidelines?|"
            r"allowed|permitted|governance)\b"
        ),
    ),
    (
        "business_definitions",
        "definition_terms",
        re.compile(
            r"\b(?:meanings?|means?|meant|definitions?|define|defined|"
            r"concepts?|difference between|explain|explanation|calculations?|"
            r"calculated|formula|statuses|labels?)\b"
            r"|\bwhat does .{0,80} mean\b"
        ),
    ),
    (
        "erp_docs",
        "documentation_terms",
        re.compile(
            r"\b(?:documentation|docs|doc|guides?|articles?|manual|pages?|"
            r"knowledge base|overview|modules?|features?|reference)\b"
        ),
    ),
)

_DOCS_OBJECT = re.compile(
    r"\b(?:documentation|docs|doc|knowledge base|guides?|manual|articles?|"
    r"pages?|reference)\b"
)
_WEAK_FRAME = re.compile(r"\b(?:what is|what are|what s|tell me about)\b")
_CONCEPT_TERM = re.compile(
    r"\b(?:free stock|reserved stock|on hand stock|available stock|low stock|"
    r"reorder level|dispatch status|order status|sales order status|"
    r"invoice status|payment status|stock adjustment|stock items?|"
    r"stock|inventory|warehouse|products?|skus?|orders?|invoices?|"
    r"purchase orders?|sales orders?|dispatches?|deliver(?:y|ies)|"
    r"customers?|suppliers?|business definitions?|schemas?|workflows?|"
    r"polic(?:y|ies)|status|statuses)\b"
)


def _clean(text: str) -> str:
    return _NON_ALNUM.sub(" ", text.lower()).strip()


def _require_query(query: object) -> str:
    if not isinstance(query, str):
        raise RagInvalidArgumentsError("query", "query must be a string")
    stripped = query.strip()
    if not stripped:
        raise RagInvalidArgumentsError("query", "query must not be empty")
    if "\n" in stripped or "\r" in stripped:
        raise RagInvalidArgumentsError("query", "query must be a single line")
    if len(stripped) > MAX_QUERY_CHARS:
        raise RagInvalidArgumentsError(
            "query",
            f"query must be at most {MAX_QUERY_CHARS} characters",
        )
    return stripped


def _detect_live_fact(
    text: str,
    *,
    tracking_fallback: bool = True,
) -> tuple[LiveFactKind | None, tuple[str, ...], frozenset[str]]:
    """Return ``(kind, signals, hard_markers)`` for a cleaned query."""

    signals: list[str] = []

    if _RECORD_ID.search(text):
        signals.append("record_identifier")
        if _STATUS_WORD.search(text) or _TRACKING_WORD.search(text):
            return "status", tuple(signals), frozenset({"status"})
        return "record_lookup", tuple(signals), frozenset({"record"})

    if (
        _STATUS_OF.search(text)
        or _ARTICLE_STATUS.search(text)
        or _STATUS_TEMPORAL.search(text)
        or _TRACKING.search(text)
    ):
        signals.append("status_reference")
        return "status", tuple(signals), frozenset({"status"})
    if tracking_fallback and _TRACKING_WORD.search(text) and _ENTITY.search(text):
        signals.append("tracking_word")
        return "status", tuple(signals), frozenset({"status"})
    if _IN_STOCK.search(text):
        signals.append("availability_phrase")
        return "quantity", tuple(signals), frozenset({"availability"})

    if _COUNT_QUERY.search(text) and (
        _ENTITY.search(text) or _MEASUREMENT.search(text) or _MONEY.search(text)
    ):
        signals.append("count_question")
        return "count", tuple(signals), frozenset({"count"})

    if _HOW_MUCH.search(text):
        if _MONEY.search(text) or _MONEY_VERB.search(text):
            signals.append("how_much_money")
            return "money", tuple(signals), frozenset({"how_much"})
        if _MEASUREMENT.search(text) or _ENTITY.search(text):
            signals.append("how_much_quantity")
            return "quantity", tuple(signals), frozenset({"how_much"})

    if _PRESENCE.search(text) and (
        _ENTITY.search(text) or _MEASUREMENT.search(text)
    ):
        signals.append("presence_question")
        kind: LiveFactKind = (
            "quantity" if _MEASUREMENT.search(text) else "listing"
        )
        return kind, tuple(signals), frozenset({"presence"})

    if _LIST_VERB.search(text):
        if "which" in text and _PLURAL_ENTITY.search(text):
            signals.append("which_entity")
            return "listing", tuple(signals), frozenset({"listing"})
        if _ENTITY.search(text) or _MEASUREMENT.search(text) or _MONEY.search(text):
            signals.append("listing_verb")
            if _MONEY.search(text):
                kind = "money"
            elif _MEASUREMENT.search(text) and not _ENTITY.search(text):
                kind = "quantity"
            else:
                kind = "listing"
            return kind, tuple(signals), frozenset({"listing"})

    if (
        _MONEY_OF_DOMAIN.search(text)
        or _TOTAL_TARGET.search(text)
        or _SALES_PERIOD.search(text)
        or _POSSESSIVE_MONEY.search(text)
    ):
        signals.append("money_request")
        return "money", tuple(signals), frozenset({"money"})

    temporal = _TEMPORAL_TARGET.search(text)
    if temporal is not None:
        signals.append("temporal_value")
        matched = temporal.group(0)
        if any(
            word in matched
            for word in (
                "revenue",
                "profit",
                "price",
                "cost",
                "invoice amount",
                "invoice total",
                "sales total",
                "total sales",
            )
        ):
            kind = "money"
        elif any(
            word in matched
            for word in (
                "products",
                "skus",
                "orders",
                "invoices",
                "customers",
                "suppliers",
                "dispatches",
                "shipments",
                "deliveries",
                "items",
                "records",
                "users",
                "employees",
            )
        ):
            kind = "listing"
        else:
            kind = "quantity"
        return kind, tuple(signals), frozenset({"temporal"})

    if _POSSESSIVE_DOMAIN.search(text):
        signals.append("possessive_value")
        kind = "quantity" if _MEASUREMENT.search(text) else "listing"
        return kind, tuple(signals), frozenset({"possessive"})

    if _MEASUREMENT_OF_ENTITY.search(text):
        signals.append("measurement_of_entity")
        return "quantity", tuple(signals), frozenset({"measurement"})

    if _MONEY.search(text):
        signals.append("money_terms")
        return "money", tuple(signals), frozenset()

    if _MEASUREMENT_COMPOUND.search(text):
        signals.append("measurement_compound")
        return "quantity", tuple(signals), frozenset()

    return None, tuple(signals), frozenset()


def _detect_documentation_intent(
    text: str,
) -> tuple[Category | None, str | None]:
    for category, signal, pattern in _DOC_PATTERNS:
        if pattern.search(text):
            return category, signal
    return None, None


def _dedupe_signals(signals: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(signals))[:_MAX_SIGNALS]


def classify_query(query: str) -> GuardDecision:
    """Classify ``query`` as allowed, blocked, or ambiguous.

    The function is deterministic and offline. Invalid input raises
    :class:`~backend.agent.rag.errors.RagInvalidArgumentsError`.
    """

    stripped = _require_query(query)
    text = _clean(stripped)

    doc_category, doc_signal = _detect_documentation_intent(text)
    live_kind, live_signals, hard_markers = _detect_live_fact(
        text,
        tracking_fallback=doc_category is None,
    )
    emitted = list(live_signals)
    if doc_signal is not None:
        emitted.append(doc_signal)

    if hard_markers:
        if (
            _DOCS_OBJECT.search(text)
            and hard_markers <= {"listing", "presence"}
        ):
            return GuardDecision(
                verdict=GuardVerdict.ALLOWED,
                reason=GuardReason.DOCUMENTATION_INTENT,
                suggested_category=doc_category or "erp_docs",
                signals=_dedupe_signals(emitted),
            )
        if (
            _DOCS_OBJECT.search(text)
            and doc_category in {"policies_faqs", "schema", "workflows"}
            and not (hard_markers & {"record", "count", "money", "status"})
        ):
            return GuardDecision(
                verdict=GuardVerdict.ALLOWED,
                reason=GuardReason.DOCUMENTATION_INTENT,
                suggested_category=doc_category,
                signals=_dedupe_signals(emitted),
            )
        if (
            doc_category == "schema"
            and hard_markers == {"listing"}
            and "which_entity" in live_signals
        ):
            return GuardDecision(
                verdict=GuardVerdict.ALLOWED,
                reason=GuardReason.DOCUMENTATION_INTENT,
                suggested_category=doc_category,
                signals=_dedupe_signals(emitted),
            )
        if doc_category is not None:
            return GuardDecision(
                verdict=GuardVerdict.AMBIGUOUS,
                reason=GuardReason.MIXED_INTENT,
                live_fact_kind=live_kind,
                suggested_category=doc_category,
                guidance=MIXED_INTENT_GUIDANCE,
                signals=_dedupe_signals(emitted),
            )
        assert live_kind is not None
        return GuardDecision(
            verdict=GuardVerdict.BLOCKED,
            reason=GuardReason.LIVE_FACT_REQUEST,
            live_fact_kind=live_kind,
            guidance=GUIDANCE_BY_KIND[live_kind],
            signals=_dedupe_signals(emitted),
        )

    if doc_category is not None:
        return GuardDecision(
            verdict=GuardVerdict.ALLOWED,
            reason=GuardReason.DOCUMENTATION_INTENT,
            suggested_category=doc_category,
            signals=_dedupe_signals(emitted),
        )

    if live_kind is not None:
        return GuardDecision(
            verdict=GuardVerdict.BLOCKED,
            reason=GuardReason.LIVE_FACT_REQUEST,
            live_fact_kind=live_kind,
            guidance=GUIDANCE_BY_KIND[live_kind],
            signals=_dedupe_signals(emitted),
        )

    if _WEAK_FRAME.search(text) and _CONCEPT_TERM.search(text):
        return GuardDecision(
            verdict=GuardVerdict.ALLOWED,
            reason=GuardReason.CONCEPTUAL_QUESTION,
            suggested_category="business_definitions",
            signals=_dedupe_signals(emitted),
        )

    if _DOMAIN.search(text):
        return GuardDecision(
            verdict=GuardVerdict.AMBIGUOUS,
            reason=GuardReason.UNSPECIFIED_DOMAIN,
            guidance=UNSPECIFIED_DOMAIN_GUIDANCE,
            signals=_dedupe_signals(emitted),
        )

    return GuardDecision(
        verdict=GuardVerdict.ALLOWED,
        reason=GuardReason.GENERAL_QUESTION,
        signals=_dedupe_signals(emitted),
    )


__all__ = [
    "GUIDANCE_BY_KIND",
    "MIXED_INTENT_GUIDANCE",
    "UNSPECIFIED_DOMAIN_GUIDANCE",
    "GuardDecision",
    "GuardReason",
    "GuardVerdict",
    "classify_query",
]
