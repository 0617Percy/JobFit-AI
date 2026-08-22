"""Diagnosis, rewrite, recommendation, and interview preparation contracts."""

from __future__ import annotations

from pydantic import Field

from jobfit.models.common import (
    GapRemediability,
    Importance,
    NonEmptyStr,
    RecommendationLevel,
    StrictModel,
)
from jobfit.models.knowledge_advice import KnowledgeCitationUseDraft


class StrengthItem(StrictModel):
    title: NonEmptyStr
    summary: str = Field(min_length=1)
    requirement_ids: list[NonEmptyStr] = Field(min_length=1)
    evidence_ids: list[NonEmptyStr] = Field(min_length=1)
    why_it_matters: str = Field(min_length=1)


class GapItem(StrictModel):
    title: NonEmptyStr
    summary: str = Field(min_length=1)
    requirement_ids: list[NonEmptyStr] = Field(min_length=1)
    remediability: GapRemediability
    risk_level: Importance
    recommended_action: str = Field(min_length=1)
    user_confirmation_needed: bool


class ApplicationRecommendation(StrictModel):
    level: RecommendationLevel
    reasoning: list[NonEmptyStr] = Field(min_length=1)
    blocking_requirement_ids: list[str] = Field(default_factory=list)
    before_applying_actions: list[str] = Field(default_factory=list)


class RewriteSuggestionDraft(StrictModel):
    """LLM-facing rewrite without a model-controlled identifier."""

    original_text: str = Field(min_length=1)
    rewritten_text: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    requirement_ids: list[NonEmptyStr] = Field(min_length=1)
    evidence_ids: list[NonEmptyStr] = Field(min_length=1)
    introduced_claims: list[str] = Field(default_factory=list)
    user_confirmation_needed: list[str] = Field(default_factory=list)


class RewriteSuggestion(RewriteSuggestionDraft):
    suggestion_id: NonEmptyStr


class InterviewQuestionDraft(StrictModel):
    """LLM-facing interview question without a model-controlled identifier."""

    question: str = Field(min_length=1)
    intent: str = Field(min_length=1)
    answer_framework: list[NonEmptyStr] = Field(min_length=1)
    resume_evidence_ids: list[NonEmptyStr] = Field(default_factory=list)
    requirement_ids: list[NonEmptyStr] = Field(min_length=1)
    emphasis: list[str] = Field(default_factory=list)
    risks_to_avoid: list[str] = Field(default_factory=list)


class InterviewQuestion(InterviewQuestionDraft):
    question_id: NonEmptyStr


class AdviceBundleDraft(StrictModel):
    """LLM-facing advice bundle; final report validation remains deterministic."""

    strengths: list[StrengthItem] = Field(max_length=3)
    gaps: list[GapItem] = Field(max_length=3)
    recommendation_reasoning: list[NonEmptyStr] = Field(min_length=1)
    rewrite_suggestions: list[RewriteSuggestionDraft] = Field(default_factory=list)
    interview_questions: list[InterviewQuestionDraft] = Field(
        min_length=5,
        max_length=5,
    )
    knowledge_citation_uses: list[KnowledgeCitationUseDraft] = Field(
        default_factory=list,
        max_length=30,
    )
