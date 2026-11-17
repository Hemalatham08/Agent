"""Deterministic text normalization, tokenization, and slug generation.

All functions are pure and locale-independent. They deliberately use only the
standard library so the RAG package adds no runtime dependency.
"""

from __future__ import annotations

import re
import unicodedata

STOPWORDS = frozenset(
    {
        "a",
        "about",
        "above",
        "after",
        "again",
        "against",
        "all",
        "also",
        "am",
        "an",
        "and",
        "any",
        "are",
        "as",
        "at",
        "be",
        "because",
        "been",
        "before",
        "being",
        "below",
        "between",
        "both",
        "but",
        "by",
        "can",
        "could",
        "did",
        "do",
        "does",
        "doing",
        "down",
        "during",
        "each",
        "few",
        "for",
        "from",
        "further",
        "had",
        "has",
        "have",
        "having",
        "he",
        "her",
        "here",
        "hers",
        "herself",
        "him",
        "himself",
        "his",
        "how",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "itself",
        "just",
        "may",
        "me",
        "mean",
        "means",
        "meant",
        "meaning",
        "might",
        "more",
        "most",
        "must",
        "my",
        "myself",
        "no",
        "nor",
        "not",
        "now",
        "of",
        "off",
        "on",
        "once",
        "only",
        "or",
        "other",
        "our",
        "ours",
        "ourselves",
        "out",
        "over",
        "own",
        "per",
        "same",
        "shall",
        "she",
        "should",
        "so",
        "some",
        "such",
        "than",
        "that",
        "the",
        "their",
        "theirs",
        "them",
        "themselves",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "through",
        "to",
        "too",
        "under",
        "until",
        "up",
        "us",
        "very",
        "via",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "which",
        "while",
        "who",
        "whom",
        "whose",
        "why",
        "will",
        "with",
        "within",
        "without",
        "would",
        "you",
        "your",
        "yours",
        "yourself",
        "yourselves",
    }
)

_SEPARATOR_PATTERN = re.compile(r"[_/.\-]+")
_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
_SLUG_PATTERN = re.compile(r"[^a-z0-9]+")

# Endings that are already singular despite ending in "s".
_NON_PLURAL_ENDINGS = ("as", "is", "os", "ss", "us")

# Irregular plural forms that conservative suffix rules would corrupt.
_IRREGULAR_PLURALS = {
    "statuses": "status",
    "analyses": "analysis",
    "axes": "axis",
    "indices": "index",
    "matrices": "matrix",
    "buses": "bus",
    "viruses": "virus",
    "theses": "thesis",
    "crises": "crisis",
    "phenomena": "phenomenon",
    "criteria": "criterion",
    "datums": "datum",
    "media": "medium",
    "appendices": "appendix",
}

# Query expansion mappings: a term maps to its documented expansion forms.
# Kept small and curated to avoid precision drift; expansion is opt-in in BM25.
QUERY_EXPANSIONS: dict[str, tuple[str, ...]] = {
    "dispatched": ("dispatch",),
    "dispatch": ("dispatched",),
    "confirmed": ("confirm",),
    "confirm": ("confirmed",),
    "created": ("create",),
    "create": ("created",),
    "adjusted": ("adjust",),
    "adjust": ("adjusted",),
    "adjustment": ("adjust",),
    "received": ("receive", "receipt"),
    "receive": ("received",),
    "receipt": ("received",),
    "ordered": ("order",),
    "order": ("ordered",),
    "approved": ("approve",),
    "approve": ("approved",),
    "cancelled": ("cancel",),
    "cancel": ("cancelled",),
    "items": ("item",),
    "item": ("items",),
    "stocks": ("stock",),
    "stock": ("stocks",),
    "delivered": ("delivery",),
    "delivery": ("delivered",),
    "variants": ("variant",),
    "variant": ("variants",),
}


def _fold(text: str) -> str:
    """NFC/NFKD fold to lowercase ASCII letters and digits only."""

    decomposed = unicodedata.normalize("NFKD", text)
    without_marks = "".join(
        character
        for character in decomposed
        if not unicodedata.combining(character)
    )
    return without_marks.casefold()


def normalize(text: str) -> str:
    """Return space-separated lowercase ASCII tokens for ``text``.

    Underscores, slashes, dots, and hyphens are treated as separators so that
    schema identifiers such as ``on_hand_qty`` normalize to
    ``on hand qty``.
    """

    if not isinstance(text, str):
        raise TypeError("text must be a string")

    folded = _SEPARATOR_PATTERN.sub(" ", _fold(text))
    return " ".join(_TOKEN_PATTERN.findall(folded))


def _singularize(token: str) -> str:
    """Apply conservative plural normalization to one token.

    ``-ies`` and ``-es`` rules cover the domain vocabulary that matters here
    (``categories``, ``dispatches``, ``classes``). Plain ``-s`` is stripped
    only when the token does not already end like a singular word.
    Irregular forms are mapped explicitly to avoid producing invalid stems
    such as ``statuse`` from ``statuses``.
    """

    if token in _IRREGULAR_PLURALS:
        return _IRREGULAR_PLURALS[token]
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 5 and token.endswith(("ches", "shes", "sses", "xes", "zes")):
        return token[:-2]
    if len(token) > 4 and token.endswith("s") and not token.endswith(
        _NON_PLURAL_ENDINGS
    ):
        return token[:-1]
    return token


def tokenize(text: str) -> list[str]:
    """Return deterministic, meaningful search tokens for ``text``.

    Drops one-character tokens, pure numbers, and English stopwords, then
    applies light plural normalization. The same token is produced for the
    same input on every call and platform.
    """

    tokens: list[str] = []
    for raw in normalize(text).split():
        if len(raw) < 2:
            continue
        if raw.isdigit():
            continue
        if raw in STOPWORDS:
            continue
        token = _singularize(raw)
        if token in STOPWORDS:
            continue
        tokens.append(token)
    return tokens


def slugify(text: str, *, max_len: int = 40) -> str:
    """Return a stable lowercase slug for a heading or document title."""

    if not isinstance(text, str):
        raise TypeError("text must be a string")
    if isinstance(max_len, bool) or not isinstance(max_len, int) or max_len < 1:
        raise ValueError("max_len must be a positive integer")

    slug = _SLUG_PATTERN.sub("-", _fold(text)).strip("-")
    slug = slug[:max_len].strip("-")
    return slug or "overview"


__all__ = [
    "STOPWORDS",
    "normalize",
    "slugify",
    "tokenize",
    "QUERY_EXPANSIONS",
    "expand_query_terms",
    "expansion_trace",
]


def expand_query_terms(tokens: list[str]) -> list[str]:
    """Return deterministic query terms with curated expansions appended.

    Original tokens are always kept in order; expansion terms are appended in
    first-occurrence order without duplicates. No index or corpus mutation is
    performed. Pure and deterministic.
    """

    expanded: list[str] = list(tokens)
    seen: set[str] = set(expanded)
    for token in tokens:
        for expansion in QUERY_EXPANSIONS.get(token, ()):
            if expansion not in seen:
                expanded.append(expansion)
                seen.add(expansion)
    return expanded


def expansion_trace(tokens: list[str]) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Return curated expansion pairs for ``tokens`` without mutating input.

    Each entry is ``(source_term, added_terms)`` where ``added_terms`` are the
    curated expansions for ``source_term`` that were not already present in the
    original token list, in first-occurrence order. Returns an empty tuple when
    no expansions apply. Pure and deterministic.
    """

    seen: set[str] = set(tokens)
    pairs: list[tuple[str, tuple[str, ...]]] = []
    for token in tokens:
        additions = [
            expansion
            for expansion in QUERY_EXPANSIONS.get(token, ())
            if expansion not in seen
        ]
        if additions:
            pairs.append((token, tuple(additions)))
            seen.update(additions)
    return tuple(pairs)
