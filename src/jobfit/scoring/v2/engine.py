"""R36-R40 pure AnalysisCore assembly for the side-by-side v2 engine."""

from collections.abc import Sequence
from dataclasses import dataclass

from jobfit.models.v2 import (
    AbilityStatus,
    AnalysisCore,
    Evidence,
    EvidenceStatus,
    JobProfile,
    Requirement,
    RequirementMatch,
    RequirementSource,
    RequirementType,
    ResumeProfile,
    VersionManifest,
)
from jobfit.scoring.v2.decision import (
    ClarificationCandidate,
    CriticalDecision,
    HardDecision,
    SeniorityFacts,
    evaluate_confidence,
    evaluate_critical,
    evaluate_hard,
    evaluate_readiness,
    evaluate_recommendation,
    evaluate_seniority,
    select_clarifications,
    should_force_continue,
)
from jobfit.scoring.v2.errors import DecisionInputError, DecisionNotFinalizableError
from jobfit.scoring.v2.score import compute_scores

SCORING_RULE_VERSION = "1.0.0"
ANALYSIS_ENGINE_VERSION = "1.0.0"
CALIBRATION_STATUS = "FROZEN_FOR_IMPLEMENTATION"


@dataclass(frozen=True)
class AnalysisCoreResult:
    analysis_core: AnalysisCore
    computed_matches: tuple[RequirementMatch, ...]
    hard_decision: HardDecision
    critical_decision: CriticalDecision
    selected_clarifications: tuple[ClarificationCandidate, ...]


class DeterministicDecisionEngine:
    """Pure side-by-side v2 engine; it has no production workflow integration."""

    def build_analysis_core(
        self,
        *,
        analysis_id: str,
        resume_profile: ResumeProfile,
        job_profile: JobProfile,
        requirements: Sequence[Requirement],
        matches: Sequence[RequirementMatch],
        evidence: Sequence[Evidence],
        seniority_facts: SeniorityFacts,
        clarification_candidates: Sequence[ClarificationCandidate] = (),
        explicitly_skipped_required_clarification: bool = False,
        answered_unknown: bool = False,
        technical_failure: bool = False,
        role_scope_valid: bool = True,
    ) -> AnalysisCoreResult:
        if technical_failure:
            raise DecisionNotFinalizableError(
                "A technical failure cannot be converted into forced continuation."
            )
        _validate_identity_inputs(resume_profile, job_profile, requirements)
        evidence_by_id = _evidence_map(evidence)
        selected_clarifications = select_clarifications(clarification_candidates)
        hard = evaluate_hard(requirements, matches)
        critical = evaluate_critical(requirements, matches, evidence_by_id)
        scorable_conflicts = sum(
            1
            for requirement, match in _requirements_and_matches(requirements, matches)
            if requirement.requirement_type
            in {RequirementType.CORE, RequirementType.SUPPORTING}
            and match.evidence_status is EvidenceStatus.CONFLICT
        )
        seniority_unknown = (
            seniority_facts.required_years is not None
            and resume_profile.candidate_profile.years_of_full_time_experience is None
        )
        required_count = (
            sum(1 for item in selected_clarifications if item.required)
            + len(hard.pending_ids)
            + len(critical.pending_ids)
            + scorable_conflicts
            + int(seniority_unknown)
            + int(not role_scope_valid)
        )
        forced_continue = should_force_continue(
            required_question_count=required_count,
            explicitly_skipped=explicitly_skipped_required_clarification,
            answered_unknown=answered_unknown,
            technical_failure=technical_failure,
        )
        score = compute_scores(
            requirements,
            matches,
            evidence_by_id,
            forced_continue=forced_continue,
        )
        seniority = evaluate_seniority(
            resume_profile.candidate_profile,
            seniority_facts,
            forced_continue=forced_continue,
        )
        clarification_required = required_count > 0
        clarification_recommended = any(
            not item.required for item in selected_clarifications
        )
        if clarification_required and not forced_continue:
            raise DecisionNotFinalizableError(
                "Required clarification prevents a formal AnalysisCore decision."
            )
        core_requirement_ids = {
            item.requirement_id
            for item in requirements
            if item.requirement_type is RequirementType.CORE
            and item.source is RequirementSource.JD
        }
        core_matches = [
            item
            for item in score.computed_matches
            if item.requirement_id in core_requirement_ids
        ]
        confidence = evaluate_confidence(
            resume_profile,
            core_matches,
            hard_pending_ids=hard.pending_ids,
            seniority=seniority,
            clarification_required=clarification_required and not forced_continue,
            clarification_recommended=clarification_recommended,
            forced_continue=forced_continue,
            role_scope_valid=role_scope_valid,
        )
        has_gap = bool(critical.gap_ids) or any(
            item.evidence_status in {EvidenceStatus.MISSING, EvidenceStatus.WEAK}
            or item.ability_status is AbilityStatus.CONFIRMED_GAP
            for item in core_matches
        )
        readiness = evaluate_readiness(
            clarification_required=clarification_required,
            clarification_recommended=clarification_recommended,
            has_evidence_or_confirmed_gap=has_gap,
            eligibility=hard.eligibility_status,
            confidence=confidence,
            forced_continue=forced_continue,
        )
        recommendation = evaluate_recommendation(
            score.final_fit_score,
            seniority=seniority,
            eligibility=hard.eligibility_status,
            readiness=readiness,
            critical_gap_count=len(critical.gap_ids),
            confidence=confidence,
            forced_continue=forced_continue,
        )
        core = AnalysisCore(
            analysis_id=analysis_id,
            resume_version_id=resume_profile.resume_version_id,
            jd_snapshot_id=job_profile.jd_snapshot_id,
            analysis_readiness=readiness,
            eligibility_status=hard.eligibility_status,
            seniority_alignment=seniority,
            base_fit_score=score.base_fit_score,
            preferred_bonus=score.preferred_bonus,
            final_fit_score=score.final_fit_score,
            critical_gap_requirement_ids=list(critical.gap_ids),
            confidence=confidence,
            recommendation=recommendation.recommendation,
            recommendation_reason_codes=list(recommendation.reason_codes),
            hard_blocker_ids=list(hard.blocker_ids),
            hard_pending_ids=list(hard.pending_ids),
            forced_continue=forced_continue,
        )
        return AnalysisCoreResult(
            analysis_core=core,
            computed_matches=score.computed_matches,
            hard_decision=hard,
            critical_decision=critical,
            selected_clarifications=selected_clarifications,
        )


def build_v2_version_manifest(
    *,
    software_version: str,
    prompt_pack_version: str,
    schema_version: str,
    knowledge_version: str,
    business_test_set_version: str,
    golden_set_version: str,
) -> VersionManifest:
    return VersionManifest(
        software_version=software_version,
        prompt_pack_version=prompt_pack_version,
        schema_version=schema_version,
        scoring_rule_version=SCORING_RULE_VERSION,
        knowledge_version=knowledge_version,
        analysis_engine_version=ANALYSIS_ENGINE_VERSION,
        business_test_set_version=business_test_set_version,
        golden_set_version=golden_set_version,
    )


def _validate_identity_inputs(
    resume_profile: ResumeProfile,
    job_profile: JobProfile,
    requirements: Sequence[Requirement],
) -> None:
    requirement_ids = [item.requirement_id for item in requirements]
    if len(requirement_ids) != len(set(requirement_ids)):
        raise DecisionInputError("Requirement IDs must be unique.")
    if requirement_ids != list(job_profile.requirement_ids):
        raise DecisionInputError(
            "JobProfile requirement order must equal the decision requirement order."
        )
    for requirement in requirements:
        if (
            requirement.source is RequirementSource.JD
            and requirement.jd_snapshot_id != job_profile.jd_snapshot_id
        ):
            raise DecisionInputError(
                f"Requirement {requirement.requirement_id!r} belongs to another JD."
            )
    if not resume_profile.resume_version_id:
        raise DecisionInputError("Resume version identity is required.")


def _evidence_map(evidence: Sequence[Evidence]) -> dict[str, Evidence]:
    result: dict[str, Evidence] = {}
    for item in evidence:
        if item.evidence_id in result:
            raise DecisionInputError(f"Duplicate evidence ID {item.evidence_id!r}.")
        result[item.evidence_id] = item
    return result


def _requirements_and_matches(
    requirements: Sequence[Requirement],
    matches: Sequence[RequirementMatch],
) -> list[tuple[Requirement, RequirementMatch]]:
    match_by_requirement = {item.requirement_id: item for item in matches}
    return [
        (requirement, match_by_requirement[requirement.requirement_id])
        for requirement in requirements
        if requirement.requirement_id in match_by_requirement
    ]
