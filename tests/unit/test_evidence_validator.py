"""Tests for local requirement coverage and evidence grounding validation."""

from __future__ import annotations

from decimal import Decimal

import pytest

from jobfit.errors import ErrorCode, JobFitError
from jobfit.models import (
    EvidenceSourceType,
    MatchStatus,
    RequirementMatch,
)
from jobfit.validators import EvidenceValidator


def test_validator_accepts_complete_grounded_matches(matching_case) -> None:
    matches = _valid_matches(matching_case)

    result = EvidenceValidator().validate_matches(
        matching_case.document,
        matching_case.registry,
        matching_case.job.requirements.items,
        matches,
    )

    assert result.valid is True
    assert result.issues == []


@pytest.mark.parametrize(
    ("case_name", "mutator"),
    [
        (
            "unknown_requirement",
            lambda case, matches: [
                *matches,
                case.match(
                    "req-unknown",
                    MatchStatus.UNKNOWN,
                    missing_note="当前简历未提供足够证据确认该能力。",
                ),
            ],
        ),
        (
            "duplicate_requirement",
            lambda _case, matches: [*matches, matches[0]],
        ),
        (
            "missing_requirement",
            lambda _case, matches: matches[:-1],
        ),
    ],
)
def test_validator_rejects_requirement_coverage_errors(
    matching_case,
    case_name: str,
    mutator,
) -> None:
    del case_name
    invalid = mutator(matching_case, _valid_matches(matching_case))

    with pytest.raises(JobFitError) as exc_info:
        EvidenceValidator().validate_or_raise(
            matching_case.document,
            matching_case.registry,
            matching_case.job.requirements.items,
            invalid,
        )

    assert exc_info.value.code is ErrorCode.EVIDENCE_INVALID


def test_validator_rejects_matched_without_direct_evidence(matching_case) -> None:
    invalid = matching_case.match(
            "req-production",
            MatchStatus.PARTIAL_MATCH,
            ("ev-context",),
        ).model_copy(
        update={
            "match_status": MatchStatus.MATCHED,
            "match_score": Decimal("1.0"),
        }
    )

    _assert_invalid(matching_case, invalid, "req-production")


def test_validator_rejects_partial_without_evidence(matching_case) -> None:
    invalid = RequirementMatch.model_construct(
        requirement_id="req-production",
        match_status=MatchStatus.PARTIAL_MATCH,
        match_score=Decimal("0.6"),
        evidence_items=[],
        reasoning="存在部分相关性。",
        confidence=Decimal("0.8"),
        missing_evidence_note=None,
        improvement_suggestion="补充证据。",
    )

    _assert_invalid(matching_case, invalid, "req-production")


def test_validator_rejects_unknown_evidence_id(matching_case) -> None:
    canonical = matching_case.registry.get("ev-python")
    unknown = canonical.model_copy(update={"evidence_id": "ev-unknown"})
    invalid = matching_case.match(
        "req-python",
        MatchStatus.MATCHED,
        ("ev-python",),
    ).model_copy(update={"evidence_items": [unknown]})

    _assert_invalid(matching_case, invalid, "req-python")


def test_validator_rejects_incorrect_character_range(matching_case) -> None:
    canonical = matching_case.registry.get("ev-python")
    other_quote = "课程项目"
    other_start = matching_case.document.normalized_text.index(other_quote)
    altered = canonical.model_copy(
        update={
            "quote": other_quote,
            "start_char": other_start,
            "end_char": other_start + len(other_quote),
        }
    )
    invalid = matching_case.match(
        "req-python",
        MatchStatus.MATCHED,
        ("ev-python",),
    ).model_copy(update={"evidence_items": [altered]})

    _assert_invalid(matching_case, invalid, "req-python")


def test_validator_rejects_job_description_as_resume_evidence(matching_case) -> None:
    canonical = matching_case.registry.get("ev-python")
    jd_evidence = canonical.model_copy(
        update={"source_type": EvidenceSourceType.JOB_DESCRIPTION}
    )
    invalid = matching_case.match(
        "req-python",
        MatchStatus.MATCHED,
        ("ev-python",),
    ).model_copy(update={"evidence_items": [jd_evidence]})

    _assert_invalid(matching_case, invalid, "req-python")


def test_validator_rejects_technically_unrelated_evidence(matching_case) -> None:
    invalid = matching_case.match(
        "req-python",
        MatchStatus.PARTIAL_MATCH,
        ("ev-course",),
        reasoning="课程项目只能提供有限的相关证据。",
    )

    _assert_invalid(matching_case, invalid, "req-python")


def test_validator_rejects_incorrect_status_score(matching_case) -> None:
    valid = matching_case.match(
        "req-python",
        MatchStatus.MATCHED,
        ("ev-python",),
    )
    invalid = valid.model_copy(update={"match_score": Decimal("0.42")})

    _assert_invalid(matching_case, invalid, "req-python")


def test_course_learning_is_not_accepted_as_production_match(matching_case) -> None:
    invalid = matching_case.match(
        "req-production",
        MatchStatus.MATCHED,
        ("ev-course",),
        reasoning="该课程项目证明具备生产级部署经验。",
    )

    _assert_invalid(matching_case, invalid, "req-production")


def test_negative_python_evidence_is_not_accepted_as_match(matching_case) -> None:
    invalid = matching_case.match(
        "req-python",
        MatchStatus.MATCHED,
        ("ev-no-python",),
    )

    _assert_invalid(matching_case, invalid, "req-python")


def test_unknown_cannot_claim_user_definitely_lacks_skill(matching_case) -> None:
    invalid = matching_case.match(
        "req-sql",
        MatchStatus.UNKNOWN,
        reasoning="用户不具备SQL能力。",
        missing_note="用户不会SQL。",
    )

    _assert_invalid(matching_case, invalid, "req-sql")


def test_reasoning_cannot_add_unseen_numeric_experience(matching_case) -> None:
    invalid = matching_case.match(
        "req-python",
        MatchStatus.MATCHED,
        ("ev-python",),
        reasoning="候选人具备5年Python生产经验。",
    )

    _assert_invalid(matching_case, invalid, "req-python")


def _valid_matches(matching_case) -> list[RequirementMatch]:
    return [
        matching_case.match(
            "req-python",
            MatchStatus.MATCHED,
            ("ev-python",),
            reasoning="简历明确写明使用Python完成数据处理。",
        ),
        matching_case.match(
            "req-production",
            MatchStatus.PARTIAL_MATCH,
            ("ev-course",),
            reasoning="课程项目相关，但没有生产部署证据。",
        ),
        matching_case.match(
            "req-java",
            MatchStatus.NOT_MATCHED,
            ("ev-no-java",),
            reasoning="简历明确写明没有Java经验。",
            missing_note="存在明确否定表述。",
        ),
        matching_case.match(
            "req-sql",
            MatchStatus.UNKNOWN,
            reasoning="当前简历没有足够证据确认SQL能力。",
            missing_note="当前简历未提供足够证据确认该能力。",
        ),
    ]


def _assert_invalid(matching_case, invalid: RequirementMatch, requirement_id: str) -> None:
    matches = [
        invalid if item.requirement_id == requirement_id else item
        for item in _valid_matches(matching_case)
    ]
    with pytest.raises(JobFitError) as exc_info:
        EvidenceValidator().validate_or_raise(
            matching_case.document,
            matching_case.registry,
            matching_case.job.requirements.items,
            matches,
        )
    assert exc_info.value.code is ErrorCode.EVIDENCE_INVALID
