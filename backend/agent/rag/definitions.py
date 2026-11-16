"""Tool definitions for the isolated, documentation-only RAG tool layer.

The three ``rag.knowledge.*`` tools are read-only and never touch the ERP
database. They expose reviewed Markdown documentation, business definitions,
workflows, policies/FAQs, and schema explanations. Live facts such as stock
quantities, record counts, monetary totals, prices, and order statuses remain
the responsibility of the ERP SQL tools.

Each definition uses only the schema subset understood by
:func:`backend.agent.tools.validation.validate_arguments`. Range checks for
``top_k`` and the exact ``category`` values are enforced by the handlers and by
the retriever, not by the schema validator.
"""

from __future__ import annotations

from pydantic import JsonValue

from backend.agent.rag.corpus import CATEGORIES
from backend.agent.tools.contracts import ToolDefinition

RAG_TOOL_VERSION = "1.0.0"

_RAG_READ_ONLY_METADATA: dict[str, JsonValue] = {
    "read_only": True,
    "documentation_only": True,
    "live_data": False,
}

_CATEGORY_SCHEMA: dict[str, JsonValue] = {
    "type": "string",
    "enum": list(CATEGORIES),
}

RAG_TOOL_DEFINITIONS: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        name="rag.knowledge.search",
        description=(
            "Search the reviewed ERP documentation corpus for conceptual "
            "answers about ERP modules, business definitions, workflows, "
            "policies and FAQs, and schema explanations. Use this only for "
            "meaning, process, policy, or data-model questions. Never use it "
            "for live stock quantities, product counts, sales totals, prices, "
            "or order and dispatch statuses; those require the ERP SQL tools. "
            "Arguments: query (required, single line, at most 300 characters), "
            "category (optional one of: erp_docs, business_definitions, "
            "workflows, policies_faqs, schema), top_k (optional integer from "
            "1 to 5, default 3)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "category": dict(_CATEGORY_SCHEMA),
                "top_k": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 5,
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        version=RAG_TOOL_VERSION,
        metadata=dict(_RAG_READ_ONLY_METADATA),
    ),
    ToolDefinition(
        name="rag.knowledge.get",
        description=(
            "Return one reviewed documentation page by its exact doc_id, "
            "including bounded page content and metadata. Use this after "
            "rag.knowledge.search when the full page is needed. Only corpus "
            "documentation is accessible: this tool never returns live ERP "
            "records or arbitrary filesystem paths. Required argument: doc_id "
            "(a documentation identifier such as free-stock)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "doc_id": {"type": "string"},
            },
            "required": ["doc_id"],
            "additionalProperties": False,
        },
        version=RAG_TOOL_VERSION,
        metadata=dict(_RAG_READ_ONLY_METADATA),
    ),
    ToolDefinition(
        name="rag.knowledge.topics",
        description=(
            "List the available documentation topics with compact metadata "
            "(doc_id, title, category, fact_kind, summary, version, and "
            "updated_at). Use this to discover which documentation pages exist "
            "before searching or reading a page. Optional argument: category "
            "(one of the approved documentation categories). This tool never "
            "returns page bodies, filesystem paths, or live ERP data."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "category": dict(_CATEGORY_SCHEMA),
            },
            "additionalProperties": False,
        },
        version=RAG_TOOL_VERSION,
        metadata=dict(_RAG_READ_ONLY_METADATA),
    ),
)

RAG_TOOL_NAMES: tuple[str, ...] = tuple(
    definition.name for definition in RAG_TOOL_DEFINITIONS
)

RAG_TOOL_DEFINITIONS_BY_NAME: dict[str, ToolDefinition] = {
    definition.name: definition for definition in RAG_TOOL_DEFINITIONS
}

__all__ = [
    "RAG_TOOL_DEFINITIONS",
    "RAG_TOOL_DEFINITIONS_BY_NAME",
    "RAG_TOOL_NAMES",
    "RAG_TOOL_VERSION",
]
