"""B1 target-backed contracts required by the B4 clarification flow."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

import jobfit.models.v2 as v2


def test_b4_contracts_expose_review_and_structured_question_fields() -> None:
    assert v2.AnalysisReadiness("review_required") is v2.AnalysisReadiness.REVIEW_REQUIRED

    question = v2.ClarificationQuestion(
        question_id="question-hard-days",
        analysis_id="analysis-1",
        question_type="hard_eligibility",
        prompt_text="Can you work at least five days each week?",
        target_object_ids=["requirement-days"],
        target_field="weekly_availability_days",
        reason_code="ELIGIBILITY_PENDING",
        priority=1,
        required=True,
        possible_impact=["eligibility", "recommendation"],
        answer_schema={"answer_type": "boolean"},
        source_requirement_ids=["requirement-days"],
        why_this_question_exists="The explicit hard condition is unresolved.",
    )

    assert question.status is v2.ClarificationQuestionStatus.PENDING
    assert question.answer_schema.answer_type is v2.ClarificationAnswerType.BOOLEAN
    assert question.priority == 1


def test_answer_contract_distinguishes_answer_skip_and_unable() -> None:
    answered = v2.ClarificationAnswer(
        question_id="question-1",
        analysis_id="analysis-1",
        status="answered",
        value=True,
        normalized_fact={"weekly_availability_days": 5},
    )
    skipped = v2.ClarificationAnswer(
        question_id="question-1",
        analysis_id="analysis-1",
        status="skipped",
    )
    unable = v2.ClarificationAnswer(
        question_id="question-1",
        analysis_id="analysis-1",
        status="unable_to_confirm",
    )

    assert answered.value is True
    assert skipped.value is None
    assert unable.status is v2.ClarificationAnswerStatus.UNABLE_TO_CONFIRM

    with pytest.raises(ValidationError, match="answered clarification requires"):
        v2.ClarificationAnswer(
            question_id="question-1",
            analysis_id="analysis-1",
            status="answered",
        )
    with pytest.raises(ValidationError, match="cannot carry an answer value"):
        v2.ClarificationAnswer(
            question_id="question-1",
            analysis_id="analysis-1",
            status="skipped",
            value=False,
        )


def test_user_clarification_keeps_non_answers_fact_free() -> None:
    clarification = v2.UserClarification(
        clarification_id="clarification-1",
        analysis_id="analysis-1",
        origin_question_id="question-1",
        source_identity="user-clarification:analysis-1:1",
        question_type="hard_eligibility",
        question="Can you satisfy the condition?",
        answer=None,
        answer_status="skipped",
        target_object_ids=["requirement-1"],
        affected_requirement_ids=["requirement-1"],
    )

    assert clarification.answer is None
    assert clarification.normalized_fact is None
    assert clarification.creates_evidence is False

    with pytest.raises(ValidationError, match="non-answer clarification"):
        v2.UserClarification(
            clarification_id="clarification-2",
            analysis_id="analysis-1",
            origin_question_id="question-1",
            source_identity="user-clarification:analysis-1:2",
            question="Can you satisfy the condition?",
            answer="yes",
            answer_status="unable_to_confirm",
        )


def test_question_contract_rejects_duplicate_references_and_invalid_schema() -> None:
    with pytest.raises(ValidationError, match="source_requirement_ids"):
        v2.ClarificationQuestion(
            question_id="question-1",
            analysis_id="analysis-1",
            question_type="hard_eligibility",
            prompt_text="Can you satisfy the condition?",
            target_object_ids=["requirement-1"],
            target_field="eligibility",
            reason_code="ELIGIBILITY_PENDING",
            priority=1,
            required=True,
            possible_impact=["eligibility"],
            answer_schema={"answer_type": "boolean"},
            source_requirement_ids=["requirement-1", "requirement-1"],
            why_this_question_exists="A hard condition is unresolved.",
        )

    with pytest.raises(ValidationError, match="enum answer schema requires"):
        v2.ClarificationAnswerSchema(answer_type="enum")
