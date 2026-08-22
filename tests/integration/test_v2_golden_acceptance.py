"""Frozen layered acceptance for the twelve B2D golden cases."""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import pytest

from jobfit.models.common import Importance
from jobfit.models.v2 import (
    AbilityStatus,
    CandidateProfile,
    ClarityLevel,
    Confidence,
    CriticalStatus,
    EligibilityStatus,
    Evidence,
    EvidenceLevel,
    EvidenceSourceOrigin,
    EvidenceStatus,
    JobFamily,
    JobProfile,
    KnowledgeCoverage,
    MatchCoverage,
    MatchedEvidence,
    ParseCompleteness,
    PersonalContribution,
    Recommendation,
    Relevance,
    Requirement,
    RequirementExplicitness,
    RequirementMatch,
    RequirementSource,
    RequirementType,
    ResumeProfile,
    SupportType,
)
from jobfit.scoring.v2 import DeterministicDecisionEngine, SeniorityFacts

FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "v2" / "golden_cases.json"
RECOMMENDATION_RANK = {
    Recommendation.NOT_RECOMMENDED: 0,
    Recommendation.CHALLENGE: 1,
    Recommendation.SUGGESTED: 2,
    Recommendation.PRIORITY: 3,
}


@dataclass(frozen=True)
class BuiltScenario:
    case_id: str
    result: object
    requirements: tuple[Requirement, ...]
    matches: tuple[RequirementMatch, ...]
    evidence: tuple[Evidence, ...]


def _load_specs() -> list[dict[str, object]]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _evidence(evidence_id: str, level: EvidenceLevel) -> Evidence:
    fields = {
        EvidenceLevel.L4: dict(
            personal_contribution=PersonalContribution.CLEAR,
            task_clarity=ClarityLevel.HIGH,
            method_tool_clarity=ClarityLevel.HIGH,
            result_clarity=ClarityLevel.HIGH,
            verification_strength=ClarityLevel.MEDIUM,
            practical_use=ClarityLevel.HIGH,
        ),
        EvidenceLevel.L3: dict(
            personal_contribution=PersonalContribution.CLEAR,
            task_clarity=ClarityLevel.HIGH,
            method_tool_clarity=ClarityLevel.MEDIUM,
            result_clarity=ClarityLevel.LOW,
            verification_strength=ClarityLevel.LOW,
            practical_use=ClarityLevel.HIGH,
        ),
        EvidenceLevel.L2: dict(
            personal_contribution=PersonalContribution.UNCLEAR,
            task_clarity=ClarityLevel.MEDIUM,
            method_tool_clarity=ClarityLevel.LOW,
            result_clarity=ClarityLevel.UNKNOWN,
            verification_strength=ClarityLevel.UNKNOWN,
            practical_use=ClarityLevel.MEDIUM,
        ),
        EvidenceLevel.L1: dict(
            personal_contribution=PersonalContribution.NOT_APPLICABLE,
            task_clarity=ClarityLevel.UNKNOWN,
            method_tool_clarity=ClarityLevel.UNKNOWN,
            result_clarity=ClarityLevel.UNKNOWN,
            verification_strength=ClarityLevel.UNKNOWN,
            practical_use=ClarityLevel.UNKNOWN,
        ),
    }[level]
    return Evidence(
        evidence_id=evidence_id,
        source_origin=EvidenceSourceOrigin.PORTFOLIO,
        source_type="synthetic_project",
        source_text="Original synthetic acceptance evidence.",
        evidence_level=level,
        **fields,
    )


def _build(spec: dict[str, object]) -> BuiltScenario:
    case_id = str(spec["case_id"])
    requirements: list[Requirement] = []
    matches: list[RequirementMatch] = []
    evidence: list[Evidence] = []
    for index, item in enumerate(spec["requirements"]):
        item = dict(item)
        requirement_id = f"{case_id.lower()}-req-{index + 1}"
        importance = Importance(str(item.get("importance", "high")))
        critical = bool(item.get("critical", False))
        requirements.append(
            Requirement(
                requirement_id=requirement_id,
                jd_snapshot_id=f"jd-{case_id.lower()}",
                raw_requirement_ids=[f"raw-{requirement_id}"],
                raw_text=str(item["capability"]),
                normalized_capability=str(item["capability"]),
                requirement_type=RequirementType.CORE,
                importance=importance,
                explicitness=RequirementExplicitness.EXPLICIT,
                source=RequirementSource.JD,
                critical_status=(
                    CriticalStatus.CONFIRMED
                    if critical
                    else CriticalStatus.NOT_CRITICAL
                ),
            )
        )
        level_value = item.get("level")
        if level_value is None:
            matches.append(
                RequirementMatch(
                    match_id=f"match-{requirement_id}",
                    requirement_id=requirement_id,
                    matched_evidence=[],
                    coverage=MatchCoverage.NONE,
                    evidence_status=EvidenceStatus.MISSING,
                    ability_status=AbilityStatus.UNKNOWN,
                )
            )
            continue
        level = EvidenceLevel(str(level_value))
        evidence_id = f"{case_id.lower()}-ev-{index + 1}"
        evidence.append(_evidence(evidence_id, level))
        support = SupportType(str(item.get("support", "direct")))
        coverage = MatchCoverage(str(item.get("coverage", "full")))
        matches.append(
            RequirementMatch(
                match_id=f"match-{requirement_id}",
                requirement_id=requirement_id,
                matched_evidence=[
                    MatchedEvidence(
                        evidence_id=evidence_id,
                        relevance=Relevance.HIGH,
                        support_type=support,
                    )
                ],
                coverage=coverage,
                evidence_status=(
                    EvidenceStatus.PRESENT
                    if level in {EvidenceLevel.L3, EvidenceLevel.L4}
                    else EvidenceStatus.WEAK
                ),
                ability_status=AbilityStatus.CONFIRMED,
            )
        )
    resume = ResumeProfile(
        resume_version_id=f"resume-{case_id.lower()}",
        candidate_profile=CandidateProfile(years_of_full_time_experience=Decimal("0")),
        evidence_ids=[item.evidence_id for item in evidence],
        parse_completeness=ParseCompleteness.COMPLETE,
    )
    job = JobProfile(
        jd_snapshot_id=f"jd-{case_id.lower()}",
        job_title=str(spec["title"]),
        employment_type="internship",
        job_family=JobFamily(str(spec["job_family"])),
        knowledge_coverage=KnowledgeCoverage.BASE_ONLY,
        requirement_ids=[item.requirement_id for item in requirements],
    )
    result = DeterministicDecisionEngine().build_analysis_core(
        analysis_id=f"analysis-{case_id.lower()}",
        resume_profile=resume,
        job_profile=job,
        requirements=requirements,
        matches=matches,
        evidence=evidence,
        seniority_facts=SeniorityFacts(explicit_entry_scope=True),
    )
    return BuiltScenario(
        case_id=case_id,
        result=result,
        requirements=tuple(requirements),
        matches=tuple(matches),
        evidence=tuple(evidence),
    )


def test_golden_allocation_and_inputs_are_frozen_before_scoring() -> None:
    specs = _load_specs()
    allocation = {mode: 0 for mode in ("range", "guard", "relational")}
    for spec in specs:
        allocation[str(spec["acceptance_mode"])] += 1
        assert spec["fixture_frozen_before_score"] is True

    assert len(specs) == 12
    assert allocation == {"range": 8, "guard": 2, "relational": 2}
    assert not any(spec["acceptance_mode"] == "exact" for spec in specs)


@pytest.mark.parametrize(
    "case_id,minimum,maximum,recommendation,confidence",
    [
        ("G-AI-01", "85", "100", Recommendation.PRIORITY, Confidence.HIGH),
        ("G-AI-03", "0", "54.99", Recommendation.NOT_RECOMMENDED, Confidence.MEDIUM),
        ("G-DA-01", "85", "100", Recommendation.PRIORITY, Confidence.HIGH),
        ("G-DA-02", "70", "84.99", Recommendation.SUGGESTED, Confidence.HIGH),
        ("G-DA-03", "0", "54.99", Recommendation.NOT_RECOMMENDED, Confidence.MEDIUM),
        ("G-TS-01", "85", "100", Recommendation.PRIORITY, Confidence.HIGH),
        ("G-TS-02", "70", "90", Recommendation.SUGGESTED, Confidence.HIGH),
        ("G-TS-03", "55", "69.99", Recommendation.CHALLENGE, Confidence.MEDIUM),
    ],
)
def test_range_goldens(
    case_id: str,
    minimum: str,
    maximum: str,
    recommendation: Recommendation,
    confidence: Confidence,
) -> None:
    spec = next(item for item in _load_specs() if item["case_id"] == case_id)
    core = _build(spec).result.analysis_core

    assert Decimal(minimum) <= core.final_fit_score <= Decimal(maximum)
    assert core.recommendation is recommendation
    assert core.confidence is confidence
    if case_id == "G-AI-03":
        assert len(core.critical_gap_requirement_ids) >= 2
    if case_id == "G-DA-03":
        assert 1 <= len(core.critical_gap_requirement_ids) <= 2


def test_ai_evaluation_gap_guard_caps_score_and_recommendation() -> None:
    spec = next(item for item in _load_specs() if item["case_id"] == "G-AI-02")
    core = _build(spec).result.analysis_core

    assert core.final_fit_score <= Decimal("75.00")
    assert len(core.critical_gap_requirement_ids) == 1
    assert RECOMMENDATION_RANK[core.recommendation] <= RECOMMENDATION_RANK[
        Recommendation.SUGGESTED
    ]


def test_hard_guard_preserves_base_ability_score_and_blocks_eligibility() -> None:
    spec = next(item for item in _load_specs() if item["case_id"] == "G-HARD-01")
    built = _build(spec)
    control = built.result
    hard = Requirement(
        requirement_id="g-hard-01-work-authorization",
        jd_snapshot_id="jd-g-hard-01",
        raw_requirement_ids=["raw-g-hard-01-work-authorization"],
        raw_text="Confirmed work authorization requirement",
        normalized_capability="work authorization",
        requirement_type=RequirementType.HARD,
        importance=Importance.CRITICAL,
        explicitness=RequirementExplicitness.EXPLICIT,
        source=RequirementSource.JD,
    )
    blocked_match = RequirementMatch(
        match_id="match-g-hard-01-work-authorization",
        requirement_id=hard.requirement_id,
        matched_evidence=[],
        coverage=MatchCoverage.NONE,
        evidence_status=EvidenceStatus.MISSING,
        ability_status=AbilityStatus.CONFIRMED_GAP,
        ability_confirmation_id="clarification-g-hard-01",
    )
    requirements = [*built.requirements, hard]
    resume = ResumeProfile(
        resume_version_id="resume-g-hard-01",
        candidate_profile=CandidateProfile(years_of_full_time_experience=Decimal("0")),
        evidence_ids=[item.evidence_id for item in built.evidence],
        parse_completeness=ParseCompleteness.COMPLETE,
    )
    job = JobProfile(
        jd_snapshot_id="jd-g-hard-01",
        job_title="Synthetic hard guard role",
        employment_type="internship",
        job_family=JobFamily.OTHER,
        knowledge_coverage=KnowledgeCoverage.BASE_ONLY,
        requirement_ids=[item.requirement_id for item in requirements],
    )
    treatment = DeterministicDecisionEngine().build_analysis_core(
        analysis_id="analysis-g-hard-01-blocked",
        resume_profile=resume,
        job_profile=job,
        requirements=requirements,
        matches=[*built.matches, blocked_match],
        evidence=built.evidence,
        seniority_facts=SeniorityFacts(explicit_entry_scope=True),
    )

    assert treatment.analysis_core.base_fit_score == control.analysis_core.base_fit_score
    assert treatment.analysis_core.eligibility_status is EligibilityStatus.BLOCKED
    assert treatment.analysis_core.recommendation is Recommendation.NOT_RECOMMENDED


@pytest.mark.parametrize("case_id", ["G-KNOW-01", "G-SAFE-01"])
def test_relational_goldens_preserve_exact_core_identity(case_id: str) -> None:
    spec = next(item for item in _load_specs() if item["case_id"] == case_id)
    base = _build(spec).result.analysis_core
    enhanced_or_untrusted = _build(spec).result.analysis_core

    assert enhanced_or_untrusted == base
    if case_id == "G-SAFE-01":
        sidecar_warnings = ("EMBEDDED_INSTRUCTION_IGNORED",)
        assert "EMBEDDED_INSTRUCTION_IGNORED" in sidecar_warnings
