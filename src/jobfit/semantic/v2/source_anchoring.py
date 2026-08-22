"""Small deterministic helpers for exact source-text anchoring."""

from __future__ import annotations


def exact_text_spans(
    source_text: str,
    text: str,
    *,
    base_offset: int = 0,
) -> tuple[tuple[int, int], ...]:
    """Return every exact occurrence as absolute half-open character offsets."""

    spans: list[tuple[int, int]] = []
    cursor = 0
    while True:
        match = source_text.find(text, cursor)
        if match < 0:
            return tuple(spans)
        start_char = base_offset + match
        spans.append((start_char, start_char + len(text)))
        cursor = match + 1
