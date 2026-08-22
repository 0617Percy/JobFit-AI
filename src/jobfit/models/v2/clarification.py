"""Canonical B1 contracts for the in-memory B4 clarification flow."""

from __future__ import annotations

from decimal import Decimal

from pydantic import Field, JsonValue, model_validator

from jobfit.models.common import NonEmptyStr, StrictModel
from jobfit.models.v2._base import require_unique
from jobfit.models.v2.enums import (
    AnalysisReadiness,
    ClarificationAnswerStatus,
    ClarificationAnswerType,
    ClarificationConflictType,
    ClarificationCoreImpact,
    ClarificationQuestionStatus,
    ClarificationQuestionType,
    ClarificationResolutionStatus,
)


class ClarificationAnswerSchema(StrictModel):
    answer_type: ClarificationAnswerType
    allowed_values: list[NonEmptyStr] = Field(default_factory=list)
    minimum: Decimal | None = None
    maximum: Decimal | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> ClarificationAnswerSchema:
        require_unique(self.allowed_values, "allowed_values")
        if self.answer_type in {
            ClarificationAnswerType.ENUM,
            ClarificationAnswerType.MULTI_SELECT,
        } and not self.allowed_values:
            raise ValueError("enum answer schema requires allowed_values")
        if self.answer_type is ClarificationAnswerType.NUMBER_RANGE:
            if self.minimum is None or self.maximum is None:
                raise ValueError("number range requires minimum and maximum")
            if self.maximum < self.minimum:
                raise ValueError("number range maximum must not be below minimum")
        elif self.minimum is not None or self.maximum is not None:
            raise ValueError("only number range answers may define numeric bounds")
        return self


class ClarificationQuestion(StrictModel):
    question_id: NonEmptyStr
    analysis_id: NonEmptyStr
    question_type: ClarificationQuestionType
    prompt_text: NonEmptyStr
    target_object_ids: list[NonEmptyStr] = Field(min_length=1)
    target_field: NonEmptyStr
    reason_code: NonEmptyStr
    priority: int = Field(ge=1, le=5)
    required: bool
    possible_impact: list[ClarificationCoreImpact] = Field(min_length=1)
    answer_schema: ClarificationAnswerSchema
    source_requirement_ids: list[NonEmptyStr] = Field(default_factory=list)
    source_evidence_ids: list[NonEmptyStr] = Field(default_factory=list)
    why_this_question_exists: NonEmptyStr
    source_value: JsonValue | None = None
    status: ClarificationQuestionStatus = ClarificationQuestionStatus.PENDING

    @model_validator(mode="after")
    def validate_references(self) -> ClarificationQuestion:
        for field_name in (
            "target_object_ids",
            "source_requirement_ids",
            "source_evidence_ids",
            "possible_impact",
        ):
            require_unique(getattr(self, field_name), field_name)
        if not self.source_requirement_ids and not self.source_evidence_ids:
            raise ValueError("question requires a traceable source object")
        return self


class UnresolvedClarificationFact(StrictModel):
    fact_id: NonEmptyStr
    analysis_id: NonEmptyStr
    question_type: ClarificationQuestionType
    target_object_ids: list[NonEmptyStr] = Field(min_length=1)
    target_field: NonEmptyStr
    reason_code: NonEmptyStr
    required: bool
    possible_impact: list[ClarificationCoreImpact] = Field(min_length=1)
    answer_schema: ClarificationAnswerSchema
    source_requirement_ids: list[NonEmptyStr] = Field(default_factory=list)
    source_evidence_ids: list[NonEmptyStr] = Field(default_factory=list)
    source_fact_present: bool
    answer_can_change_core_result: bool
    source_value: JsonValue | None = None

    @model_validator(mode="after")
    def validate_source(self) -> UnresolvedClarificationFact:
        for field_name in (
            "target_object_ids",
            "possible_impact",
            "source_requirement_ids",
            "source_evidence_ids",
        ):
            require_unique(getattr(self, field_name), field_name)
        if not self.source_requirement_ids and not self.source_evidence_ids:
            raise ValueError("unresolved fact requires a traceable source")
        return self


class ClarificationAnswer(StrictModel):
    question_id: NonEmptyStr
    analysis_id: NonEmptyStr
    status: ClarificationAnswerStatus
    value: JsonValue | None = None
    normalized_fact: dict[str, JsonValue] | None = None
    raw_text: str | None = None
    answer_sequence: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def validate_answer_state(self) -> ClarificationAnswer:
        if self.status is ClarificationAnswerStatus.ANSWERED:
            if self.value is None:
                raise ValueError("answered clarification requires an answer value")
        elif (
            self.value is not None
            or self.normalized_fact is not None
            or self.raw_text is not None
        ):
            raise ValueError("non-answer state cannot carry an answer value")
        return self


class ClarificationConflict(StrictModel):
    conflict_id: NonEmptyStr
    analysis_id: NonEmptyStr
    question_id: NonEmptyStr
    conflict_type: ClarificationConflictType
    target_object_ids: list[NonEmptyStr] = Field(min_length=1)
    message: NonEmptyStr

    @model_validator(mode="after")
    def validate_targets(self) -> ClarificationConflict:
        require_unique(self.target_object_ids, "target_object_ids")
        return self


class ClarificationResolution(StrictModel):
    analysis_id: NonEmptyStr
    status: ClarificationResolutionStatus
    analysis_readiness: AnalysisReadiness
    forced_continue: bool = False
    clarification_ids: list[NonEmptyStr] = Field(default_factory=list)
    conflict_ids: list[NonEmptyStr] = Field(default_factory=list)
    affected_requirement_ids: list[NonEmptyStr] = Field(default_factory=list)
    affected_evidence_ids: list[NonEmptyStr] = Field(default_factory=list)
    warnings: list[NonEmptyStr] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_resolution(self) -> ClarificationResolution:
        for field_name in (
            "clarification_ids",
            "conflict_ids",
            "affected_requirement_ids",
            "affected_evidence_ids",
            "warnings",
        ):
            require_unique(getattr(self, field_name), field_name)
        if self.status is ClarificationResolutionStatus.REVIEW_REQUIRED:
            if self.analysis_readiness is not AnalysisReadiness.REVIEW_REQUIRED:
                raise ValueError("review resolution requires review readiness")
            if not self.conflict_ids:
                raise ValueError("review resolution requires a conflict")
        if self.forced_continue is not (
            self.status is ClarificationResolutionStatus.FORCED_CONTINUE
        ):
            raise ValueError("forced_continue must agree with resolution status")
        return self
