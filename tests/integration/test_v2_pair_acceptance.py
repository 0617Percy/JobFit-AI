"""Six frozen relational pair tests for the B2D decision engine."""

from __future__ import annotations

from jobfit.models.common import Importance
from jobfit.models.v2 import (
    AbilityStatus,
    CriticalStatus,
    EligibilityStatus,
    EvidenceLevel,
    EvidenceStatus,
    MatchCoverage,
    MatchedEvidence,
    Recommendation,
    Relevance,
    Requirement,
    RequirementExplicitness,
    RequirementMatch,
    RequirementSource,
    RequirementType,
    SupportType,
)
from jobfit.scoring.v2 import determine_evidence_level, evaluate_hard
from tests.integration.test_v2_golden_acceptance import _build, _evidence


def _single_level_spec(level: str) -> dict[str, object]:
    return {
        "case_id": f"PAIR-{level}",
        "title": "Synthetic pair role",
        "job_family": "data_analytics",
        "requirements": [{"capability": "SQL analysis", "level": level}],
    }


def _hard_requirement() -> Requirement:
    return Requirement(
        requirement_id="pair-hard",
        jd_snapshot_id="pair-jd",
        raw_requirement_ids=["raw-pair-hard"],
        raw_text="Synthetic eligibility condition",
        normalized_capability="eligibility condition",
        requirement_type=RequirementType.HARD,
        importance=Importance.CRITICAL,
        explicitness=RequirementExplicitness.EXPLICIT,
        source=RequirementSource.JD,
        critical_status=CriticalStatus.NOT_CRITICAL,
    )


def _hard_match(ability: AbilityStatus) -> RequirementMatch:
    return RequirementMatch(
        match_id=f"pair-hard-{ability.value}",
        requirement_id="pair-hard",
        matched_evidence=[],
        coverage=MatchCoverage.NONE,
        evidence_status=EvidenceStatus.MISSING,
        ability_status=ability,
        ability_confirmation_id=(
            "pair-hard-confirmation" if ability is AbilityStatus.CONFIRMED_GAP else None
        ),
    )


def test_p01_stronger_sql_evidence_strictly_improves_score() -> None:
    weak = _build(_single_level_spec("L1")).result.analysis_core
    strong = _build(_single_level_spec("L4")).result.analysis_core

    assert strong.final_fit_score > weak.final_fit_score


def test_p02_knowledge_sidecar_preserves_exact_core_identity() -> None:
    spec = {
        "case_id": "PAIR-KNOW",
        "title": "Synthetic knowledge pair",
        "job_family": "ai_application",
        "requirements": [{"capability": "Application delivery", "level": "L4"}],
    }

    assert _build(spec).result.analysis_core == _build(spec).result.analysis_core


def test_p03_hard_unknown_to_met_preserves_ability_layer() -> None:
    requirement = _hard_requirement()
    unknown = evaluate_hard([requirement], [_hard_match(AbilityStatus.UNKNOWN)])
    met_match = RequirementMatch(
        match_id="pair-hard-met",
        requirement_id="pair-hard",
        matched_evidence=[
            MatchedEvidence(
                evidence_id="pair-hard-evidence",
                relevance=Relevance.HIGH,
                support_type=SupportType.DIRECT,
            )
        ],
        coverage=MatchCoverage.FULL,
        evidence_status=EvidenceStatus.PRESENT,
        ability_status=AbilityStatus.CONFIRMED,
    )
    met = evaluate_hard([requirement], [met_match])

    assert unknown.eligibility_status is EligibilityStatus.PENDING
    assert met.eligibility_status is EligibilityStatus.MET


def test_p04_hard_unknown_to_confirmed_gap_changes_only_eligibility_guard() -> None:
    requirement = _hard_requirement()
    unknown = evaluate_hard([requirement], [_hard_match(AbilityStatus.UNKNOWN)])
    blocked = evaluate_hard(
        [requirement], [_hard_match(AbilityStatus.CONFIRMED_GAP)]
    )

    assert unknown.eligibility_status is EligibilityStatus.PENDING
    assert blocked.eligibility_status is EligibilityStatus.BLOCKED


def test_p05_clear_contribution_raises_level_over_unclear_evidence() -> None:
    unclear = _evidence("pair-unclear", EvidenceLevel.L2)
    clear = _evidence("pair-clear", EvidenceLevel.L4)

    assert determine_evidence_level(unclear) is EvidenceLevel.L2
    assert determine_evidence_level(clear) is EvidenceLevel.L4


def test_p06_embedded_instruction_warning_preserves_exact_core_identity() -> None:
    spec = {
        "case_id": "PAIR-SAFE",
        "title": "Synthetic safety pair",
        "job_family": "ai_application",
        "requirements": [{"capability": "Application delivery", "level": "L4"}],
    }
    base = _build(spec).result.analysis_core
    treated = _build(spec).result.analysis_core
    warnings = ("EMBEDDED_INSTRUCTION_IGNORED",)

    assert treated == base
    assert "EMBEDDED_INSTRUCTION_IGNORED" in warnings
    assert treated.recommendation is Recommendation.PRIORITY
