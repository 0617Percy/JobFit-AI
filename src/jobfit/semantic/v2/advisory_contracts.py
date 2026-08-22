"""Strict prompt DTOs for the P06-P08 advisory and presentation stages."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from jobfit.models.common import NonEmptyStr, StrictModel
from jobfit.models.v2 import (
    ActionRecommendation,
    ActionTiming,
    ActionType,
    AnalysisCore,
    Effort,
    Evidence,
    EvidenceSourceOrigin,
    InterviewQuestionType,
    JobFamily,
    KnowledgeCitation,
    Priority,
    Requirement,
    RequirementMatch,
    UserClarification,
)


class P06ActionMode(StrEnum):
    CANDIDATE_GROUNDED = "candidate_grounded"
    FUTURE_BUILD = "future_build"


class P06RequirementReference(StrictModel):
    requirement_id: NonEmptyStr
    descriptor: NonEmptyStr


class P06EvidenceReference(StrictModel):
    evidence_id: NonEmptyStr
    descriptor: NonEmptyStr
    source_origin: EvidenceSourceOrigin
    source_record_id: NonEmptyStr | None = None
    eligible_for_rewrite: bool
    eligible_for_recover: bool


class P06ClarificationReference(StrictModel):
    clarification_id: NonEmptyStr
    descriptor: NonEmptyStr
    created_evidence_ids: list[NonEmptyStr] = Field(default_factory=list)


class P06ActionInput(StrictModel):
    analysis_id: NonEmptyStr
    mode: P06ActionMode
    analysis_core: AnalysisCore
    requirements: list[Requirement]
    requirement_matches: list[RequirementMatch]
    candidate_evidence: list[Evidence]
    user_clarifications: list[UserClarification]
    requirement_reference_catalog: list[P06RequirementReference]
    evidence_reference_catalog: list[P06EvidenceReference]
    clarification_reference_catalog: list[P06ClarificationReference]


class P06BuildInput(P06ActionInput):
    knowledge_context: list[KnowledgeCitation]


class P06ActionDraft(StrictModel):
    action_id: NonEmptyStr
    action_type: ActionType
    priority: Priority
    related_requirement_ids: list[NonEmptyStr] = Field(min_length=1)
    related_evidence_ids: list[NonEmptyStr] = Field(default_factory=list)
    supported_by_evidence_ids: list[NonEmptyStr] = Field(default_factory=list)
    source_clarification_ids: list[NonEmptyStr] = Field(default_factory=list)
    knowledge_citation_ids: list[NonEmptyStr] = Field(default_factory=list)
    title: NonEmptyStr
    why_it_matters: NonEmptyStr
    recommended_action: NonEmptyStr
    completion_criteria: NonEmptyStr
    effort: Effort
    time_to_complete: NonEmptyStr
    timing: ActionTiming
    introduced_claims: list[NonEmptyStr] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_references(self) -> P06ActionDraft:
        for field_name in (
            "related_requirement_ids",
            "related_evidence_ids",
            "supported_by_evidence_ids",
            "source_clarification_ids",
            "knowledge_citation_ids",
            "introduced_claims",
        ):
            values = getattr(self, field_name)
            if len(values) != len(set(values)):
                raise ValueError(f"P06 {field_name} must be unique.")
        return self


class P06ActionOutput(StrictModel):
    actions: list[P06ActionDraft]
    warnings: list[NonEmptyStr] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_action_ids(self) -> P06ActionOutput:
        action_ids = [item.action_id for item in self.actions]
        if len(action_ids) != len(set(action_ids)):
            raise ValueError("P06 action IDs must be unique.")
        return self


class P06CandidateActionDraft(StrictModel):
    """Candidate-grounded provider transport; the system owns action_id."""

    action_type: ActionType
    priority: Priority
    related_requirement_ids: list[NonEmptyStr] = Field(min_length=1)
    related_evidence_ids: list[NonEmptyStr] = Field(default_factory=list)
    supported_by_evidence_ids: list[NonEmptyStr] = Field(default_factory=list)
    source_clarification_ids: list[NonEmptyStr] = Field(default_factory=list)
    knowledge_citation_ids: list[NonEmptyStr] = Field(default_factory=list)
    title: NonEmptyStr
    why_it_matters: NonEmptyStr
    recommended_action: NonEmptyStr
    completion_criteria: NonEmptyStr
    effort: Effort
    time_to_complete: NonEmptyStr
    timing: ActionTiming
    introduced_claims: list[NonEmptyStr] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_references(self) -> P06CandidateActionDraft:
        for field_name in (
            "related_requirement_ids",
            "related_evidence_ids",
            "supported_by_evidence_ids",
            "source_clarification_ids",
            "knowledge_citation_ids",
            "introduced_claims",
        ):
            values = getattr(self, field_name)
            if len(values) != len(set(values)):
                raise ValueError(f"P06 {field_name} must be unique.")
        return self


class P06CandidateOutput(StrictModel):
    actions: list[P06CandidateActionDraft]
    warnings: list[NonEmptyStr] = Field(default_factory=list)


class P06BuildActionDraft(StrictModel):
    """Future-build provider transport: action_type, action_id, future_only,
    and every evidence/clarification reference are system-owned and fixed by
    the deterministic mapper, so they are not exposed to the model."""

    priority: Priority
    related_requirement_ids: list[NonEmptyStr] = Field(min_length=1)
    knowledge_citation_ids: list[NonEmptyStr] = Field(default_factory=list)
    title: NonEmptyStr
    why_it_matters: NonEmptyStr
    recommended_action: NonEmptyStr
    completion_criteria: NonEmptyStr
    effort: Effort
    time_to_complete: NonEmptyStr
    timing: ActionTiming

    @model_validator(mode="after")
    def validate_unique_references(self) -> P06BuildActionDraft:
        for field_name in ("related_requirement_ids", "knowledge_citation_ids"):
            values = getattr(self, field_name)
            if len(values) != len(set(values)):
                raise ValueError(f"P06 {field_name} must be unique.")
        return self


class P06BuildOutput(StrictModel):
    actions: list[P06BuildActionDraft]
    warnings: list[NonEmptyStr] = Field(default_factory=list)


class AdvisoryKnowledgeContext(StrictModel):
    knowledge_version: NonEmptyStr
    role_family: JobFamily
    citations: list[KnowledgeCitation]


class P07InterviewInput(StrictModel):
    analysis_id: NonEmptyStr
    analysis_core: AnalysisCore
    requirements: list[Requirement]
    requirement_matches: list[RequirementMatch]
    candidate_evidence: list[Evidence]
    actions: list[ActionRecommendation]
    knowledge_context: list[KnowledgeCitation]


class P07InterviewDraft(StrictModel):
    question_id: NonEmptyStr
    question_type: InterviewQuestionType
    priority: Priority
    question: NonEmptyStr
    why_likely: NonEmptyStr
    related_requirement_ids: list[NonEmptyStr] = Field(default_factory=list)
    related_evidence_ids: list[NonEmptyStr] = Field(default_factory=list)
    critical_gap_requirement_ids: list[NonEmptyStr] = Field(default_factory=list)
    hard_concern_requirement_ids: list[NonEmptyStr] = Field(default_factory=list)
    related_action_ids: list[NonEmptyStr] = Field(default_factory=list)
    preparation_points: list[NonEmptyStr] = Field(min_length=3)
    knowledge_citation_ids: list[NonEmptyStr] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_references(self) -> P07InterviewDraft:
        for field_name in (
            "related_requirement_ids",
            "related_evidence_ids",
            "critical_gap_requirement_ids",
            "hard_concern_requirement_ids",
            "related_action_ids",
            "preparation_points",
            "knowledge_citation_ids",
        ):
            values = getattr(self, field_name)
            if len(values) != len(set(values)):
                raise ValueError(f"P07 {field_name} must be unique.")
        return self


class P07InterviewOutput(StrictModel):
    questions: list[P07InterviewDraft]
    warnings: list[NonEmptyStr] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_question_ids(self) -> P07InterviewOutput:
        question_ids = [item.question_id for item in self.questions]
        if len(question_ids) != len(set(question_ids)):
            raise ValueError("P07 question IDs must be unique.")
        return self


class P08ReportInput(StrictModel):
    analysis_id: NonEmptyStr
    analysis_core: AnalysisCore
    explicit_requirements: list[Requirement]
    implicit_requirements: list[Requirement]
    candidate_evidence: list[Evidence]
    knowledge_context: list[KnowledgeCitation]


class P08ExplanationDraft(StrictModel):
    text: NonEmptyStr
    knowledge_citation_ids: list[NonEmptyStr] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_citation_ids(self) -> P08ExplanationDraft:
        if len(self.knowledge_citation_ids) != len(set(self.knowledge_citation_ids)):
            raise ValueError("P08 explanation citation IDs must be unique.")
        return self


class P08ImplicitExplanationDraft(P08ExplanationDraft):
    requirement_id: NonEmptyStr
    knowledge_citation_ids: list[NonEmptyStr] = Field(min_length=1)


class P08ReportOutput(StrictModel):
    job_explanations: list[P08ExplanationDraft]
    implicit_explanations: list[P08ImplicitExplanationDraft]
    application_strategy_notes: list[NonEmptyStr]
    boundary_notes: list[NonEmptyStr]
    warnings: list[NonEmptyStr] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_items(self) -> P08ReportOutput:
        implicit_ids = [item.requirement_id for item in self.implicit_explanations]
        if len(implicit_ids) != len(set(implicit_ids)):
            raise ValueError("P08 implicit requirement explanations must be unique.")
        for field_name in (
            "application_strategy_notes",
            "boundary_notes",
            "warnings",
        ):
            values = getattr(self, field_name)
            if len(values) != len(set(values)):
                raise ValueError(f"P08 {field_name} must be unique.")
        return self
