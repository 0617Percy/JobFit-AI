"""Requirement matching and deterministic scoring result contracts."""

from __future__ import annotations

from decimal import Decimal

from pydantic import Field, model_validator

from jobfit.models.common import (
    EvidenceKind,
    MatchStatus,
    NonEmptyStr,
    RecommendationLevel,
    RequirementCategory,
    StrictModel,
)
from jobfit.models.document import EvidenceItem


class RequirementMatchDraft(StrictModel):
    """LLM-facing semantic judgment without a program-computed score."""

    requirement_id: NonEmptyStr
    match_status: MatchStatus
    evidence_items: list[EvidenceItem] = Field(default_factory=list)
    reasoning: str = Field(min_length=1)
    confidence: Decimal = Field(ge=0, le=1)
    missing_evidence_note: str | None = None
    improvement_suggestion: str = Field(min_length=1)


class RequirementMatch(RequirementMatchDraft):
    match_score: Decimal = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_grounding(self) -> RequirementMatch:
        evidence_ids = [item.evidence_id for item in self.evidence_items]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("Duplicate evidence_id values are not allowed")
        if self.match_status is MatchStatus.MATCHED and not any(
            item.evidence_kind is EvidenceKind.DIRECT
            for item in self.evidence_items
        ):
            raise ValueError("A matched requirement must have direct evidence")
        if (
            self.match_status is MatchStatus.PARTIAL_MATCH
            and not self.evidence_items
        ):
            raise ValueError("A partial match must have at least one evidence item")
        if (
            self.match_status in {MatchStatus.NOT_MATCHED, MatchStatus.UNKNOWN}
            and not self.missing_evidence_note
        ):
            raise ValueError(
                "missing_evidence_note is required when evidence is absent"
            )
        return self


class DimensionScore(StrictModel):
    category: RequirementCategory
    base_points: Decimal = Field(ge=0, le=100)
    effective_points: Decimal = Field(ge=0, le=100)
    earned_points: Decimal = Field(ge=0, le=100)
    active: bool
    requirement_ids: list[NonEmptyStr]
    coverage_ratio: Decimal = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_dimension_totals(self) -> DimensionScore:
        if self.earned_points > self.effective_points:
            raise ValueError("earned_points cannot exceed effective_points")
        if self.active and not self.requirement_ids:
            raise ValueError("Active dimensions require at least one requirement")
        if not self.active and (
            self.effective_points != 0
            or self.earned_points != 0
            or self.requirement_ids
        ):
            raise ValueError("Inactive dimensions cannot carry effective points")
        return self


class MatchScoreSummary(StrictModel):
    raw_score: Decimal = Field(ge=0, le=100)
    score_cap: Decimal = Field(ge=0, le=100)
    final_score: Decimal = Field(ge=0, le=100)
    dimension_scores: list[DimensionScore]
    mandatory_coverage_ratio: Decimal = Field(ge=0, le=1)
    strong_evidence_coverage_ratio: Decimal = Field(ge=0, le=1)
    confirmed_hard_blockers: list[NonEmptyStr]
    unverified_hard_blockers: list[NonEmptyStr]
    cap_reasons: list[str] = Field(default_factory=list)
    recommendation_level: RecommendationLevel

    @model_validator(mode="after")
    def validate_score_cap(self) -> MatchScoreSummary:
        if self.final_score > self.raw_score:
            raise ValueError("final_score cannot exceed raw_score")
        if self.final_score > self.score_cap:
            raise ValueError("final_score cannot exceed score_cap")
        return self
