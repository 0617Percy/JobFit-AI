"""Cross-module invariants for final report validation."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from jobfit.models import (
    EvidenceItem,
    Importance,
    RecommendationLevel,
    ValidationSeverity,
)
from jobfit.validators.report import ReportValidator


def test_complete_components_pass_with_non_blocking_info(report_case) -> None:
    result = _validate(report_case)

    assert result.valid is True
    assert not _errors(result)
    assert "REPORT_VALIDATION_COMPLETED" in _codes(result)


@pytest.mark.parametrize("mode", ["missing", "duplicate"])
def test_requirement_match_coverage_is_revalidated(report_case, mode: str) -> None:
    matches = (
        report_case.matches[:-1]
        if mode == "missing"
        else [*report_case.matches, report_case.matches[0]]
    )

    result = _validate(report_case, matches=matches)

    assert result.valid is False
    assert (
        "REQUIREMENT_MISSING" if mode == "missing" else "REQUIREMENT_DUPLICATE"
    ) in _codes(result)


def test_invalid_evidence_and_tampered_status_score_fail(report_case) -> None:
    canonical = report_case.registry.get("ev-python")
    unknown = EvidenceItem(
        **canonical.model_dump(exclude={"evidence_id"}),
        evidence_id="ev-invented",
    )
    invalid_evidence_match = report_case.matches[0].model_copy(
        update={"evidence_items": [unknown]}
    )
    invalid_score_match = report_case.matches[0].model_copy(
        update={"match_score": Decimal("0.99")}
    )

    evidence_result = _validate(
        report_case,
        matches=[invalid_evidence_match, *report_case.matches[1:]],
    )
    score_result = _validate(
        report_case,
        matches=[invalid_score_match, *report_case.matches[1:]],
    )

    assert "EVIDENCE_ID_UNKNOWN" in _codes(evidence_result)
    assert "MATCH_SCORE_INVALID" in _codes(score_result)


def test_requirement_factor_and_weight_are_recomputed(report_case) -> None:
    requirement = report_case.job.requirements.items[0]
    changed = requirement.model_copy(
        update={
            "priority_factor": requirement.priority_factor + Decimal("1"),
            "weight": requirement.weight + Decimal("1"),
        }
    )
    job = report_case.job.model_copy(
        update={
            "requirements": report_case.job.requirements.model_copy(
                update={
                    "items": [
                        changed,
                        *report_case.job.requirements.items[1:],
                    ]
                }
            )
        }
    )

    result = _validate(report_case, job=job)

    assert result.valid is False
    assert "REQUIREMENT_PRIORITY_FACTOR_MISMATCH" in _codes(result)
    assert "REQUIREMENT_WEIGHT_MISMATCH" in _codes(result)


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("raw_score", Decimal("1"), "SCORE_RAW_MISMATCH"),
        ("score_cap", Decimal("1"), "SCORE_CAP_MISMATCH"),
        ("final_score", Decimal("1"), "SCORE_FINAL_MISMATCH"),
        (
            "mandatory_coverage_ratio",
            Decimal("0.1234"),
            "SCORE_MANDATORY_COVERAGE_MISMATCH",
        ),
        (
            "strong_evidence_coverage_ratio",
            Decimal("0.1234"),
            "SCORE_STRONG_EVIDENCE_MISMATCH",
        ),
        (
            "recommendation_level",
            RecommendationLevel.PRIORITY_APPLY,
            "RECOMMENDATION_LEVEL_MISMATCH",
        ),
    ],
)
def test_tampered_score_summary_is_rejected(
    report_case,
    field: str,
    value,
    code: str,
) -> None:
    score = report_case.score.model_copy(update={field: value})

    result = _validate(report_case, score=score)

    assert result.valid is False
    assert code in _codes(result)


def test_tampered_dimensions_blockers_and_cap_reasons_are_rejected(
    report_case,
) -> None:
    position = next(
        index
        for index, item in enumerate(report_case.score.dimension_scores)
        if item.active and item.earned_points > 0
    )
    dimension = report_case.score.dimension_scores[position].model_copy(
        update={
            "earned_points": (
                report_case.score.dimension_scores[position].earned_points
                - Decimal("1")
            )
        }
    )
    dimensions = list(report_case.score.dimension_scores)
    dimensions[position] = dimension
    score = report_case.score.model_copy(
        update={
            "dimension_scores": dimensions,
            "confirmed_hard_blockers": ["req-java"],
            "cap_reasons": ["invented cap reason"],
        }
    )

    result = _validate(report_case, score=score)

    assert result.valid is False
    assert "SCORE_DIMENSIONS_MISMATCH" in _codes(result)
    assert "SCORE_BLOCKERS_MISMATCH" in _codes(result)
    assert "SCORE_CAP_REASONS_MISMATCH" in _codes(result)


def test_recommendation_level_blockers_and_language_must_match_score(
    report_case,
) -> None:
    recommendation = report_case.advice.recommendation.model_copy(
        update={
            "level": RecommendationLevel.PRIORITY_APPLY,
            "blocking_requirement_ids": ["req-java"],
            "reasoning": ["[req-python] 强烈建议优先投递。"],
        }
    )
    advice = replace(report_case.advice, recommendation=recommendation)

    result = _validate(report_case, advice=advice)

    assert "REPORT_RECOMMENDATION_LEVEL_MISMATCH" in _codes(result)
    assert "REPORT_BLOCKERS_MISMATCH" in _codes(result)
    assert "RECOMMENDATION_LANGUAGE_CONFLICT" in _codes(result)


def test_strengths_must_be_grounded_unique_and_limited(report_case) -> None:
    strength = report_case.advice.strengths[0]
    unknown_evidence = strength.model_copy(
        update={"evidence_ids": ["ev-invented"]}
    )
    ungrounded = _validate(
        report_case,
        advice=replace(report_case.advice, strengths=[unknown_evidence]),
    )
    duplicated = _validate(
        report_case,
        advice=replace(
            report_case.advice,
            strengths=[strength, strength.model_copy(), strength.model_copy(), strength],
        ),
    )

    assert "STRENGTH_EVIDENCE_INVALID" in _codes(ungrounded)
    assert "STRENGTH_LIMIT_EXCEEDED" in _codes(duplicated)
    assert "STRENGTH_DUPLICATE" in _codes(duplicated)


def test_unknown_gap_cannot_use_definitive_language(report_case) -> None:
    gap = next(
        item
        for item in report_case.advice.gaps
        if "req-sql" in item.requirement_ids
    ).model_copy(
        update={"summary": "用户确定不会SQL，完全不具备该能力。"}
    )
    advice = replace(report_case.advice, gaps=[gap])

    result = _validate(report_case, advice=advice)

    assert result.valid is False
    assert "GAP_UNKNOWN_SEMANTICS_INVALID" in _codes(result)


def test_hard_gap_requires_critical_risk_and_short_term_classification(
    report_case,
) -> None:
    requirement = report_case.job.requirements.items[3].model_copy(
        update={
            "hard_condition_kind": "work_authorization",
            "importance": Importance.CRITICAL,
        }
    )
    job = report_case.job.model_copy(
        update={
            "requirements": report_case.job.requirements.model_copy(
                update={
                    "items": [
                        *report_case.job.requirements.items[:3],
                        requirement,
                    ]
                }
            )
        }
    )

    result = _validate(report_case, job=job)

    assert "GAP_HARD_CONDITION_INCONSISTENT" in _codes(result)


@pytest.mark.parametrize("mode", ["count", "reference"])
def test_interview_questions_are_revalidated(report_case, mode: str) -> None:
    if mode == "count":
        questions = report_case.advice.interview_questions[:-1]
    else:
        questions = list(report_case.advice.interview_questions)
        questions[0] = questions[0].model_copy(
            update={"requirement_ids": ["req-invented"]}
        )
    advice = replace(report_case.advice, interview_questions=questions)

    result = _validate(report_case, advice=advice)

    assert result.valid is False
    assert "INTERVIEW_SET_INVALID" in _codes(result)


def test_limitations_are_required_and_warning_does_not_block(report_case) -> None:
    missing = _validate(report_case, limitations=[])
    confirmation_rewrite = report_case.advice.direct_rewrites[0].model_copy(
        update={
            "rewritten_text": "主导Python数据处理。",
            "introduced_claims": ["职责强化：主导"],
            "user_confirmation_needed": ["确认是否主导"],
        }
    )
    advice = replace(
        report_case.advice,
        direct_rewrites=[],
        confirmation_required_rewrites=[confirmation_rewrite],
    )
    warning_only = _validate(report_case, advice=advice)

    assert "LIMITATIONS_REQUIRED" in _codes(missing)
    assert warning_only.valid is True
    assert "REWRITE_CONFIRMATION_REQUIRED" in _codes(warning_only)
    assert any(
        issue.severity is ValidationSeverity.WARNING
        for issue in warning_only.issues
    )


def test_sensitive_internal_text_is_rejected(report_case) -> None:
    recommendation = report_case.advice.recommendation.model_copy(
        update={
            "reasoning": [
                "[req-python] 本地路径 C:\\Users\\Private\\resume.txt"
            ]
        }
    )
    advice = replace(report_case.advice, recommendation=recommendation)

    result = _validate(report_case, advice=advice)

    assert "REPORT_SENSITIVE_CONTENT" in _codes(result)


def _validate(report_case, **updates):
    return ReportValidator().validate_components(
        document=updates.get("document", report_case.document),
        resume=updates.get("resume", report_case.resume),
        job=updates.get("job", report_case.job),
        matches=updates.get("matches", report_case.matches),
        score=updates.get("score", report_case.score),
        advice=updates.get("advice", report_case.advice),
        registry=updates.get("registry", report_case.registry),
        limitations=updates.get("limitations", report_case.limitations),
    )


def _codes(result) -> set[str]:
    return {issue.code for issue in result.issues}


def _errors(result):
    return [
        issue
        for issue in result.issues
        if issue.severity is ValidationSeverity.ERROR
    ]
