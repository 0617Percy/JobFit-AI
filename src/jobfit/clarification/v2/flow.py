"""B4 readiness gate and frozen B2 decision-engine orchestration."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from jobfit.clarification.v2.questions import build_clarification_questions
from jobfit.clarification.v2.validation import validate_active_questions
from jobfit.models.v2 import (
    AnalysisReadiness,
    ClarificationQuestion,
    ClarificationQuestionType,
    Evidence,
    JobProfile,
    Requirement,
    RequirementMatch,
    ResumeProfile,
    UnresolvedClarificationFact,
)
from jobfit.scoring.v2 import (
    AnalysisCoreResult,
    ClarificationCandidate,
    ClarificationImpact,
    DeterministicDecisionEngine,
    SeniorityFacts,
)

_IMPACT = {
    ClarificationQuestionType.HARD_ELIGIBILITY: ClarificationImpact.ELIGIBILITY,
    ClarificationQuestionType.ROLE_SENIORITY: ClarificationImpact.ROLE_VALIDITY,
    ClarificationQuestionType.CRITICAL_EVIDENCE: ClarificationImpact.CRITICAL_GUARD,
    ClarificationQuestionType.EVIDENCE_OWNERSHIP: ClarificationImpact.CRITICAL_GUARD,
    ClarificationQuestionType.SCORE_BAND: ClarificationImpact.SCORE_BAND,
    ClarificationQuestionType.CONFIDENCE: ClarificationImpact.CONFIDENCE,
}


@dataclass(frozen=True)
class ClarificationFlowStart:
    analysis_id: str
    questions: tuple[ClarificationQuestion, ...]
    analysis_readiness: AnalysisReadiness
    analysis_result: AnalysisCoreResult | None


def start_clarification_flow(
    *,
    analysis_id: str,
    resume_profile: ResumeProfile,
    job_profile: JobProfile,
    requirements: Sequence[Requirement],
    matches: Sequence[RequirementMatch],
    evidence: Sequence[Evidence],
    seniority_facts: SeniorityFacts,
    unresolved_facts: Sequence[UnresolvedClarificationFact] = (),
    role_scope_valid: bool = True,
) -> ClarificationFlowStart:
    """Select questions once and either pause or produce the frozen B2 result."""
    questions = build_clarification_questions(
        analysis_id=analysis_id,
        resume_profile=resume_profile,
        job_profile=job_profile,
        requirements=requirements,
        matches=matches,
        evidence=evidence,
        seniority_facts=seniority_facts,
        unresolved_facts=unresolved_facts,
    )
    validate_active_questions(
        questions,
        analysis_id=analysis_id,
        requirements=requirements,
        evidence=evidence,
        resume_profile=resume_profile,
        job_profile=job_profile,
    )
    if any(item.required for item in questions):
        return ClarificationFlowStart(
            analysis_id=analysis_id,
            questions=questions,
            analysis_readiness=AnalysisReadiness.CLARIFICATION_REQUIRED,
            analysis_result=None,
        )

    candidates = tuple(_as_b2_candidate(item) for item in questions)
    result = DeterministicDecisionEngine().build_analysis_core(
        analysis_id=analysis_id,
        resume_profile=resume_profile,
        job_profile=job_profile,
        requirements=requirements,
        matches=matches,
        evidence=evidence,
        seniority_facts=seniority_facts,
        clarification_candidates=candidates,
        role_scope_valid=role_scope_valid,
    )
    return ClarificationFlowStart(
        analysis_id=analysis_id,
        questions=questions,
        analysis_readiness=result.analysis_core.analysis_readiness,
        analysis_result=result,
    )


def _as_b2_candidate(question: ClarificationQuestion) -> ClarificationCandidate:
    return ClarificationCandidate(
        question_id=question.question_id,
        impact=_IMPACT[question.question_type],
        question_type=question.question_type.value,
        question=question.prompt_text,
        requirement_id=(
            question.source_requirement_ids[0]
            if question.source_requirement_ids
            else None
        ),
        can_change_core_decision=True,
        required=question.required,
    )
