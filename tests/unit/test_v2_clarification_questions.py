"""Deterministic B4 candidate detection and question selection."""

from __future__ import annotations

from decimal import Decimal

import pytest

from jobfit.clarification.v2.questions import build_clarification_questions
from jobfit.models.common import Importance
from jobfit.models.v2 import (
    AbilityStatus,
    CandidateProfile,
    ClarificationAnswerSchema,
    ClarificationCoreImpact,
    ClarificationQuestionType,
    CriticalStatus,
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


def _requirement(
    requirement_id: str,
    requirement_type: RequirementType,
) -> Requirement:
    return Requirement(
        requirement_id=requirement_id,
        jd_snapshot_id="jd-1",
        raw_requirement_ids=[f"raw-{requirement_id}"],
        raw_text=f"Explicit condition {requirement_id}",
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


def _missing_match(requirement_id: str) -> RequirementMatch:
    return RequirementMatch(
        match_id=f"match-{requirement_id}",
        requirement_id=requirement_id,
        matched_evidence=[],
        coverage=MatchCoverage.NONE,
        evidence_status=EvidenceStatus.MISSING,
        ability_status=AbilityStatus.UNKNOWN,
    )


def _profiles(requirement_ids: list[str]) -> tuple[ResumeProfile, JobProfile]:
    return (
        ResumeProfile(
            resume_version_id="resume-1",
            candidate_profile=CandidateProfile(
                years_of_full_time_experience=Decimal("1")
            ),
            evidence_ids=[],
            parse_completeness=ParseCompleteness.COMPLETE,
        ),
        JobProfile(
            jd_snapshot_id="jd-1",
            job_title="Synthetic Role",
            job_family=JobFamily.OTHER,
            knowledge_coverage=KnowledgeCoverage.BASE_ONLY,
            requirement_ids=requirement_ids,
        ),
    )


def _fact(
    fact_id: str,
    question_type: ClarificationQuestionType,
    *,
    required: bool = True,
) -> UnresolvedClarificationFact:
    impact = {
        ClarificationQuestionType.HARD_ELIGIBILITY: ClarificationCoreImpact.ELIGIBILITY,
        ClarificationQuestionType.ROLE_SENIORITY: ClarificationCoreImpact.SENIORITY,
        ClarificationQuestionType.CRITICAL_EVIDENCE: ClarificationCoreImpact.CRITICAL_STATUS,
        ClarificationQuestionType.SCORE_BAND: ClarificationCoreImpact.SCORE_BAND,
        ClarificationQuestionType.CONFIDENCE: ClarificationCoreImpact.CONFIDENCE,
        ClarificationQuestionType.EVIDENCE_OWNERSHIP: ClarificationCoreImpact.SCORE_BAND,
    }[question_type]
    return UnresolvedClarificationFact(
        fact_id=fact_id,
        analysis_id="analysis-1",
        question_type=question_type,
        target_object_ids=["req-hard"],
        target_field=fact_id,
        reason_code=f"REASON_{fact_id.upper()}",
        required=required,
        possible_impact=[impact],
        answer_schema=ClarificationAnswerSchema(answer_type="boolean"),
        source_requirement_ids=["req-hard"],
        source_fact_present=True,
        answer_can_change_core_result=True,
    )


def test_four_high_value_candidates_are_capped_at_three_in_frozen_order() -> None:
    requirement = _requirement("req-hard", RequirementType.HARD)
    resume, job = _profiles([requirement.requirement_id])
    facts = [
        _fact("confidence", ClarificationQuestionType.CONFIDENCE, required=False),
        _fact("score", ClarificationQuestionType.SCORE_BAND, required=False),
        _fact("critical", ClarificationQuestionType.CRITICAL_EVIDENCE),
        _fact("seniority", ClarificationQuestionType.ROLE_SENIORITY),
    ]

    questions = build_clarification_questions(
        analysis_id="analysis-1",
        resume_profile=resume,
        job_profile=job,
        requirements=[requirement],
        matches=[_missing_match("req-hard")],
        evidence=[],
        seniority_facts=SeniorityFacts(explicit_entry_scope=True),
        unresolved_facts=facts,
    )

    assert len(questions) == 3
    assert [item.question_type for item in questions] == [
        ClarificationQuestionType.HARD_ELIGIBILITY,
        ClarificationQuestionType.ROLE_SENIORITY,
        ClarificationQuestionType.CRITICAL_EVIDENCE,
    ]
    assert all(item.required for item in questions)


def test_low_value_confidence_never_displaces_hard_question() -> None:
    hard = _requirement("req-hard", RequirementType.HARD)
    resume, job = _profiles([hard.requirement_id])
    questions = build_clarification_questions(
        analysis_id="analysis-1",
        resume_profile=resume,
        job_profile=job,
        requirements=[hard],
        matches=[_missing_match(hard.requirement_id)],
        evidence=[],
        seniority_facts=SeniorityFacts(explicit_entry_scope=True),
        unresolved_facts=[
            _fact("confidence", ClarificationQuestionType.CONFIDENCE, required=False)
        ],
    )

    assert questions[0].question_type is ClarificationQuestionType.HARD_ELIGIBILITY
    assert questions[0].priority == 1


def test_missing_skill_is_not_turned_into_a_clarification_question() -> None:
    core = _requirement("req-skill", RequirementType.CORE)
    resume, job = _profiles([core.requirement_id])

    questions = build_clarification_questions(
        analysis_id="analysis-1",
        resume_profile=resume,
        job_profile=job,
        requirements=[core],
        matches=[_missing_match(core.requirement_id)],
        evidence=[],
        seniority_facts=SeniorityFacts(explicit_entry_scope=True),
    )

    assert questions == ()


def test_hard_unknown_generates_one_required_traceable_stable_question() -> None:
    hard = _requirement("req-hard", RequirementType.HARD)
    resume, job = _profiles([hard.requirement_id])
    kwargs = dict(
        analysis_id="analysis-1",
        resume_profile=resume,
        job_profile=job,
        requirements=[hard],
        matches=[_missing_match(hard.requirement_id)],
        evidence=[],
        seniority_facts=SeniorityFacts(explicit_entry_scope=True),
    )

    first = build_clarification_questions(**kwargs)
    second = build_clarification_questions(**kwargs)

    assert first == second
    assert len(first) == 1
    assert first[0].required is True
    assert first[0].reason_code == "ELIGIBILITY_PENDING"
    assert first[0].source_requirement_ids == [hard.requirement_id]
    assert first[0].target_object_ids == [hard.requirement_id]


def test_invalid_unresolved_fact_ownership_and_reference_fail_closed() -> None:
    hard = _requirement("req-hard", RequirementType.HARD)
    resume, job = _profiles([hard.requirement_id])
    base = _fact("confidence", ClarificationQuestionType.CONFIDENCE)
    kwargs = dict(
        analysis_id="analysis-1",
        resume_profile=resume,
        job_profile=job,
        requirements=[hard],
        matches=[_missing_match(hard.requirement_id)],
        evidence=[],
        seniority_facts=SeniorityFacts(explicit_entry_scope=True),
    )
    with pytest.raises(ValueError, match="another analysis"):
        build_clarification_questions(
            **kwargs,
            unresolved_facts=[base.model_copy(update={"analysis_id": "analysis-2"})],
        )
    with pytest.raises(ValueError, match="unknown requirement"):
        build_clarification_questions(
            **kwargs,
            unresolved_facts=[
                base.model_copy(update={"source_requirement_ids": ["unknown"]})
            ],
        )


def test_non_material_or_duplicate_fact_does_not_add_question() -> None:
    hard = _requirement("req-hard", RequirementType.HARD)
    resume, job = _profiles([hard.requirement_id])
    fact = _fact("confidence", ClarificationQuestionType.CONFIDENCE, required=False)
    questions = build_clarification_questions(
        analysis_id="analysis-1",
        resume_profile=resume,
        job_profile=job,
        requirements=[hard],
        matches=[_missing_match(hard.requirement_id)],
        evidence=[],
        seniority_facts=SeniorityFacts(explicit_entry_scope=True),
        unresolved_facts=[
            fact,
            fact,
            fact.model_copy(update={"source_fact_present": False}),
            fact.model_copy(update={"answer_can_change_core_result": False}),
        ],
    )
    assert len(questions) == 2


def test_hard_requirement_without_match_and_duplicate_requirement_fail_closed() -> None:
    hard = _requirement("req-hard", RequirementType.HARD)
    resume, job = _profiles([hard.requirement_id])
    with pytest.raises(ValueError, match="requires one match"):
        build_clarification_questions(
            analysis_id="analysis-1",
            resume_profile=resume,
            job_profile=job,
            requirements=[hard],
            matches=[],
            evidence=[],
            seniority_facts=SeniorityFacts(explicit_entry_scope=True),
        )
    with pytest.raises(ValueError, match="Duplicate requirement identity"):
        build_clarification_questions(
            analysis_id="analysis-1",
            resume_profile=resume,
            job_profile=job,
            requirements=[hard, hard],
            matches=[_missing_match(hard.requirement_id)],
            evidence=[],
            seniority_facts=SeniorityFacts(explicit_entry_scope=True),
        )
