"""Deterministic heading-aware chunking for the RAG knowledge corpus.

Pipeline
--------
``KnowledgeDocument.body`` is normalized (line endings, trailing whitespace,
blank-line runs), scanned into heading-scoped sections by a fenced-code-aware
state machine, split when oversized, merged when tiny, filtered, then
materialized as immutable :class:`~backend.agent.rag.models.KnowledgeChunk`
values.

Splitting an oversized section tries, in order: paragraph boundaries, sentence
boundaries, whitespace, then a hard cut at the limit. The final fragment of a
section is never left below ``MIN_MEANINGFUL_CHARS`` non-whitespace characters
when the source text has enough content to avoid it, so meaningful prose is not
discarded at a split boundary.

Merging joins a group shorter than ``min_chunk_chars`` with the next group
sharing the same ``section_path`` (or the previous one when it is last). A
group without a same-path sibling is kept as-is. Groups with fewer than
``MIN_MEANINGFUL_CHARS`` non-whitespace characters are dropped afterwards.

Searchable text for a chunk is ``title + section_path + text`` (see
:func:`searchable_text`). ``token_count`` counts exactly that composition, so
the BM25 index can reproduce it without the original document.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from backend.agent.rag.config import (
    DEFAULT_MAX_CHUNK_CHARS,
    DEFAULT_MIN_CHUNK_CHARS,
    MAX_CHUNK_SIZE,
)
from backend.agent.rag.models import KnowledgeChunk, KnowledgeDocument
from backend.agent.rag.text import slugify, tokenize

MIN_MEANINGFUL_CHARS = 20
MAX_CHUNKS_PER_SECTION = 99

_HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)(?:[ \t]+#+)?[ \t]*$")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_SENTENCE_BREAKS = (". ", "! ", "? ")


@dataclass
class _Section:
    section_path: tuple[str, ...]
    lines: list[str]


@dataclass(frozen=True)
class _Group:
    section_path: tuple[str, ...]
    text: str


def _non_ws_len(text: str) -> int:
    return sum(1 for character in text if not character.isspace())


def _normalize_lines(body: str) -> list[str]:
    """Normalize line endings, trailing whitespace, and blank-line runs."""

    text = body.replace("\r\n", "\n").replace("\r", "\n")
    lines: list[str] = []
    blank_run = 0
    for raw_line in text.split("\n"):
        line = raw_line.rstrip()
        if line == "":
            blank_run += 1
            if blank_run > 1:
                continue
        else:
            blank_run = 0
        lines.append(line)

    while lines and lines[0] == "":
        lines.pop(0)
    while lines and lines[-1] == "":
        lines.pop()
    return lines


def _append_section(sections: list[_Section], section: _Section) -> None:
    if any(line.strip() for line in section.lines):
        sections.append(section)


def _scan_sections(lines: list[str]) -> list[_Section]:
    """Split normalized lines into sections without honouring fenced headings."""

    sections: list[_Section] = []
    stack: list[tuple[int, str]] = []
    current = _Section((), [])
    in_fence = False
    fence_char = ""
    fence_len = 0

    for line in lines:
        if in_fence:
            current.lines.append(line)
            match = _FENCE.match(line)
            if (
                match is not None
                and match.group(1)[0] == fence_char
                and len(match.group(1)) >= fence_len
                and not match.group(2).strip()
            ):
                in_fence = False
            continue

        fence = _FENCE.match(line)
        if fence is not None:
            in_fence = True
            fence_char = fence.group(1)[0]
            fence_len = len(fence.group(1))
            current.lines.append(line)
            continue

        heading = _HEADING.match(line)
        if heading is not None:
            _append_section(sections, current)
            level = len(heading.group(1))
            title = heading.group(2).strip()
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
            current = _Section(
                tuple(stack_title for _, stack_title in stack),
                [title],
            )
            continue

        current.lines.append(line)

    _append_section(sections, current)
    return sections


def _meaningful_part(text: str, cut: int) -> bool:
    return cut > 0 and _non_ws_len(text[:cut]) >= MIN_MEANINGFUL_CHARS


def _last_paragraph_boundary(text: str, limit: int) -> int | None:
    end = limit
    while True:
        index = text.rfind("\n\n", 0, end)
        if index <= 0:
            return None
        if _meaningful_part(text, index):
            return index
        end = index


def _last_sentence_boundary(text: str, limit: int) -> int | None:
    best: int | None = None
    for marker in _SENTENCE_BREAKS:
        end = limit
        while True:
            index = text.rfind(marker, 0, end)
            if index <= 0:
                break
            cut = index + 1
            if _meaningful_part(text, cut):
                if best is None or cut > best:
                    best = cut
                break
            end = index
    return best


def _last_whitespace_boundary(text: str, limit: int) -> int | None:
    end = limit
    while end > 0:
        index = max(
            text.rfind(" ", 0, end),
            text.rfind("\n", 0, end),
            text.rfind("\t", 0, end),
        )
        if index <= 0:
            return None
        if _meaningful_part(text, index):
            return index
        end = index
    return None


def _find_split_index(text: str, limit: int) -> int:
    """Choose the highest-priority boundary at or before ``limit``."""

    paragraph = _last_paragraph_boundary(text, limit)
    if paragraph is not None:
        return paragraph

    sentence = _last_sentence_boundary(text, limit)
    if sentence is not None:
        return sentence

    whitespace = _last_whitespace_boundary(text, limit)
    if whitespace is not None:
        return whitespace

    return limit


def _tail_start_for_non_ws(text: str, required: int) -> int | None:
    """Index of the ``required``-th non-whitespace character from the end."""

    count = 0
    for index in range(len(text) - 1, -1, -1):
        if not text[index].isspace():
            count += 1
            if count == required:
                return index
    return None


def _split_oversized(text: str, limit: int) -> list[str]:
    """Split ``text`` into ordered parts no longer than ``limit``."""

    if len(text) <= limit:
        return [text]

    parts: list[str] = []
    remaining = text
    while len(remaining) > limit:
        cut = _find_split_index(remaining, limit)

        # Do not strand a final fragment below the meaningful threshold.
        if _non_ws_len(remaining[cut:]) < MIN_MEANINGFUL_CHARS:
            adjusted = _tail_start_for_non_ws(remaining, MIN_MEANINGFUL_CHARS)
            if (
                adjusted is not None
                and 0 < adjusted < cut
                and _non_ws_len(remaining[:adjusted]) >= MIN_MEANINGFUL_CHARS
            ):
                cut = adjusted

        part = remaining[:cut].rstrip()
        remaining = remaining[cut:].lstrip()
        if part:
            parts.append(part)

    if remaining.strip():
        parts.append(remaining.strip())
    return parts


def _join_text(left: str, right: str) -> str:
    if not left:
        return right
    if not right:
        return left
    return f"{left}\n\n{right}"


def _merge_small_groups(
    groups: list[_Group],
    *,
    min_chunk_chars: int,
    max_chunk_chars: int,
) -> list[_Group]:
    merged: list[_Group] = []
    index = 0
    while index < len(groups):
        group = groups[index]
        if len(group.text) >= min_chunk_chars:
            merged.append(group)
            index += 1
            continue

        next_index: int | None = None
        for candidate in range(index + 1, len(groups)):
            if groups[candidate].section_path == group.section_path:
                next_index = candidate
                break
        if next_index is not None:
            target = groups[next_index]
            combined = _join_text(group.text, target.text)
            if len(combined) <= max_chunk_chars:
                groups[next_index] = _Group(target.section_path, combined)
                index += 1
                continue

        previous_index: int | None = None
        for candidate in range(len(merged) - 1, -1, -1):
            if merged[candidate].section_path == group.section_path:
                previous_index = candidate
                break
        if previous_index is not None:
            target = merged[previous_index]
            combined = _join_text(target.text, group.text)
            if len(combined) <= max_chunk_chars:
                merged[previous_index] = _Group(target.section_path, combined)
                index += 1
                continue

        merged.append(group)
        index += 1
    return merged


def _validate_size(value: object, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    if value < minimum or value > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def searchable_text(chunk: KnowledgeChunk) -> str:
    """Return the exact text whose tokens populate the BM25 index."""

    section = " > ".join(chunk.section_path) or "Overview"
    return f"{chunk.title}\n{section}\n{chunk.text}"


def chunk_document(
    doc: KnowledgeDocument,
    *,
    max_chunk_chars: int = DEFAULT_MAX_CHUNK_CHARS,
    min_chunk_chars: int = DEFAULT_MIN_CHUNK_CHARS,
) -> tuple[KnowledgeChunk, ...]:
    """Return the deterministic chunk sequence for one knowledge document."""

    if not isinstance(doc, KnowledgeDocument):
        raise TypeError("doc must be a KnowledgeDocument")

    max_chars = _validate_size(
        max_chunk_chars,
        "max_chunk_chars",
        1,
        MAX_CHUNK_SIZE,
    )
    min_chars = _validate_size(
        min_chunk_chars,
        "min_chunk_chars",
        0,
        max_chars,
    )

    lines = _normalize_lines(doc.body)
    sections = _scan_sections(lines)

    groups: list[_Group] = []
    for section in sections:
        text = "\n".join(section.lines).strip("\n")
        if not text.strip():
            continue
        for part in _split_oversized(text, max_chars):
            stripped = part.strip()
            if stripped:
                groups.append(_Group(section.section_path, stripped))

    groups = _merge_small_groups(
        groups,
        min_chunk_chars=min_chars,
        max_chunk_chars=max_chars,
    )

    notable_groups = [
        group
        for group in groups
        if _non_ws_len(group.text) >= MIN_MEANINGFUL_CHARS
    ]

    ordinals: dict[str, int] = {}
    chunks: list[KnowledgeChunk] = []
    for group in notable_groups:
        text = group.text.strip()
        if len(text) > max_chars:
            raise ValueError("chunking produced an oversized chunk")

        leaf_heading = group.section_path[-1] if group.section_path else ""
        section_slug = slugify(leaf_heading or "overview", max_len=40)
        ordinal = ordinals.get(section_slug, 0) + 1
        if ordinal > MAX_CHUNKS_PER_SECTION:
            raise ValueError(
                "section produced more than "
                f"{MAX_CHUNKS_PER_SECTION} chunks: {section_slug}"
            )
        ordinals[section_slug] = ordinal

        section_display = " > ".join(group.section_path) or "Overview"
        searchable = f"{doc.title}\n{section_display}\n{text}"

        chunks.append(
            KnowledgeChunk(
                chunk_id=f"{doc.doc_id}#{section_slug}#{ordinal:02d}",
                doc_id=doc.doc_id,
                title=doc.title,
                section_path=group.section_path,
                category=doc.category,
                fact_kind=doc.fact_kind,
                text=text,
                token_count=len(tokenize(searchable)),
                source_path=doc.source_path,
                updated_at=doc.updated_at,
            )
        )

    return tuple(chunks)


__all__ = [
    "DEFAULT_MAX_CHUNK_CHARS",
    "DEFAULT_MIN_CHUNK_CHARS",
    "MIN_MEANINGFUL_CHARS",
    "chunk_document",
    "searchable_text",
]
