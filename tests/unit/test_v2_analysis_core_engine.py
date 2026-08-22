"""Frozen R36-R40 AnalysisCore assembly and version identity tests."""

from __future__ import annotations

from decimal import Decimal

import pytest

from jobfit.models.common import Importance
from jobfit.models.v2 import (
    AbilityStatus,
    AnalysisReadiness,
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
    JobFitDomainBundle,
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
    SeniorityAlignment,
    SupportType,
)
from jobfit.scoring.v2 import (
    ANALYSIS_ENGINE_VERSION,
    CALIBRATION_STATUS,
    SCORING_RULE_VERSION,
    ClarificationCandidate,
    ClarificationImpact,
    DecisionNotFinalizableError,
    DeterministicDecisionEngine,
    SeniorityFacts,
    build_v2_version_manifest,
)
from jobfit.validators.v2 import DomainValidator


def make_evidence(evidence_id: str = "ev-core") -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        source_origin=EvidenceSourceOrigin.PORTFOLIO,
        source_type="project",
        source_text="Built and verified a complete application.",
        personal_contribution=PersonalContribution.CLEAR,
        task_clarity=ClarityLevel.HIGH,
        method_tool_clarity=ClarityLevel.HIGH,
        result_clarity=ClarityLevel.HIGH,
        verification_strength=ClarityLevel.MEDIUM,
        practical_use=ClarityLevel.HIGH,
        evidence_level=EvidenceLevel.L4,
    )


def make_requirement(
    requirement_id: str = "req-core",
    requirement_type: RequirementType = RequirementType.CORE,
) -> Requirement:
    return Requirement(
        requirement_id=requirement_id,
        jd_snapshot_id="jd-v1",
        raw_requirement_ids=[f"raw-{requirement_id}"],
        raw_text=requirement_id,
        normalized_capability=requirement_id,
        requirement_type=requirement_type,
        importance=(
            Importance.CRITICAL
            if requirement_type is RequirementType.HARD
            else Importance.HIGH
        ),
        explicitness=RequirementExplicitness.EXPLICIT,
        source=RequirementSource.JD,
        critical_status=CriticalStatus.NOT_CRITICAL,
    )


def make_match(
    requirement_id: str = "req-core",
    evidence_id: str | None = "ev-core",
    *,
    conflict: bool = False,
    confirmed_gap: bool = False,
) -> RequirementMatch:
    if evidence_id is None:
        return RequirementMatch(
            match_id=f"match-{requirement_id}",
            requirement_id=requirement_id,
            matched_evidence=[],
            coverage=MatchCoverage.NONE,
            evidence_status=EvidenceStatus.MISSING,
            ability_status=(
                AbilityStatus.CONFIRMED_GAP
                if confirmed_gap
                else AbilityStatus.UNKNOWN
            ),
            ability_confirmation_id=("clarification-hard" if confirmed_gap else None),
        )
    return RequirementMatch(
        match_id=f"match-{requirement_id}",
        requirement_id=requirement_id,
        matched_evidence=[
            MatchedEvidence(
                evidence_id=evidence_id,
                relevance=Relevance.HIGH,
                support_type=SupportType.DIRECT,
            )
        ],
        coverage=MatchCoverage.FULL,
        evidence_status=(
            EvidenceStatus.CONFLICT if conflict else EvidenceStatus.PRESENT
        ),
        ability_status=(AbilityStatus.CONFLICT if conflict else AbilityStatus.CONFIRMED),
    )


def make_profiles(requirement_ids: list[str]) -> tuple[ResumeProfile, JobProfile]:
    return (
        ResumeProfile(
            resume_version_id="resume-v1",
            candidate_profile=CandidateProfile(
                years_of_full_time_experience=Decimal("0")
            ),
            evidence_ids=["ev-core"],
            parse_completeness=ParseCompleteness.COMPLETE,
        ),
        JobProfile(
            jd_snapshot_id="jd-v1",
            job_title="Synthetic Entry Role",
            employment_type="internship",
            job_family=JobFamily.OTHER,
            knowledge_coverage=KnowledgeCoverage.BASE_ONLY,
            requirement_ids=requirement_ids,
        ),
    )


def test_engine_builds_a_valid_deterministic_analysis_core() -> None:
    evidence = make_evidence()
    requirement = make_requirement()
    match = make_match()
    resume, job = make_profiles([requirement.requirement_id])
    engine = DeterministicDecisionEngine()

    first = engine.build_analysis_core(
        analysis_id="analysis-v2-001",
        resume_profile=resume,
        job_profile=job,
        requirements=[requirement],
        matches=[match],
        evidence=[evidence],
        seniority_facts=SeniorityFacts(explicit_entry_scope=True),
    )
    second = engine.build_analysis_core(
        analysis_id="analysis-v2-001",
        resume_profile=resume,
        job_profile=job,
        requirements=[requirement],
        matches=[match],
        evidence=[evidence],
        seniority_facts=SeniorityFacts(explicit_entry_scope=True),
    )

    core = first.analysis_core
    assert first == second
    assert core.analysis_readiness is AnalysisReadiness.READY
    assert core.eligibility_status is EligibilityStatus.MET
    assert core.seniority_alignment is SeniorityAlignment.ALIGNED
    assert core.base_fit_score == Decimal("100.00")
    assert core.final_fit_score == Decimal("100.00")
    assert core.confidence is Confidence.HIGH
    assert core.recommendation is Recommendation.PRIORITY

    bundle = JobFitDomainBundle(
        resume_profile=resume,
        evidence=[evidence],
        job_profile=job,
        requirements=[requirement],
        requirement_matches=list(first.computed_matches),
        analysis_core=core,
    )
    assert DomainValidator().validate(bundle).valid is True


def test_hard_block_changes_eligibility_but_not_ability_score() -> None:
    evidence = make_evidence()
    core_requirement = make_requirement()
    hard_requirement = make_requirement("req-hard", RequirementType.HARD)
    resume, control_job = make_profiles([core_requirement.requirement_id])
    _, treatment_job = make_profiles(
        [core_requirement.requirement_id, hard_requirement.requirement_id]
    )
    engine = DeterministicDecisionEngine()
    control = engine.build_analysis_core(
        analysis_id="analysis-control",
        resume_profile=resume,
        job_profile=control_job,
        requirements=[core_requirement],
        matches=[make_match()],
        evidence=[evidence],
        seniority_facts=SeniorityFacts(explicit_entry_scope=True),
    )
    treatment = engine.build_analysis_core(
        analysis_id="analysis-treatment",
        resume_profile=resume,
        job_profile=treatment_job,
        requirements=[core_requirement, hard_requirement],
        matches=[make_match(), make_match("req-hard", None, confirmed_gap=True)],
        evidence=[evidence],
        seniority_facts=SeniorityFacts(explicit_entry_scope=True),
    )

    assert treatment.analysis_core.base_fit_score == control.analysis_core.base_fit_score
    assert treatment.analysis_core.eligibility_status is EligibilityStatus.BLOCKED
    assert treatment.analysis_core.recommendation is Recommendation.NOT_RECOMMENDED


def test_unresolved_conflict_requires_clarification_unless_explicitly_skipped() -> None:
    evidence = make_evidence()
    requirement = make_requirement()
    resume, job = make_profiles([requirement.requirement_id])
    question = ClarificationCandidate(
        question_id="question-conflict",
        impact=ClarificationImpact.SCORE_BAND,
        requirement_id=requirement.requirement_id,
        question_type="evidence_conflict",
        question="Which account is accurate?",
        required=True,
    )
    engine = DeterministicDecisionEngine()

    with pytest.raises(DecisionNotFinalizableError, match="conflict"):
        engine.build_analysis_core(
            analysis_id="analysis-conflict",
            resume_profile=resume,
            job_profile=job,
            requirements=[requirement],
            matches=[make_match(conflict=True)],
            evidence=[evidence],
            seniority_facts=SeniorityFacts(explicit_entry_scope=True),
            clarification_candidates=[question],
        )

    forced = engine.build_analysis_core(
        analysis_id="analysis-forced",
        resume_profile=resume,
        job_profile=job,
        requirements=[requirement],
        matches=[make_match(conflict=True)],
        evidence=[evidence],
        seniority_facts=SeniorityFacts(explicit_entry_scope=True),
        clarification_candidates=[question],
        explicitly_skipped_required_clarification=True,
    )
    assert forced.analysis_core.forced_continue is True
    assert forced.analysis_core.analysis_readiness is AnalysisReadiness.READY_WITH_GAPS
    assert forced.analysis_core.confidence is Confidence.LOW


def test_version_manifest_uses_frozen_rule_and_engine_versions() -> None:
    manifest = build_v2_version_manifest(
        software_version="1.1.0",
        prompt_pack_version="1.0.0",
        schema_version="2.0.0",
        knowledge_version="2026.08.1",
        business_test_set_version="1.0.0",
        golden_set_version="1.0.0",
    )

    assert SCORING_RULE_VERSION == "1.0.0"
    assert ANALYSIS_ENGINE_VERSION == "1.0.0"
    assert CALIBRATION_STATUS == "FROZEN_FOR_IMPLEMENTATION"
    assert manifest.scoring_rule_version == SCORING_RULE_VERSION
    assert manifest.analysis_engine_version == ANALYSIS_ENGINE_VERSION
