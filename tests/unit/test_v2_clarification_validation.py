"""B4 clarification cross-object and answer-schema validation."""

from copy import deepcopy

import pytest

from jobfit.clarification.v2.validation import (
    ClarificationValidationError,
    validate_active_questions,
    validate_clarification_answer,
)
from jobfit.models.common import Importance
from jobfit.models.v2 import (
    ClarificationAnswer,
    ClarificationAnswerSchema,
    ClarificationAnswerStatus,
    ClarificationCoreImpact,
    ClarificationQuestion,
    ClarificationQuestionStatus,
    ClarificationQuestionType,
    Requirement,
    RequirementExplicitness,
    RequirementSource,
    RequirementType,
)


def _requirement() -> Requirement:
    return Requirement(
        requirement_id="req-hard",
        jd_snapshot_id="jd-1",
        raw_requirement_ids=["raw-1"],
        raw_text="Explicit condition",
        normalized_capability="eligibility",
        requirement_type=RequirementType.HARD,
        importance=Importance.CRITICAL,
        explicitness=RequirementExplicitness.EXPLICIT,
        source=RequirementSource.JD,
    )


def _question(question_id: str = "question-1") -> ClarificationQuestion:
    return ClarificationQuestion(
        question_id=question_id,
        analysis_id="analysis-1",
        question_type=ClarificationQuestionType.HARD_ELIGIBILITY,
        prompt_text="Can you confirm the condition?",
        target_object_ids=["req-hard"],
        target_field="eligibility_condition",
        reason_code="ELIGIBILITY_PENDING",
        priority=1,
        required=True,
        possible_impact=[ClarificationCoreImpact.ELIGIBILITY],
        answer_schema=ClarificationAnswerSchema(answer_type="boolean"),
        source_requirement_ids=["req-hard"],
        why_this_question_exists="The explicit condition affects eligibility.",
    )


def test_validation_rejects_duplicate_or_more_than_three_active_questions() -> None:
    question = _question()
    with pytest.raises(ClarificationValidationError, match="unique"):
        validate_active_questions(
            [question, question],
            analysis_id="analysis-1",
            requirements=[_requirement()],
            evidence=[],
        )
    with pytest.raises(ClarificationValidationError, match="three"):
        validate_active_questions(
            [_question(f"q-{index}") for index in range(4)],
            analysis_id="analysis-1",
            requirements=[_requirement()],
            evidence=[],
        )


def test_validation_rejects_cross_analysis_and_unknown_requirement() -> None:
    cross_analysis = _question().model_copy(update={"analysis_id": "analysis-2"})
    with pytest.raises(ClarificationValidationError, match="another analysis"):
        validate_active_questions(
            [cross_analysis],
            analysis_id="analysis-1",
            requirements=[_requirement()],
            evidence=[],
        )
    unknown = _question().model_copy(
        update={"source_requirement_ids": ["req-unknown"]}
    )
    with pytest.raises(ClarificationValidationError, match="unknown requirement"):
        validate_active_questions(
            [unknown],
            analysis_id="analysis-1",
            requirements=[_requirement()],
            evidence=[],
        )


def test_answer_must_reference_exact_question_and_analysis() -> None:
    answer = ClarificationAnswer(
        question_id="question-missing",
        analysis_id="analysis-1",
        status=ClarificationAnswerStatus.ANSWERED,
        value=True,
    )
    with pytest.raises(ClarificationValidationError, match="nonexistent"):
        validate_clarification_answer(answer, _question())

    cross_analysis = answer.model_copy(
        update={"question_id": "question-1", "analysis_id": "analysis-2"}
    )
    with pytest.raises(ClarificationValidationError, match="another analysis"):
        validate_clarification_answer(cross_analysis, _question())


def test_answer_schema_rejects_invalid_boolean_without_mutating_question() -> None:
    question = _question()
    original = deepcopy(question)
    answer = ClarificationAnswer(
        question_id=question.question_id,
        analysis_id=question.analysis_id,
        status=ClarificationAnswerStatus.ANSWERED,
        value="yes",
    )
    with pytest.raises(ClarificationValidationError, match="Boolean"):
        validate_clarification_answer(answer, question)
    assert question == original


def test_validation_rejects_unknown_evidence_reference() -> None:
    question = _question().model_copy(
        update={"source_evidence_ids": ["evidence-unknown"]}
    )
    with pytest.raises(ClarificationValidationError, match="unknown evidence"):
        validate_active_questions(
            [question],
            analysis_id="analysis-1",
            requirements=[_requirement()],
            evidence=[],
        )


def test_validation_rejects_unknown_target_and_invalid_question_state() -> None:
    with pytest.raises(ClarificationValidationError, match="unknown object"):
        validate_active_questions(
            [_question().model_copy(update={"target_object_ids": ["unknown"]})],
            analysis_id="analysis-1",
            requirements=[_requirement()],
            evidence=[],
        )
    with pytest.raises(ClarificationValidationError, match="pending"):
        validate_active_questions(
            [
                _question().model_copy(
                    update={"status": ClarificationQuestionStatus.ANSWERED}
                )
            ],
            analysis_id="analysis-1",
            requirements=[_requirement()],
            evidence=[],
        )


def test_validation_rejects_invalid_required_optional_combination() -> None:
    with pytest.raises(ClarificationValidationError, match="must be required"):
        validate_active_questions(
            [_question().model_copy(update={"required": False})],
            analysis_id="analysis-1",
            requirements=[_requirement()],
            evidence=[],
        )
    with pytest.raises(ClarificationValidationError, match="cannot be required"):
        validate_active_questions(
            [
                _question().model_copy(
                    update={
                        "question_type": ClarificationQuestionType.CONFIDENCE,
                        "required": True,
                    }
                )
            ],
            analysis_id="analysis-1",
            requirements=[_requirement()],
            evidence=[],
        )


def test_hard_question_cannot_be_applied_to_non_hard_requirement() -> None:
    core = _requirement().model_copy(
        update={"requirement_type": RequirementType.CORE}
    )
    with pytest.raises(ClarificationValidationError, match="explicit hard"):
        validate_active_questions(
            [_question()],
            analysis_id="analysis-1",
            requirements=[core],
            evidence=[],
        )


@pytest.mark.parametrize(
    ("answer_type", "allowed", "value", "error"),
    [
        ("enum", ["a", "b"], "c", "allowed enum"),
        ("multi_select", ["a", "b"], "a", "multi-select"),
        ("multi_select", ["a", "b"], ["a", "a"], "unique"),
        ("number_range", [], True, "Numeric"),
        ("number_range", [], "not-a-number", "Numeric"),
        ("number_range", [], 11, "outside"),
        ("short_fact", [], "", "non-empty"),
    ],
)
def test_answer_schema_rejects_each_invalid_shape(
    answer_type: str,
    allowed: list[str],
    value: object,
    error: str,
) -> None:
    schema_kwargs = {
        "answer_type": answer_type,
        "allowed_values": allowed,
    }
    if answer_type == "number_range":
        schema_kwargs.update({"minimum": 0, "maximum": 10})
    question = _question().model_copy(
        update={"answer_schema": ClarificationAnswerSchema(**schema_kwargs)}
    )
    answer = ClarificationAnswer(
        question_id=question.question_id,
        analysis_id=question.analysis_id,
        status=ClarificationAnswerStatus.ANSWERED,
        value=value,
    )
    with pytest.raises(ClarificationValidationError, match=error):
        validate_clarification_answer(answer, question)


@pytest.mark.parametrize(
    ("schema", "value"),
    [
        (ClarificationAnswerSchema(answer_type="enum", allowed_values=["a"]), "a"),
        (
            ClarificationAnswerSchema(
                answer_type="multi_select", allowed_values=["a", "b"]
            ),
            ["a", "b"],
        ),
        (
            ClarificationAnswerSchema(
                answer_type="number_range", minimum=0, maximum=10
            ),
            5,
        ),
        (ClarificationAnswerSchema(answer_type="short_fact"), "fact"),
    ],
)
def test_answer_schema_accepts_each_supported_shape(
    schema: ClarificationAnswerSchema,
    value: object,
) -> None:
    question = _question().model_copy(update={"answer_schema": schema})
    answer = ClarificationAnswer(
        question_id=question.question_id,
        analysis_id=question.analysis_id,
        status=ClarificationAnswerStatus.ANSWERED,
        value=value,
    )
    validate_clarification_answer(answer, question)
