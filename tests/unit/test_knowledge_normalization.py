"""Safe, deterministic normalization for knowledge search queries."""

from __future__ import annotations

import pytest

from jobfit.knowledge.normalization import (
    MAX_SEARCH_QUERY_CHARS,
    MAX_SEARCH_TOKENS,
    build_fts_match_expression,
    normalize_search_text,
    tokenize_search_query,
)


def test_normalization_uses_nfkc_casefold_whitespace_and_control_cleanup() -> None:
    assert normalize_search_text("  ＰＹＴＨＯＮ\u0000\tData  ") == "python data"


def test_tokenization_supports_english_numbers_and_chinese_bigrams() -> None:
    tokens = tokenize_search_query("Python 3 数据分析 Python")

    assert tokens == (
        "python",
        "3",
        "数据分析",
        "数据",
        "据分",
        "分析",
    )


def test_tokenization_is_bounded_and_stably_deduplicated() -> None:
    text = " ".join(f"token{index}" for index in range(MAX_SEARCH_TOKENS + 20))
    first = tokenize_search_query(text)
    second = tokenize_search_query(text)

    assert first == second
    assert len(first) == MAX_SEARCH_TOKENS
    assert len(normalize_search_text("x" * (MAX_SEARCH_QUERY_CHARS + 20))) == (
        MAX_SEARCH_QUERY_CHARS
    )


def test_empty_or_control_only_query_has_no_tokens() -> None:
    assert normalize_search_text("\u0000\u0001\t") == ""
    assert tokenize_search_query("\u0000\u0001\t") == ()
    assert build_fts_match_expression(()) == ""


def test_fts_expression_quotes_only_normalized_tokens_not_input_operators() -> None:
    tokens = tokenize_search_query('Python" OR NOT NEAR(x) 100%_')
    expression = build_fts_match_expression(tokens)

    assert expression == '"python" OR "or" OR "not" OR "near" OR "x" OR "100"'
    assert 'NEAR(' not in expression
    assert '%_' not in expression


@pytest.mark.parametrize(
    "unsafe",
    (
        ('bad"token',),
        ("contains space",),
        ("*",),
        ("(",),
    ),
)
def test_fts_expression_rejects_tokens_that_bypass_tokenizer(
    unsafe: tuple[str, ...],
) -> None:
    with pytest.raises(ValueError):
        build_fts_match_expression(unsafe)
