"""Deterministic B4 clarification question construction."""

from __future__ import annotations

from collections.abc import Sequence

from jobfit.extractors.common import stable_id
from jobfit.models.v2 import (
    AbilityStatus,
    ClarificationAnswerSchema,
    ClarificationAnswerType,
    ClarificationCoreImpact,
    ClarificationQuestion,
    ClarificationQuestionType,
    Evidence,
    EvidenceStatus,
    JobProfile,
    Requirement,
    RequirementMatch,
    RequirementSource,
    RequirementType,
    ResumeProfile,
    UnresolvedClarificationFact,
)
from jobfit.scoring.v2 import (
    ClarificationCandidate,
    ClarificationImpact,
    SeniorityFacts,
    select_clarifications,
)

_PRIORITY = {
    ClarificationQuestionType.HARD_ELIGIBILITY: 1,
    ClarificationQuestionType.ROLE_SENIORITY: 2,
    ClarificationQuestionType.CRITICAL_EVIDENCE: 3,
    ClarificationQuestionType.EVIDENCE_OWNERSHIP: 3,
    ClarificationQuestionType.SCORE_BAND: 4,
    ClarificationQuestionType.CONFIDENCE: 5,
}

_B2_IMPACT = {
    ClarificationQuestionType.HARD_ELIGIBILITY: ClarificationImpact.ELIGIBILITY,
    ClarificationQuestionType.ROLE_SENIORITY: ClarificationImpact.ROLE_VALIDITY,
    ClarificationQuestionType.CRITICAL_EVIDENCE: ClarificationImpact.CRITICAL_GUARD,
    ClarificationQuestionType.EVIDENCE_OWNERSHIP: ClarificationImpact.CRITICAL_GUARD,
    ClarificationQuestionType.SCORE_BAND: ClarificationImpact.SCORE_BAND,
    ClarificationQuestionType.CONFIDENCE: ClarificationImpact.CONFIDENCE,
}


def build_clarification_questions(
    *,
    analysis_id: str,
    resume_profile: ResumeProfile,
    job_profile: JobProfile,
    requirements: Sequence[Requirement],
    matches: Sequence[RequirementMatch],
    evidence: Sequence[Evidence],
    seniority_facts: SeniorityFacts,
    unresolved_facts: Sequence[UnresolvedClarificationFact] = (),
) -> tuple[ClarificationQuestion, ...]:
    """Build at most three valuable, traceable questions in frozen priority order."""
    del evidence
    requirement_by_id = _unique_by_id(
        requirements,
        "requirement_id",
        "requirement",
    )
    match_by_requirement = _unique_by_id(
        matches,
        "requirement_id",
        "requirement match",
    )
    facts = [
        *_hard_unknown_facts(
            analysis_id,
            requirements,
            match_by_requirement,
        ),
        *_seniority_facts(
            analysis_id,
            resume_profile,
            job_profile,
            seniority_facts,
            requirements,
        ),
        *unresolved_facts,
    ]
    questions: list[ClarificationQuestion] = []
    seen_ids: set[str] = set()
    for fact in facts:
        if fact.analysis_id != analysis_id:
            raise ValueError("Unresolved fact belongs to another analysis.")
        if not fact.source_fact_present or not fact.answer_can_change_core_result:
            continue
        unknown_requirements = set(fact.source_requirement_ids) - set(
            requirement_by_id
        )
        if unknown_requirements:
            raise ValueError("Unresolved fact references an unknown requirement.")
        question = _question_from_fact(fact)
        if question.question_id not in seen_ids:
            questions.append(question)
            seen_ids.add(question.question_id)

    b2_candidates = [
        ClarificationCandidate(
            question_id=item.question_id,
            impact=_B2_IMPACT[item.question_type],
            question_type=item.question_type.value,
            question=item.prompt_text,
            requirement_id=(
                item.source_requirement_ids[0]
                if item.source_requirement_ids
                else None
            ),
            can_change_core_decision=True,
            required=item.required,
        )
        for item in questions
    ]
    selected_ids = {
        item.question_id for item in select_clarifications(b2_candidates)
    }
    selected = [item for item in questions if item.question_id in selected_ids]
    return tuple(
        sorted(
            selected,
            key=lambda item: (
                item.priority,
                item.source_requirement_ids[0]
                if item.source_requirement_ids
                else "",
                item.target_field,
                item.question_id,
            ),
        )
    )


def _hard_unknown_facts(
    analysis_id: str,
    requirements: Sequence[Requirement],
    match_by_requirement: dict[str, RequirementMatch],
) -> list[UnresolvedClarificationFact]:
    result: list[UnresolvedClarificationFact] = []
    for requirement in requirements:
        if not (
            requirement.requirement_type is RequirementType.HARD
            and requirement.source is RequirementSource.JD
        ):
            continue
        match = match_by_requirement.get(requirement.requirement_id)
        if match is None:
            raise ValueError("Every hard requirement requires one match.")
        unresolved = (
            match.ability_status in {AbilityStatus.UNKNOWN, AbilityStatus.CONFLICT}
            or match.evidence_status
            in {EvidenceStatus.MISSING, EvidenceStatus.CONFLICT}
        )
        if not unresolved:
            continue
        result.append(
            UnresolvedClarificationFact(
                fact_id=f"hard:{requirement.requirement_id}",
                analysis_id=analysis_id,
                question_type=ClarificationQuestionType.HARD_ELIGIBILITY,
                target_object_ids=[requirement.requirement_id],
                target_field="eligibility_condition",
                reason_code="ELIGIBILITY_PENDING",
                required=True,
                possible_impact=[
                    ClarificationCoreImpact.ELIGIBILITY,
                    ClarificationCoreImpact.HARD_PENDING,
                    ClarificationCoreImpact.RECOMMENDATION,
                ],
                answer_schema=ClarificationAnswerSchema(
                    answer_type=ClarificationAnswerType.BOOLEAN
                ),
                source_requirement_ids=[requirement.requirement_id],
                source_fact_present=True,
                answer_can_change_core_result=True,
                source_value=requirement.raw_text,
            )
        )
    return result


def _seniority_facts(
    analysis_id: str,
    resume_profile: ResumeProfile,
    job_profile: JobProfile,
    seniority: SeniorityFacts,
    requirements: Sequence[Requirement],
) -> list[UnresolvedClarificationFact]:
    if (
        seniority.explicit_entry_scope
        or seniority.required_years is None
        or resume_profile.candidate_profile.years_of_full_time_experience is not None
    ):
        return []
    source_ids = [
        item.requirement_id
        for item in requirements
        if item.source is RequirementSource.JD
    ]
    if not source_ids:
        return []
    return [
        UnresolvedClarificationFact(
            fact_id="seniority:years",
            analysis_id=analysis_id,
            question_type=ClarificationQuestionType.ROLE_SENIORITY,
            target_object_ids=[resume_profile.resume_version_id],
            target_field="years_of_full_time_experience",
            reason_code="SENIORITY_INPUT_UNRESOLVED",
            required=True,
            possible_impact=[
                ClarificationCoreImpact.SENIORITY,
                ClarificationCoreImpact.RECOMMENDATION,
            ],
            answer_schema=ClarificationAnswerSchema(
                answer_type=ClarificationAnswerType.NUMBER_RANGE,
                minimum=0,
                maximum=60,
            ),
            source_requirement_ids=source_ids,
            source_fact_present=bool(job_profile.seniority_signals or source_ids),
            answer_can_change_core_result=True,
        )
    ]


def _question_from_fact(fact: UnresolvedClarificationFact) -> ClarificationQuestion:
    question_id = stable_id(
        "question",
        fact.analysis_id,
        fact.question_type.value,
        fact.target_field,
        *fact.target_object_ids,
    )
    return ClarificationQuestion(
        question_id=question_id,
        analysis_id=fact.analysis_id,
        question_type=fact.question_type,
        prompt_text=_prompt_text(fact),
        target_object_ids=list(fact.target_object_ids),
        target_field=fact.target_field,
        reason_code=fact.reason_code,
        priority=_PRIORITY[fact.question_type],
        required=fact.required,
        possible_impact=list(fact.possible_impact),
        answer_schema=fact.answer_schema,
        source_requirement_ids=list(fact.source_requirement_ids),
        source_evidence_ids=list(fact.source_evidence_ids),
        why_this_question_exists=(
            "This unresolved source-backed fact can change a core analysis result."
        ),
        source_value=fact.source_value,
    )


def _prompt_text(fact: UnresolvedClarificationFact) -> str:
    if fact.question_type is ClarificationQuestionType.HARD_ELIGIBILITY:
        return "Can you confirm whether you satisfy this explicit eligibility condition?"
    if fact.question_type is ClarificationQuestionType.ROLE_SENIORITY:
        return "How many years of full-time experience can you explicitly confirm?"
    if fact.question_type is ClarificationQuestionType.EVIDENCE_OWNERSHIP:
        return "Which parts of the referenced work were you personally responsible for?"
    if fact.question_type is ClarificationQuestionType.CRITICAL_EVIDENCE:
        return "Can you clarify the existing ambiguous evidence for this requirement?"
    if fact.question_type is ClarificationQuestionType.SCORE_BAND:
        return "Can you confirm the existing unresolved fact that may change the result band?"
    return "Can you confirm the existing unresolved fact affecting analysis confidence?"


def _unique_by_id(
    items: Sequence[object],
    field_name: str,
    label: str,
) -> dict[str, object]:
    result: dict[str, object] = {}
    for item in items:
        object_id = getattr(item, field_name)
        if object_id in result:
            raise ValueError(f"Duplicate {label} identity.")
        result[object_id] = item
    return result
