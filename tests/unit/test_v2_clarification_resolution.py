"""B4 hard-pending clarification resolution behavior."""

from decimal import Decimal

from jobfit.clarification.v2.questions import build_clarification_questions
from jobfit.clarification.v2.resolution import resolve_clarification
from jobfit.models.common import Importance
from jobfit.models.v2 import (
    AbilityStatus,
    AnalysisReadiness,
    CandidateProfile,
    ClarificationAnswer,
    ClarificationAnswerStatus,
    ClarificationResolutionStatus,
    EligibilityStatus,
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
)
from jobfit.scoring.v2 import SeniorityFacts


def _case() -> tuple[
    ResumeProfile,
    JobProfile,
    list[Requirement],
    list[RequirementMatch],
]:
    requirement = Requirement(
        requirement_id="req-hard",
        jd_snapshot_id="jd-1",
        raw_requirement_ids=["raw-hard"],
        raw_text="Explicit work authorization condition",
        normalized_capability="work authorization",
        requirement_type=RequirementType.HARD,
        importance=Importance.CRITICAL,
        explicitness=RequirementExplicitness.EXPLICIT,
        source=RequirementSource.JD,
    )
    match = RequirementMatch(
        match_id="match-hard",
        requirement_id=requirement.requirement_id,
        matched_evidence=[],
        coverage=MatchCoverage.NONE,
        evidence_status=EvidenceStatus.MISSING,
        ability_status=AbilityStatus.UNKNOWN,
    )
    core = Requirement(
        requirement_id="req-core",
        jd_snapshot_id="jd-1",
        raw_requirement_ids=["raw-core"],
        raw_text="Build a synthetic application",
        normalized_capability="application delivery",
        requirement_type=RequirementType.CORE,
        importance=Importance.HIGH,
        explicitness=RequirementExplicitness.EXPLICIT,
        source=RequirementSource.JD,
    )
    core_match = RequirementMatch(
        match_id="match-core",
        requirement_id=core.requirement_id,
        matched_evidence=[],
        coverage=MatchCoverage.NONE,
        evidence_status=EvidenceStatus.MISSING,
        ability_status=AbilityStatus.UNKNOWN,
    )
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
        requirement_ids=[requirement.requirement_id, core.requirement_id],
    )
    return resume, job, [requirement, core], [match, core_match]


def _question():
    resume, job, requirements, matches = _case()
    return build_clarification_questions(
        analysis_id="analysis-1",
        resume_profile=resume,
        job_profile=job,
        requirements=requirements,
        matches=matches,
        evidence=[],
        seniority_facts=SeniorityFacts(explicit_entry_scope=True),
    )[0]


def _resolve(status: ClarificationAnswerStatus, value=None, **kwargs):
    resume, job, requirements, matches = _case()
    question = _question()
    return resolve_clarification(
        analysis_id="analysis-1",
        resume_profile=resume,
        job_profile=job,
        requirements=requirements,
        matches=matches,
        evidence=[],
        seniority_facts=SeniorityFacts(explicit_entry_scope=True),
        question=question,
        answer=ClarificationAnswer(
            question_id=question.question_id,
            analysis_id="analysis-1",
            status=status,
            value=value,
        ),
        **kwargs,
    )


def test_hard_yes_moves_pending_to_met_without_mutating_jd_requirement() -> None:
    original_requirement = _case()[2][0]
    result = _resolve(ClarificationAnswerStatus.ANSWERED, True)

    assert result.analysis_result.analysis_core.eligibility_status is EligibilityStatus.MET
    assert result.analysis_result.analysis_core.hard_pending_ids == []
    assert result.updated_requirements[0] == original_requirement
    assert result.updated_matches[0].ability_status is AbilityStatus.CONFIRMED
    assert result.updated_evidence[0].source_record_id == result.clarification.clarification_id


def test_hard_no_moves_to_blocked_and_keeps_base_score_invariant() -> None:
    yes = _resolve(ClarificationAnswerStatus.ANSWERED, True)
    no = _resolve(ClarificationAnswerStatus.ANSWERED, False)

    assert no.analysis_result.analysis_core.eligibility_status is EligibilityStatus.BLOCKED
    assert no.updated_matches[0].ability_status is AbilityStatus.CONFIRMED_GAP
    assert (
        no.analysis_result.analysis_core.base_fit_score
        == yes.analysis_result.analysis_core.base_fit_score
    )


def test_hard_skip_forces_continue_without_creating_a_confirmed_gap() -> None:
    result = _resolve(ClarificationAnswerStatus.SKIPPED)

    assert result.resolution.status is ClarificationResolutionStatus.FORCED_CONTINUE
    assert result.resolution.forced_continue is True
    assert result.analysis_result.analysis_core.forced_continue is True
    assert result.updated_matches[0].ability_status is AbilityStatus.UNKNOWN
    assert result.updated_evidence == ()


def test_unable_to_confirm_stays_pending_and_does_not_force_continue() -> None:
    result = _resolve(ClarificationAnswerStatus.UNABLE_TO_CONFIRM)

    assert result.analysis_result is None
    assert result.resolution.status is ClarificationResolutionStatus.PENDING
    assert result.resolution.analysis_readiness is AnalysisReadiness.CLARIFICATION_REQUIRED
    assert result.resolution.forced_continue is False
    assert result.updated_matches[0].ability_status is AbilityStatus.UNKNOWN


def test_contradictory_reanswer_enters_review_required() -> None:
    first = _resolve(ClarificationAnswerStatus.ANSWERED, True)
    second = _resolve(
        ClarificationAnswerStatus.ANSWERED,
        False,
        prior_clarifications=[first.clarification],
    )

    assert second.analysis_result is None
    assert second.resolution.status is ClarificationResolutionStatus.REVIEW_REQUIRED
    assert second.resolution.analysis_readiness is AnalysisReadiness.REVIEW_REQUIRED
    assert len(second.conflicts) == 1
    assert second.updated_matches[0].ability_status is AbilityStatus.UNKNOWN
