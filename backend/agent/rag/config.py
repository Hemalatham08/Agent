"""Immutable configuration for the documentation-only RAG package.

The configuration is intentionally strict: an unset environment variable uses
the documented default, but a present-and-invalid value fails fast with
:class:`~backend.agent.rag.errors.RagConfigurationError`. Nothing is silently
corrected.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.agent.rag.errors import RagConfigurationError

RAG_ENABLED_ENV = "RAG_ENABLED"
RAG_KNOWLEDGE_DIR_ENV = "RAG_KNOWLEDGE_DIR"
RAG_DEFAULT_TOP_K_ENV = "RAG_DEFAULT_TOP_K"
RAG_MIN_SCORE_ENV = "RAG_MIN_SCORE"
RAG_MAX_SNIPPET_CHARS_ENV = "RAG_MAX_SNIPPET_CHARS"
RAG_MAX_TOTAL_CHARS_ENV = "RAG_MAX_TOTAL_CHARS"

DEFAULT_KNOWLEDGE_DIR = Path(__file__).resolve().parent / "knowledge"

DEFAULT_TOP_K = 3
MAX_TOP_K = 5
DEFAULT_MIN_SCORE = 0.10
RELATIVE_SCORE_FLOOR = 0.25

DEFAULT_MAX_SNIPPET_CHARS = 700
MIN_SNIPPET_CHARS = 100
MAX_SNIPPET_CHARS = 2000

DEFAULT_MAX_TOTAL_CHARS = 3000
MIN_TOTAL_CHARS = 500
MAX_TOTAL_CHARS = 6000

DEFAULT_MAX_DOCUMENT_CHARS = 6000
MIN_DOCUMENT_CHARS = 100
MAX_DOCUMENT_CHARS = 100_000

DEFAULT_MAX_HITS_PER_DOC = 2
MAX_HITS_PER_DOC = 10

DEFAULT_MAX_CHUNK_CHARS = 1200
MIN_CHUNK_SIZE = 200
MAX_CHUNK_SIZE = 5000
DEFAULT_MIN_CHUNK_CHARS = 120

BM25_K1 = 1.2
BM25_B = 0.75
MAX_BM25_K1 = 5.0

MAX_QUERY_CHARS = 300
MAX_DOCS = 200
MAX_CHUNKS = 5000
MAX_CORPUS_BYTES = 2_000_000


def _require_int(value: Any, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RagConfigurationError(
            f"{name} must be an integer between {minimum} and {maximum}"
        )
    if value < minimum or value > maximum:
        raise RagConfigurationError(
            f"{name} must be an integer between {minimum} and {maximum}"
        )
    return value


def _require_number(
    value: Any,
    name: str,
    minimum: float,
    maximum: float | None = None,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RagConfigurationError(f"{name} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise RagConfigurationError(f"{name} must be a finite number")
    if number < minimum or (maximum is not None and number > maximum):
        if maximum is None:
            raise RagConfigurationError(f"{name} must be at least {minimum}")
        raise RagConfigurationError(
            f"{name} must be between {minimum} and {maximum}"
        )
    return number


def _resolve_knowledge_dir(value: Any) -> Path:
    if isinstance(value, Path):
        raw = str(value).strip()
    elif isinstance(value, str):
        raw = value.strip()
    else:
        raise RagConfigurationError(
            "knowledge_dir must be a filesystem path or string"
        )

    if not raw:
        raise RagConfigurationError("knowledge_dir must not be empty")

    try:
        resolved = Path(raw).expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        raise RagConfigurationError("knowledge_dir is invalid") from None

    if not resolved.exists():
        raise RagConfigurationError("knowledge_dir does not exist")
    if not resolved.is_dir():
        raise RagConfigurationError("knowledge_dir must be a directory")
    return resolved


def _read_env(name: str) -> str | None:
    raw = os.environ.get(name)
    if raw is None:
        return None
    value = raw.strip()
    return value or None


def _env_bool(name: str, default: bool) -> bool:
    raw = _read_env(name)
    if raw is None:
        return default
    lowered = raw.lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    raise RagConfigurationError(f"{name} must be true or false")


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = _read_env(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise RagConfigurationError(
            f"{name} must be an integer between {minimum} and {maximum}"
        ) from None
    if value < minimum or value > maximum:
        raise RagConfigurationError(
            f"{name} must be an integer between {minimum} and {maximum}"
        )
    return value


def _env_float(
    name: str,
    default: float,
    minimum: float,
    maximum: float | None = None,
) -> float:
    raw = _read_env(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        raise RagConfigurationError(f"{name} must be a finite number") from None
    if not math.isfinite(value):
        raise RagConfigurationError(f"{name} must be a finite number")
    if value < minimum or (maximum is not None and value > maximum):
        raise RagConfigurationError(f"{name} is out of range")
    return value


@dataclass(frozen=True)
class RagConfig:
    """Validated configuration for the isolated RAG package.

    ``knowledge_dir`` must already exist. Creating or seeding the corpus is a
    corpus-stage concern, not a configuration concern.
    """

    knowledge_dir: Path
    enabled: bool = False
    default_top_k: int = DEFAULT_TOP_K
    min_score: float = DEFAULT_MIN_SCORE
    max_snippet_chars: int = DEFAULT_MAX_SNIPPET_CHARS
    max_total_chars: int = DEFAULT_MAX_TOTAL_CHARS
    max_document_chars: int = DEFAULT_MAX_DOCUMENT_CHARS
    max_hits_per_doc: int = DEFAULT_MAX_HITS_PER_DOC
    max_chunk_chars: int = DEFAULT_MAX_CHUNK_CHARS
    min_chunk_chars: int = DEFAULT_MIN_CHUNK_CHARS
    bm25_k1: float = BM25_K1
    bm25_b: float = BM25_B

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "knowledge_dir",
            _resolve_knowledge_dir(self.knowledge_dir),
        )

        if not isinstance(self.enabled, bool):
            raise RagConfigurationError("enabled must be a boolean")

        _require_int(self.default_top_k, "default_top_k", 1, MAX_TOP_K)

        object.__setattr__(
            self,
            "min_score",
            _require_number(self.min_score, "min_score", 0.0),
        )

        _require_int(
            self.max_snippet_chars,
            "max_snippet_chars",
            MIN_SNIPPET_CHARS,
            MAX_SNIPPET_CHARS,
        )
        _require_int(
            self.max_total_chars,
            "max_total_chars",
            MIN_TOTAL_CHARS,
            MAX_TOTAL_CHARS,
        )
        if self.max_total_chars < self.max_snippet_chars:
            raise RagConfigurationError(
                "max_total_chars must be greater than or equal to "
                "max_snippet_chars"
            )

        _require_int(
            self.max_document_chars,
            "max_document_chars",
            MIN_DOCUMENT_CHARS,
            MAX_DOCUMENT_CHARS,
        )
        _require_int(
            self.max_hits_per_doc,
            "max_hits_per_doc",
            1,
            MAX_HITS_PER_DOC,
        )
        _require_int(
            self.max_chunk_chars,
            "max_chunk_chars",
            MIN_CHUNK_SIZE,
            MAX_CHUNK_SIZE,
        )
        _require_int(
            self.min_chunk_chars,
            "min_chunk_chars",
            0,
            self.max_chunk_chars,
        )

        k1 = _require_number(
            self.bm25_k1,
            "bm25_k1",
            0.0,
            MAX_BM25_K1,
        )
        if k1 <= 0:
            raise RagConfigurationError("bm25_k1 must be greater than 0")
        object.__setattr__(self, "bm25_k1", k1)

        object.__setattr__(
            self,
            "bm25_b",
            _require_number(self.bm25_b, "bm25_b", 0.0, 1.0),
        )

    @classmethod
    def from_env(cls) -> RagConfig:
        raw_dir = _read_env(RAG_KNOWLEDGE_DIR_ENV)
        knowledge_dir: Path | str = (
            DEFAULT_KNOWLEDGE_DIR if raw_dir is None else raw_dir
        )

        return cls(
            knowledge_dir=knowledge_dir,
            enabled=_env_bool(RAG_ENABLED_ENV, False),
            default_top_k=_env_int(
                RAG_DEFAULT_TOP_K_ENV,
                DEFAULT_TOP_K,
                1,
                MAX_TOP_K,
            ),
            min_score=_env_float(
                RAG_MIN_SCORE_ENV,
                DEFAULT_MIN_SCORE,
                0.0,
            ),
            max_snippet_chars=_env_int(
                RAG_MAX_SNIPPET_CHARS_ENV,
                DEFAULT_MAX_SNIPPET_CHARS,
                MIN_SNIPPET_CHARS,
                MAX_SNIPPET_CHARS,
            ),
            max_total_chars=_env_int(
                RAG_MAX_TOTAL_CHARS_ENV,
                DEFAULT_MAX_TOTAL_CHARS,
                MIN_TOTAL_CHARS,
                MAX_TOTAL_CHARS,
            ),
        )


__all__ = [
    "BM25_B",
    "BM25_K1",
    "DEFAULT_KNOWLEDGE_DIR",
    "DEFAULT_MAX_CHUNK_CHARS",
    "DEFAULT_MAX_DOCUMENT_CHARS",
    "DEFAULT_MAX_HITS_PER_DOC",
    "DEFAULT_MAX_SNIPPET_CHARS",
    "DEFAULT_MAX_TOTAL_CHARS",
    "DEFAULT_MIN_CHUNK_CHARS",
    "DEFAULT_MIN_SCORE",
    "DEFAULT_TOP_K",
    "MAX_BM25_K1",
    "MAX_CHUNKS",
    "MAX_CHUNK_SIZE",
    "MAX_CORPUS_BYTES",
    "MAX_DOCS",
    "MAX_DOCUMENT_CHARS",
    "MAX_HITS_PER_DOC",
    "MAX_QUERY_CHARS",
    "MAX_SNIPPET_CHARS",
    "MAX_TOP_K",
    "MAX_TOTAL_CHARS",
    "MIN_CHUNK_SIZE",
    "MIN_DOCUMENT_CHARS",
    "MIN_SNIPPET_CHARS",
    "MIN_TOTAL_CHARS",
    "RAG_DEFAULT_TOP_K_ENV",
    "RAG_ENABLED_ENV",
    "RAG_KNOWLEDGE_DIR_ENV",
    "RAG_MAX_SNIPPET_CHARS_ENV",
    "RAG_MAX_TOTAL_CHARS_ENV",
    "RAG_MIN_SCORE_ENV",
    "RELATIVE_SCORE_FLOOR",
    "RagConfig",
]
