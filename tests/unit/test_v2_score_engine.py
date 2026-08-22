"""Frozen R08-R20 deterministic v2 scoring behavior."""

from __future__ import annotations

from decimal import Decimal

import pytest

from jobfit.models.common import Importance
from jobfit.models.v2 import (
    AbilityStatus,
    ClarityLevel,
    CriticalStatus,
    Evidence,
    EvidenceLevel,
    EvidenceSourceOrigin,
    EvidenceStatus,
    MatchCoverage,
    MatchedEvidence,
    PersonalContribution,
    Relevance,
    Requirement,
    RequirementExplicitness,
    RequirementMatch,
    RequirementSource,
    RequirementType,
    SupportType,
)
from jobfit.scoring.v2 import (
    DecisionInputError,
    DecisionNotFinalizableError,
    compute_scores,
)


def make_evidence(
    evidence_id: str,
    level: EvidenceLevel,
) -> Evidence:
    structural: dict[EvidenceLevel, dict[str, object]] = {
        EvidenceLevel.L4: {},
        EvidenceLevel.L3: {
            "result_clarity": ClarityLevel.UNKNOWN,
            "verification_strength": ClarityLevel.UNKNOWN,
        },
        EvidenceLevel.L2: {
            "personal_contribution": PersonalContribution.UNCLEAR,
        },
        EvidenceLevel.L1: {
            "personal_contribution": PersonalContribution.NOT_APPLICABLE,
            "task_clarity": ClarityLevel.UNKNOWN,
            "method_tool_clarity": ClarityLevel.UNKNOWN,
            "result_clarity": ClarityLevel.UNKNOWN,
            "verification_strength": ClarityLevel.UNKNOWN,
            "practical_use": ClarityLevel.UNKNOWN,
        },
    }
    payload: dict[str, object] = {
        "evidence_id": evidence_id,
        "source_origin": EvidenceSourceOrigin.PORTFOLIO,
        "source_type": "project",
        "source_text": "Structured test evidence.",
        "personal_contribution": PersonalContribution.CLEAR,
        "task_clarity": ClarityLevel.HIGH,
        "method_tool_clarity": ClarityLevel.HIGH,
        "result_clarity": ClarityLevel.HIGH,
        "verification_strength": ClarityLevel.MEDIUM,
        "practical_use": ClarityLevel.HIGH,
        "evidence_level": level,
    }
    payload.update(structural[level])
    return Evidence(**payload)


def make_requirement(
    requirement_id: str,
    requirement_type: RequirementType,
    importance: Importance,
) -> Requirement:
    if requirement_type is RequirementType.IMPLICIT:
        return Requirement(
            requirement_id=requirement_id,
            normalized_capability=requirement_id,
            requirement_type=requirement_type,
            importance=importance,
            explicitness=RequirementExplicitness.IMPLICIT,
            source=RequirementSource.KNOWLEDGE,
        )
    return Requirement(
        requirement_id=requirement_id,
        jd_snapshot_id="jd-v1",
        raw_requirement_ids=[f"raw-{requirement_id}"],
        raw_text=requirement_id,
        normalized_capability=requirement_id,
        requirement_type=requirement_type,
        importance=importance,
        explicitness=RequirementExplicitness.EXPLICIT,
        source=RequirementSource.JD,
        critical_status=CriticalStatus.NOT_CRITICAL,
    )


def make_match(
    requirement_id: str,
    evidence_id: str | None,
    *,
    relevance: Relevance = Relevance.HIGH,
    support_type: SupportType = SupportType.DIRECT,
    evidence_status: EvidenceStatus = EvidenceStatus.PRESENT,
    ability_status: AbilityStatus = AbilityStatus.CONFIRMED,
) -> RequirementMatch:
    missing = evidence_id is None
    return RequirementMatch(
        match_id=f"match-{requirement_id}",
        requirement_id=requirement_id,
        matched_evidence=(
            []
            if missing
            else [
                MatchedEvidence(
                    evidence_id=evidence_id,
                    relevance=relevance,
                    support_type=support_type,
                )
            ]
        ),
        coverage=MatchCoverage.NONE if missing else MatchCoverage.FULL,
        evidence_status=EvidenceStatus.MISSING if missing else evidence_status,
        ability_status=AbilityStatus.UNKNOWN if missing else ability_status,
    )


def test_weighted_score_uses_importance_and_core_supporting_80_20() -> None:
    requirements = [
        make_requirement("core-high", RequirementType.CORE, Importance.HIGH),
        make_requirement("core-low", RequirementType.CORE, Importance.LOW),
        make_requirement(
            "support-medium",
            RequirementType.SUPPORTING,
            Importance.MEDIUM,
        ),
        make_requirement(
            "preferred-high",
            RequirementType.PREFERRED,
            Importance.HIGH,
        ),
    ]
    evidence = {
        "ev-core-high": make_evidence("ev-core-high", EvidenceLevel.L4),
        "ev-core-low": make_evidence("ev-core-low", EvidenceLevel.L1),
        "ev-support": make_evidence("ev-support", EvidenceLevel.L4),
        "ev-preferred": make_evidence("ev-preferred", EvidenceLevel.L3),
    }
    matches = [
        make_match("core-high", "ev-core-high"),
        make_match("core-low", "ev-core-low"),
        make_match("support-medium", "ev-support", relevance=Relevance.MEDIUM),
        make_match("preferred-high", "ev-preferred"),
    ]

    result = compute_scores(requirements, matches, evidence)

    assert result.core_ratio == Decimal("0.825")
    assert result.supporting_ratio == Decimal("0.75")
    assert result.base_fit_score == Decimal("81.00")
    assert result.preferred_bonus == Decimal("2")
    assert result.final_fit_score == Decimal("83.00")


def test_empty_supporting_renormalizes_core_to_one_hundred_percent() -> None:
    requirement = make_requirement("core", RequirementType.CORE, Importance.HIGH)
    evidence = make_evidence("ev-core", EvidenceLevel.L3)
    match = make_match("core", evidence.evidence_id, relevance=Relevance.MEDIUM)

    result = compute_scores([requirement], [match], {evidence.evidence_id: evidence})

    assert result.core_ratio == Decimal("0.6375")
    assert result.supporting_ratio is None
    assert result.base_fit_score == Decimal("63.75")


def test_empty_core_does_not_manufacture_a_formal_score() -> None:
    supporting = make_requirement(
        "supporting",
        RequirementType.SUPPORTING,
        Importance.HIGH,
    )
    evidence = make_evidence("ev-supporting", EvidenceLevel.L4)

    with pytest.raises(DecisionNotFinalizableError, match="Core"):
        compute_scores(
            [supporting],
            [make_match("supporting", evidence.evidence_id)],
            {evidence.evidence_id: evidence},
        )


def test_missing_core_stays_in_denominator_with_zero_contribution() -> None:
    requirements = [
        make_requirement("known", RequirementType.CORE, Importance.MEDIUM),
        make_requirement("unknown", RequirementType.CORE, Importance.MEDIUM),
    ]
    evidence = make_evidence("ev-known", EvidenceLevel.L4)

    result = compute_scores(
        requirements,
        [make_match("known", evidence.evidence_id), make_match("unknown", None)],
        {evidence.evidence_id: evidence},
    )

    assert result.base_fit_score == Decimal("50.00")
    assert result.computed_matches[1].ability_status is AbilityStatus.UNKNOWN


def test_hard_and_implicit_are_excluded_from_score_and_bonus() -> None:
    core = make_requirement("core", RequirementType.CORE, Importance.HIGH)
    hard = make_requirement("hard", RequirementType.HARD, Importance.CRITICAL)
    implicit = make_requirement(
        "implicit",
        RequirementType.IMPLICIT,
        Importance.CRITICAL,
    )
    evidence = {
        name: make_evidence(name, EvidenceLevel.L4)
        for name in ("ev-core", "ev-hard", "ev-implicit")
    }

    result = compute_scores(
        [core, hard, implicit],
        [
            make_match("core", "ev-core"),
            make_match("hard", "ev-hard"),
            make_match("implicit", "ev-implicit"),
        ],
        evidence,
    )

    assert result.base_fit_score == Decimal("100.00")
    assert result.preferred_bonus == Decimal("0")
    assert result.computed_matches[1].match_score_component is None
    assert result.computed_matches[2].match_score_component is None


def test_preferred_bonus_uses_distinct_requirements_and_caps_at_five() -> None:
    core = make_requirement("core", RequirementType.CORE, Importance.HIGH)
    preferred = [
        make_requirement(f"pref-{index}", RequirementType.PREFERRED, Importance.HIGH)
        for index in range(3)
    ]
    evidence = {
        "ev-core": make_evidence("ev-core", EvidenceLevel.L4),
        **{
            f"ev-pref-{index}": make_evidence(
                f"ev-pref-{index}",
                EvidenceLevel.L4,
            )
            for index in range(3)
        },
    }
    matches = [make_match("core", "ev-core")]
    matches.extend(
        make_match(f"pref-{index}", f"ev-pref-{index}")
        for index in range(3)
    )

    result = compute_scores([core, *preferred], matches, evidence)

    assert result.preferred_bonus == Decimal("5")
    assert result.final_fit_score == Decimal("100.00")


def test_contextual_preferred_evidence_earns_no_bonus() -> None:
    core = make_requirement("core", RequirementType.CORE, Importance.HIGH)
    preferred = make_requirement(
        "preferred",
        RequirementType.PREFERRED,
        Importance.HIGH,
    )
    evidence = {
        "ev-core": make_evidence("ev-core", EvidenceLevel.L4),
        "ev-preferred": make_evidence("ev-preferred", EvidenceLevel.L4),
    }

    result = compute_scores(
        [core, preferred],
        [
            make_match("core", "ev-core"),
            make_match(
                "preferred",
                "ev-preferred",
                support_type=SupportType.CONTEXTUAL,
            ),
        ],
        evidence,
    )

    assert result.preferred_bonus == Decimal("0")


def test_base_rounds_half_up_once_after_group_normalization() -> None:
    requirements = [
        make_requirement(f"core-{index}", RequirementType.CORE, Importance.LOW)
        for index in range(3)
    ]
    evidence = {
        "ev-1": make_evidence("ev-1", EvidenceLevel.L4),
        "ev-2": make_evidence("ev-2", EvidenceLevel.L4),
    }

    result = compute_scores(
        requirements,
        [
            make_match("core-0", "ev-1"),
            make_match("core-1", "ev-2"),
            make_match("core-2", None),
        ],
        evidence,
    )

    assert result.base_fit_score == Decimal("66.67")
    assert result.final_fit_score == Decimal("66.67")


def test_duplicate_or_missing_requirement_match_fails_closed() -> None:
    core = make_requirement("core", RequirementType.CORE, Importance.HIGH)
    evidence = make_evidence("ev-core", EvidenceLevel.L4)
    match = make_match("core", evidence.evidence_id)

    with pytest.raises(DecisionInputError, match="exactly one match"):
        compute_scores([core], [], {evidence.evidence_id: evidence})
    with pytest.raises(DecisionInputError, match="duplicate"):
        compute_scores([core], [match, match], {evidence.evidence_id: evidence})
