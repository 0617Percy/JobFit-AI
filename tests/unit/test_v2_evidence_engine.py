"""Frozen R01-R07 evidence-level and match-component behavior."""

from __future__ import annotations

from decimal import Decimal

import pytest

from jobfit.models.v2 import (
    AbilityStatus,
    ClarityLevel,
    Evidence,
    EvidenceLevel,
    EvidenceSourceOrigin,
    EvidenceStatus,
    MatchCoverage,
    MatchedEvidence,
    PersonalContribution,
    Relevance,
    RequirementMatch,
    SupportType,
)
from jobfit.scoring.v2 import (
    DecisionInputError,
    DecisionNotFinalizableError,
    compute_requirement_match,
    determine_evidence_level,
    validate_evidence_level,
)


def make_evidence(evidence_id: str, **updates: object) -> Evidence:
    payload: dict[str, object] = {
        "evidence_id": evidence_id,
        "source_origin": EvidenceSourceOrigin.PORTFOLIO,
        "source_type": "project",
        "source_text": "Implemented a tested application feature.",
        "personal_contribution": PersonalContribution.CLEAR,
        "task_clarity": ClarityLevel.HIGH,
        "method_tool_clarity": ClarityLevel.HIGH,
        "result_clarity": ClarityLevel.HIGH,
        "verification_strength": ClarityLevel.MEDIUM,
        "practical_use": ClarityLevel.HIGH,
        "evidence_level": EvidenceLevel.L4,
    }
    payload.update(updates)
    return Evidence(**payload)


def make_match(*relations: MatchedEvidence, **updates: object) -> RequirementMatch:
    payload: dict[str, object] = {
        "match_id": "match-001",
        "requirement_id": "req-001",
        "matched_evidence": list(relations),
        "coverage": MatchCoverage.FULL,
        "evidence_status": EvidenceStatus.PRESENT,
        "ability_status": AbilityStatus.CONFIRMED,
        "best_evidence_level": None,
    }
    payload.update(updates)
    return RequirementMatch(**payload)


@pytest.mark.parametrize(
    ("evidence", "expected"),
    [
        (make_evidence("ev-l4"), EvidenceLevel.L4),
        (
            make_evidence(
                "ev-l3",
                personal_contribution=PersonalContribution.PARTIAL,
                result_clarity=ClarityLevel.UNKNOWN,
                verification_strength=ClarityLevel.UNKNOWN,
                evidence_level=EvidenceLevel.L3,
            ),
            EvidenceLevel.L3,
        ),
        (
            make_evidence(
                "ev-l2",
                personal_contribution=PersonalContribution.UNCLEAR,
                evidence_level=EvidenceLevel.L2,
            ),
            EvidenceLevel.L2,
        ),
        (
            make_evidence(
                "ev-l1",
                personal_contribution=PersonalContribution.NOT_APPLICABLE,
                task_clarity=ClarityLevel.UNKNOWN,
                method_tool_clarity=ClarityLevel.UNKNOWN,
                result_clarity=ClarityLevel.UNKNOWN,
                verification_strength=ClarityLevel.UNKNOWN,
                practical_use=ClarityLevel.UNKNOWN,
                evidence_level=EvidenceLevel.L1,
            ),
            EvidenceLevel.L1,
        ),
    ],
)
def test_evidence_level_is_derived_from_frozen_structural_features(
    evidence: Evidence,
    expected: EvidenceLevel,
) -> None:
    assert determine_evidence_level(evidence) is expected
    assert validate_evidence_level(evidence) is evidence


def test_ambiguity_and_non_task_ownership_apply_the_frozen_caps() -> None:
    ambiguous = make_evidence(
        "ev-ambiguous",
        ambiguity=True,
        evidence_level=EvidenceLevel.L2,
    )
    task_without_contribution = make_evidence(
        "ev-no-owner",
        personal_contribution=PersonalContribution.NOT_APPLICABLE,
        evidence_level=EvidenceLevel.L1,
    )

    assert determine_evidence_level(ambiguous) is EvidenceLevel.L2
    assert determine_evidence_level(task_without_contribution) is EvidenceLevel.L1


def test_model_supplied_level_that_conflicts_with_features_fails_closed() -> None:
    overstated = make_evidence(
        "ev-overstated",
        personal_contribution=PersonalContribution.UNCLEAR,
        evidence_level=EvidenceLevel.L4,
    )

    with pytest.raises(DecisionInputError, match="evidence level"):
        validate_evidence_level(overstated)


def test_match_uses_one_max_relation_without_stacking_and_stable_ties() -> None:
    direct_l3 = make_evidence(
        "ev-direct",
        result_clarity=ClarityLevel.UNKNOWN,
        verification_strength=ClarityLevel.UNKNOWN,
        evidence_level=EvidenceLevel.L3,
    )
    transferable_l3 = direct_l3.model_copy(update={"evidence_id": "ev-transfer"})
    low_l4 = make_evidence("ev-low")
    match = make_match(
        MatchedEvidence(
            evidence_id=transferable_l3.evidence_id,
            relevance=Relevance.HIGH,
            support_type=SupportType.TRANSFERABLE,
        ),
        MatchedEvidence(
            evidence_id=direct_l3.evidence_id,
            relevance=Relevance.HIGH,
            support_type=SupportType.DIRECT,
        ),
        MatchedEvidence(
            evidence_id=low_l4.evidence_id,
            relevance=Relevance.LOW,
            support_type=SupportType.DIRECT,
        ),
    )

    result = compute_requirement_match(
        match,
        {
            direct_l3.evidence_id: direct_l3,
            transferable_l3.evidence_id: transferable_l3,
            low_l4.evidence_id: low_l4,
        },
    )

    assert result.selected_evidence_id == "ev-direct"
    assert result.match.best_evidence_level is EvidenceLevel.L3
    assert result.match.match_score_component == Decimal("0.8500")


def test_relevance_is_the_only_numeric_relation_multiplier() -> None:
    evidence = make_evidence("ev-medium")
    relation = MatchedEvidence(
        evidence_id=evidence.evidence_id,
        relevance=Relevance.MEDIUM,
        support_type=SupportType.CONTEXTUAL,
    )

    result = compute_requirement_match(make_match(relation), {evidence.evidence_id: evidence})

    assert result.match.match_score_component == Decimal("0.7500")


def test_missing_match_is_l0_semantics_without_an_evidence_object() -> None:
    missing = make_match(
        coverage=MatchCoverage.NONE,
        evidence_status=EvidenceStatus.MISSING,
        ability_status=AbilityStatus.UNKNOWN,
        best_evidence_level=None,
    )

    result = compute_requirement_match(missing, {})

    assert result.selected_evidence_id is None
    assert result.match.best_evidence_level is None
    assert result.match.match_score_component == Decimal("0.0000")


def test_dangling_relation_and_unforced_conflict_fail_closed() -> None:
    relation = MatchedEvidence(
        evidence_id="ev-missing",
        relevance=Relevance.HIGH,
        support_type=SupportType.DIRECT,
    )
    with pytest.raises(DecisionInputError, match="unknown evidence"):
        compute_requirement_match(make_match(relation), {})

    evidence = make_evidence("ev-conflict")
    conflict = make_match(
        MatchedEvidence(
            evidence_id=evidence.evidence_id,
            relevance=Relevance.HIGH,
            support_type=SupportType.DIRECT,
        ),
        evidence_status=EvidenceStatus.CONFLICT,
        ability_status=AbilityStatus.CONFLICT,
    )
    with pytest.raises(DecisionNotFinalizableError, match="conflict"):
        compute_requirement_match(conflict, {evidence.evidence_id: evidence})

    forced = compute_requirement_match(
        conflict,
        {evidence.evidence_id: evidence},
        forced_continue=True,
    )
    assert forced.selected_evidence_id is None
    assert forced.match.match_score_component == Decimal("0.0000")
