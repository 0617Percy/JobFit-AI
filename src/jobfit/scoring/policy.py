"""Deterministic scoring constants and pure policy decisions."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

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

BASE_POINTS = {
    RequirementCategory.ELIGIBILITY: Decimal("20"),
    RequirementCategory.TECHNICAL_SKILL: Decimal("25"),
    RequirementCategory.EXPERIENCE_PROJECT: Decimal("25"),
    RequirementCategory.DOMAIN_BUSINESS: Decimal("15"),
    RequirementCategory.EDUCATION_LANGUAGE: Decimal("10"),
    RequirementCategory.COMMUNICATION_KEYWORD: Decimal("5"),
}

STATUS_VALUES = {
    MatchStatus.MATCHED: Decimal("1.0"),
    MatchStatus.PARTIAL_MATCH: Decimal("0.6"),
    MatchStatus.NOT_MATCHED: Decimal("0.0"),
    MatchStatus.UNKNOWN: Decimal("0.0"),
}

IMPORTANCE_FACTORS = {
    Importance.CRITICAL: Decimal("4"),
    Importance.HIGH: Decimal("3"),
    Importance.MEDIUM: Decimal("2"),
    Importance.LOW: Decimal("1"),
}

TYPE_FACTORS = {
    RequirementType.MUST_HAVE: Decimal("1.00"),
    RequirementType.RESPONSIBILITY: Decimal("0.90"),
    RequirementType.PREFERRED: Decimal("0.70"),
    RequirementType.IMPLICIT: Decimal("0.50"),
}

MANDATORY_MULTIPLIER = Decimal("1.25")
OPTIONAL_MULTIPLIER = Decimal("1.00")
IMPLICIT_WEIGHT_CAP = Decimal("10.00")
STRONG_EVIDENCE_CONFIDENCE = Decimal("0.70")


@dataclass(frozen=True, slots=True)
class ScoreCapDecision:
    score_cap: Decimal
    confirmed_hard_blockers: list[str]
    unverified_hard_blockers: list[str]
    cap_reasons: list[str]
    recommendation_cap: RecommendationLevel | None


def calculate_priority_factor(requirement: JobRequirement) -> Decimal:
    mandatory_factor = (
        MANDATORY_MULTIPLIER
        if requirement.mandatory
        else OPTIONAL_MULTIPLIER
    )
    return (
        IMPORTANCE_FACTORS[requirement.importance]
        * TYPE_FACTORS[requirement.requirement_type]
        * mandatory_factor
    )


def determine_score_cap(
    requirements: Sequence[JobRequirement],
    matches: Sequence[RequirementMatch],
) -> ScoreCapDecision:
    match_by_id = {item.requirement_id: item for item in matches}
    confirmed: list[str] = []
    unverified: list[str] = []
    reasons: list[str] = []
    cap = Decimal("100")
    recommendation_cap: RecommendationLevel | None = None

    explicit_hard_requirements = [
        item
        for item in requirements
        if item.mandatory
        and item.requirement_type is not RequirementType.IMPLICIT
        and item.hard_condition_kind is not HardConditionKind.NONE
        and item.source_end_char - item.source_start_char == len(item.source_text)
    ]
    for requirement in sorted(
        explicit_hard_requirements,
        key=lambda item: item.requirement_id,
    ):
        status = match_by_id[requirement.requirement_id].match_status
        if status is MatchStatus.NOT_MATCHED:
            confirmed.append(requirement.requirement_id)
            reasons.append(
                f"{requirement.requirement_id}: confirmed hard condition not matched"
            )
            cap = min(cap, Decimal("49"))
            recommendation_cap = RecommendationLevel.NOT_PRIORITY
        elif status is MatchStatus.UNKNOWN:
            unverified.append(requirement.requirement_id)
            reasons.append(
                f"{requirement.requirement_id}: hard condition remains unverified"
            )
            cap = min(cap, Decimal("69"))
            if recommendation_cap is None:
                recommendation_cap = RecommendationLevel.TRY_APPLY

    critical_non_hard_gaps = [
        item.requirement_id
        for item in requirements
        if item.mandatory
        and item.importance is Importance.CRITICAL
        and item.hard_condition_kind is HardConditionKind.NONE
        and item.requirement_type is not RequirementType.IMPLICIT
        and match_by_id[item.requirement_id].match_status
        is MatchStatus.NOT_MATCHED
    ]
    for requirement_id in sorted(critical_non_hard_gaps):
        reasons.append(
            f"{requirement_id}: critical mandatory requirement not matched"
        )
        cap = min(cap, Decimal("69"))
        if recommendation_cap is None:
            recommendation_cap = RecommendationLevel.TRY_APPLY

    high_or_critical_gaps = sorted(
        item.requirement_id
        for item in requirements
        if item.mandatory
        and item.importance in {Importance.HIGH, Importance.CRITICAL}
        and item.requirement_type is not RequirementType.IMPLICIT
        and match_by_id[item.requirement_id].match_status
        is MatchStatus.NOT_MATCHED
    )
    if len(high_or_critical_gaps) >= 2:
        reasons.append(
            "multiple high-or-critical mandatory requirements not matched: "
            + ",".join(high_or_critical_gaps)
        )
        cap = min(cap, Decimal("69"))
        if recommendation_cap is None:
            recommendation_cap = RecommendationLevel.TRY_APPLY

    return ScoreCapDecision(
        score_cap=cap,
        confirmed_hard_blockers=confirmed,
        unverified_hard_blockers=unverified,
        cap_reasons=reasons,
        recommendation_cap=recommendation_cap,
    )


def select_recommendation(
    *,
    final_score: Decimal,
    mandatory_coverage_ratio: Decimal,
    strong_evidence_coverage_ratio: Decimal,
    confirmed_hard_blockers: Sequence[str],
    unverified_hard_blockers: Sequence[str],
    has_critical_mandatory_gap: bool,
) -> RecommendationLevel:
    if confirmed_hard_blockers:
        return RecommendationLevel.NOT_PRIORITY
    if (
        final_score >= Decimal("80")
        and mandatory_coverage_ratio >= Decimal("0.85")
        and strong_evidence_coverage_ratio >= Decimal("0.70")
        and not has_critical_mandatory_gap
    ):
        level = RecommendationLevel.PRIORITY_APPLY
    elif (
        final_score >= Decimal("68")
        and mandatory_coverage_ratio >= Decimal("0.65")
    ):
        level = RecommendationLevel.OPTIMIZE_THEN_APPLY
    elif final_score >= Decimal("50"):
        level = RecommendationLevel.TRY_APPLY
    else:
        level = RecommendationLevel.NOT_PRIORITY

    if unverified_hard_blockers and level in {
        RecommendationLevel.PRIORITY_APPLY,
        RecommendationLevel.OPTIMIZE_THEN_APPLY,
    }:
        return RecommendationLevel.TRY_APPLY
    return level
