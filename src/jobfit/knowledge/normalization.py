"""Pure, bounded normalization for deterministic knowledge search."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence

MAX_SEARCH_QUERY_CHARS = 1_000
MAX_SEARCH_TOKENS = 50
MAX_SEARCH_TOKEN_CHARS = 64

_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_WHITESPACE_RE = re.compile(r"\s+")
_SEARCH_TERM_RE = re.compile(r"[a-z0-9]+|[\u3400-\u4dbf\u4e00-\u9fff]+")
_SAFE_FTS_TOKEN_RE = re.compile(r"^[a-z0-9\u3400-\u4dbf\u4e00-\u9fff]+$")


def normalize_search_text(value: str) -> str:
    """Normalize untrusted query text without preserving control syntax."""
    if not isinstance(value, str):
        raise TypeError("search text must be a string")
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = _CONTROL_RE.sub(" ", normalized)
    normalized = _WHITESPACE_RE.sub(" ", normalized).strip()
    return normalized[:MAX_SEARCH_QUERY_CHARS].rstrip()


def _cjk_terms(value: str) -> tuple[str, ...]:
    if len(value) <= 2:
        return (value,)
    return (value, *(value[index : index + 2] for index in range(len(value) - 1)))


def tokenize_search_query(value: str) -> tuple[str, ...]:
    """Return stable English tokens and Chinese phrases/bigrams."""
    normalized = normalize_search_text(value)
    tokens: list[str] = []
    seen: set[str] = set()
    for match in _SEARCH_TERM_RE.finditer(normalized):
        term = match.group(0)
        candidates = (
            _cjk_terms(term)
            if any("\u3400" <= char <= "\u9fff" for char in term)
            else (term,)
        )
        for candidate in candidates:
            bounded = candidate[:MAX_SEARCH_TOKEN_CHARS]
            if bounded and bounded not in seen:
                tokens.append(bounded)
                seen.add(bounded)
                if len(tokens) == MAX_SEARCH_TOKENS:
                    return tuple(tokens)
    return tuple(tokens)


def build_fts_match_expression(tokens: Sequence[str]) -> str:
    """Build a generated FTS OR expression from tokenizer-safe terms only."""
    normalized: list[str] = []
    for token in tokens:
        if not isinstance(token, str) or not _SAFE_FTS_TOKEN_RE.fullmatch(token):
            raise ValueError("FTS tokens must come from tokenize_search_query")
        if token not in normalized:
            normalized.append(token)
    return " OR ".join(f'"{token}"' for token in normalized)


def normalize_query_terms(values: Sequence[str]) -> tuple[str, ...]:
    """Tokenize multiple fields while preserving first occurrence order."""
    tokens: list[str] = []
    seen: set[str] = set()
    for value in values:
        for token in tokenize_search_query(value):
            if token not in seen:
                tokens.append(token)
                seen.add(token)
                if len(tokens) == MAX_SEARCH_TOKENS:
                    return tuple(tokens)
    return tuple(tokens)


__all__ = [
    "MAX_SEARCH_QUERY_CHARS",
    "MAX_SEARCH_TOKEN_CHARS",
    "MAX_SEARCH_TOKENS",
    "build_fts_match_expression",
    "normalize_query_terms",
    "normalize_search_text",
    "tokenize_search_query",
]
