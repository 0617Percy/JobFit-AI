"""Job description extraction and normalized requirement contracts."""

from __future__ import annotations

from decimal import Decimal

from pydantic import Field, model_validator

from jobfit.models.common import (
    HardConditionKind,
    Importance,
    LanguageCode,
    NonEmptyStr,
    RequirementCategory,
    RequirementType,
    StrictModel,
)


class JobRequirementDraft(StrictModel):
    """LLM-facing requirement before IDs and weights are assigned by code."""

    requirement_text: str = Field(min_length=1)
    source_text: str = Field(min_length=1)
    source_start_char: int = Field(ge=0)
    source_end_char: int = Field(gt=0)
    requirement_type: RequirementType
    category: RequirementCategory
    importance: Importance
    mandatory: bool
    hard_condition_kind: HardConditionKind = HardConditionKind.NONE
    normalized_key: NonEmptyStr

    @model_validator(mode="after")
    def validate_requirement_rules(self) -> JobRequirementDraft:
        if self.source_end_char <= self.source_start_char:
            raise ValueError(
                "source_end_char must be greater than source_start_char"
            )
        if self.requirement_type is RequirementType.IMPLICIT and self.mandatory:
            raise ValueError("Implicit requirements cannot be mandatory")
        if self.requirement_type is RequirementType.IMPLICIT and self.importance in {
            Importance.HIGH,
            Importance.CRITICAL,
        }:
            raise ValueError("Implicit requirements cannot exceed medium importance")
        if (
            self.requirement_type is RequirementType.IMPLICIT
            and self.hard_condition_kind is not HardConditionKind.NONE
        ):
            raise ValueError("Implicit requirements cannot be hard conditions")
        if (
            self.hard_condition_kind is not HardConditionKind.NONE
            and self.importance is not Importance.CRITICAL
        ):
            raise ValueError("Hard conditions must have critical importance")
        if (
            self.hard_condition_kind is not HardConditionKind.NONE
            and not self.mandatory
        ):
            raise ValueError("Hard conditions must be mandatory")
        return self


class JobRequirement(JobRequirementDraft):
    requirement_id: NonEmptyStr
    priority_factor: Decimal = Field(ge=0)
    weight: Decimal = Field(ge=0, le=100)


class JobRequirementCollection(StrictModel):
    items: list[JobRequirement] = Field(min_length=1)
    deduplication_notes: list[str] = Field(default_factory=list)
    source_coverage_ratio: Decimal = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_unique_requirements(self) -> JobRequirementCollection:
        requirement_ids = [item.requirement_id for item in self.items]
        if len(requirement_ids) != len(set(requirement_ids)):
            raise ValueError("Duplicate requirement_id values are not allowed")
        normalized_keys = [item.normalized_key for item in self.items]
        if len(normalized_keys) != len(set(normalized_keys)):
            raise ValueError("Duplicate normalized_key values are not allowed")
        return self


class JobProfile(StrictModel):
    job_id: NonEmptyStr
    title: str | None = None
    company: str | None = None
    language: LanguageCode
    jd_text: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    requirements: JobRequirementCollection
    keywords: list[str] = Field(default_factory=list)
    extraction_warnings: list[str] = Field(default_factory=list)


class JobExtractionDraft(StrictModel):
    title: str | None = None
    company: str | None = None
    language: LanguageCode = LanguageCode.UNKNOWN
    summary: str | None = None
    requirements: list[JobRequirementDraft] = Field(min_length=1)
    keywords: list[str] = Field(default_factory=list)
    extraction_warnings: list[str] = Field(default_factory=list)
