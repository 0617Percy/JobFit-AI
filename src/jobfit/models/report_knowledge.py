"""Compact, immutable job-knowledge view embedded in AnalysisReport 1.1."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Self

from pydantic import AnyHttpUrl, ConfigDict, Field, field_serializer, model_validator

from jobfit.models.common import Importance, NonEmptyStr, RequirementType, StrictModel
from jobfit.models.knowledge import (
    EvidencePatternStrength,
    KnowledgeQuestionType,
    KnowledgeRetrievalStatus,
    KnowledgeSearchBackend,
    KnowledgeSourceType,
    KnowledgeWarningCode,
    ReliabilityLevel,
)


class ReportCitationStatus(StrEnum):
    REFERENCE = "reference"
    VALIDATED_ADVICE = "validated_advice"


class _ReportKnowledgeModel(StrictModel):
    model_config = ConfigDict(frozen=True)


class ReportRoleProfileReference(_ReportKnowledgeModel):
    role_profile_id: NonEmptyStr
    job_family_code: NonEmptyStr
    name: NonEmptyStr
    seniority: NonEmptyStr
    industry: NonEmptyStr | None = None
    relevance_score: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))

    @field_serializer("relevance_score")
    def serialize_relevance_score(self, value: Decimal) -> str:
        return format(value, "f")


class ReportKnowledgeRequirement(_ReportKnowledgeModel):
    knowledge_requirement_id: NonEmptyStr
    title: NonEmptyStr
    description: str = Field(min_length=1, max_length=500)
    requirement_type: RequirementType
    importance: Importance
    is_common_hard_blocker: bool = False
    expected_evidence: list[NonEmptyStr] = Field(default_factory=list, max_length=5)
    citation_ids: list[NonEmptyStr] = Field(default_factory=list, max_length=10)


class ReportKnowledgeEvidencePattern(_ReportKnowledgeModel):
    evidence_pattern_id: NonEmptyStr
    knowledge_requirement_id: NonEmptyStr
    description: str = Field(min_length=1, max_length=300)
    strength: EvidencePatternStrength
    citation_ids: list[NonEmptyStr] = Field(default_factory=list, max_length=10)


class ReportKnowledgeInterviewReference(_ReportKnowledgeModel):
    knowledge_question_id: NonEmptyStr
    competency_dimension_code: NonEmptyStr
    question: str = Field(min_length=1, max_length=300)
    question_type: KnowledgeQuestionType
    citation_ids: list[NonEmptyStr] = Field(default_factory=list, max_length=10)


class ReportKnowledgeWarning(_ReportKnowledgeModel):
    code: KnowledgeWarningCode
    message: str = Field(min_length=1, max_length=300)
    recoverable: bool = True


class ReportKnowledgeCitation(_ReportKnowledgeModel):
    citation_id: NonEmptyStr
    source_id: NonEmptyStr
    source_title: NonEmptyStr
    source_type: KnowledgeSourceType
    source_url: AnyHttpUrl | None = None
    knowledge_version_id: NonEmptyStr
    role_profile_id: NonEmptyStr | None = None
    section: str | None = Field(default=None, max_length=120)
    reliability_level: ReliabilityLevel
    short_summary: str = Field(min_length=1, max_length=240)
    used_by: list[NonEmptyStr] = Field(default_factory=list, max_length=20)
    validation_status: ReportCitationStatus = ReportCitationStatus.REFERENCE

    @model_validator(mode="after")
    def validate_usage(self) -> Self:
        if self.used_by != sorted(set(self.used_by)):
            raise ValueError("used_by must be unique and stably sorted")
        if (
            self.validation_status is ReportCitationStatus.VALIDATED_ADVICE
            and not self.used_by
        ):
            raise ValueError("validated advice citation requires a target")
        if self.validation_status is ReportCitationStatus.REFERENCE and self.used_by:
            raise ValueError("reference-only citation cannot claim advice use")
        return self


class ReportKnowledgeAdviceTrace(_ReportKnowledgeModel):
    validated: bool
    fallback_used: bool
    prompt_version: NonEmptyStr
    validator_version: NonEmptyStr
    generation_strategy_version: NonEmptyStr
    used_citation_ids: list[NonEmptyStr] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_citation_order(self) -> Self:
        if self.used_citation_ids != sorted(set(self.used_citation_ids)):
            raise ValueError("used_citation_ids must be unique and stably sorted")
        return self


class ReportKnowledgeSection(_ReportKnowledgeModel):
    enabled: bool
    status: KnowledgeRetrievalStatus
    knowledge_version_id: NonEmptyStr | None = None
    knowledge_version: NonEmptyStr | None = None
    knowledge_content_hash: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    retrieval_mode: KnowledgeSearchBackend = KnowledgeSearchBackend.DISABLED
    retrieval_strategy_version: str = Field(pattern=r"^\d+\.\d+$")
    selected_role_profile: ReportRoleProfileReference | None = None
    role_candidates: list[ReportRoleProfileReference] = Field(
        default_factory=list,
        max_length=3,
    )
    requirements: list[ReportKnowledgeRequirement] = Field(
        default_factory=list,
        max_length=12,
    )
    evidence_patterns: list[ReportKnowledgeEvidencePattern] = Field(
        default_factory=list,
        max_length=12,
    )
    interview_references: list[ReportKnowledgeInterviewReference] = Field(
        default_factory=list,
        max_length=10,
    )
    citations: list[ReportKnowledgeCitation] = Field(default_factory=list, max_length=20)
    warnings: list[ReportKnowledgeWarning] = Field(default_factory=list, max_length=10)
    advice_trace: ReportKnowledgeAdviceTrace | None = None
    fallback_used: bool = False

    @model_validator(mode="after")
    def enforce_status_invariants(self) -> Self:
        details = (
            self.selected_role_profile,
            self.requirements,
            self.evidence_patterns,
            self.interview_references,
            self.citations,
            self.advice_trace,
        )
        if self.status is KnowledgeRetrievalStatus.AVAILABLE:
            if (
                not self.enabled
                or self.knowledge_version_id is None
                or self.knowledge_version is None
                or self.knowledge_content_hash is None
                or self.selected_role_profile is None
            ):
                raise ValueError("available report knowledge requires one identity")
            return self
        if self.status is KnowledgeRetrievalStatus.AMBIGUOUS:
            if not self.enabled or len(self.role_candidates) < 2:
                raise ValueError("ambiguous report knowledge requires candidates")
            if any(details):
                raise ValueError("ambiguous report knowledge cannot expose role details")
            return self
        if self.status is KnowledgeRetrievalStatus.DISABLED:
            if self.enabled:
                raise ValueError("disabled report knowledge cannot be enabled")
            if any(details) or any(
                (
                    self.knowledge_version_id,
                    self.knowledge_version,
                    self.knowledge_content_hash,
                    self.role_candidates,
                )
            ):
                raise ValueError("disabled report knowledge cannot expose content")
            return self
        if any(details) or self.role_candidates:
            raise ValueError("non-available report knowledge cannot expose role details")
        if self.status is KnowledgeRetrievalStatus.UNAVAILABLE and any(
            (
                self.knowledge_version_id,
                self.knowledge_version,
                self.knowledge_content_hash,
            )
        ):
            raise ValueError("unavailable report knowledge cannot claim an identity")
        if not self.enabled:
            raise ValueError("enabled knowledge status requires enabled=true")
        return self


__all__ = [
    "ReportCitationStatus",
    "ReportKnowledgeAdviceTrace",
    "ReportKnowledgeCitation",
    "ReportKnowledgeEvidencePattern",
    "ReportKnowledgeInterviewReference",
    "ReportKnowledgeRequirement",
    "ReportKnowledgeSection",
    "ReportKnowledgeWarning",
    "ReportRoleProfileReference",
]
