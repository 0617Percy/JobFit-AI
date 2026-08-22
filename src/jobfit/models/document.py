"""Document, segment, and evidence contracts."""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from typing import Any

from pydantic import Field, JsonValue, model_validator

from jobfit.models.common import (
    DocumentSourceKind,
    EvidenceKind,
    EvidenceSourceType,
    LanguageCode,
    NonEmptyStr,
    StrictModel,
)


class TextSegment(StrictModel):
    segment_id: NonEmptyStr
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)
    text: str = Field(min_length=1)
    page_number: int | None = Field(default=None, ge=1)
    section_hint: str | None = None

    @model_validator(mode="after")
    def validate_range(self) -> TextSegment:
        if self.end_char <= self.start_char:
            raise ValueError("end_char must be greater than start_char")
        if self.end_char - self.start_char != len(self.text):
            raise ValueError("Segment offsets must match the exact text length")
        return self

    @property
    def start_index(self) -> int:
        """Compatibility name used by UI and evidence display code."""
        return self.start_char

    @property
    def end_index(self) -> int:
        """Compatibility name used by UI and evidence display code."""
        return self.end_char


class DocumentContent(StrictModel):
    document_id: NonEmptyStr
    source_kind: DocumentSourceKind
    original_filename: str | None = None
    media_type: str | None = None
    byte_size: int | None = Field(default=None, ge=0)
    source: str | None = None
    raw_text: str = Field(min_length=1)
    normalized_text: str = Field(min_length=1)
    text_length: int | None = Field(default=None, ge=1)
    language: LanguageCode = LanguageCode.UNKNOWN
    segments: list[TextSegment] = Field(default_factory=list)
    content_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_content(self) -> DocumentContent:
        actual_length = len(self.normalized_text)
        if self.text_length is not None and self.text_length != actual_length:
            raise ValueError("text_length must equal normalized_text length")
        object.__setattr__(self, "text_length", actual_length)

        for segment in self.segments:
            if segment.end_char > actual_length:
                raise ValueError("Segment range exceeds normalized_text length")
            quoted = self.normalized_text[segment.start_char : segment.end_char]
            if quoted != segment.text:
                raise ValueError("Segment text must exactly match normalized_text")
        return self


class EvidenceItem(StrictModel):
    evidence_id: NonEmptyStr
    document_id: NonEmptyStr
    segment_id: NonEmptyStr
    source_type: EvidenceSourceType
    source_reference: NonEmptyStr
    quote: str = Field(min_length=1)
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)
    page_number: int | None = Field(default=None, ge=1)
    evidence_kind: EvidenceKind
    confidence: Decimal = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_quote_range(self) -> EvidenceItem:
        if self.end_char <= self.start_char:
            raise ValueError("end_char must be greater than start_char")
        if self.end_char - self.start_char != len(self.quote):
            raise ValueError("Evidence offsets must match the exact quote length")
        return self

    @property
    def text(self) -> str:
        """Reader-facing compatibility name for the exact evidence quote."""
        return self.quote


class EvidenceRegistry:
    """Deterministic resolver for evidence IDs used across model boundaries."""

    def __init__(self, items: Iterable[EvidenceItem] = ()) -> None:
        self._items: dict[str, EvidenceItem] = {}
        for item in items:
            if item.evidence_id in self._items:
                raise ValueError(f"Duplicate evidence_id: {item.evidence_id}")
            self._items[item.evidence_id] = item

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(self._items)

    def get(self, evidence_id: str) -> EvidenceItem:
        try:
            return self._items[evidence_id]
        except KeyError as exc:
            raise KeyError(f"Unknown evidence_id: {evidence_id}") from exc

    def require_many(self, evidence_ids: Iterable[str]) -> list[EvidenceItem]:
        return [self.get(evidence_id) for evidence_id in evidence_ids]

    def __len__(self) -> int:
        return len(self._items)

    def __contains__(self, evidence_id: Any) -> bool:
        return evidence_id in self._items
