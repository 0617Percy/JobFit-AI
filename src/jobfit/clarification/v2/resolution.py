"""Deterministic B4 clarification resolution."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass

from jobfit.clarification.v2.recompute import apply_bounded_clarification_update
from jobfit.clarification.v2.validation import (
    ClarificationValidationError,
    validate_active_questions,
    validate_clarification_answer,
)
from jobfit.extractors.common import stable_id
from jobfit.models.v2 import (
    AbilityStatus,
    AnalysisReadiness,
    ClarificationAnswer,
    ClarificationAnswerStatus,
    ClarificationConflict,
    ClarificationConflictType,
    ClarificationQuestion,
    ClarificationQuestionType,
    ClarificationResolution,
    ClarificationResolutionStatus,
    ClarityLevel,
    Evidence,
    EvidenceLevel,
    EvidenceSourceOrigin,
    EvidenceStatus,
    JobProfile,
    MatchCoverage,
    MatchedEvidence,
    PersonalContribution,
    Relevance,
    Requirement,
    RequirementMatch,
    ResumeProfile,
    SupportType,
    UserClarification,
)
from jobfit.scoring.v2 import (
    AnalysisCoreResult,
    DeterministicDecisionEngine,
    SeniorityFacts,
)


@dataclass(frozen=True)
class ClarificationOutcome:
    updated_resume_profile: ResumeProfile
    updated_job_profile: JobProfile
    updated_requirements: tuple[Requirement, ...]
    updated_matches: tuple[RequirementMatch, ...]
    updated_evidence: tuple[Evidence, ...]
    clarification: UserClarification
    resolution: ClarificationResolution
    conflicts: tuple[ClarificationConflict, ...]
    analysis_result: AnalysisCoreResult | None


def resolve_clarification(
    *,
    analysis_id: str,
    resume_profile: ResumeProfile,
    job_profile: JobProfile,
    requirements: Sequence[Requirement],
    matches: Sequence[RequirementMatch],
    evidence: Sequence[Evidence],
    seniority_facts: SeniorityFacts,
    question: ClarificationQuestion,
    answer: ClarificationAnswer,
    prior_clarifications: Sequence[UserClarification] = (),
) -> ClarificationOutcome:
    validate_active_questions(
        [question],
        analysis_id=analysis_id,
        requirements=requirements,
        evidence=evidence,
        resume_profile=resume_profile,
        job_profile=job_profile,
    )
    validate_clarification_answer(answer, question)
    clarification = _create_clarification(question, answer)
    conflicts = _find_conflicts(clarification, prior_clarifications)
    if conflicts:
        resolution = ClarificationResolution(
            analysis_id=analysis_id,
            status=ClarificationResolutionStatus.REVIEW_REQUIRED,
            analysis_readiness=AnalysisReadiness.REVIEW_REQUIRED,
            clarification_ids=[clarification.clarification_id],
            conflict_ids=[item.conflict_id for item in conflicts],
        )
        return _outcome(
            resume_profile,
            job_profile,
            requirements,
            matches,
            evidence,
            clarification,
            resolution,
            conflicts,
        )

    if answer.raw_text and _contains_embedded_instruction(answer.raw_text):
        safe_clarification = clarification.model_copy(
            update={
                "answer": None,
                "answer_status": ClarificationAnswerStatus.UNABLE_TO_CONFIRM,
                "normalized_fact": None,
                "warnings": ["EMBEDDED_INSTRUCTION_IGNORED"],
            }
        )
        resolution = ClarificationResolution(
            analysis_id=analysis_id,
            status=ClarificationResolutionStatus.PENDING,
            analysis_readiness=AnalysisReadiness.CLARIFICATION_REQUIRED,
            clarification_ids=[safe_clarification.clarification_id],
            warnings=["EMBEDDED_INSTRUCTION_IGNORED"],
        )
        return _outcome(
            resume_profile,
            job_profile,
            requirements,
            matches,
            evidence,
            safe_clarification,
            resolution,
        )

    if answer.status is ClarificationAnswerStatus.UNABLE_TO_CONFIRM:
        resolution = ClarificationResolution(
            analysis_id=analysis_id,
            status=ClarificationResolutionStatus.PENDING,
            analysis_readiness=AnalysisReadiness.CLARIFICATION_REQUIRED,
            clarification_ids=[clarification.clarification_id],
        )
        return _outcome(
            resume_profile,
            job_profile,
            requirements,
            matches,
            evidence,
            clarification,
            resolution,
        )

    updated_resume = resume_profile
    updated_matches = tuple(matches)
    updated_evidence = tuple(evidence)
    affected_requirements: list[str] = []
    affected_evidence: list[str] = []
    if answer.status is ClarificationAnswerStatus.ANSWERED:
        if question.question_type is ClarificationQuestionType.HARD_ELIGIBILITY:
            updated_matches, updated_evidence, clarification = _apply_hard_answer(
                question,
                answer,
                clarification,
                matches,
                evidence,
            )
            affected_requirements = list(question.source_requirement_ids)
        else:
            recompute = apply_bounded_clarification_update(
                resume_profile=resume_profile,
                matches=matches,
                evidence=evidence,
                question=question,
                answer=answer,
                clarification_id=clarification.clarification_id,
            )
            updated_resume = recompute.resume_profile
            updated_matches = recompute.matches
            updated_evidence = recompute.evidence
            affected_requirements = list(recompute.affected_requirement_ids)
            affected_evidence = list(recompute.affected_evidence_ids)
            clarification = clarification.model_copy(
                update={
                    "affects_recommendation": True,
                    "affected_requirement_ids": affected_requirements,
                    "affected_evidence_ids": affected_evidence,
                    "normalized_fact": {
                        question.target_field: answer.value,
                    },
                }
            )

    skipped = answer.status is ClarificationAnswerStatus.SKIPPED
    analysis_result = DeterministicDecisionEngine().build_analysis_core(
        analysis_id=analysis_id,
        resume_profile=updated_resume,
        job_profile=job_profile,
        requirements=requirements,
        matches=updated_matches,
        evidence=updated_evidence,
        seniority_facts=seniority_facts,
        explicitly_skipped_required_clarification=skipped and question.required,
    )
    resolution = ClarificationResolution(
        analysis_id=analysis_id,
        status=(
            ClarificationResolutionStatus.FORCED_CONTINUE
            if skipped and question.required
            else ClarificationResolutionStatus.RESOLVED
        ),
        analysis_readiness=analysis_result.analysis_core.analysis_readiness,
        forced_continue=skipped and question.required,
        clarification_ids=[clarification.clarification_id],
        affected_requirement_ids=affected_requirements,
        affected_evidence_ids=affected_evidence,
    )
    return _outcome(
        updated_resume,
        job_profile,
        requirements,
        updated_matches,
        updated_evidence,
        clarification,
        resolution,
        analysis_result=analysis_result,
    )


def _contains_embedded_instruction(text: str) -> bool:
    normalized = " ".join(text.casefold().split())
    markers = (
        "ignore all rules",
        "ignore previous",
        "system prompt",
        "give me priority",
        "override recommendation",
        "忽略所有规则",
        "给我priority",
    )
    return any(marker in normalized for marker in markers)


def _create_clarification(
    question: ClarificationQuestion,
    answer: ClarificationAnswer,
) -> UserClarification:
    clarification_id = stable_id(
        "clarification",
        question.analysis_id,
        question.question_id,
        answer.answer_sequence,
    )
    answer_text = (
        json.dumps(answer.value, ensure_ascii=False, sort_keys=True)
        if answer.status is ClarificationAnswerStatus.ANSWERED
        else None
    )
    return UserClarification(
        clarification_id=clarification_id,
        analysis_id=question.analysis_id,
        question_type=question.question_type.value,
        question=question.prompt_text,
        answer=answer_text,
        answer_status=answer.status,
        origin_question_id=question.question_id,
        source_identity=clarification_id,
        answer_sequence=answer.answer_sequence,
        target_object_ids=list(question.target_object_ids),
        normalized_fact=answer.normalized_fact,
    )


def _find_conflicts(
    clarification: UserClarification,
    prior: Sequence[UserClarification],
) -> tuple[ClarificationConflict, ...]:
    conflicts: list[ClarificationConflict] = []
    for item in prior:
        if item.analysis_id != clarification.analysis_id:
            raise ClarificationValidationError(
                "Prior clarification belongs to another analysis."
            )
        if (
            item.origin_question_id == clarification.origin_question_id
            and item.answer_status is ClarificationAnswerStatus.ANSWERED
            and clarification.answer_status is ClarificationAnswerStatus.ANSWERED
            and item.answer != clarification.answer
        ):
            conflicts.append(
                ClarificationConflict(
                    conflict_id=stable_id(
                        "conflict",
                        clarification.analysis_id,
                        clarification.origin_question_id,
                        item.clarification_id,
                        clarification.clarification_id,
                    ),
                    analysis_id=clarification.analysis_id,
                    question_id=clarification.origin_question_id or "unknown",
                    conflict_type=ClarificationConflictType.CONTRADICTORY_REANSWER,
                    target_object_ids=list(clarification.target_object_ids),
                    message="Contradictory answers require explicit review.",
                )
            )
    return tuple(conflicts)


def _apply_hard_answer(
    question: ClarificationQuestion,
    answer: ClarificationAnswer,
    clarification: UserClarification,
    matches: Sequence[RequirementMatch],
    evidence: Sequence[Evidence],
) -> tuple[tuple[RequirementMatch, ...], tuple[Evidence, ...], UserClarification]:
    requirement_id = question.source_requirement_ids[0]
    target_matches = [item for item in matches if item.requirement_id == requirement_id]
    if len(target_matches) != 1:
        raise ClarificationValidationError(
            "Hard answer must target exactly one hard requirement match."
        )
    updated = list(matches)
    index = updated.index(target_matches[0])
    if answer.value is False:
        updated[index] = target_matches[0].model_copy(
            update={
                "matched_evidence": [],
                "coverage": MatchCoverage.NONE,
                "evidence_status": EvidenceStatus.MISSING,
                "ability_status": AbilityStatus.CONFIRMED_GAP,
                "ability_confirmation_id": clarification.clarification_id,
                "best_evidence_level": None,
                "match_score_component": None,
            }
        )
        clarification = clarification.model_copy(
            update={
                "affects_recommendation": True,
                "affected_requirement_ids": [requirement_id],
                "normalized_fact": {"eligibility_confirmed": False},
            }
        )
        return tuple(updated), tuple(evidence), clarification

    evidence_id = stable_id("evidence", clarification.clarification_id)
    created = Evidence(
        evidence_id=evidence_id,
        source_origin=EvidenceSourceOrigin.USER_CLARIFICATION,
        source_type="eligibility_confirmation",
        source_record_id=clarification.clarification_id,
        source_text="User explicitly confirmed the eligibility condition.",
        normalized_capabilities=[requirement_id],
        personal_contribution=PersonalContribution.NOT_APPLICABLE,
        task_clarity=ClarityLevel.UNKNOWN,
        method_tool_clarity=ClarityLevel.UNKNOWN,
        result_clarity=ClarityLevel.UNKNOWN,
        verification_strength=ClarityLevel.UNKNOWN,
        practical_use=ClarityLevel.UNKNOWN,
        evidence_level=EvidenceLevel.L1,
    )
    updated[index] = target_matches[0].model_copy(
        update={
            "matched_evidence": [
                MatchedEvidence(
                    evidence_id=evidence_id,
                    relevance=Relevance.HIGH,
                    support_type=SupportType.DIRECT,
                )
            ],
            "coverage": MatchCoverage.FULL,
            "evidence_status": EvidenceStatus.PRESENT,
            "ability_status": AbilityStatus.CONFIRMED,
            "ability_confirmation_id": clarification.clarification_id,
        }
    )
    clarification = clarification.model_copy(
        update={
            "creates_evidence": True,
            "affects_recommendation": True,
            "affected_requirement_ids": [requirement_id],
            "created_evidence_ids": [evidence_id],
            "normalized_fact": {"eligibility_confirmed": True},
        }
    )
    return tuple(updated), (*evidence, created), clarification


def _outcome(
    resume_profile: ResumeProfile,
    job_profile: JobProfile,
    requirements: Sequence[Requirement],
    matches: Sequence[RequirementMatch],
    evidence: Sequence[Evidence],
    clarification: UserClarification,
    resolution: ClarificationResolution,
    conflicts: Sequence[ClarificationConflict] = (),
    *,
    analysis_result: AnalysisCoreResult | None = None,
) -> ClarificationOutcome:
    return ClarificationOutcome(
        updated_resume_profile=resume_profile,
        updated_job_profile=job_profile,
        updated_requirements=tuple(requirements),
        updated_matches=tuple(matches),
        updated_evidence=tuple(evidence),
        clarification=clarification,
        resolution=resolution,
        conflicts=tuple(conflicts),
        analysis_result=analysis_result,
    )
