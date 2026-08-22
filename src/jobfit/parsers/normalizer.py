"""Deterministic text normalization with evidence-safe segment offsets."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from jobfit.models import TextSegment


@dataclass(frozen=True, slots=True)
class TextPart:
    """A source-aware text unit such as a paragraph, cell, or PDF page."""

    text: str
    page_number: int | None = None
    section_hint: str | None = None


def _normalize_content(raw: str) -> str:
    text = raw.removeprefix("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip(" \t\f\v") for line in text.split("\n")]

    normalized_lines: list[str] = []
    consecutive_blank_lines = 0
    for line in lines:
        if not line:
            consecutive_blank_lines += 1
            if consecutive_blank_lines > 2:
                continue
        else:
            consecutive_blank_lines = 0
        normalized_lines.append(line)

    while normalized_lines and not normalized_lines[0]:
        normalized_lines.pop(0)
    while normalized_lines and not normalized_lines[-1]:
        normalized_lines.pop()
    return "\n".join(normalized_lines)


def _segments_from_paragraphs(normalized: str) -> list[TextSegment]:
    segments: list[TextSegment] = []
    cursor = 0
    chunks = re.split(r"\n{2,}", normalized)
    for chunk in chunks:
        if not chunk:
            continue
        start_char = normalized.find(chunk, cursor)
        end_char = start_char + len(chunk)
        segments.append(
            TextSegment(
                segment_id=f"seg-{len(segments) + 1:03d}",
                text=chunk,
                start_char=start_char,
                end_char=end_char,
            )
        )
        cursor = end_char
    return segments


def normalize_text(raw: str) -> tuple[str, list[TextSegment]]:
    """Normalize plain text and create paragraph-level evidence segments."""

    normalized = _normalize_content(raw)
    if not normalized:
        return "", []
    return normalized, _segments_from_paragraphs(normalized)


def normalize_parts(
    parts: Iterable[TextPart],
) -> tuple[str, list[TextSegment]]:
    """Normalize ordered source units while retaining page and section metadata."""

    normalized_parts: list[tuple[str, TextPart]] = []
    for part in parts:
        normalized_part = _normalize_content(part.text)
        if normalized_part:
            normalized_parts.append((normalized_part, part))

    text_chunks: list[str] = []
    segments: list[TextSegment] = []
    cursor = 0
    for normalized_part, part in normalized_parts:
        if text_chunks:
            cursor += 1
        text_chunks.append(normalized_part)
        end_char = cursor + len(normalized_part)
        segments.append(
            TextSegment(
                segment_id=f"seg-{len(segments) + 1:03d}",
                text=normalized_part,
                start_char=cursor,
                end_char=end_char,
                page_number=part.page_number,
                section_hint=part.section_hint,
            )
        )
        cursor = end_char

    return "\n".join(text_chunks), segments
