"""Fixtures shared by the Stage 6 RAG tool tests.

The helper corpus is deliberately small, deterministic, and free of live ERP
values. Every body passes the Stage 3 live-fact lint, so the corpus loader can
validate it without escape markers.
"""

from __future__ import annotations

from pathlib import Path

from backend.agent.rag.config import RagConfig
from backend.agent.rag.platform import RagToolPlatform

FREE_STOCK_BODY = (
    "# Free Stock and Reserved Stock\n\n"
    "## Definition\n\n"
    "Free stock is the amount of inventory that can still be promised to new "
    "demand after reserved stock is subtracted from on-hand stock.\n\n"
    "## Related Terms\n\n"
    "Reserved stock is inventory held for confirmed demand. Low stock is "
    "evaluated against a reorder level, which is a planning threshold rather "
    "than a live balance."
)

DISPATCH_WORKFLOW_BODY = (
    "# Dispatch Workflow\n\n"
    "## Steps\n\n"
    "A sales order is confirmed, stock is reserved, a dispatch is prepared, "
    "and the shipment is recorded. Each step updates the ERP record.\n\n"
    "## Responsibilities\n\n"
    "Warehouse staff confirm picking while sales staff confirm the customer "
    "request. The workflow explains responsibilities, not current records."
)

SALES_ORDER_SCHEMA_BODY = (
    "# Sales Order Schema\n\n"
    "## Tables\n\n"
    "The sales order table stores the order header and its line items. A "
    "primary key identifies each header, and a foreign key links each line to "
    "its header.\n\n"
    "## Columns\n\n"
    "Columns describe identifiers, dates, quantities, and status labels. "
    "Schema documentation explains structure and never contains stored "
    "records."
)

RETURNS_POLICY_BODY = (
    "# Returns Policy and FAQ\n\n"
    "## Policy\n\n"
    "Returns are accepted when the product is unused and the request is raised "
    "within the allowed window. The policy explains eligibility, not a "
    "specific return record.\n\n"
    "## FAQ\n\n"
    "Ask the support team for a return decision. Documentation does not "
    "contain customer or order records."
)

PLATFORM_OVERVIEW_BODY = (
    "# Platform Overview\n\n"
    "## Modules\n\n"
    "The ERP documentation describes products, inventory, sales orders, and "
    "dispatches. Each module page explains concepts and navigation.\n\n"
    "## Scope\n\n"
    "Documentation is reference material. Current stock, prices, and statuses "
    "always come from the ERP system."
)

_TRUNCATION_SENTENCE = (
    "This documentation paragraph explains a conceptual topic in enough "
    "detail to exceed a small configured output bound without recording live "
    "business values. "
)

LONG_REFERENCE_BODY = (
    "# Long Reference Page\n\n"
    "## Details\n\n"
    + _TRUNCATION_SENTENCE * 12
)

CORPUS_DOCUMENTS: tuple[tuple[str, str, str, str, str, str], ...] = (
    (
        "business_definitions",
        "free-stock",
        "Free Stock and Reserved Stock",
        "definition",
        "How free stock relates to on-hand stock and reserved stock.",
        FREE_STOCK_BODY,
    ),
    (
        "workflows",
        "dispatch-workflow",
        "Dispatch Workflow",
        "workflow",
        "The steps and responsibilities of the dispatch process.",
        DISPATCH_WORKFLOW_BODY,
    ),
    (
        "schema",
        "sales-order-schema",
        "Sales Order Schema",
        "schema",
        "The tables and columns used by sales orders.",
        SALES_ORDER_SCHEMA_BODY,
    ),
    (
        "policies_faqs",
        "returns-policy",
        "Returns Policy and FAQ",
        "policy",
        "Eligibility for returns and answers to common questions.",
        RETURNS_POLICY_BODY,
    ),
    (
        "erp_docs",
        "platform-overview",
        "Platform Overview",
        "overview",
        "The modules covered by the ERP documentation.",
        PLATFORM_OVERVIEW_BODY,
    ),
)


def write_knowledge_document(
    root: Path,
    category: str,
    doc_id: str,
    *,
    title: str,
    fact_kind: str,
    summary: str,
    body: str,
    version: str = "1.0.0",
    updated_at: str = "2026-11-01",
    tags: str = "[test]",
    aliases: str = "[]",
) -> Path:
    directory = root / category
    directory.mkdir(parents=True, exist_ok=True)
    content = (
        "---\n"
        f"doc_id: {doc_id}\n"
        f"title: {title}\n"
        f"category: {category}\n"
        f"fact_kind: {fact_kind}\n"
        f"version: {version}\n"
        f"updated_at: {updated_at}\n"
        f"summary: {summary}\n"
        f"tags: {tags}\n"
        f"aliases: {aliases}\n"
        "---\n\n"
        f"{body}\n"
    )
    path = directory / f"{doc_id}.md"
    path.write_text(content, encoding="utf-8")
    return path


def write_tool_corpus(root: Path) -> Path:
    for category, doc_id, title, fact_kind, summary, body in CORPUS_DOCUMENTS:
        write_knowledge_document(
            root,
            category,
            doc_id,
            title=title,
            fact_kind=fact_kind,
            summary=summary,
            body=body,
        )
    return root


def write_long_document(root: Path) -> Path:
    return write_knowledge_document(
        root,
        "erp_docs",
        "long-reference",
        title="Long Reference Page",
        fact_kind="overview",
        summary="A deliberately long documentation page for output bounds.",
        body=LONG_REFERENCE_BODY,
    )


def make_rag_config(root: Path, **overrides: object) -> RagConfig:
    values: dict[str, object] = {
        "knowledge_dir": root,
        "min_chunk_chars": 0,
    }
    values.update(overrides)
    return RagConfig(**values)


def make_platform(root: Path, **overrides: object) -> RagToolPlatform:
    return RagToolPlatform.from_config(make_rag_config(root, **overrides))


__all__ = [
    "CORPUS_DOCUMENTS",
    "DISPATCH_WORKFLOW_BODY",
    "FREE_STOCK_BODY",
    "LONG_REFERENCE_BODY",
    "PLATFORM_OVERVIEW_BODY",
    "RETURNS_POLICY_BODY",
    "SALES_ORDER_SCHEMA_BODY",
    "make_platform",
    "make_rag_config",
    "write_knowledge_document",
    "write_long_document",
    "write_tool_corpus",
]
