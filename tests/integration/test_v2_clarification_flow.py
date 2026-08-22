"""B4 readiness flow integration with the frozen B2 engine."""

from decimal import Decimal

from jobfit.clarification.v2.flow import start_clarification_flow
from jobfit.models.common import Importance
from jobfit.models.v2 import (
    AbilityStatus,
    AnalysisReadiness,
    CandidateProfile,
    ClarificationAnswerSchema,
    ClarificationAnswerType,
    ClarificationCoreImpact,
    ClarificationQuestionType,
    EvidenceStatus,
    JobFamily,
    JobProfile,
    KnowledgeCoverage,
    MatchCoverage,
    ParseCompleteness,
    Requirement,
    RequirementExplicitness,
    RequirementMatch,
    RequirementSource,
    RequirementType,
    ResumeProfile,
    UnresolvedClarificationFact,
)
from jobfit.scoring.v2 import SeniorityFacts


def _ready_case(requirement_type: RequirementType = RequirementType.CORE):
    requirement = Requirement(
        requirement_id="req-1",
        jd_snapshot_id="jd-1",
        raw_requirement_ids=["raw-1"],
        raw_text="Synthetic explicit requirement",
        normalized_capability="synthetic capability",
        requirement_type=requirement_type,
        importance=Importance.HIGH,
        explicitness=RequirementExplicitness.EXPLICIT,
        source=RequirementSource.JD,
    )
    core = Requirement(
        requirement_id="req-core",
        jd_snapshot_id="jd-1",
        raw_requirement_ids=["raw-core"],
        raw_text="Synthetic core requirement",
        normalized_capability="core capability",
        requirement_type=RequirementType.CORE,
        importance=Importance.HIGH,
        explicitness=RequirementExplicitness.EXPLICIT,
        source=RequirementSource.JD,
    )
    requirements = (
        [requirement]
        if requirement_type is RequirementType.CORE
        else [requirement, core]
    )
    matches = [
        RequirementMatch(
            match_id=f"match-{item.requirement_id}",
            requirement_id=item.requirement_id,
            matched_evidence=[],
            coverage=MatchCoverage.NONE,
            evidence_status=EvidenceStatus.MISSING,
            ability_status=AbilityStatus.UNKNOWN,
        )
        for item in requirements
    ]
    resume = ResumeProfile(
        resume_version_id="resume-1",
        candidate_profile=CandidateProfile(
            years_of_full_time_experience=Decimal("1")
        ),
        evidence_ids=[],
        parse_completeness=ParseCompleteness.COMPLETE,
    )
    job = JobProfile(
        jd_snapshot_id="jd-1",
        job_title="Synthetic Role",
        job_family=JobFamily.OTHER,
        knowledge_coverage=KnowledgeCoverage.BASE_ONLY,
        requirement_ids=[item.requirement_id for item in requirements],
    )
    return resume, job, requirements, matches


def test_zero_questions_builds_formal_b2_result() -> None:
    resume, job, requirements, matches = _ready_case()
    result = start_clarification_flow(
        analysis_id="analysis-1",
        resume_profile=resume,
        job_profile=job,
        requirements=requirements,
        matches=matches,
        evidence=[],
        seniority_facts=SeniorityFacts(explicit_entry_scope=True),
    )

    assert result.questions == ()
    assert result.analysis_result is not None
    assert result.analysis_readiness is AnalysisReadiness.READY_WITH_GAPS


def test_required_hard_question_prevents_formal_core_until_answered() -> None:
    resume, job, requirements, matches = _ready_case(RequirementType.HARD)
    result = start_clarification_flow(
        analysis_id="analysis-1",
        resume_profile=resume,
        job_profile=job,
        requirements=requirements,
        matches=matches,
        evidence=[],
        seniority_facts=SeniorityFacts(explicit_entry_scope=True),
    )

    assert len(result.questions) == 1
    assert result.questions[0].required is True
    assert result.analysis_result is None
    assert result.analysis_readiness is AnalysisReadiness.CLARIFICATION_REQUIRED


def test_optional_material_question_produces_clarification_recommended() -> None:
    resume, job, requirements, matches = _ready_case()
    fact = UnresolvedClarificationFact(
        fact_id="confidence-fact",
        analysis_id="analysis-1",
        question_type=ClarificationQuestionType.CONFIDENCE,
        target_object_ids=["req-1"],
        target_field="verification_scope",
        reason_code="CONFIDENCE_MATERIAL",
        required=False,
        possible_impact=[ClarificationCoreImpact.CONFIDENCE],
        answer_schema=ClarificationAnswerSchema(
            answer_type=ClarificationAnswerType.BOOLEAN
        ),
        source_requirement_ids=["req-1"],
        source_fact_present=True,
        answer_can_change_core_result=True,
    )
    result = start_clarification_flow(
        analysis_id="analysis-1",
        resume_profile=resume,
        job_profile=job,
        requirements=requirements,
        matches=matches,
        evidence=[],
        seniority_facts=SeniorityFacts(explicit_entry_scope=True),
        unresolved_facts=[fact],
    )

    assert len(result.questions) == 1
    assert result.questions[0].required is False
    assert result.analysis_result is not None
    assert result.analysis_readiness is AnalysisReadiness.CLARIFICATION_RECOMMENDED
