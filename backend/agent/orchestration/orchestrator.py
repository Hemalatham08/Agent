from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from typing import Any

from backend.agent.erp.runner import ErpToolRunner
from backend.agent.llm.base import LlmClient
from backend.agent.llm.errors import (
    LlmConnectionError,
    LlmError,
    LlmModelNotFoundError,
    LlmTimeoutError,
)
from backend.agent.llm.models import (
    ChatMessage,
    ChatRole,
    ToolSelectionDecision,
)
from backend.agent.orchestration.context import format_tool_output_message
from backend.agent.orchestration.dependencies import (
    DependencyStep,
    format_dependency_feedback,
    resolve_argument_dependencies,
)
from backend.agent.orchestration.models import (
    AgentExecutionResult,
    ToolCallSummary,
)
from backend.agent.orchestration.prompts import build_system_prompt
from backend.agent.tools.contracts import (
    ToolDefinition,
    ToolExecutionRequest,
    ToolExecutionStatus,
)
from backend.agent.tools.registry import ToolRegistry

_DROP = object()
_INTEGER_TEXT_PATTERN = re.compile(r"^[+-]?\d+$")

# Optional execution plans are short, advisory metadata. These bounds keep a
# model from using the plan field to smuggle oversized prompts into history.
_MAX_EXECUTION_PLAN_STEPS = 8
_MAX_EXECUTION_PLAN_STEP_CHARS = 160
_EXECUTION_PLAN_TOOL_PATTERN = re.compile(r"\berp\.[a-z0-9_]+\.[a-z0-9_]+\b")

_DISPATCH_TOOL_PREFIX = "erp.dispatches."
_DELIVERY_SEMANTICS_NOTE = (
    "Note: dispatch records establish that goods were handed over to the "
    "carrier at the warehouse; confirmed customer delivery receipts are not "
    "tracked in this ERP."
)
_MAX_FALLBACK_OUTPUT_CHARS = 1200
_PRODUCT_COUNT_TOOL = "erp.products.count"
_WAREHOUSE_LIST_TOOL = "erp.warehouses.list"
_WAREHOUSE_LIST_ANALYTICAL_TERMS = (
    "stock",
    "inventory",
    "low",
    "reorder",
    "quantity",
    "qty",
    "product",
    "sku",
    "item",
    "sales",
    "order",
    "dispatch",
    "shipment",
    "delivery",
    "capacity",
    "utilization",
    "movement",
    "transfer",
)
_WAREHOUSE_LIST_PHRASES = (
    "list warehouse",
    "list all warehouse",
    "list the warehouse",
    "list available warehouse",
    "list of warehouses",
    "show warehouse",
    "show all warehouse",
    "show me warehouse",
    "show me all warehouse",
    "show me the warehouse",
    "display warehouse",
    "all warehouses",
    "available warehouses",
    "warehouse list",
    "warehouses list",
    "what warehouse",
    "what are the warehouse",
    "which warehouses",
    "warehouse names",
    "warehouse locations",
    "warehouse cities",
    "names of warehouses",
    "how many warehouses",
    "warehouses do we have",
    "warehouses are there",
    "warehouses exist",
    "tell me the warehouse",
)
_UNSUPPORTED_ERP_TERMS = (
    "create",
    "delete",
    "update",
    "adjust",
    "purchase order",
    "quality",
    "inspection",
    "payment",
    "outstanding",
    "accounting",
    "price",
)

# (source key, column label, formatter kind)
_AnalyticsColumn = tuple[str, str, str]

_ANALYTICS_FALLBACK_TABLES: dict[
    str,
    tuple[tuple[_AnalyticsColumn, ...], tuple[_AnalyticsColumn, ...]],
] = {
    "erp.finance.sales_summary": (
        (
            ("key", "Group", "text"),
            ("label", "Label", "text"),
            ("orders", "Orders", "int"),
            ("units", "Units", "int"),
            ("revenue", "Revenue", "money"),
            ("gross_profit", "Gross profit", "money"),
            ("gross_margin_pct", "Gross margin %", "percent"),
        ),
        (
            ("orders", "Orders", "int"),
            ("units", "Units", "int"),
            ("revenue", "Revenue", "money"),
            ("cost", "Cost", "money"),
            ("gross_profit", "Gross profit", "money"),
            ("gross_margin_pct", "Gross margin %", "percent"),
        ),
    ),
    "erp.finance.purchase_summary": (
        (
            ("key", "Group", "text"),
            ("label", "Label", "text"),
            ("orders", "Orders", "int"),
            ("units_ordered", "Units ordered", "int"),
            ("units_received", "Units received", "int"),
            ("ordered_value", "Ordered value", "money"),
            ("received_value", "Received value", "money"),
            ("open_value", "Open value", "money"),
        ),
        (
            ("orders", "Orders", "int"),
            ("units_ordered", "Units ordered", "int"),
            ("units_received", "Units received", "int"),
            ("ordered_value", "Ordered value", "money"),
            ("received_value", "Received value", "money"),
            ("open_value", "Open value", "money"),
        ),
    ),
    "erp.warehouse.movement_summary": (
        (
            ("key", "Group", "text"),
            ("label", "Label", "text"),
            ("movement_count", "Movements", "int"),
            ("opening_qty", "Opening", "int"),
            ("receipts_qty", "Receipts", "int"),
            ("dispatch_qty", "Dispatch", "int"),
            ("adjustment_qty", "Adjustments", "int"),
            ("inbound_qty", "Inbound", "int"),
            ("outbound_qty", "Outbound", "int"),
            ("receipts_net_qty", "Receipts net", "int"),
            ("net_change", "Net change", "int"),
        ),
        (
            ("movement_count", "Movements", "int"),
            ("opening_qty", "Opening", "int"),
            ("receipts_qty", "Receipts", "int"),
            ("dispatch_qty", "Dispatch", "int"),
            ("adjustment_qty", "Adjustments", "int"),
            ("inbound_qty", "Inbound", "int"),
            ("outbound_qty", "Outbound", "int"),
            ("receipts_net_qty", "Receipts net", "int"),
            ("net_change", "Net change", "int"),
        ),
    ),
    "erp.fulfillment.summary": (
        (
            ("key", "Group", "text"),
            ("label", "Label", "text"),
            ("dispatches", "Dispatches", "int"),
            ("ordered_qty", "Ordered", "int"),
            ("picked_qty", "Picked", "int"),
            ("dispatched_qty", "Dispatched", "int"),
            ("open_qty", "Open", "int"),
            ("pick_fill_pct", "Pick fill %", "percent"),
            ("order_fill_pct", "Order fill %", "percent"),
        ),
        (
            ("dispatches", "Dispatches", "int"),
            ("ordered_qty", "Ordered", "int"),
            ("picked_qty", "Picked", "int"),
            ("dispatched_qty", "Dispatched", "int"),
            ("open_qty", "Open", "int"),
            ("pick_fill_pct", "Pick fill %", "percent"),
            ("order_fill_pct", "Order fill %", "percent"),
            (
                "dispatched_order_fill_pct",
                "Dispatched-order fill %",
                "percent",
            ),
        ),
    ),
}


def _format_analytics_value(value: Any, kind: str) -> str:
    """Format one verified tool value without changing or inventing it."""

    if value is None:
        return "—"
    try:
        if kind == "money":
            return f"{float(value):,.2f}"
        if kind == "percent":
            return f"{float(value):.2f}"
        if kind == "int":
            return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)
    return str(value)


def _markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()


def _analytics_fallback_title(tool_name: str, output: Mapping[str, Any]) -> str:
    group_by = output.get("group_by") or "group"
    if tool_name == "erp.finance.sales_summary":
        basis = output.get("basis") or "unknown"
        return f"Sales summary by {group_by} (basis: {basis})"
    if tool_name == "erp.finance.purchase_summary":
        basis = output.get("basis") or "unknown"
        return f"Purchase summary by {group_by} (basis: {basis})"
    if tool_name == "erp.warehouse.movement_summary":
        return f"Stock movement summary by {group_by}"
    return f"Fulfillment summary by {group_by}"


def _analytics_fallback_lines(
    tool_name: str,
    output: Any,
) -> list[str] | None:
    """Render a deterministic summary from verified analytics tool output.

    Returns ``None`` when the tool is not an analytics tool or its output does
    not have the expected rows structure, so the caller can retain the existing
    generic fallback behavior.
    """

    table = _ANALYTICS_FALLBACK_TABLES.get(tool_name)
    if table is None or not isinstance(output, Mapping):
        return None
    rows = output.get("rows")
    if not isinstance(rows, list):
        return None

    columns, total_columns = table
    lines = [_analytics_fallback_title(tool_name, output)]

    totals = output.get("totals")
    if isinstance(totals, Mapping):
        total_parts = [
            f"{label}: {_format_analytics_value(totals.get(key), kind)}"
            for key, label, kind in total_columns
            if key in totals
        ]
        if total_parts:
            currency = output.get("currency")
            suffix = (
                f" Currency: {currency}."
                if isinstance(currency, str) and currency.strip()
                else ""
            )
            lines.append("Totals: " + "; ".join(total_parts) + "." + suffix)

    shown = len(rows)
    row_count = output.get("row_count")
    if (
        isinstance(row_count, int)
        and not isinstance(row_count, bool)
        and row_count != shown
    ):
        summary = f"Showing {shown} of {row_count} rows."
    else:
        summary = f"Showing {shown} rows."
    if output.get("truncated") is True:
        summary += " Results are truncated."
    lines.append(summary)

    if rows:
        lines.append("")
        lines.append("| " + " | ".join(label for _, label, _ in columns) + " |")
        lines.append("| " + " | ".join("---" for _ in columns) + " |")
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            cells = [
                _markdown_cell(_format_analytics_value(row.get(key), kind))
                for key, _, kind in columns
            ]
            lines.append("| " + " | ".join(cells) + " |")
    else:
        lines.append("No rows matched the query.")

    notes = output.get("notes")
    if isinstance(notes, list):
        note_lines = [
            note.strip() for note in notes if isinstance(note, str) and note.strip()
        ]
        if note_lines:
            lines.append("")
            lines.append("Notes:")
            lines.extend(f"- {note}" for note in note_lines)

    return lines


# Column definitions for the human-readable fallback tables. Each entry is
# (output key, display label, value kind). Only keys that exist on the
# corresponding ERP tool output are used, so no values are ever invented.
_PRODUCT_TABLE_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("product_id", "Product ID", "text"),
    ("sku", "SKU", "text"),
    ("product_name", "Product name", "text"),
    ("category", "Category", "text"),
    ("material", "Material", "text"),
    ("size", "Size", "text"),
    ("grade", "Grade", "text"),
    ("unit", "Unit", "text"),
)

_INVENTORY_TABLE_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("product_id", "Product ID", "text"),
    ("product_name", "Product name", "text"),
    ("warehouse_id", "Warehouse ID", "text"),
    ("warehouse_name", "Warehouse", "text"),
    ("on_hand_qty", "On hand", "int"),
    ("reserved_qty", "Reserved", "int"),
    ("free_stock", "Free stock", "int"),
    ("reorder_level", "Reorder level", "int"),
    ("low_stock", "Low stock", "text"),
)

_WAREHOUSE_TABLE_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("warehouse_id", "Warehouse ID", "text"),
    ("warehouse_name", "Warehouse name", "text"),
    ("city", "City", "text"),
)


def _render_simple_table(
    title: str,
    columns: tuple[tuple[str, str, str], ...],
    rows: list[Any],
    output: Any,
) -> list[str]:
    """Render a title, row summary, and markdown table from verified rows.

    Never invents values: missing fields render as ``—`` and actual zero
    quantities remain ``0``.
    """

    lines: list[str] = [title]
    shown = len(rows)
    row_count = output.get("row_count") if isinstance(output, Mapping) else None
    if (
        isinstance(row_count, int)
        and not isinstance(row_count, bool)
        and row_count != shown
    ):
        summary = f"Showing {shown} of {row_count} rows."
    else:
        summary = f"Showing {shown} rows."
    if isinstance(output, Mapping) and output.get("truncated") is True:
        summary += " Results are truncated."
    lines.append(summary)

    if rows:
        lines.append("")
        lines.append("| " + " | ".join(label for _, label, _ in columns) + " |")
        lines.append("| " + " | ".join("---" for _ in columns) + " |")
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            cells = [
                _markdown_cell(_format_analytics_value(row.get(key), kind))
                for key, _, kind in columns
            ]
            lines.append("| " + " | ".join(cells) + " |")
    else:
        lines.append("No rows matched the query.")
    return lines


def _products_table_lines(output: Any) -> list[str] | None:
    if not isinstance(output, Mapping):
        return None
    items = output.get("items")
    if not isinstance(items, list):
        return None
    return _render_simple_table("Products", _PRODUCT_TABLE_COLUMNS, items, output)


def _inventory_table_lines(output: Any) -> list[str] | None:
    if not isinstance(output, Mapping):
        return None
    items = output.get("items")
    if not isinstance(items, list):
        return None
    return _render_simple_table("Inventory", _INVENTORY_TABLE_COLUMNS, items, output)


def _warehouses_table_lines(output: Any) -> list[str] | None:
    if not isinstance(output, Mapping):
        return None
    items = output.get("items")
    if not isinstance(items, list):
        return None
    return _render_simple_table("Warehouses", _WAREHOUSE_TABLE_COLUMNS, items, output)


def _simple_table_fallback_lines(tool_name: str, output: Any) -> list[str] | None:
    """Return readable table lines for product, inventory, and warehouse tools.

    Returns ``None`` for tools without a dedicated table renderer so the
    caller can retain the existing generic JSON fallback behavior.
    """

    if tool_name == "erp.products.search":
        return _products_table_lines(output)
    if tool_name in ("erp.inventory.get", "erp.inventory.list", "erp.inventory.low_stock"):
        return _inventory_table_lines(output)
    if tool_name == "erp.warehouses.list":
        return _warehouses_table_lines(output)
    return None


def _required_tool_evidence(question: str) -> tuple[str, ...] | None:
    """Return the approved tool family required for a known ERP question.

    ``None`` represents a non-factual request, such as a greeting. An empty
    tuple represents an ERP domain that has no approved read-only tool.
    """

    text = question.lower()
    if any(term in text for term in _UNSUPPORTED_ERP_TERMS):
        return ()
    if _is_warehouse_list_question(text):
        return (_WAREHOUSE_LIST_TOOL,)
    if any(term in text for term in ("movement", "inbound", "outbound", "stock movement")):
        return ("erp.warehouse.movement_summary",)
    if any(term in text for term in ("inventory", "stock", "warehouse")):
        return ("erp.inventory.", "erp.warehouses.")
    if "sales order" in text:
        return ("erp.sales_orders.",)
    if any(term in text for term in ("dispatch", "shipment", "delivered")):
        return ("erp.dispatches.",)
    if any(term in text for term in ("revenue", "gross profit", "gross margin", "invoiced", "total sales", "sales total")):
        return ("erp.finance.sales_summary",)
    if any(term in text for term in ("purchase", "procurement", "supplier", "spend")):
        return ("erp.finance.purchase_summary",)
    if any(term in text for term in ("fulfillment", "fulfilment", "fill rate", "pick fill", "order fill", "picked")):
        return ("erp.fulfillment.summary",)
    if "product" in text or "sku" in text:
        if any(
            phrase in text
            for phrase in ("how many", "count", "number of", "total products")
        ):
            return (_PRODUCT_COUNT_TOOL,)
        return ("erp.products.",)
    return None


def _is_warehouse_list_question(text: str) -> bool:
    """Return whether the question clearly asks for the warehouse list.

    Warehouse-specific analytical questions (stock, inventory, low stock,
    dispatch, and similar) mention warehouses but are not list requests and
    must keep their existing tool and synthesis behavior.
    """

    if "warehouse" not in text:
        return False
    if any(term in text for term in _WAREHOUSE_LIST_ANALYTICAL_TERMS):
        return False
    return any(phrase in text for phrase in _WAREHOUSE_LIST_PHRASES)


def _tool_matches(expected: str, tool_name: str) -> bool:
    """Return whether a tool result belongs to an approved evidence family.

    The product count and warehouse list tools are exact-match only, so a
    successful result can never be used as evidence for another question.
    """

    if expected in (_PRODUCT_COUNT_TOOL, _WAREHOUSE_LIST_TOOL):
        return tool_name == expected
    if tool_name == _PRODUCT_COUNT_TOOL:
        return False
    return tool_name.startswith(expected)


def _has_required_evidence(
    requirement: tuple[str, ...],
    outputs: list[tuple[str, Any]],
) -> bool:
    return any(
        isinstance(output, Mapping)
        and any(_tool_matches(expected, tool_name) for expected in requirement)
        for tool_name, output in outputs
    )


def _authoritative_product_count(
    outputs: list[tuple[str, Any]],
) -> int | None:
    for tool_name, output in outputs:
        if tool_name != _PRODUCT_COUNT_TOOL or not isinstance(output, Mapping):
            continue
        count = output.get("product_count")
        if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
            return count
    return None


def _authoritative_warehouse_list(
    outputs: list[tuple[str, Any]],
) -> str | None:
    """Render the warehouse list from actual tool output, or ``None``.

    ``None`` means no usable warehouse list output exists or the output is
    structurally malformed. Callers must never synthesize records in that
    case. A structurally valid empty list renders a truthful empty answer.
    """

    output = None
    for tool_name, candidate in outputs:
        if tool_name == _WAREHOUSE_LIST_TOOL and isinstance(candidate, Mapping):
            output = candidate
            break
    if output is None:
        return None

    items = output.get("items")
    if not isinstance(items, list):
        return None

    row_count = output.get("row_count")
    if row_count is not None:
        if isinstance(row_count, bool) or not isinstance(row_count, int):
            return None
        if row_count != len(items):
            return None

    if not items:
        return "There are no warehouses in the ERP."

    lines = [f"There are {len(items)} warehouses in the ERP:"]
    for item in items:
        if not isinstance(item, Mapping):
            return None
        warehouse_id = item.get("warehouse_id")
        warehouse_name = item.get("warehouse_name")
        if not isinstance(warehouse_id, str) or not warehouse_id.strip():
            return None
        if not isinstance(warehouse_name, str) or not warehouse_name.strip():
            return None
        city = item.get("city")
        if isinstance(city, str) and city.strip():
            lines.append(
                f"- {warehouse_name.strip()} ({warehouse_id.strip()}) — "
                f"{city.strip()}"
            )
        else:
            lines.append(f"- {warehouse_name.strip()} ({warehouse_id.strip()})")
    return "\n".join(lines)


def _grounding_failure_answer(
    requirement: tuple[str, ...],
    summaries: list[ToolCallSummary],
) -> tuple[str, str]:
    if not requirement:
        return (
            "I cannot provide a verified answer for that ERP domain because no "
            "approved read-only tool is available.",
            "unsupported_capability",
        )

    relevant_failures = [
        summary
        for summary in summaries
        if any(_tool_matches(expected, summary.tool_name) for expected in requirement)
        and summary.status != ToolExecutionStatus.SUCCEEDED.value
    ]
    if relevant_failures:
        failure = relevant_failures[-1]
        detail = f" The tool reported: {failure.error}." if failure.error else ""
        return (
            "I could not retrieve verified ERP data for this question, so I "
            f"cannot provide an authoritative answer.{detail}",
            "tool_evidence_failed",
        )

    return (
        "I cannot provide a verified ERP answer because no successful relevant "
        "tool result was retrieved.",
        "missing_tool_evidence",
    )


def _grounded_answer(
    requirement: tuple[str, ...] | None,
    answer_text: str,
    successful_outputs: list[tuple[str, Any]],
    summaries: list[ToolCallSummary],
) -> tuple[str, str, str | None]:
    """Apply the milestone grounding rules to a candidate final answer.

    Returns ``(answer, status, error)``. Product counts and warehouse lists
    are always replaced with the value returned by the registered tool,
    never with text proposed by the language model.
    """

    if requirement is None:
        return answer_text, "completed", None

    if not _has_required_evidence(requirement, successful_outputs):
        answer, error = _grounding_failure_answer(requirement, summaries)
        return answer, "error", error

    if requirement == (_PRODUCT_COUNT_TOOL,):
        product_count = _authoritative_product_count(successful_outputs)
        if product_count is None:
            return (
                "I could not retrieve a valid authoritative product count, "
                "so I cannot provide a verified answer.",
                "error",
                "invalid_tool_evidence",
            )
        return f"There are {product_count} products in the ERP.", "completed", None

    if requirement == (_WAREHOUSE_LIST_TOOL,):
        warehouse_list = _authoritative_warehouse_list(successful_outputs)
        if warehouse_list is None:
            return (
                "I could not retrieve a valid authoritative warehouse list, "
                "so I cannot provide a verified answer.",
                "error",
                "invalid_tool_evidence",
            )
        return warehouse_list, "completed", None

    return answer_text, "completed", None


def _clean_json_text(text: str) -> str:
    """Strip markdown fences and whitespace from model JSON output."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # Remove opening fence
        first_newline = cleaned.find("\n")
        if first_newline != -1:
            cleaned = cleaned[first_newline + 1 :]
        else:
            cleaned = cleaned[3:]
        # Remove closing fence
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

    # If surrounded by other text, try to locate first '{' and matching '}'
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        cleaned = cleaned[start : end + 1]

    return cleaned


def _coerce_schema_value(value: Any, expected_type: Any) -> Any:
    """Coerce one model-supplied argument value toward ``expected_type``.

    Returns the coerced value, or the ``_DROP`` sentinel when the value
    cannot be used for the declared type and should fall back to the
    handler default (or a clear missing-required validation error).
    """

    if value is None:
        return _DROP
    if expected_type == "integer":
        if isinstance(value, bool):
            return _DROP
        if isinstance(value, int):
            return value
        if isinstance(value, float) and math.isfinite(value):
            return int(value) if value.is_integer() else _DROP
        if isinstance(value, str):
            text = value.strip()
            if _INTEGER_TEXT_PATTERN.fullmatch(text):
                return int(text)
            return _DROP
        return _DROP
    if expected_type == "number":
        if isinstance(value, bool):
            return _DROP
        if isinstance(value, (int, float)):
            return value
        if isinstance(value, str):
            try:
                return float(value.strip())
            except ValueError:
                return _DROP
        return _DROP
    if expected_type == "string":
        if isinstance(value, str):
            return value
        if isinstance(value, int) and not isinstance(value, bool):
            return str(value)
        return _DROP
    if expected_type == "boolean":
        return value if isinstance(value, bool) else _DROP
    return value


def normalize_tool_arguments(
    arguments: Mapping[str, Any],
    definition: ToolDefinition,
) -> dict[str, Any]:
    """Validate and safely normalize model-supplied tool arguments.

    Small language models frequently emit ``null`` for optional arguments,
    quote integers (``"20"``), or send identifiers as bare numbers. The
    executor enforces strict JSON types, so those harmless mistakes would
    otherwise fail validation and trigger repeated tool calls. This
    normalizer only performs schema-driven, loss-free coercions:

    * ``null`` values are dropped so handler defaults apply;
    * integer-typed arguments accept digit strings and integral floats;
    * number-typed arguments accept numeric strings;
    * string-typed arguments accept integers (identifier-like values).

    Values that cannot satisfy the declared type are dropped rather than
    executed, and undeclared properties are preserved so the executor still
    reports them as unexpected arguments.
    """

    if not isinstance(arguments, Mapping):
        return {}

    schema = definition.input_schema
    properties = (
        schema.get("properties") if isinstance(schema, Mapping) else None
    )
    if not isinstance(properties, Mapping):
        return dict(arguments)

    normalized: dict[str, Any] = {}
    for name, value in arguments.items():
        property_schema = properties.get(name)
        if not isinstance(property_schema, Mapping):
            normalized[name] = value
            continue
        coerced = _coerce_schema_value(value, property_schema.get("type"))
        if coerced is _DROP:
            continue
        normalized[name] = coerced
    return normalized


def _failure_feedback_lines(tool_name: str, result: Any) -> list[str]:
    """Build actionable feedback for a failed tool execution."""

    error = getattr(result, "error", None)
    code = getattr(error, "code", None) or "tool_error"
    message = getattr(error, "message", None) or "Unknown tool error"
    lines = [f"Tool `{tool_name}` failed with error [{code}]: {message}"]

    details = getattr(error, "details", None)
    if isinstance(details, Mapping):
        issues = details.get("issues")
        if isinstance(issues, list):
            for issue in issues:
                if isinstance(issue, Mapping):
                    issue_message = issue.get("message")
                    if isinstance(issue_message, str) and issue_message.strip():
                        lines.append(f"- {issue_message}")

    if code == "erp_not_found":
        lines.append(
            "Do not guess identifiers. Only use identifiers that appear in "
            "earlier tool output or that the user explicitly provided."
        )

    lines.append(
        "Either correct the arguments for this tool based on the error above, "
        "or provide a final answer using the data already retrieved."
    )
    return lines


def _used_dispatch_tools(summaries: list[ToolCallSummary]) -> bool:
    return any(
        summary.tool_name.startswith(_DISPATCH_TOOL_PREFIX)
        and summary.status == ToolExecutionStatus.SUCCEEDED.value
        for summary in summaries
    )


def _parse_batch_call(raw_call: Any) -> tuple[str, dict[str, Any]]:
    """Extract a tool name and argument mapping from a multi-call decision."""

    if not isinstance(raw_call, Mapping):
        return "", {}
    tool_name = raw_call.get("tool_name")
    if not isinstance(tool_name, str):
        tool_name = raw_call.get("name")
    if not isinstance(tool_name, str):
        tool_name = ""
    arguments = raw_call.get("arguments")
    return tool_name.strip(), (
        dict(arguments) if isinstance(arguments, Mapping) else {}
    )


def _normalize_execution_plan(
    raw_plan: Any,
) -> tuple[list[str] | None, str | None]:
    """Normalize an optional model-supplied execution plan.

    Returns ``(plan, error)``. ``plan`` is ``None`` when the field is absent,
    empty, or unusable. The plan is descriptive metadata only; it is never
    used to authorize or execute a tool.
    """

    if raw_plan is None:
        return None, None
    if not isinstance(raw_plan, list):
        return None, (
            "The 'execution_plan' field must be a JSON array of short strings "
            "or null."
        )

    steps: list[str] = []
    for item in raw_plan:
        if not isinstance(item, str):
            return None, "Each 'execution_plan' entry must be a short string."
        step = item.strip()
        if not step:
            continue
        if len(step) > _MAX_EXECUTION_PLAN_STEP_CHARS:
            return None, (
                "Each 'execution_plan' step must be at most "
                f"{_MAX_EXECUTION_PLAN_STEP_CHARS} characters."
            )
        steps.append(step)

    if len(steps) > _MAX_EXECUTION_PLAN_STEPS:
        return None, (
            "The 'execution_plan' may contain at most "
            f"{_MAX_EXECUTION_PLAN_STEPS} steps."
        )

    return (steps or None), None


def _validate_execution_plan(
    raw_plan: Any,
    registry: ToolRegistry,
) -> tuple[list[str] | None, str | None]:
    """Validate an optional plan against the approved ERP tool catalog.

    The plan never authorizes execution. This helper only checks that the
    metadata is well formed and that any tool names it mentions are registered.
    Actual tool calls still pass through ``ToolRegistry.exists`` and the normal
    argument/runner validation.
    """

    plan, error = _normalize_execution_plan(raw_plan)
    if error is not None or plan is None:
        return plan, error

    unknown: list[str] = []
    for step in plan:
        for tool_name in _EXECUTION_PLAN_TOOL_PATTERN.findall(step):
            if not registry.exists(tool_name) and tool_name not in unknown:
                unknown.append(tool_name)
    if unknown:
        referenced = ", ".join(f"`{name}`" for name in unknown)
        return None, (
            "The execution plan references tools that are not in the approved "
            f"ERP catalog: {referenced}. Plans may only describe steps using "
            "approved tools."
        )

    return plan, None


def _adapt_llm_client(client: LlmClient, registry: ToolRegistry) -> LlmClient:
    """Wrap a raw Gemini SDK client in the provider-neutral adapter.

    Provider selection normally supplies the adapter directly. This fallback
    keeps direct ``GeminiClient`` injection working without changing the Gemini
    production client.
    """

    try:
        from backend.ai_providers.gemini.adapter import GeminiLlmClientAdapter
        from backend.ai_providers.gemini.client import GeminiClient
    except Exception:  # pragma: no cover - optional dependency safety
        return client

    if isinstance(client, GeminiClient):
        return GeminiLlmClientAdapter(
            client.config,
            client=client,
            tool_registry=registry,
        )
    return client


class AgentOrchestrator:
    """Orchestrates natural-language question understanding, tool calling, and grounded answers."""

    def __init__(
        self,
        *,
        client: LlmClient,
        runner: ErpToolRunner,
        registry: ToolRegistry,
        max_tool_calls: int = 5,
    ) -> None:
        self.client = _adapt_llm_client(client, registry)
        self.runner = runner
        self.registry = registry
        self.max_tool_calls = max(1, max_tool_calls)
        # LLM round trips (including retries, corrective feedback, and
        # unparseable output) are bounded separately from executed tool calls
        # so that invalid arguments never burn the tool-call budget.
        self.max_llm_rounds = self.max_tool_calls * 3

    def process_question(
        self,
        question: str,
        *,
        session_id: str | None = None,
    ) -> AgentExecutionResult:
        stripped_question = (question or "").strip()
        if not stripped_question:
            return AgentExecutionResult(
                answer="Please provide a business question.",
                status="completed",
                tool_calls=[],
                session_id=session_id,
            )

        grounding_requirement = _required_tool_evidence(stripped_question)

        # 1. Health & model availability check
        try:
            self.client.validate_availability()
        except LlmConnectionError as err:
            provider_label = getattr(self.client, "provider_label", "Ollama")
            connection_hint = getattr(
                self.client,
                "connection_hint",
                "Please ensure Ollama is installed and running (`ollama serve`).",
            )
            unavailable_error = getattr(
                self.client,
                "unavailable_error_code",
                "ollama_unavailable",
            )
            return AgentExecutionResult(
                answer=(
                    f"The AI assistant is currently unable to reach the local {provider_label} service "
                    f"at '{self.client.config.base_url}'. {connection_hint}"
                ),
                status="error",
                error=unavailable_error,
                session_id=session_id,
            )
        except LlmModelNotFoundError as err:
            return AgentExecutionResult(
                answer=str(err),
                status="error",
                error="model_not_found",
                session_id=session_id,
            )
        except Exception as err:
            return AgentExecutionResult(
                answer=f"Could not connect to the local language model: {err}",
                status="error",
                error="llm_initialization_error",
                session_id=session_id,
            )

        # 2. Build system prompt from dynamic tool catalog
        tool_definitions = self.registry.export_definitions()
        system_prompt = build_system_prompt(tool_definitions)

        messages: list[ChatMessage] = [
            ChatMessage(role=ChatRole.SYSTEM, content=system_prompt),
            ChatMessage(role=ChatRole.USER, content=stripped_question),
        ]

        executed_summaries: list[ToolCallSummary] = []
        executed_calls_set: set[tuple[str, str]] = set()
        successful_outputs: list[tuple[str, Any]] = []
        execution_steps: list[DependencyStep] = []

        iteration = 0
        tool_executions = 0
        plan_feedback_given = False

        while (
            tool_executions < self.max_tool_calls
            and iteration < self.max_llm_rounds
        ):
            iteration += 1

            # 3. Call LLM
            try:
                response = self.client.chat(messages, format="json", temperature=0.0)
            except LlmTimeoutError:
                if successful_outputs:
                    return self._llm_failure_result(
                        error="llm_timeout",
                        timeout=True,
                        executed_summaries=executed_summaries,
                        successful_outputs=successful_outputs,
                        grounding_requirement=grounding_requirement,
                        iteration=iteration,
                        session_id=session_id,
                    )
                return AgentExecutionResult(
                    answer="The request to the local AI service timed out while processing your question.",
                    tool_calls=executed_summaries,
                    status="error",
                    error="llm_timeout",
                    iterations=iteration,
                    session_id=session_id,
                )
            except LlmError as err:
                if successful_outputs:
                    return self._llm_failure_result(
                        error="llm_error",
                        timeout=False,
                        executed_summaries=executed_summaries,
                        successful_outputs=successful_outputs,
                        grounding_requirement=grounding_requirement,
                        iteration=iteration,
                        session_id=session_id,
                    )
                return AgentExecutionResult(
                    answer=f"The AI service encountered an error: {err}",
                    tool_calls=executed_summaries,
                    status="error",
                    error="llm_error",
                    iterations=iteration,
                    session_id=session_id,
                )

            # 4. Parse decision
            raw_content = response.content
            cleaned_json = _clean_json_text(raw_content)

            try:
                data: Any = json.loads(cleaned_json)
            except Exception:
                data = None

            plan_error: str | None = None
            if isinstance(data, Mapping):
                # Validate the optional plan before schema validation. A
                # malformed plan is replaced with None so it cannot make the
                # decision itself unparseable, and so it can never authorize
                # a tool call.
                data = dict(data)
                plan, plan_error = _validate_execution_plan(
                    data.get("execution_plan"),
                    self.registry,
                )
                data["execution_plan"] = plan

            if data is None:
                # Give model one chance to correct its JSON output
                messages.append(ChatMessage(role=ChatRole.ASSISTANT, content=raw_content))
                messages.append(
                    ChatMessage(
                        role=ChatRole.USER,
                        content=(
                            "Your previous response was not valid JSON conforming to the schema. "
                            "Please respond with a single valid JSON object with keys 'thought', 'action', "
                            "'tool_name', 'arguments', 'final_answer', and optional 'execution_plan'."
                        ),
                    )
                )
                continue

            try:
                decision = ToolSelectionDecision.model_validate(data)
            except Exception:
                messages.append(ChatMessage(role=ChatRole.ASSISTANT, content=raw_content))
                messages.append(
                    ChatMessage(
                        role=ChatRole.USER,
                        content=(
                            "Your previous response did not conform to the decision schema. "
                            "Please respond with a single valid JSON object with keys 'thought', 'action', "
                            "'tool_name', 'arguments', 'final_answer', and optional 'execution_plan'."
                        ),
                    )
                )
                continue

            if plan_error is not None:
                if not plan_feedback_given:
                    # Give the model exactly one chance to correct its plan.
                    plan_feedback_given = True
                    messages.append(
                        ChatMessage(role=ChatRole.ASSISTANT, content=raw_content)
                    )
                    messages.append(
                        ChatMessage(
                            role=ChatRole.USER,
                            content=(
                                f"Your execution plan is invalid: {plan_error} "
                                "Respond again with a corrected plan, or omit "
                                "'execution_plan' for a simple request."
                            ),
                        )
                    )
                    continue
                # A correction was already requested. Do not retry forever:
                # ignore the invalid plan and continue with the requested
                # action under the normal validation rules.

            # 5. Handle Native Multi-Tool Call (Gemini adapter protocol)
            if decision.action == "call_tools":
                raw_calls = data.get("tool_calls") if isinstance(data, Mapping) else None
                if not isinstance(raw_calls, list) or not raw_calls:
                    messages.append(
                        ChatMessage(role=ChatRole.ASSISTANT, content=raw_content)
                    )
                    messages.append(
                        ChatMessage(
                            role=ChatRole.USER,
                            content=(
                                "The 'call_tools' action requires a non-empty "
                                "'tool_calls' array. Please respond again."
                            ),
                        )
                    )
                    continue

                tool_executions, early_result = self._process_tool_call_batch(
                    raw_calls=raw_calls,
                    raw_content=raw_content,
                    messages=messages,
                    executed_summaries=executed_summaries,
                    executed_calls_set=executed_calls_set,
                    successful_outputs=successful_outputs,
                    execution_steps=execution_steps,
                    tool_executions=tool_executions,
                    grounding_requirement=grounding_requirement,
                    iteration=iteration,
                    session_id=session_id,
                )
                if early_result is not None:
                    return early_result
                continue

            # 6. Handle Final Answer
            if decision.action == "final_answer":
                answer_text = (decision.final_answer or "").strip()
                if not answer_text:
                    answer_text = "I have processed your request, but no additional explanation was generated."

                answer_text, status, error = _grounded_answer(
                    grounding_requirement,
                    answer_text,
                    successful_outputs,
                    executed_summaries,
                )
                return AgentExecutionResult(
                    answer=answer_text,
                    tool_calls=executed_summaries,
                    status=status,
                    error=error,
                    iterations=iteration,
                    session_id=session_id,
                )

            # 6. Handle Tool Call
            if decision.action == "call_tool":
                tool_name = (decision.tool_name or "").strip()
                arguments = decision.arguments or {}

                # Check if tool is registered
                if not tool_name or not self.registry.exists(tool_name):
                    valid_tools = ", ".join(f"`{d['name']}`" for d in tool_definitions)
                    messages.append(ChatMessage(role=ChatRole.ASSISTANT, content=raw_content))
                    messages.append(
                        ChatMessage(
                            role=ChatRole.USER,
                            content=(
                                f"Tool '{tool_name}' is not recognized in the approved ERP catalog. "
                                f"Available tools: [{valid_tools}]. Please choose an approved tool or provide a final answer."
                            ),
                        )
                    )
                    continue

                # Validate and normalize model arguments against the tool schema
                definition = self.registry.get(tool_name)

                # Resolve explicit $steps references before normalization. The
                # resolver only reads earlier successful execution outputs and
                # never authorizes a tool or bypasses normal validation.
                arguments, dependency_issues = resolve_argument_dependencies(
                    arguments,
                    definition,
                    execution_steps,
                )
                if dependency_issues:
                    messages.append(
                        ChatMessage(role=ChatRole.ASSISTANT, content=raw_content)
                    )
                    messages.append(
                        ChatMessage(
                            role=ChatRole.USER,
                            content=format_dependency_feedback(
                                dependency_issues
                            ),
                        )
                    )
                    continue

                arguments = normalize_tool_arguments(arguments, definition)

                # Check for repeated identical tool call
                args_key = json.dumps(arguments, sort_keys=True, default=str)
                call_sig = (tool_name, args_key)
                if call_sig in executed_calls_set:
                    messages.append(ChatMessage(role=ChatRole.ASSISTANT, content=raw_content))
                    messages.append(
                        ChatMessage(
                            role=ChatRole.USER,
                            content=(
                                f"Tool '{tool_name}' was already called with arguments {arguments}. "
                                "Do not repeat identical calls. Please proceed to answer the user's question "
                                "using the retrieved data or pick a different tool."
                            ),
                        )
                    )
                    continue

                # Execute tool through ErpToolRunner
                request = ToolExecutionRequest(tool_name=tool_name, arguments=arguments)
                result = self.runner.execute(request)

                executed_calls_set.add(call_sig)

                # Only calls that actually reached a handler consume the
                # tool-call budget; pre-flight validation failures do not.
                if result.started_at is not None:
                    tool_executions += 1
                    execution_steps.append(
                        DependencyStep(
                            step_number=len(execution_steps) + 1,
                            tool_name=tool_name,
                            status=result.status.value,
                            output=(
                                result.output
                                if result.status
                                is ToolExecutionStatus.SUCCEEDED
                                else None
                            ),
                        )
                    )

                summary = ToolCallSummary(
                    tool_name=tool_name,
                    arguments=arguments,
                    status=result.status.value,
                    duration_ms=result.duration_ms,
                    error=result.error.message if result.error else None,
                    output=(
                        result.output
                        if result.status is ToolExecutionStatus.SUCCEEDED
                        else None
                    ),
                )
                executed_summaries.append(summary)

                # Feed result back to model
                messages.append(ChatMessage(role=ChatRole.ASSISTANT, content=raw_content))

                if result.status is ToolExecutionStatus.SUCCEEDED:
                    successful_outputs.append((tool_name, result.output))
                    if grounding_requirement == (_WAREHOUSE_LIST_TOOL,):
                        warehouse_list = _authoritative_warehouse_list(
                            successful_outputs
                        )
                        if warehouse_list is not None:
                            return AgentExecutionResult(
                                answer=warehouse_list,
                                tool_calls=executed_summaries,
                                status="completed",
                                iterations=iteration,
                                session_id=session_id,
                            )
                    if grounding_requirement == (_PRODUCT_COUNT_TOOL,):
                        product_count = _authoritative_product_count(successful_outputs)
                        if product_count is not None:
                            return AgentExecutionResult(
                                answer=f"There are {product_count} products in the ERP.",
                                tool_calls=executed_summaries,
                                status="completed",
                                iterations=iteration,
                                session_id=session_id,
                            )
                    messages.append(
                        ChatMessage(
                            role=ChatRole.USER,
                            content=format_tool_output_message(
                                tool_name,
                                result.output,
                            ),
                        )
                    )
                elif result.status is ToolExecutionStatus.FAILED:
                    messages.append(
                        ChatMessage(
                            role=ChatRole.USER,
                            content="\n".join(
                                _failure_feedback_lines(tool_name, result)
                            ),
                        )
                    )
                else:  # CANCELLED / TIMEOUT
                    messages.append(
                        ChatMessage(
                            role=ChatRole.USER,
                            content=f"Tool `{tool_name}` execution was cancelled or timed out.",
                        )
                    )
                continue

            # 6b. Unrecognized action - ask the model to correct itself
            messages.append(ChatMessage(role=ChatRole.ASSISTANT, content=raw_content))
            messages.append(
                ChatMessage(
                    role=ChatRole.USER,
                    content=(
                        f"Unknown action '{decision.action}'. The 'action' field must be either "
                        "'call_tool' (with 'tool_name' and 'arguments') or 'final_answer' "
                        "(with 'final_answer'). Please respond again."
                    ),
                )
            )

        # 7. Tool-call budget or LLM round limit reached - synthesize answer
        return self._synthesize_final_answer(
            messages,
            executed_summaries,
            successful_outputs,
            iteration,
            grounding_requirement=grounding_requirement,
            session_id=session_id,
        )

    def _process_tool_call_batch(
        self,
        *,
        raw_calls: list[Any],
        raw_content: str,
        messages: list[ChatMessage],
        executed_summaries: list[ToolCallSummary],
        executed_calls_set: set[tuple[str, str]],
        successful_outputs: list[tuple[str, Any]],
        execution_steps: list[DependencyStep],
        tool_executions: int,
        grounding_requirement: tuple[str, ...] | None,
        iteration: int,
        session_id: str | None,
    ) -> tuple[int, AgentExecutionResult | None]:
        """Execute all tool calls returned in one native provider response.

        This path is only used by clients that emit the ``call_tools`` decision
        (currently the Gemini adapter). The single-call ``call_tool`` path used
        by Ollama and Qwen3 is left unchanged.
        """

        messages.append(ChatMessage(role=ChatRole.ASSISTANT, content=raw_content))

        # Only reject calls that repeat an earlier conversation turn. Identical
        # calls inside one native batch are allowed: Gemini can legitimately
        # request the same lookup more than once in a single response.
        previous_calls = set(executed_calls_set)

        for raw_call in raw_calls:
            tool_name, arguments = _parse_batch_call(raw_call)

            if tool_executions >= self.max_tool_calls:
                executed_summaries.append(
                    ToolCallSummary(
                        tool_name=tool_name or "unknown",
                        arguments=arguments,
                        status=ToolExecutionStatus.CANCELLED.value,
                    )
                )
                messages.append(
                    ChatMessage(
                        role=ChatRole.USER,
                        content=(
                            f"Tool `{tool_name or 'unknown'}` execution was "
                            "cancelled or timed out."
                        ),
                    )
                )
                continue

            if not tool_name or not self.registry.exists(tool_name):
                executed_summaries.append(
                    ToolCallSummary(
                        tool_name=tool_name or "unknown",
                        arguments=arguments,
                        status=ToolExecutionStatus.FAILED.value,
                        error=f"Unknown tool: {tool_name or 'unknown'}",
                    )
                )
                messages.append(
                    ChatMessage(
                        role=ChatRole.USER,
                        content=(
                            f"Tool `{tool_name or 'unknown'}` failed with error "
                            "[unknown_tool]: Tool is not recognized in the "
                            "approved ERP catalog."
                        ),
                    )
                )
                continue

            definition = self.registry.get(tool_name)

            # Resolve explicit $steps references before normalization. Calls in
            # one native batch execute in order, so a later call may reference
            # an earlier successful call in the same batch. A forward reference
            # to a later call in the batch is rejected.
            arguments, dependency_issues = resolve_argument_dependencies(
                arguments,
                definition,
                execution_steps,
            )
            if dependency_issues:
                messages.append(
                    ChatMessage(
                        role=ChatRole.USER,
                        content=format_dependency_feedback(dependency_issues),
                    )
                )
                continue

            arguments = normalize_tool_arguments(arguments, definition)

            args_key = json.dumps(arguments, sort_keys=True, default=str)
            call_sig = (tool_name, args_key)
            if call_sig in previous_calls:
                executed_summaries.append(
                    ToolCallSummary(
                        tool_name=tool_name,
                        arguments=arguments,
                        status=ToolExecutionStatus.FAILED.value,
                        error="Duplicate tool call with identical arguments.",
                    )
                )
                messages.append(
                    ChatMessage(
                        role=ChatRole.USER,
                        content=(
                            f"Tool `{tool_name}` was already called with "
                            f"arguments {arguments}. Do not repeat identical "
                            "calls."
                        ),
                    )
                )
                continue

            request = ToolExecutionRequest(tool_name=tool_name, arguments=arguments)
            result = self.runner.execute(request)
            executed_calls_set.add(call_sig)

            if result.started_at is not None:
                tool_executions += 1
                execution_steps.append(
                    DependencyStep(
                        step_number=len(execution_steps) + 1,
                        tool_name=tool_name,
                        status=result.status.value,
                        output=(
                            result.output
                            if result.status is ToolExecutionStatus.SUCCEEDED
                            else None
                        ),
                    )
                )

            executed_summaries.append(
                ToolCallSummary(
                    tool_name=tool_name,
                    arguments=arguments,
                    status=result.status.value,
                    duration_ms=result.duration_ms,
                    error=result.error.message if result.error else None,
                    output=(
                        result.output
                        if result.status is ToolExecutionStatus.SUCCEEDED
                        else None
                    ),
                )
            )

            if result.status is ToolExecutionStatus.SUCCEEDED:
                successful_outputs.append((tool_name, result.output))
                messages.append(
                    ChatMessage(
                        role=ChatRole.USER,
                        content=format_tool_output_message(
                            tool_name,
                            result.output,
                        ),
                    )
                )
            elif result.status is ToolExecutionStatus.FAILED:
                messages.append(
                    ChatMessage(
                        role=ChatRole.USER,
                        content="\n".join(
                            _failure_feedback_lines(tool_name, result)
                        ),
                    )
                )
            else:  # CANCELLED / TIMEOUT
                messages.append(
                    ChatMessage(
                        role=ChatRole.USER,
                        content=(
                            f"Tool `{tool_name}` execution was cancelled or "
                            "timed out."
                        ),
                    )
                )

        if grounding_requirement == (_WAREHOUSE_LIST_TOOL,):
            warehouse_list = _authoritative_warehouse_list(successful_outputs)
            if warehouse_list is not None:
                return tool_executions, AgentExecutionResult(
                    answer=warehouse_list,
                    tool_calls=executed_summaries,
                    status="completed",
                    iterations=iteration,
                    session_id=session_id,
                )

        if grounding_requirement == (_PRODUCT_COUNT_TOOL,):
            product_count = _authoritative_product_count(successful_outputs)
            if product_count is not None:
                return tool_executions, AgentExecutionResult(
                    answer=f"There are {product_count} products in the ERP.",
                    tool_calls=executed_summaries,
                    status="completed",
                    iterations=iteration,
                    session_id=session_id,
                )

        return tool_executions, None

    def _synthesize_final_answer(
        self,
        messages: list[ChatMessage],
        executed_summaries: list[ToolCallSummary],
        successful_outputs: list[tuple[str, Any]],
        iteration: int,
        *,
        grounding_requirement: tuple[str, ...] | None,
        session_id: str | None,
    ) -> AgentExecutionResult:
        """Compose a final answer after the loop budget was exhausted.

        The model gets one last chance to answer. If it fails, previously
        retrieved data is preserved in a deterministic summary so partial
        failures never invalidate successful tool results. Grounding rules
        are applied to synthesized answers exactly as they are to normal
        final answers.
        """

        reminder = (
            f"You have reached the maximum allowed tool calls ({self.max_tool_calls}). "
            "Please provide your final answer now based on the data retrieved so far, "
            "explaining any limitations."
        )
        if _used_dispatch_tools(executed_summaries):
            reminder += (
                " Clearly distinguish dispatched quantities (handed over to the "
                "carrier) from confirmed customer delivery, which this ERP does "
                "not track."
            )
        messages.append(ChatMessage(role=ChatRole.USER, content=reminder))

        final_text = ""
        try:
            final_resp = self.client.chat(messages, format="json", temperature=0.0)
            cleaned = _clean_json_text(final_resp.content)
            data = json.loads(cleaned)
            if isinstance(data, Mapping) and data.get("action") == "call_tools":
                for raw_call in data.get("tool_calls") or []:
                    tool_name, arguments = _parse_batch_call(raw_call)
                    executed_summaries.append(
                        ToolCallSummary(
                            tool_name=tool_name or "unknown",
                            arguments=arguments,
                            status=ToolExecutionStatus.CANCELLED.value,
                        )
                    )
            else:
                # Plans are not actionable once the budget is exhausted; drop
                # any plan so malformed metadata cannot block synthesis.
                final_payload = dict(data) if isinstance(data, Mapping) else data
                if isinstance(final_payload, dict):
                    final_payload.pop("execution_plan", None)
                final_decision = ToolSelectionDecision.model_validate(final_payload)
                final_text = (final_decision.final_answer or "").strip()
        except Exception:
            final_text = ""

        if final_text:
            # When verified tool data exists and the model's answer would be
            # returned verbatim (no authoritative replacement), prefer the
            # deterministic fallback so an incomplete model answer cannot drop
            # relevant successful ERP outputs. The normal in-loop final_answer
            # path is left untouched. Product count and warehouse list answers
            # keep their authoritative replacement because _grounded_answer
            # already renders them from verified tool data.
            verbatim_case = grounding_requirement is None or grounding_requirement not in (
                (_PRODUCT_COUNT_TOOL,),
                (_WAREHOUSE_LIST_TOOL,),
            )
            evidence_ok = grounding_requirement is None or _has_required_evidence(
                grounding_requirement, successful_outputs
            )
            if successful_outputs and verbatim_case and evidence_ok:
                return AgentExecutionResult(
                    answer=self._fallback_answer(executed_summaries, successful_outputs),
                    tool_calls=executed_summaries,
                    status="completed",
                    iterations=iteration,
                    session_id=session_id,
                )
            answer, status, error = _grounded_answer(
                grounding_requirement,
                final_text,
                successful_outputs,
                executed_summaries,
            )
            return AgentExecutionResult(
                answer=answer,
                tool_calls=executed_summaries,
                status=status,
                error=error,
                iterations=iteration,
                session_id=session_id,
            )

        if grounding_requirement == (_PRODUCT_COUNT_TOOL,):
            answer, status, error = _grounded_answer(
                grounding_requirement,
                "",
                successful_outputs,
                executed_summaries,
            )
            return AgentExecutionResult(
                answer=answer,
                tool_calls=executed_summaries,
                status=status,
                error=error,
                iterations=iteration,
                session_id=session_id,
            )

        if grounding_requirement is not None and not _has_required_evidence(
            grounding_requirement,
            successful_outputs,
        ):
            answer, status, error = _grounded_answer(
                grounding_requirement,
                "",
                successful_outputs,
                executed_summaries,
            )
            return AgentExecutionResult(
                answer=answer,
                tool_calls=executed_summaries,
                status=status,
                error=error,
                iterations=iteration,
                session_id=session_id,
            )

        return AgentExecutionResult(
            answer=self._fallback_answer(executed_summaries, successful_outputs),
            tool_calls=executed_summaries,
            status="incomplete",
            iterations=iteration,
            session_id=session_id,
        )

    def _llm_failure_result(
        self,
        *,
        error: str,
        timeout: bool,
        executed_summaries: list[ToolCallSummary],
        successful_outputs: list[tuple[str, Any]],
        grounding_requirement: tuple[str, ...] | None,
        iteration: int,
        session_id: str | None,
    ) -> AgentExecutionResult:
        """Return verified tool data when the LLM fails after a successful call."""

        if grounding_requirement is not None and not _has_required_evidence(
            grounding_requirement,
            successful_outputs,
        ):
            answer, status, grounding_error = _grounded_answer(
                grounding_requirement,
                "",
                successful_outputs,
                executed_summaries,
            )
            return AgentExecutionResult(
                answer=answer,
                tool_calls=executed_summaries,
                status=status,
                error=grounding_error,
                iterations=iteration,
                session_id=session_id,
            )

        if grounding_requirement == (_PRODUCT_COUNT_TOOL,):
            product_count = _authoritative_product_count(successful_outputs)
            if product_count is None:
                answer, status, grounding_error = _grounded_answer(
                    grounding_requirement,
                    "",
                    successful_outputs,
                    executed_summaries,
                )
                return AgentExecutionResult(
                    answer=answer,
                    tool_calls=executed_summaries,
                    status=status,
                    error=grounding_error,
                    iterations=iteration,
                    session_id=session_id,
                )
            return AgentExecutionResult(
                answer=f"There are {product_count} products in the ERP.",
                tool_calls=executed_summaries,
                status="incomplete",
                error=error,
                iterations=iteration,
                session_id=session_id,
            )

        intro = (
            "The AI service timed out before a final answer could be composed. "
            "The following data was successfully retrieved:"
            if timeout
            else "The AI service encountered an error before a final answer could be composed. "
            "The following data was successfully retrieved:"
        )
        return AgentExecutionResult(
            answer=self._fallback_answer(
                executed_summaries,
                successful_outputs,
                intro=intro,
            ),
            tool_calls=executed_summaries,
            status="incomplete",
            error=error,
            iterations=iteration,
            session_id=session_id,
        )

    @staticmethod
    def _fallback_answer(
        executed_summaries: list[ToolCallSummary],
        successful_outputs: list[tuple[str, Any]],
        *,
        intro: str = (
            "The tool-call limit was reached before a final answer could be "
            "composed. The following data was successfully retrieved:"
        ),
    ) -> str:
        """Grounded deterministic answer used when the model cannot compose one."""

        lines: list[str] = [intro]
        for tool_name, output in successful_outputs:
            analytics_lines = _analytics_fallback_lines(tool_name, output)
            if analytics_lines is not None:
                lines.append("")
                lines.extend(analytics_lines)
                continue

            simple_lines = _simple_table_fallback_lines(tool_name, output)
            if simple_lines is not None:
                rendered = "\n".join(simple_lines)
                if len(rendered) > _MAX_FALLBACK_OUTPUT_CHARS:
                    rendered = rendered[:_MAX_FALLBACK_OUTPUT_CHARS] + "... (truncated)"
                lines.append("")
                lines.append(f"`{tool_name}`:")
                lines.extend(rendered.split("\n"))
                continue

            rendered = json.dumps(output, ensure_ascii=False, default=str)
            if len(rendered) > _MAX_FALLBACK_OUTPUT_CHARS:
                rendered = rendered[:_MAX_FALLBACK_OUTPUT_CHARS] + "... (truncated)"
            lines.append(f"- `{tool_name}`: {rendered}")
        if not successful_outputs:
            lines.append("- No tool data could be retrieved.")

        failed = [
            f"`{summary.tool_name}` ({summary.error or summary.status})"
            for summary in executed_summaries
            if summary.status != ToolExecutionStatus.SUCCEEDED.value
        ]
        if failed:
            lines.append(
                "Tool calls that did not return data: " + ", ".join(failed)
            )
        if _used_dispatch_tools(executed_summaries):
            lines.append(_DELIVERY_SEMANTICS_NOTE)
        return "\n".join(lines)
