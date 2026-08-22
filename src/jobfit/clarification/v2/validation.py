"""Four-layer validation for B4 clarification questions and answers."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal, InvalidOperation

from jobfit.models.v2 import (
    ClarificationAnswer,
    ClarificationAnswerStatus,
    ClarificationAnswerType,
    ClarificationQuestion,
    ClarificationQuestionStatus,
    ClarificationQuestionType,
    Evidence,
    JobProfile,
    Requirement,
    RequirementSource,
    RequirementType,
    ResumeProfile,
)


class ClarificationValidationError(ValueError):
    """Raised when clarification input is unsafe or cross-object invalid."""


def validate_active_questions(
    questions: Sequence[ClarificationQuestion],
    *,
    analysis_id: str,
    requirements: Sequence[Requirement],
    evidence: Sequence[Evidence],
    resume_profile: ResumeProfile | None = None,
    job_profile: JobProfile | None = None,
) -> None:
    """Validate active question identity, limits, ownership, and references."""
    if len(questions) > 3:
        raise ClarificationValidationError("At most three active questions are allowed.")
    question_ids = [item.question_id for item in questions]
    if len(question_ids) != len(set(question_ids)):
        raise ClarificationValidationError("Active question IDs must be unique.")
    requirement_ids = {item.requirement_id for item in requirements}
    requirement_by_id = {item.requirement_id: item for item in requirements}
    evidence_ids = {item.evidence_id for item in evidence}
    target_ids = requirement_ids | evidence_ids
    if resume_profile is not None:
        target_ids.add(resume_profile.resume_version_id)
    if job_profile is not None:
        target_ids.add(job_profile.jd_snapshot_id)
    for question in questions:
        if question.analysis_id != analysis_id:
            raise ClarificationValidationError(
                "Question belongs to another analysis."
            )
        if not set(question.source_requirement_ids) <= requirement_ids:
            raise ClarificationValidationError(
                "Question references an unknown requirement."
            )
        if not set(question.source_evidence_ids) <= evidence_ids:
            raise ClarificationValidationError("Question references unknown evidence.")
        if not set(question.target_object_ids) <= target_ids:
            raise ClarificationValidationError("Question targets an unknown object.")
        if question.status is not ClarificationQuestionStatus.PENDING:
            raise ClarificationValidationError("Only pending questions may be active.")
        if question.question_type in {
            ClarificationQuestionType.HARD_ELIGIBILITY,
            ClarificationQuestionType.ROLE_SENIORITY,
        } and not question.required:
            raise ClarificationValidationError(
                "Hard and seniority questions must be required."
            )
        if (
            question.question_type is ClarificationQuestionType.CONFIDENCE
            and question.required
        ):
            raise ClarificationValidationError(
                "Confidence-only questions cannot be required."
            )
        source_requirements = [
            requirement_by_id[item] for item in question.source_requirement_ids
        ]
        if any(item.source is not RequirementSource.JD for item in source_requirements):
            raise ClarificationValidationError(
                "Knowledge requirements cannot source core clarification."
            )
        if question.question_type is ClarificationQuestionType.HARD_ELIGIBILITY and (
            len(source_requirements) != 1
            or source_requirements[0].requirement_type is not RequirementType.HARD
        ):
            raise ClarificationValidationError(
                "Hard answer must target exactly one explicit hard requirement."
            )


def validate_clarification_answer(
    answer: ClarificationAnswer,
    question: ClarificationQuestion,
) -> None:
    """Validate one answer against the exact question and its answer contract."""
    if answer.question_id != question.question_id:
        raise ClarificationValidationError("Answer references a nonexistent question.")
    if answer.analysis_id != question.analysis_id:
        raise ClarificationValidationError("Answer belongs to another analysis.")
    if answer.status is not ClarificationAnswerStatus.ANSWERED:
        return

    value = answer.value
    schema = question.answer_schema
    if schema.answer_type is ClarificationAnswerType.BOOLEAN:
        if not isinstance(value, bool):
            raise ClarificationValidationError("Boolean answer required.")
    elif schema.answer_type is ClarificationAnswerType.ENUM:
        if not isinstance(value, str) or value not in schema.allowed_values:
            raise ClarificationValidationError("Answer is outside the allowed enum.")
    elif schema.answer_type is ClarificationAnswerType.MULTI_SELECT:
        if not isinstance(value, list) or any(
            not isinstance(item, str) or item not in schema.allowed_values
            for item in value
        ):
            raise ClarificationValidationError("Invalid multi-select answer.")
        if len(value) != len(set(value)):
            raise ClarificationValidationError("Multi-select answers must be unique.")
    elif schema.answer_type is ClarificationAnswerType.NUMBER_RANGE:
        if isinstance(value, bool):
            raise ClarificationValidationError("Numeric answer required.")
        try:
            numeric = Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise ClarificationValidationError("Numeric answer required.") from exc
        if numeric < schema.minimum or numeric > schema.maximum:  # type: ignore[operator]
            raise ClarificationValidationError("Numeric answer is outside the range.")
    elif not isinstance(value, str) or not value.strip():
        raise ClarificationValidationError("A non-empty short fact is required.")
