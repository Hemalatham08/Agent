"""Deterministic loader for the version-controlled Markdown knowledge corpus.

A knowledge document is a UTF-8 Markdown file inside one of the approved
category directories. It starts with strict, flat front matter::

    ---
    doc_id: free-stock
    title: Free Stock, Reserved Stock, and Low Stock
    category: business_definitions
    fact_kind: definition
    version: 1.0.0
    updated_at: 2026-11-01
    summary: How free stock relates to on-hand stock and reorder levels.
    tags: [stock, reorder level]
    aliases: [available stock]
    ---

Rules enforced while loading:

* the file stem must equal ``doc_id``;
* ``category`` must be an approved category and match the directory name;
* unknown, duplicate, or missing front matter fields are rejected;
* the corpus is bounded by document count, total bytes, and body characters;
* bodies are scanned for live ERP facts (currency, quantities, counts,
  identifiers) before chunking;
* every document must produce at least one meaningful chunk.

Loading is pure filesystem work: no ERP database, network, LLM, or external
service is involved. Ordering, hashing, and the resulting
:class:`~backend.agent.rag.models.CorpusBundle` are byte-for-byte
deterministic for a given corpus.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from backend.agent.rag.chunking import (
    DEFAULT_MAX_CHUNK_CHARS,
    DEFAULT_MIN_CHUNK_CHARS,
    chunk_document,
)
from backend.agent.rag.config import MAX_CORPUS_BYTES, MAX_DOCS, RagConfig
from backend.agent.rag.errors import RagCorpusError
from backend.agent.rag.models import CorpusBundle, KnowledgeDocument

CATEGORIES: tuple[str, ...] = (
    "erp_docs",
    "business_definitions",
    "workflows",
    "policies_faqs",
    "schema",
)

REQUIRED_FIELDS: tuple[str, ...] = (
    "doc_id",
    "title",
    "category",
    "fact_kind",
    "version",
    "updated_at",
    "summary",
)

OPTIONAL_FIELDS: tuple[str, ...] = ("tags", "aliases")
ALLOWED_FIELDS: tuple[str, ...] = REQUIRED_FIELDS + OPTIONAL_FIELDS
LIST_FIELDS: tuple[str, ...] = ("tags", "aliases")

FRONT_MATTER_DELIMITER = "---"
ALLOW_LINE_MARKER = "rag-lint: allow-line"
MAX_BODY_CHARS = 20_000
INDEX_VERSION_CHARS = 12
MAX_EXCERPT_CHARS = 120

_FRONT_MATTER_LINE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*):(?:[ \t]*(.*))?$")
_INLINE_CODE = re.compile(r"`[^`\n]*`")

# Live ERP fact patterns. Each rule is deliberately narrow so that conceptual
# prose passes; the escape hatch exists for documented examples.
_CURRENCY = re.compile(
    r"(?:[$€£¥₹]\s*\d)"
    r"|(?:\b(?:usd|eur|gbp|inr|jpy|aud|cad|rs\.?)\s*\d)",
    re.IGNORECASE,
)
_UNIT = (
    r"(?:units?|pcs|pieces?|boxes?|cartons?|pallets?|kg|kilograms?"
    r"|litres?|liters?|metres?|meters?|dozens?)"
)
_QUANTITY = re.compile(rf"\b\d[\d,.]*\s*{_UNIT}\b", re.IGNORECASE)
_COUNT_WORD = (
    r"(?:products?|orders?|invoices?|customers?|suppliers?|dispatches"
    r"|skus?|records?|users?|employees?|items?)"
)
_COUNT = re.compile(rf"\b\d[\d,.]*\s+{_COUNT_WORD}\b", re.IGNORECASE)
_STOCK_VALUE = re.compile(
    r"\b(?:stock|quantity|quantities|qty|on[ -]?hand|inventory|balance"
    r"|balances|amount|amounts|total|totals)\b"
    r"[^.\n]{0,40}?\b\d[\d,.]*\b",
    re.IGNORECASE,
)
_RECORD_ID = re.compile(
    r"\b(?:order|invoice|dispatch|delivery|receipt|customer|supplier"
    r"|product|sku|purchase\s+order)\b"
    r"\s*(?:no\.?|number|#)\s*[a-z0-9-]*\d{2,}\b"
    r"|\b#[a-z]*\d{2,}\b",
    re.IGNORECASE,
)

LIVE_FACT_RULES: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("L1", _CURRENCY, "a currency amount"),
    ("L2", _QUANTITY, "a numeric quantity with a unit"),
    ("L3", _COUNT, "a numeric record count"),
    ("L4", _STOCK_VALUE, "a numeric stock, quantity, or total value"),
    ("L5", _RECORD_ID, "a specific record identifier"),
)


@dataclass(frozen=True)
class LiveFactViolation:
    """One detected live-fact expression, with a 1-based text line."""

    line: int
    rule: str
    excerpt: str


def find_live_fact_violations(text: str) -> tuple[LiveFactViolation, ...]:
    """Return live ERP fact candidates found in ``text``.

    Inline code spans are ignored because they usually hold column or field
    names. Fenced blocks are **not** ignored: a SQL sample must not smuggle in
    live values. A line containing ``rag-lint: allow-line`` is exempt.
    """

    if not isinstance(text, str):
        raise TypeError("text must be a string")

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    violations: list[LiveFactViolation] = []
    for index, raw_line in enumerate(normalized.split("\n")):
        if ALLOW_LINE_MARKER in raw_line:
            continue
        line = _INLINE_CODE.sub(" ", raw_line)
        for rule, pattern, _description in LIVE_FACT_RULES:
            if pattern.search(line):
                excerpt = raw_line.strip()
                if len(excerpt) > MAX_EXCERPT_CHARS:
                    excerpt = excerpt[: MAX_EXCERPT_CHARS - 3] + "..."
                violations.append(
                    LiveFactViolation(line=index + 1, rule=rule, excerpt=excerpt)
                )
                break
    return tuple(violations)


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _parse_front_matter(
    text: str,
    *,
    path: str,
) -> tuple[dict[str, tuple[str, int]], str, str, int]:
    """Return ``(entries, body, normalized_text, body_start_line)``."""

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    if not lines or lines[0].strip() != FRONT_MATTER_DELIMITER:
        raise RagCorpusError(
            "file must start with '---' front matter",
            path=path,
            line=1,
            rule="front_matter",
        )

    entries: dict[str, tuple[str, int]] = {}
    close_index: int | None = None
    for index in range(1, len(lines)):
        raw = lines[index]
        if raw.strip() == FRONT_MATTER_DELIMITER:
            close_index = index
            break
        if not raw.strip():
            continue
        match = _FRONT_MATTER_LINE.match(raw.rstrip())
        if match is None:
            raise RagCorpusError(
                "front matter lines must use 'key: value'",
                path=path,
                line=index + 1,
                rule="front_matter",
            )
        key = match.group(1)
        value = (match.group(2) or "").strip()
        if key in entries:
            raise RagCorpusError(
                f"duplicate front matter field '{key}'",
                path=path,
                line=index + 1,
                rule="front_matter",
            )
        entries[key] = (value, index + 1)

    if close_index is None:
        raise RagCorpusError(
            "front matter is not closed with '---'",
            path=path,
            rule="front_matter",
        )

    body = "\n".join(lines[close_index + 1 :]).strip("\n")
    return entries, body, normalized, close_index + 2


def _required_value(
    entries: dict[str, tuple[str, int]],
    name: str,
    *,
    path: str,
) -> str:
    value = _unquote(entries[name][0]).strip()
    if not value:
        raise RagCorpusError(
            f"front matter field '{name}' must not be empty",
            path=path,
            line=entries[name][1],
            rule="metadata",
        )
    return value


def _list_value(
    entries: dict[str, tuple[str, int]],
    name: str,
    *,
    path: str,
) -> tuple[str, ...]:
    if name not in entries:
        return ()

    raw, line = entries[name]
    value = raw.strip()
    if not value:
        return ()

    if value.startswith("["):
        if not value.endswith("]"):
            raise RagCorpusError(
                f"front matter field '{name}' has an unterminated list",
                path=path,
                line=line,
                rule="metadata",
            )
        value = value[1:-1].strip()
        if not value:
            return ()
    elif value.endswith("]"):
        raise RagCorpusError(
            f"front matter field '{name}' has an unterminated list",
            path=path,
            line=line,
            rule="metadata",
        )

    items: list[str] = []
    for part in value.split(","):
        item = _unquote(part.strip()).strip()
        if not item:
            raise RagCorpusError(
                f"front matter field '{name}' contains a blank entry",
                path=path,
                line=line,
                rule="metadata",
            )
        items.append(item)
    return tuple(items)


def _check_front_matter_keys(
    entries: dict[str, tuple[str, int]],
    *,
    path: str,
) -> None:
    missing = [field for field in REQUIRED_FIELDS if field not in entries]
    if missing:
        raise RagCorpusError(
            "missing required front matter field(s): " + ", ".join(missing),
            path=path,
            line=1,
            rule="metadata",
        )

    unknown = sorted(set(entries) - set(ALLOWED_FIELDS))
    if unknown:
        raise RagCorpusError(
            "unknown front matter field(s): " + ", ".join(unknown),
            path=path,
            line=entries[unknown[0]][1],
            rule="metadata",
        )


def _load_document(root: Path, category: str, path: Path) -> KnowledgeDocument:
    relative = path.relative_to(root).as_posix()

    try:
        raw = path.read_bytes()
    except OSError:
        raise RagCorpusError(
            "file could not be read",
            path=relative,
            rule="io_read",
        ) from None

    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise RagCorpusError(
            f"file is not valid UTF-8 (byte offset {exc.start})",
            path=relative,
            rule="encoding",
        ) from None

    entries, body, normalized, body_start_line = _parse_front_matter(
        text,
        path=relative,
    )
    _check_front_matter_keys(entries, path=relative)

    doc_id = _required_value(entries, "doc_id", path=relative)
    title = _required_value(entries, "title", path=relative)
    category_value = _required_value(entries, "category", path=relative)
    fact_kind = _required_value(entries, "fact_kind", path=relative)
    version = _required_value(entries, "version", path=relative)
    updated_at = _required_value(entries, "updated_at", path=relative)
    summary = _required_value(entries, "summary", path=relative)
    tags = _list_value(entries, "tags", path=relative)
    aliases = _list_value(entries, "aliases", path=relative)

    if category_value not in CATEGORIES:
        raise RagCorpusError(
            f"unknown category '{category_value}'; expected one of: "
            + ", ".join(CATEGORIES),
            path=relative,
            line=entries["category"][1],
            rule="category",
        )
    if category_value != category:
        raise RagCorpusError(
            f"category '{category_value}' does not match directory "
            f"'{category}'",
            path=relative,
            line=entries["category"][1],
            rule="category_mismatch",
        )
    if doc_id != path.stem:
        raise RagCorpusError(
            f"doc_id '{doc_id}' must match the file stem '{path.stem}'",
            path=relative,
            line=entries["doc_id"][1],
            rule="doc_id_mismatch",
        )

    if not body.strip():
        raise RagCorpusError(
            "document body is empty",
            path=relative,
            line=body_start_line,
            rule="metadata",
        )
    if len(body) > MAX_BODY_CHARS:
        raise RagCorpusError(
            f"document body exceeds {MAX_BODY_CHARS} characters",
            path=relative,
            rule="max_document_chars",
        )

    violations = find_live_fact_violations(body)
    if violations:
        first = violations[0]
        description = next(
            message
            for rule, _pattern, message in LIVE_FACT_RULES
            if rule == first.rule
        )
        raise RagCorpusError(
            f"live ERP fact detected ({description}): '{first.excerpt}'. "
            "Documentation must not contain live business values; append "
            f"'<!-- {ALLOW_LINE_MARKER} -->' only for a conceptual example.",
            path=relative,
            line=body_start_line + first.line - 1,
            rule=f"live_fact:{first.rule}",
        )

    try:
        return KnowledgeDocument(
            doc_id=doc_id,
            title=title,
            category=category_value,
            fact_kind=fact_kind,
            version=version,
            updated_at=updated_at,
            summary=summary,
            tags=tags,
            aliases=aliases,
            source_path=relative,
            content_hash=hashlib.sha256(
                normalized.encode("utf-8")
            ).hexdigest(),
            body=body,
        )
    except ValidationError as exc:
        error = exc.errors()[0]
        field = str(error["loc"][0]) if error["loc"] else None
        line = entries[field][1] if field in entries else 1
        label = field or "document"
        raise RagCorpusError(
            f"invalid front matter for '{label}': {error['msg']}",
            path=relative,
            line=line,
            rule="metadata",
        ) from None


def _collect_files(root: Path) -> list[tuple[str, Path]]:
    try:
        entries = sorted(root.iterdir(), key=lambda item: item.name)
    except OSError:
        raise RagCorpusError(
            "knowledge directory could not be read",
            path=str(root),
            rule="io_read",
        ) from None

    files: list[tuple[str, Path]] = []
    for entry in entries:
        if entry.name.startswith("."):
            continue
        if entry.is_dir():
            if entry.name not in CATEGORIES:
                raise RagCorpusError(
                    f"unknown knowledge directory '{entry.name}'; expected "
                    "one of: " + ", ".join(CATEGORIES),
                    path=entry.name,
                    rule="category",
                )
            try:
                children = sorted(entry.iterdir(), key=lambda item: item.name)
            except OSError:
                raise RagCorpusError(
                    "category directory could not be read",
                    path=entry.name,
                    rule="io_read",
                ) from None
            for child in children:
                if child.name.startswith("."):
                    continue
                if child.is_dir():
                    raise RagCorpusError(
                        "nested knowledge directories are not supported",
                        path=f"{entry.name}/{child.name}",
                        rule="nested_directory",
                    )
                if child.suffix.lower() != ".md":
                    continue
                files.append((entry.name, child))
        elif entry.suffix.lower() == ".md":
            raise RagCorpusError(
                "knowledge documents must live in a category directory",
                path=entry.name,
                rule="misplaced_document",
            )

    files.sort(key=lambda item: (item[0], item[1].name))
    return files


def _check_corpus_limits(root: Path, files: list[tuple[str, Path]]) -> None:
    if len(files) > MAX_DOCS:
        raise RagCorpusError(
            f"corpus contains {len(files)} documents; limit is {MAX_DOCS}",
            path=str(root),
            rule="max_documents",
        )

    total_bytes = 0
    for _category, path in files:
        try:
            total_bytes += path.stat().st_size
        except OSError:
            raise RagCorpusError(
                "document size could not be read",
                path=path.relative_to(root).as_posix(),
                rule="io_read",
            ) from None

    if total_bytes > MAX_CORPUS_BYTES:
        raise RagCorpusError(
            f"corpus is {total_bytes} bytes; limit is {MAX_CORPUS_BYTES}",
            path=str(root),
            rule="max_corpus_bytes",
        )


def index_version_for(documents: tuple[KnowledgeDocument, ...]) -> str:
    """Return a deterministic short version for a document set."""

    hasher = hashlib.sha256()
    for document in sorted(documents, key=lambda item: item.doc_id):
        hasher.update(document.doc_id.encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(document.content_hash.encode("ascii"))
        hasher.update(b"\n")
    return hasher.hexdigest()[:INDEX_VERSION_CHARS]


def load_corpus_from_dir(
    knowledge_dir: str | Path,
    *,
    max_chunk_chars: int = DEFAULT_MAX_CHUNK_CHARS,
    min_chunk_chars: int = DEFAULT_MIN_CHUNK_CHARS,
) -> CorpusBundle:
    """Load and validate a knowledge directory into a deterministic bundle."""

    root = Path(knowledge_dir).expanduser()
    try:
        root = root.resolve()
    except (OSError, RuntimeError):
        raise RagCorpusError(
            "knowledge directory path is invalid",
            path=str(knowledge_dir),
            rule="missing_directory",
        ) from None

    if not root.exists():
        raise RagCorpusError(
            "knowledge directory does not exist",
            path=str(knowledge_dir),
            rule="missing_directory",
        )
    if not root.is_dir():
        raise RagCorpusError(
            "knowledge path must be a directory",
            path=str(knowledge_dir),
            rule="missing_directory",
        )

    files = _collect_files(root)
    _check_corpus_limits(root, files)

    documents: list[KnowledgeDocument] = []
    chunks = []
    seen: dict[str, str] = {}

    for category, path in files:
        document = _load_document(root, category, path)

        previous = seen.get(document.doc_id)
        if previous is not None:
            raise RagCorpusError(
                f"duplicate doc_id '{document.doc_id}' in "
                f"'{previous}' and '{document.source_path}'",
                path=document.source_path,
                rule="duplicate_doc_id",
            )
        seen[document.doc_id] = document.source_path

        document_chunks = chunk_document(
            document,
            max_chunk_chars=max_chunk_chars,
            min_chunk_chars=min_chunk_chars,
        )
        if not document_chunks:
            raise RagCorpusError(
                f"document '{document.doc_id}' produced no meaningful chunks; "
                "add explanatory body text",
                path=document.source_path,
                rule="no_chunks",
            )

        documents.append(document)
        chunks.extend(document_chunks)

    return CorpusBundle(
        documents=tuple(documents),
        chunks=tuple(chunks),
        index_version=index_version_for(tuple(documents)),
    )


def load_corpus(config: RagConfig) -> CorpusBundle:
    """Load the corpus described by ``config``."""

    if not isinstance(config, RagConfig):
        raise TypeError("config must be a RagConfig")

    return load_corpus_from_dir(
        config.knowledge_dir,
        max_chunk_chars=config.max_chunk_chars,
        min_chunk_chars=config.min_chunk_chars,
    )


__all__ = [
    "ALLOW_LINE_MARKER",
    "CATEGORIES",
    "FRONT_MATTER_DELIMITER",
    "LIVE_FACT_RULES",
    "MAX_BODY_CHARS",
    "LiveFactViolation",
    "find_live_fact_violations",
    "index_version_for",
    "load_corpus",
    "load_corpus_from_dir",
]
