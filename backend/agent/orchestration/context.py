"""Bounded model-facing projection of ERP tool outputs (Phase 3A).

The orchestrator keeps the full raw tool output for grounding, API responses,
charts, and Phase 2 ``$steps`` dependency resolution. Only the message sent to
the reasoning model is bounded by this module.

The projection is intentionally conservative:

* dictionaries are copied, never mutated;
* large record lists are shortened before any final compact representation;
* scalar metadata such as ``row_count``, ``truncated``, ``totals``, and
  ``notes`` is preserved when it fits;
* every returned value is JSON-serializable;
* the complete message, including the existing ``Tool `name` output:`` prefix,
  never exceeds ``MAX_TOOL_OUTPUT_MESSAGE_CHARS``.

Context truncation is deliberately separate from ERP-level truncation. A result
may contain both ``truncated: true`` (the ERP itself limited the rows) and
``context_truncated: true`` (only part of the returned rows were shown to the
model).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

# Conservative defaults. These are module constants, not environment
# variables, so deployment behavior stays predictable.
MAX_TOOL_OUTPUT_MESSAGE_CHARS = 6000
MAX_TOP_LEVEL_LIST_ITEMS = 10
MAX_NESTED_LIST_ITEMS = 3

# Small metadata lists such as analytics ``notes`` stay useful even when record
# lists are heavily bounded.
MAX_METADATA_LIST_ITEMS = 5
MAX_PROJECTION_DEPTH = 8
MAX_FINAL_STRING_CHARS = 120

CONTEXT_NOTE = (
    "Displayed list entries are only a subset of the tool result. "
    "Do not claim that omitted records do not exist. "
    "This is context truncation, not ERP-level data truncation."
)

_METADATA_LIST_KEYS = frozenset({"notes", "warnings", "errors"})

_SCALAR_METADATA_KEYS = (
    "row_count",
    "truncated",
    "items_row_count",
    "items_truncated",
    "dispatches_row_count",
    "dispatches_truncated",
    "product_count",
    "group_by",
    "basis",
    "currency",
    "so_id",
    "dispatch_id",
    "product_id",
)


@dataclass
class _ProjectionStats:
    """Aggregate list statistics across one projection attempt."""

    shown: int = 0
    omitted: int = 0
    truncated: bool = False


def estimate_tokens(text: str) -> int:
    """Return a cheap approximate token count for logging and guardrails.

    This is a heuristic only (roughly four characters per token). It is never
    used to hard-truncate model output.
    """

    if not text:
        return 0
    return len(text) // 4


def format_tool_output_message(
    tool_name: str,
    output: Any,
    *,
    max_chars: int = MAX_TOOL_OUTPUT_MESSAGE_CHARS,
) -> str:
    """Build the model-facing tool result message with the existing prefix.

    The content after the prefix is always valid JSON so the Gemini adapter's
    ``_tool_feedback_payload`` parser can continue to reconstruct native tool
    responses.
    """

    name = str(tool_name)
    prefix = f"Tool `{name}` output:\n"
    if len(prefix) >= max_chars:
        # Tool names are bounded by the registry, but stay safe if a caller
        # supplies an unexpectedly long value.
        name = "tool"
        prefix = f"Tool `{name}` output:\n"

    budget = max(1, max_chars - len(prefix))
    projected = project_tool_output(name, output, max_chars=budget)
    serialized = _serialize(projected)

    if len(serialized) > budget:
        # ``project_tool_output`` already enforces the budget, but keep a final
        # guard so the prefix + JSON contract is never violated.
        projected = _final_compact(output, budget)
        serialized = _serialize(projected)

    if len(serialized) > budget:
        projected = _minimal_compact(output, budget)
        serialized = _serialize(projected)

    return prefix + serialized


def project_tool_output(
    tool_name: str,
    output: Any,
    *,
    max_chars: int = MAX_TOOL_OUTPUT_MESSAGE_CHARS,
    top_level_limit: int = MAX_TOP_LEVEL_LIST_ITEMS,
    nested_limit: int = MAX_NESTED_LIST_ITEMS,
) -> Any:
    """Return a bounded, JSON-serializable copy of ``output``.

    ``tool_name`` is accepted for symmetry with the message formatter and for
    future per-tool tuning; it does not alter the projection today.
    """

    del tool_name  # Reserved for future per-tool projection rules.

    budget = max(256, int(max_chars))

    for current_top, current_nested in _limit_candidates(
        top_level_limit,
        nested_limit,
    ):
        stats = _ProjectionStats()
        projected, shown, omitted, truncated = _project_value(
            output,
            depth=0,
            top_limit=current_top,
            nested_limit=current_nested,
            stats=stats,
        )
        projected = _attach_root_metadata(
            projected,
            local_shown=shown,
            local_omitted=omitted,
            local_truncated=truncated,
            stats=stats,
        )
        if len(_serialize(projected)) <= budget:
            return projected

    return _final_compact(output, budget)


def _limit_candidates(
    top_limit: int,
    nested_limit: int,
) -> list[tuple[int, int]]:
    """Return progressively smaller list limits, largest first."""

    candidates: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    current = (max(0, int(top_limit)), max(0, int(nested_limit)))

    while True:
        if current not in seen:
            seen.add(current)
            candidates.append(current)
        if current == (0, 0):
            break
        next_top = 0 if current[0] <= 1 else current[0] // 2
        next_nested = 0 if current[1] <= 1 else current[1] // 2
        if (next_top, next_nested) == current:
            break
        current = (next_top, next_nested)

    return candidates


def _project_value(
    value: Any,
    *,
    depth: int,
    top_limit: int,
    nested_limit: int,
    stats: _ProjectionStats,
) -> tuple[Any, int, int, bool]:
    """Project one value and return ``(value, shown, omitted, truncated)``."""

    if depth > MAX_PROJECTION_DEPTH:
        return _depth_marker(value), 0, 0, True

    if isinstance(value, Mapping):
        return _project_mapping(
            value,
            depth=depth,
            top_limit=top_limit,
            nested_limit=nested_limit,
            stats=stats,
        )

    if isinstance(value, (list, tuple)):
        projected, shown, omitted, truncated = _project_sequence(
            value,
            depth=depth,
            limit=top_limit if depth == 0 else nested_limit,
            top_limit=top_limit,
            nested_limit=nested_limit,
            stats=stats,
        )
        return projected, shown, omitted, truncated

    return _json_safe_scalar(value), 0, 0, False


def _project_mapping(
    mapping: Mapping[Any, Any],
    *,
    depth: int,
    top_limit: int,
    nested_limit: int,
    stats: _ProjectionStats,
) -> tuple[dict[str, Any], int, int, bool]:
    """Project a dictionary, bounding its direct list values."""

    result: dict[str, Any] = {}
    local_shown = 0
    local_omitted = 0
    local_truncated = False

    for key, value in mapping.items():
        key_text = key if isinstance(key, str) else str(key)

        if isinstance(value, (list, tuple)):
            limit = _list_limit(
                key_text,
                depth=depth,
                top_limit=top_limit,
                nested_limit=nested_limit,
            )
            projected_list, shown, omitted, truncated = _project_sequence(
                value,
                depth=depth + 1,
                limit=limit,
                top_limit=top_limit,
                nested_limit=nested_limit,
                stats=stats,
            )
            result[key_text] = projected_list
            local_shown += shown
            local_omitted += omitted
            local_truncated = local_truncated or truncated
            continue

        if isinstance(value, Mapping):
            projected_child, _, _, _ = _project_value(
                value,
                depth=depth + 1,
                top_limit=top_limit,
                nested_limit=nested_limit,
                stats=stats,
            )
            result[key_text] = projected_child
            continue

        result[key_text] = _json_safe_scalar(value)

    if local_truncated and depth > 0:
        result["context_truncated"] = True
        result["context_items_shown"] = local_shown
        result["context_items_omitted"] = local_omitted

    return result, local_shown, local_omitted, local_truncated


def _project_sequence(
    sequence: list[Any] | tuple[Any, ...],
    *,
    depth: int,
    limit: int,
    top_limit: int,
    nested_limit: int,
    stats: _ProjectionStats,
) -> tuple[list[Any], int, int, bool]:
    """Project a list/tuple, keeping at most ``limit`` entries."""

    original_length = len(sequence)
    safe_limit = max(0, int(limit))
    truncated = original_length > safe_limit
    items = list(sequence[:safe_limit]) if truncated else list(sequence)

    projected_items: list[Any] = []
    for item in items:
        projected_item, _, _, _ = _project_value(
            item,
            depth=depth + 1,
            top_limit=top_limit,
            nested_limit=nested_limit,
            stats=stats,
        )
        projected_items.append(projected_item)

    shown = len(projected_items)
    omitted = max(0, original_length - shown)

    stats.shown += shown
    stats.omitted += omitted
    stats.truncated = stats.truncated or truncated

    return projected_items, shown, omitted, truncated


def _list_limit(
    key: str,
    *,
    depth: int,
    top_limit: int,
    nested_limit: int,
) -> int:
    if key in _METADATA_LIST_KEYS:
        return MAX_METADATA_LIST_ITEMS
    return top_limit if depth == 0 else nested_limit


def _attach_root_metadata(
    projected: Any,
    *,
    local_shown: int,
    local_omitted: int,
    local_truncated: bool,
    stats: _ProjectionStats,
) -> Any:
    """Add root-level context metadata when anything was bounded."""

    if not local_truncated and not stats.truncated:
        return projected

    shown = local_shown if local_truncated else stats.shown
    omitted = local_omitted if local_truncated else stats.omitted

    metadata = {
        "context_truncated": True,
        "context_items_shown": shown,
        "context_items_omitted": omitted,
        "context_note": CONTEXT_NOTE,
    }

    if isinstance(projected, Mapping):
        result = dict(projected)
        result.update(metadata)
        return result

    if isinstance(projected, list):
        return {"items": projected, **metadata}

    return projected


def _depth_marker(value: Any) -> dict[str, Any]:
    return {
        "context_truncated": True,
        "context_items_shown": 0,
        "context_items_omitted": _count_list_entries(value),
    }


def _final_compact(output: Any, max_chars: int) -> Any:
    """Build a compact representation when list reduction alone is not enough."""

    omitted = _count_list_entries(output)
    base: dict[str, Any] = {
        "context_truncated": True,
        "context_items_shown": 0,
        "context_items_omitted": omitted,
        "context_note": CONTEXT_NOTE,
    }

    if len(_serialize(base)) > max_chars:
        base.pop("context_note", None)
    if len(_serialize(base)) > max_chars:
        base = {
            "context_truncated": True,
            "context_items_omitted": omitted,
        }

    if isinstance(output, Mapping):
        result = dict(base)

        for key in _SCALAR_METADATA_KEYS:
            if key not in output:
                continue
            value = output[key]
            if not _is_scalar(value):
                continue
            candidate = dict(result)
            candidate[key] = _truncate_string(value, MAX_FINAL_STRING_CHARS)
            if len(_serialize(candidate)) <= max_chars:
                result = candidate

        totals = output.get("totals")
        if isinstance(totals, Mapping):
            candidate = dict(result)
            candidate["totals"] = _compact_mapping(
                totals,
                string_limit=MAX_FINAL_STRING_CHARS,
            )
            if len(_serialize(candidate)) <= max_chars:
                result = candidate

        notes = output.get("notes")
        if isinstance(notes, (list, tuple)):
            candidate = dict(result)
            candidate["notes"] = [
                _truncate_string(note, MAX_FINAL_STRING_CHARS)
                for note in list(notes)[:MAX_METADATA_LIST_ITEMS]
            ]
            if len(_serialize(candidate)) <= max_chars:
                result = candidate

        # Preserve small nested scalar mappings such as a sales-order header.
        for key, value in output.items():
            key_text = key if isinstance(key, str) else str(key)
            if key_text in result or key_text in {"totals", "notes"}:
                continue
            if not isinstance(value, Mapping):
                continue
            candidate = dict(result)
            candidate[key_text] = _compact_mapping(
                value,
                string_limit=MAX_FINAL_STRING_CHARS,
            )
            if len(_serialize(candidate)) <= max_chars:
                result = candidate

        for key, value in output.items():
            key_text = key if isinstance(key, str) else str(key)
            if key_text in result or key_text in {"totals", "notes"}:
                continue
            if not _is_scalar(value):
                continue
            candidate = dict(result)
            candidate[key_text] = _truncate_string(
                value,
                MAX_FINAL_STRING_CHARS,
            )
            if len(_serialize(candidate)) <= max_chars:
                result = candidate

        return result

    if isinstance(output, (list, tuple)):
        return {
            "items": [],
            "context_truncated": True,
            "context_items_shown": 0,
            "context_items_omitted": len(output),
            "context_note": CONTEXT_NOTE,
        }

    # Leave room for the metadata fields around the value string.
    text_budget = max(1, max_chars - 512)
    text = _truncate_string(str(output), text_budget)
    result: dict[str, Any] = {
        "value": text,
        "context_truncated": True,
        "context_items_shown": 0,
        "context_items_omitted": 0,
        "context_note": CONTEXT_NOTE,
    }
    if len(_serialize(result)) > max_chars:
        return _minimal_compact(output, max_chars)
    return result


def _minimal_compact(output: Any, max_chars: int) -> dict[str, Any]:
    """Last-resort compact object that is guaranteed to fit."""

    result: dict[str, Any] = {
        "context_truncated": True,
        "context_items_omitted": _count_list_entries(output),
    }
    if len(_serialize(result)) > max_chars:
        return {"context_truncated": True}

    if isinstance(output, Mapping):
        for key in _SCALAR_METADATA_KEYS:
            if key not in output:
                continue
            value = output[key]
            if not _is_scalar(value):
                continue
            candidate = dict(result)
            candidate[key] = _truncate_string(value, 80)
            if len(_serialize(candidate)) <= max_chars:
                result = candidate

    return result


def _compact_mapping(
    mapping: Mapping[Any, Any],
    *,
    string_limit: int,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in mapping.items():
        key_text = key if isinstance(key, str) else str(key)
        if _is_scalar(value):
            result[key_text] = _truncate_string(value, string_limit)
        elif isinstance(value, (list, tuple)):
            result[key_text] = {
                "context_truncated": True,
                "context_items_shown": 0,
                "context_items_omitted": len(value),
            }
        elif isinstance(value, Mapping):
            result[key_text] = _compact_mapping(
                value,
                string_limit=string_limit,
            )
        else:
            result[key_text] = _truncate_string(str(value), string_limit)
    return result


def _count_list_entries(value: Any) -> int:
    if isinstance(value, Mapping):
        return sum(_count_list_entries(child) for child in value.values())
    if isinstance(value, (list, tuple)):
        return len(value) + sum(_count_list_entries(child) for child in value)
    return 0


def _is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _json_safe_scalar(value: Any) -> Any:
    if _is_scalar(value):
        return value
    return str(value)


def _truncate_string(value: Any, limit: int) -> Any:
    if not isinstance(value, str):
        return value
    if len(value) <= limit:
        return value
    suffix = "... (truncated)"
    keep = max(0, limit - len(suffix))
    return value[:keep] + suffix


def _serialize(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        default=str,
        separators=(",", ":"),
    )


__all__ = [
    "CONTEXT_NOTE",
    "MAX_NESTED_LIST_ITEMS",
    "MAX_TOOL_OUTPUT_MESSAGE_CHARS",
    "MAX_TOP_LEVEL_LIST_ITEMS",
    "estimate_tokens",
    "format_tool_output_message",
    "project_tool_output",
]
