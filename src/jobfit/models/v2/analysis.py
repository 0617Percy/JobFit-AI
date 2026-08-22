"""Target deterministic-decision, advisory, and clarification contracts."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import Field, JsonValue, model_validator

from jobfit.models.common import NonEmptyStr
from jobfit.models.v2._base import ExtensibleDomainModel, require_unique
from jobfit.models.v2.enums import (
    ActionTiming,
    ActionType,
    AnalysisReadiness,
    ClarificationAnswerStatus,
    Confidence,
    Effort,
    EligibilityStatus,
    EvidenceSourceOrigin,
    EvidenceVisibility,
    InterviewQuestionType,
    Priority,
    ReasonCode,
    Recommendation,
    SeniorityAlignment,
    Transferability,
)


class AnalysisCore(ExtensibleDomainModel):
    analysis_id: NonEmptyStr
    resume_version_id: NonEmptyStr
    jd_snapshot_id: NonEmptyStr
    analysis_readiness: AnalysisReadiness
    eligibility_status: EligibilityStatus
    seniority_alignment: SeniorityAlignment
    base_fit_score: Decimal = Field(ge=0, le=100)
    preferred_bonus: Decimal = Field(ge=0, le=5)
    final_fit_score: Decimal = Field(ge=0, le=100)
    critical_gap_requirement_ids: list[NonEmptyStr] = Field(default_factory=list)
    confidence: Confidence
    recommendation: Recommendation
    recommendation_reason_codes: list[ReasonCode] = Field(default_factory=list)
    hard_blocker_ids: list[NonEmptyStr] = Field(default_factory=list)
    hard_pending_ids: list[NonEmptyStr] = Field(default_factory=list)
    forced_continue: bool = False

    @model_validator(mode="after")
    def validate_decision_state(self) -> AnalysisCore:
        for field_name in (
            "critical_gap_requirement_ids",
            "recommendation_reason_codes",
            "hard_blocker_ids",
            "hard_pending_ids",
        ):
            require_unique(getattr(self, field_name), field_name)
        if (
            self.eligibility_status is EligibilityStatus.BLOCKED
            and self.recommendation is not Recommendation.NOT_RECOMMENDED
        ):
            raise ValueError("blocked eligibility requires not_recommended")
        if self.recommendation is Recommendation.PRIORITY and (
            self.hard_blocker_ids
            or self.critical_gap_requirement_ids
            or self.confidence is Confidence.LOW
            or self.seniority_alignment is SeniorityAlignment.MISALIGNED
        ):
            raise ValueError("priority violates deterministic decision guardrails")
        if (
            self.analysis_readiness is AnalysisReadiness.CLARIFICATION_REQUIRED
            and self.eligibility_status is not EligibilityStatus.PENDING
        ):
            raise ValueError("clarification_required requires pending eligibility")
        return self


class ActionRecommendation(ExtensibleDomainModel):
    action_id: NonEmptyStr
    action_type: ActionType
    priority: Priority
    related_requirement_ids: list[NonEmptyStr] = Field(default_factory=list)
    related_evidence_ids: list[NonEmptyStr] = Field(default_factory=list)
    supported_by_evidence_ids: list[NonEmptyStr] = Field(default_factory=list)
    title: NonEmptyStr
    why_it_matters: str | None = None
    recommended_action: str | None = None
    completion_criteria: str | None = None
    effort: Effort | None = None
    time_to_complete: str | None = None
    evidence_visibility: EvidenceVisibility | None = None
    transferability: Transferability | None = None
    timing: ActionTiming | None = None
    potential_impact: str | None = None

    @model_validator(mode="after")
    def validate_evidence_boundary(self) -> ActionRecommendation:
        for field_name in (
            "related_requirement_ids",
            "related_evidence_ids",
            "supported_by_evidence_ids",
        ):
            require_unique(getattr(self, field_name), field_name)
        if self.action_type in {ActionType.REWRITE, ActionType.RECOVER} and not (
            self.supported_by_evidence_ids
        ):
            raise ValueError("Rewrite and recover actions require candidate evidence")
        if self.action_type is ActionType.BUILD and self.supported_by_evidence_ids:
            raise ValueError("Build actions cannot claim existing evidence")
        return self


class InterviewQuestion(ExtensibleDomainModel):
    question_id: NonEmptyStr
    question_type: InterviewQuestionType
    priority: Priority
    question: NonEmptyStr
    why_likely: str | None = None
    related_requirement_ids: list[NonEmptyStr] = Field(default_factory=list)
    related_evidence_ids: list[NonEmptyStr] = Field(default_factory=list)
    preparation_points: list[NonEmptyStr] = Field(default_factory=list)
    knowledge_citation_ids: list[NonEmptyStr] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_reference_lists(self) -> InterviewQuestion:
        for field_name in (
            "related_requirement_ids",
            "related_evidence_ids",
            "knowledge_citation_ids",
        ):
            require_unique(getattr(self, field_name), field_name)
        return self


class UserClarification(ExtensibleDomainModel):
    clarification_id: NonEmptyStr
    analysis_id: NonEmptyStr
    source_origin: Literal[EvidenceSourceOrigin.USER_CLARIFICATION] = (
        EvidenceSourceOrigin.USER_CLARIFICATION
    )
    question_type: str | None = None
    question: NonEmptyStr
    answer: NonEmptyStr | None = None
    answer_status: ClarificationAnswerStatus = ClarificationAnswerStatus.ANSWERED
    origin_question_id: NonEmptyStr | None = None
    source_identity: NonEmptyStr | None = None
    answer_sequence: int = Field(default=1, ge=1)
    target_object_ids: list[NonEmptyStr] = Field(default_factory=list)
    normalized_fact: dict[str, JsonValue] | None = None
    creates_evidence: bool = False
    affects_recommendation: bool = False
    affected_requirement_ids: list[NonEmptyStr] = Field(default_factory=list)
    affected_evidence_ids: list[NonEmptyStr] = Field(default_factory=list)
    created_evidence_ids: list[NonEmptyStr] = Field(default_factory=list)
    warnings: list[NonEmptyStr] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_reference_lists(self) -> UserClarification:
        for field_name in (
            "affected_requirement_ids",
            "affected_evidence_ids",
            "created_evidence_ids",
            "target_object_ids",
            "warnings",
        ):
            require_unique(getattr(self, field_name), field_name)
        if self.creates_evidence != bool(self.created_evidence_ids):
            raise ValueError(
                "creates_evidence must agree with created_evidence_ids"
            )
        if self.answer_status is ClarificationAnswerStatus.ANSWERED:
            if self.answer is None:
                raise ValueError("answered clarification requires an answer")
        elif self.answer is not None or self.normalized_fact is not None:
            raise ValueError("non-answer clarification cannot carry answer facts")
        if self.answer_status is not ClarificationAnswerStatus.ANSWERED and (
            self.creates_evidence or self.affects_recommendation
        ):
            raise ValueError("non-answer clarification cannot create decision facts")
        return self
