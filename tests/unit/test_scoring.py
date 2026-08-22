"""Tests for deterministic requirement weighting and scoring."""

from __future__ import annotations

import inspect
from decimal import Decimal

import pytest

from jobfit.errors import ErrorCode, ScoringError
from jobfit.models import (
    HardConditionKind,
    Importance,
    JobRequirement,
    MatchStatus,
    RecommendationLevel,
    RequirementCategory,
    RequirementMatch,
    RequirementType,
)
from jobfit.scoring import ScoringEngine
from jobfit.scoring.policy import (
    BASE_POINTS,
    IMPORTANCE_FACTORS,
    MANDATORY_MULTIPLIER,
    STATUS_VALUES,
    TYPE_FACTORS,
    calculate_priority_factor,
    determine_score_cap,
    select_recommendation,
)


def test_policy_base_points_total_exactly_one_hundred() -> None:
    assert sum(BASE_POINTS.values(), Decimal("0")) == Decimal("100")


def test_policy_status_values_are_fixed() -> None:
    assert {
        MatchStatus.MATCHED: Decimal("1.0"),
        MatchStatus.PARTIAL_MATCH: Decimal("0.6"),
        MatchStatus.NOT_MATCHED: Decimal("0.0"),
        MatchStatus.UNKNOWN: Decimal("0.0"),
    } == STATUS_VALUES


@pytest.mark.parametrize(
    ("importance", "expected"),
    [
        (Importance.CRITICAL, Decimal("4")),
        (Importance.HIGH, Decimal("3")),
        (Importance.MEDIUM, Decimal("2")),
        (Importance.LOW, Decimal("1")),
    ],
)
def test_importance_factors(
    importance: Importance,
    expected: Decimal,
) -> None:
    assert IMPORTANCE_FACTORS[importance] == expected


@pytest.mark.parametrize(
    ("requirement_type", "expected"),
    [
        (RequirementType.MUST_HAVE, Decimal("1.00")),
        (RequirementType.RESPONSIBILITY, Decimal("0.90")),
        (RequirementType.PREFERRED, Decimal("0.70")),
        (RequirementType.IMPLICIT, Decimal("0.50")),
    ],
)
def test_requirement_type_factors(
    requirement_type: RequirementType,
    expected: Decimal,
) -> None:
    assert TYPE_FACTORS[requirement_type] == expected


def test_mandatory_multiplier_and_priority_factor() -> None:
    optional = make_requirement(
        "req-optional",
        importance=Importance.HIGH,
        requirement_type=RequirementType.MUST_HAVE,
    )
    mandatory = make_requirement(
        "req-mandatory",
        importance=Importance.HIGH,
        requirement_type=RequirementType.MUST_HAVE,
        mandatory=True,
    )

    assert Decimal("1.25") == MANDATORY_MULTIPLIER
    assert calculate_priority_factor(optional) == Decimal("3.00")
    assert calculate_priority_factor(mandatory) == Decimal("3.7500")


def test_single_dimension_is_renormalized_to_one_hundred(matching_case) -> None:
    requirement = make_requirement("req-only")
    match = make_match(matching_case, requirement, MatchStatus.MATCHED)

    summary = ScoringEngine().score([requirement], [match])

    assert requirement.weight == Decimal("100.00")
    assert requirement.priority_factor == Decimal("2.00")
    active = [item for item in summary.dimension_scores if item.active]
    assert len(active) == 1
    assert active[0].effective_points == Decimal("100.00")
    assert summary.raw_score == Decimal("100.00")


def test_multiple_active_dimensions_use_proportional_base_points(
    matching_case,
) -> None:
    technical = make_requirement(
        "req-technical",
        category=RequirementCategory.TECHNICAL_SKILL,
    )
    experience = make_requirement(
        "req-experience",
        category=RequirementCategory.EXPERIENCE_PROJECT,
    )
    matches = [
        make_match(matching_case, technical, MatchStatus.MATCHED),
        make_match(matching_case, experience, MatchStatus.MATCHED),
    ]

    summary = ScoringEngine().score([technical, experience], matches)
    dimensions = {item.category: item for item in summary.dimension_scores}

    assert technical.weight == Decimal("50.00")
    assert experience.weight == Decimal("50.00")
    assert dimensions[RequirementCategory.TECHNICAL_SKILL].effective_points == Decimal(
        "50.00"
    )
    assert dimensions[RequirementCategory.EXPERIENCE_PROJECT].effective_points == Decimal(
        "50.00"
    )
    assert all(
        not item.active
        for category, item in dimensions.items()
        if category
        not in {
            RequirementCategory.TECHNICAL_SKILL,
            RequirementCategory.EXPERIENCE_PROJECT,
        }
    )


def test_all_requirement_weights_sum_exactly_one_hundred(
    matching_case,
) -> None:
    requirements = [
        make_requirement("req-a"),
        make_requirement("req-b", importance=Importance.HIGH),
        make_requirement(
            "req-c",
            category=RequirementCategory.EXPERIENCE_PROJECT,
        ),
    ]
    matches = [
        make_match(matching_case, item, MatchStatus.MATCHED)
        for item in requirements
    ]

    ScoringEngine().score(requirements, matches)

    assert sum(
        (item.weight for item in requirements),
        Decimal("0"),
    ) == Decimal("100.00")
    assert all(isinstance(item.weight, Decimal) for item in requirements)


def test_rounding_remainder_goes_to_last_stable_requirement_id(
    matching_case,
) -> None:
    requirements = [
        make_requirement("req-b"),
        make_requirement("req-c"),
        make_requirement("req-a"),
    ]
    matches = [
        make_match(matching_case, item, MatchStatus.MATCHED)
        for item in requirements
    ]

    ScoringEngine().score(requirements, matches)
    by_id = {item.requirement_id: item.weight for item in requirements}

    assert by_id == {
        "req-a": Decimal("33.33"),
        "req-b": Decimal("33.33"),
        "req-c": Decimal("33.34"),
    }


def test_partial_score_uses_decimal_without_float_error(matching_case) -> None:
    requirement = make_requirement("req-partial")
    match = make_match(matching_case, requirement, MatchStatus.PARTIAL_MATCH)

    summary = ScoringEngine().score([requirement], [match])

    assert summary.raw_score == Decimal("60.00")
    assert summary.dimension_scores[1].earned_points == Decimal("60.00")


def test_implicit_weight_below_cap_is_unchanged(matching_case) -> None:
    implicit = make_requirement(
        "req-implicit",
        requirement_type=RequirementType.IMPLICIT,
        importance=Importance.LOW,
    )
    normal = make_requirement(
        "req-normal",
        importance=Importance.CRITICAL,
        mandatory=True,
    )
    requirements = [implicit, normal]
    matches = [
        make_match(matching_case, item, MatchStatus.MATCHED)
        for item in requirements
    ]

    ScoringEngine().score(requirements, matches)

    assert implicit.weight < Decimal("10.00")
    assert sum((item.weight for item in requirements), Decimal("0")) == Decimal(
        "100.00"
    )


def test_implicit_weight_is_compressed_to_ten_and_redistributed(
    matching_case,
) -> None:
    implicit = make_requirement(
        "req-implicit",
        requirement_type=RequirementType.IMPLICIT,
        importance=Importance.MEDIUM,
    )
    normal = make_requirement("req-normal")
    requirements = [implicit, normal]
    matches = [
        make_match(matching_case, item, MatchStatus.MATCHED)
        for item in requirements
    ]

    ScoringEngine().score(requirements, matches)

    assert implicit.weight == Decimal("10.00")
    assert normal.weight == Decimal("90.00")


def test_multiple_implicit_requirements_share_ten_point_cap_stably(
    matching_case,
) -> None:
    requirements = [
        make_requirement(
            "req-implicit-b",
            requirement_type=RequirementType.IMPLICIT,
            importance=Importance.MEDIUM,
        ),
        make_requirement(
            "req-implicit-a",
            requirement_type=RequirementType.IMPLICIT,
            importance=Importance.MEDIUM,
        ),
        make_requirement("req-normal"),
    ]
    matches = [
        make_match(matching_case, item, MatchStatus.MATCHED)
        for item in requirements
    ]

    ScoringEngine().score(requirements, matches)
    by_id = {item.requirement_id: item.weight for item in requirements}

    assert by_id["req-implicit-a"] == Decimal("5.00")
    assert by_id["req-implicit-b"] == Decimal("5.00")
    assert by_id["req-normal"] == Decimal("90.00")


def test_all_implicit_requirements_fail_safe(matching_case) -> None:
    requirement = make_requirement(
        "req-implicit",
        requirement_type=RequirementType.IMPLICIT,
    )
    match = make_match(matching_case, requirement, MatchStatus.UNKNOWN)

    with pytest.raises(ScoringError) as exc_info:
        ScoringEngine().score([requirement], [match])

    assert exc_info.value.code is ErrorCode.SCORING_INVARIANT_FAILED


def test_implicit_requirement_cannot_trigger_hard_cap(matching_case) -> None:
    invalid = JobRequirement.model_construct(
        **make_requirement(
            "req-implicit",
            requirement_type=RequirementType.IMPLICIT,
        ).model_dump(
            exclude={"mandatory", "hard_condition_kind"},
        ),
        mandatory=True,
        hard_condition_kind=HardConditionKind.DEGREE_LEVEL,
    )
    normal = make_requirement("req-normal")
    matches = [
        make_match(matching_case, invalid, MatchStatus.NOT_MATCHED),
        make_match(matching_case, normal, MatchStatus.MATCHED),
    ]

    with pytest.raises(ScoringError):
        ScoringEngine().score([invalid, normal], matches)


def test_confirmed_hard_blocker_caps_score_at_49(matching_case) -> None:
    blocker = make_requirement(
        "req-blocker",
        importance=Importance.CRITICAL,
        mandatory=True,
        hard_condition_kind=HardConditionKind.WORK_AUTHORIZATION,
    )
    match = make_match(matching_case, blocker, MatchStatus.NOT_MATCHED)

    decision = determine_score_cap([blocker], [match])

    assert decision.score_cap == Decimal("49")
    assert decision.confirmed_hard_blockers == ["req-blocker"]
    assert decision.recommendation_cap is RecommendationLevel.NOT_PRIORITY


def test_unknown_hard_blocker_caps_score_at_69(matching_case) -> None:
    blocker = make_requirement(
        "req-blocker",
        importance=Importance.CRITICAL,
        mandatory=True,
        hard_condition_kind=HardConditionKind.DEGREE_LEVEL,
    )
    match = make_match(matching_case, blocker, MatchStatus.UNKNOWN)

    decision = determine_score_cap([blocker], [match])

    assert decision.score_cap == Decimal("69")
    assert decision.unverified_hard_blockers == ["req-blocker"]
    assert decision.recommendation_cap is RecommendationLevel.TRY_APPLY


def test_critical_mandatory_gap_caps_score_at_69(matching_case) -> None:
    requirement = make_requirement(
        "req-critical",
        importance=Importance.CRITICAL,
        mandatory=True,
    )
    match = make_match(matching_case, requirement, MatchStatus.NOT_MATCHED)

    decision = determine_score_cap([requirement], [match])

    assert decision.score_cap == Decimal("69")
    assert decision.confirmed_hard_blockers == []


def test_two_high_mandatory_gaps_cap_score_at_69(matching_case) -> None:
    requirements = [
        make_requirement(
            "req-high-a",
            importance=Importance.HIGH,
            mandatory=True,
        ),
        make_requirement(
            "req-high-b",
            importance=Importance.HIGH,
            mandatory=True,
        ),
    ]
    matches = [
        make_match(matching_case, item, MatchStatus.NOT_MATCHED)
        for item in requirements
    ]

    decision = determine_score_cap(requirements, matches)

    assert decision.score_cap == Decimal("69")


def test_no_hard_gap_keeps_cap_at_100(matching_case) -> None:
    requirement = make_requirement("req-normal")
    match = make_match(matching_case, requirement, MatchStatus.MATCHED)

    decision = determine_score_cap([requirement], [match])

    assert decision.score_cap == Decimal("100")
    assert decision.cap_reasons == []


def test_raw_score_is_truncated_by_hard_cap(matching_case) -> None:
    requirements = [
        make_requirement(
            "req-blocker",
            importance=Importance.CRITICAL,
            mandatory=True,
            hard_condition_kind=HardConditionKind.WORK_AUTHORIZATION,
        ),
        make_requirement(
            "req-match-a",
            importance=Importance.CRITICAL,
            mandatory=True,
        ),
        make_requirement(
            "req-match-b",
            importance=Importance.CRITICAL,
            mandatory=True,
        ),
    ]
    matches = [
        make_match(matching_case, requirements[0], MatchStatus.NOT_MATCHED),
        make_match(matching_case, requirements[1], MatchStatus.MATCHED),
        make_match(matching_case, requirements[2], MatchStatus.MATCHED),
    ]

    summary = ScoringEngine().score(requirements, matches)

    assert summary.raw_score > Decimal("49")
    assert summary.score_cap == Decimal("49")
    assert summary.final_score == Decimal("49")
    assert summary.recommendation_level is RecommendationLevel.NOT_PRIORITY


def test_high_raw_score_is_truncated_by_unknown_hard_cap(matching_case) -> None:
    blocker = make_requirement(
        "req-blocker",
        importance=Importance.CRITICAL,
        mandatory=True,
        hard_condition_kind=HardConditionKind.DEGREE_LEVEL,
    )
    requirements = [
        blocker,
        *[
            make_requirement(
                f"req-match-{index}",
                importance=Importance.CRITICAL,
                mandatory=True,
            )
            for index in range(4)
        ],
    ]
    matches = [
        make_match(matching_case, blocker, MatchStatus.UNKNOWN),
        *[
            make_match(matching_case, item, MatchStatus.MATCHED)
            for item in requirements[1:]
        ],
    ]

    summary = ScoringEngine().score(requirements, matches)

    assert summary.raw_score == Decimal("80.00")
    assert summary.score_cap == Decimal("69")
    assert summary.final_score == Decimal("69")
    assert summary.recommendation_level is RecommendationLevel.TRY_APPLY


@pytest.mark.parametrize(
    (
        "score",
        "mandatory",
        "strong",
        "critical_gap",
        "expected",
    ),
    [
        ("49.00", "1", "1", False, RecommendationLevel.NOT_PRIORITY),
        ("50.00", "1", "1", False, RecommendationLevel.TRY_APPLY),
        ("67.99", "1", "1", False, RecommendationLevel.TRY_APPLY),
        ("68.00", "0.65", "0", False, RecommendationLevel.OPTIMIZE_THEN_APPLY),
        ("69.00", "0.65", "0", False, RecommendationLevel.OPTIMIZE_THEN_APPLY),
        ("79.99", "1", "1", False, RecommendationLevel.OPTIMIZE_THEN_APPLY),
        ("80.00", "0.85", "0.70", False, RecommendationLevel.PRIORITY_APPLY),
        ("80.00", "0.84", "0.70", False, RecommendationLevel.OPTIMIZE_THEN_APPLY),
        ("80.00", "0.85", "0.69", False, RecommendationLevel.OPTIMIZE_THEN_APPLY),
        ("80.00", "0.85", "0.70", True, RecommendationLevel.OPTIMIZE_THEN_APPLY),
    ],
)
def test_recommendation_threshold_boundaries(
    score: str,
    mandatory: str,
    strong: str,
    critical_gap: bool,
    expected: RecommendationLevel,
) -> None:
    result = select_recommendation(
        final_score=Decimal(score),
        mandatory_coverage_ratio=Decimal(mandatory),
        strong_evidence_coverage_ratio=Decimal(strong),
        confirmed_hard_blockers=[],
        unverified_hard_blockers=[],
        has_critical_mandatory_gap=critical_gap,
    )

    assert result is expected


def test_confirmed_blocker_forces_not_priority_recommendation() -> None:
    result = select_recommendation(
        final_score=Decimal("90"),
        mandatory_coverage_ratio=Decimal("1"),
        strong_evidence_coverage_ratio=Decimal("1"),
        confirmed_hard_blockers=["req-blocker"],
        unverified_hard_blockers=[],
        has_critical_mandatory_gap=False,
    )

    assert result is RecommendationLevel.NOT_PRIORITY


def test_unknown_hard_blocker_limits_recommendation_to_try_apply() -> None:
    result = select_recommendation(
        final_score=Decimal("80"),
        mandatory_coverage_ratio=Decimal("1"),
        strong_evidence_coverage_ratio=Decimal("1"),
        confirmed_hard_blockers=[],
        unverified_hard_blockers=["req-blocker"],
        has_critical_mandatory_gap=False,
    )

    assert result is RecommendationLevel.TRY_APPLY


def test_mandatory_coverage_is_weighted_by_status(matching_case) -> None:
    requirements = [
        make_requirement("req-a", mandatory=True),
        make_requirement("req-b", mandatory=True),
    ]
    matches = [
        make_match(matching_case, requirements[0], MatchStatus.MATCHED),
        make_match(matching_case, requirements[1], MatchStatus.UNKNOWN),
    ]

    summary = ScoringEngine().score(requirements, matches)

    assert summary.mandatory_coverage_ratio == Decimal("0.5000")


def test_no_mandatory_requirements_have_full_mandatory_coverage(
    matching_case,
) -> None:
    requirement = make_requirement("req-optional")
    match = make_match(matching_case, requirement, MatchStatus.MATCHED)

    summary = ScoringEngine().score([requirement], [match])

    assert summary.mandatory_coverage_ratio == Decimal("1.0000")


def test_strong_evidence_coverage_uses_weight_and_confidence(
    matching_case,
) -> None:
    requirements = [
        make_requirement("req-strong"),
        make_requirement("req-weak"),
    ]
    matches = [
        make_match(
            matching_case,
            requirements[0],
            MatchStatus.MATCHED,
            confidence="0.70",
        ),
        make_match(
            matching_case,
            requirements[1],
            MatchStatus.MATCHED,
            confidence="0.69",
        ),
    ]

    summary = ScoringEngine().score(requirements, matches)

    assert summary.strong_evidence_coverage_ratio == Decimal("0.5000")


def test_llm_supplied_requirement_weights_are_overwritten(matching_case) -> None:
    requirement = make_requirement("req-fake")
    requirement.priority_factor = Decimal("99")
    requirement.weight = Decimal("99")
    match = make_match(matching_case, requirement, MatchStatus.PARTIAL_MATCH)

    summary = ScoringEngine().score([requirement], [match])

    assert requirement.priority_factor == Decimal("2.00")
    assert requirement.weight == Decimal("100.00")
    assert summary.recommendation_level is RecommendationLevel.TRY_APPLY
    assert "recommendation_level" not in inspect.signature(
        ScoringEngine.score
    ).parameters


def test_same_input_scores_identically_on_repeated_runs(matching_case) -> None:
    requirements = [
        make_requirement("req-a"),
        make_requirement(
            "req-b",
            category=RequirementCategory.EXPERIENCE_PROJECT,
        ),
    ]
    matches = [
        make_match(matching_case, requirements[0], MatchStatus.MATCHED),
        make_match(matching_case, requirements[1], MatchStatus.PARTIAL_MATCH),
    ]
    engine = ScoringEngine()

    first = engine.score(requirements, matches)
    first_weights = [item.weight for item in requirements]
    second = engine.score(requirements, matches)

    assert first == second
    assert [item.weight for item in requirements] == first_weights


def test_invalid_match_coverage_blocks_scoring_before_weight_mutation(
    matching_case,
) -> None:
    requirements = [
        make_requirement("req-a"),
        make_requirement("req-b"),
    ]
    matches = [
        make_match(matching_case, requirements[0], MatchStatus.MATCHED)
    ]

    with pytest.raises(ScoringError) as exc_info:
        ScoringEngine().score(requirements, matches)

    assert exc_info.value.code is ErrorCode.SCORING_INVARIANT_FAILED
    assert [item.weight for item in requirements] == [
        Decimal("0"),
        Decimal("0"),
    ]


def test_empty_requirements_are_rejected(matching_case) -> None:
    del matching_case
    with pytest.raises(ScoringError):
        ScoringEngine().score([], [])


@pytest.mark.parametrize(
    "status",
    [MatchStatus.MATCHED, MatchStatus.PARTIAL_MATCH],
)
def test_missing_required_match_evidence_blocks_scoring(
    matching_case,
    status: MatchStatus,
) -> None:
    requirement = make_requirement("req-a")
    match = make_match(
        matching_case,
        requirement,
        status,
    ).model_copy(update={"evidence_items": []})

    with pytest.raises(ScoringError):
        ScoringEngine().score([requirement], [match])


def test_invalid_match_score_blocks_scoring(matching_case) -> None:
    requirement = make_requirement("req-a")
    match = make_match(
        matching_case,
        requirement,
        MatchStatus.MATCHED,
    ).model_copy(update={"match_score": Decimal("0.5")})

    with pytest.raises(ScoringError):
        ScoringEngine().score([requirement], [match])


def make_requirement(
    requirement_id: str,
    *,
    category: RequirementCategory = RequirementCategory.TECHNICAL_SKILL,
    importance: Importance = Importance.MEDIUM,
    requirement_type: RequirementType = RequirementType.MUST_HAVE,
    mandatory: bool = False,
    hard_condition_kind: HardConditionKind = HardConditionKind.NONE,
) -> JobRequirement:
    source_text = f"requirement {requirement_id}"
    return JobRequirement(
        requirement_id=requirement_id,
        requirement_text=source_text,
        source_text=source_text,
        source_start_char=0,
        source_end_char=len(source_text),
        requirement_type=requirement_type,
        category=category,
        importance=importance,
        mandatory=mandatory,
        hard_condition_kind=hard_condition_kind,
        normalized_key=requirement_id,
        priority_factor=Decimal("0"),
        weight=Decimal("0"),
    )


def make_match(
    matching_case,
    requirement: JobRequirement,
    status: MatchStatus,
    *,
    confidence: str = "0.90",
) -> RequirementMatch:
    evidence_ids = (
        ("ev-python",)
        if status in {MatchStatus.MATCHED, MatchStatus.PARTIAL_MATCH}
        else ()
    )
    missing_note = (
        "当前简历未提供足够证据确认该能力。"
        if status in {MatchStatus.NOT_MATCHED, MatchStatus.UNKNOWN}
        else None
    )
    return matching_case.match(
        requirement.requirement_id,
        status,
        evidence_ids,
        confidence=confidence,
        missing_note=missing_note,
    )
