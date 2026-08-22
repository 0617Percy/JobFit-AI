"""R21-R35 deterministic guard and decision behavior."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from jobfit.models.common import Importance
from jobfit.models.v2 import (
    AbilityStatus,
    AnalysisReadiness,
    CandidateProfile,
    Confidence,
    CriticalStatus,
    EligibilityStatus,
    Evidence,
    EvidenceLevel,
    EvidenceStatus,
    MatchCoverage,
    ParseCompleteness,
    ReasonCode,
    Recommendation,
    Relevance,
    Requirement,
    RequirementMatch,
    RequirementSource,
    RequirementType,
    ResumeProfile,
    SeniorityAlignment,
    SupportType,
)
from jobfit.scoring.v2.errors import DecisionInputError, DecisionNotFinalizableError
from jobfit.scoring.v2.evidence import compute_requirement_match


@dataclass(frozen=True)
class HardDecision:
    eligibility_status: EligibilityStatus
    blocker_ids: tuple[str, ...]
    pending_ids: tuple[str, ...]


@dataclass(frozen=True)
class CriticalDecision:
    strong_ids: tuple[str, ...]
    borderline_ids: tuple[str, ...]
    gap_ids: tuple[str, ...]
    pending_ids: tuple[str, ...]


class SeniorScopeDemand(StrEnum):
    LEADERSHIP = "leadership"
    BUDGET = "budget"
    BUSINESS_OWNER = "business_owner"


@dataclass(frozen=True)
class SeniorityFacts:
    explicit_entry_scope: bool = False
    required_years: Decimal | None = None
    senior_scope_demands: tuple[SeniorScopeDemand, ...] = ()
    supported_scope_demands: tuple[SeniorScopeDemand, ...] = ()


class ClarificationImpact(StrEnum):
    ELIGIBILITY = "eligibility"
    ROLE_VALIDITY = "role_validity"
    CRITICAL_GUARD = "critical_guard"
    SCORE_BAND = "score_band"
    CONFIDENCE = "confidence"


@dataclass(frozen=True)
class ClarificationCandidate:
    question_id: str
    impact: ClarificationImpact
    question_type: str
    question: str
    requirement_id: str | None = None
    can_change_core_decision: bool = True
    required: bool = True


@dataclass(frozen=True)
class RecommendationDecision:
    recommendation: Recommendation
    reason_codes: tuple[ReasonCode, ...]


def evaluate_hard(
    requirements: Sequence[Requirement],
    matches: Sequence[RequirementMatch],
) -> HardDecision:
    match_by_requirement = _match_map(matches)
    blocker_ids: list[str] = []
    pending_ids: list[str] = []
    for requirement in requirements:
        if not _is_explicit_jd(requirement, RequirementType.HARD):
            continue
        match = _required_match(requirement.requirement_id, match_by_requirement)
        if match.ability_status is AbilityStatus.CONFIRMED_GAP:
            blocker_ids.append(requirement.requirement_id)
        elif (
            match.ability_status in {AbilityStatus.UNKNOWN, AbilityStatus.CONFLICT}
            or match.evidence_status in {EvidenceStatus.MISSING, EvidenceStatus.CONFLICT}
        ):
            pending_ids.append(requirement.requirement_id)
    blockers = tuple(sorted(blocker_ids))
    pending = tuple(sorted(pending_ids))
    return HardDecision(
        eligibility_status=evaluate_eligibility(blockers, pending),
        blocker_ids=blockers,
        pending_ids=pending,
    )


def evaluate_critical(
    requirements: Sequence[Requirement],
    matches: Sequence[RequirementMatch],
    evidence_by_id: Mapping[str, Evidence],
) -> CriticalDecision:
    match_by_requirement = _match_map(matches)
    strong: list[str] = []
    borderline: list[str] = []
    gaps: list[str] = []
    pending: list[str] = []
    for requirement in requirements:
        if not _is_critical_core(requirement):
            continue
        match = _required_match(requirement.requirement_id, match_by_requirement)
        if match.evidence_status is EvidenceStatus.CONFLICT:
            pending.append(requirement.requirement_id)
            continue
        computation = compute_requirement_match(
            match,
            evidence_by_id,
            forced_continue=True,
        )
        if computation.selected_evidence_id is None:
            gaps.append(requirement.requirement_id)
            continue
        relation = next(
            item
            for item in match.matched_evidence
            if item.evidence_id == computation.selected_evidence_id
        )
        level = evidence_by_id[relation.evidence_id].evidence_level
        if (
            relation.support_type is SupportType.DIRECT
            and level in {EvidenceLevel.L3, EvidenceLevel.L4}
            and relation.relevance in {Relevance.MEDIUM, Relevance.HIGH}
        ):
            strong.append(requirement.requirement_id)
        elif _is_borderline_critical_relation(relation, level, match.coverage):
            borderline.append(requirement.requirement_id)
        else:
            gaps.append(requirement.requirement_id)
    return CriticalDecision(
        strong_ids=tuple(sorted(strong)),
        borderline_ids=tuple(sorted(borderline)),
        gap_ids=tuple(sorted(gaps)),
        pending_ids=tuple(sorted(pending)),
    )


def evaluate_seniority(
    candidate: CandidateProfile,
    facts: SeniorityFacts,
    *,
    forced_continue: bool = False,
) -> SeniorityAlignment:
    demands = set(facts.senior_scope_demands)
    supported = set(facts.supported_scope_demands)
    if len(demands) != len(facts.senior_scope_demands) or not supported <= demands:
        raise DecisionInputError("Seniority scope demands are inconsistent.")
    if facts.explicit_entry_scope:
        return SeniorityAlignment.ALIGNED

    years = candidate.years_of_full_time_experience
    if facts.required_years is not None and years is None:
        if forced_continue:
            return SeniorityAlignment.BORDERLINE
        raise DecisionNotFinalizableError(
            "Material seniority input requires clarification."
        )
    unsupported = demands - supported
    shortfall = (
        max(Decimal("0"), facts.required_years - years)
        if facts.required_years is not None and years is not None
        else Decimal("0")
    )
    if not unsupported and shortfall == 0:
        return SeniorityAlignment.ALIGNED
    if len(unsupported) >= 3:
        return SeniorityAlignment.MISALIGNED
    if shortfall > 0:
        if shortfall <= Decimal("2") and len(unsupported) < 2:
            return SeniorityAlignment.BORDERLINE
        return SeniorityAlignment.MISALIGNED
    if len(unsupported) == 1:
        return SeniorityAlignment.BORDERLINE
    raise DecisionNotFinalizableError(
        "Normalized seniority facts do not map to an approved state."
    )


def evaluate_eligibility(
    blocker_ids: Sequence[str],
    pending_ids: Sequence[str],
) -> EligibilityStatus:
    if blocker_ids:
        return EligibilityStatus.BLOCKED
    if pending_ids:
        return EligibilityStatus.PENDING
    return EligibilityStatus.MET


def evaluate_confidence(
    resume_profile: ResumeProfile,
    core_matches: Sequence[RequirementMatch],
    *,
    hard_pending_ids: Sequence[str] = (),
    seniority: SeniorityAlignment = SeniorityAlignment.ALIGNED,
    clarification_required: bool = False,
    clarification_recommended: bool = False,
    forced_continue: bool = False,
    role_scope_valid: bool = True,
) -> Confidence:
    every_core_unknown = bool(core_matches) and all(
        item.ability_status is AbilityStatus.UNKNOWN for item in core_matches
    )
    any_conflict = any(
        item.evidence_status is EvidenceStatus.CONFLICT for item in core_matches
    )
    if (
        resume_profile.parse_completeness is ParseCompleteness.INSUFFICIENT
        or any_conflict
        or clarification_required
        or forced_continue
        or not role_scope_valid
        or every_core_unknown
    ):
        return Confidence.LOW
    uncertain_core_count = sum(
        1
        for item in core_matches
        if item.ability_status is not AbilityStatus.CONFIRMED_GAP
        and item.evidence_status in {EvidenceStatus.MISSING, EvidenceStatus.WEAK}
    )
    if (
        resume_profile.parse_completeness is ParseCompleteness.PARTIAL
        or bool(resume_profile.ambiguity_ids)
        or bool(hard_pending_ids)
        or seniority is SeniorityAlignment.BORDERLINE
        or clarification_recommended
        or uncertain_core_count >= 2
    ):
        return Confidence.MEDIUM
    return Confidence.HIGH


def evaluate_readiness(
    *,
    clarification_required: bool,
    clarification_recommended: bool,
    has_evidence_or_confirmed_gap: bool,
    eligibility: EligibilityStatus,
    confidence: Confidence,
    forced_continue: bool,
) -> AnalysisReadiness:
    if clarification_required and not forced_continue:
        return AnalysisReadiness.CLARIFICATION_REQUIRED
    if clarification_recommended and not forced_continue:
        return AnalysisReadiness.CLARIFICATION_RECOMMENDED
    if (
        has_evidence_or_confirmed_gap
        or eligibility is EligibilityStatus.BLOCKED
        or confidence is Confidence.LOW
        or forced_continue
    ):
        return AnalysisReadiness.READY_WITH_GAPS
    return AnalysisReadiness.READY


def select_clarifications(
    candidates: Sequence[ClarificationCandidate],
) -> tuple[ClarificationCandidate, ...]:
    priorities = {
        ClarificationImpact.ELIGIBILITY: 0,
        ClarificationImpact.ROLE_VALIDITY: 1,
        ClarificationImpact.CRITICAL_GUARD: 2,
        ClarificationImpact.SCORE_BAND: 3,
        ClarificationImpact.CONFIDENCE: 4,
    }
    selected = sorted(
        (item for item in candidates if item.can_change_core_decision),
        key=lambda item: (
            priorities[item.impact],
            item.requirement_id or "",
            item.question_type,
            item.question_id,
        ),
    )
    return tuple(selected[:3])


def should_force_continue(
    *,
    required_question_count: int,
    explicitly_skipped: bool,
    answered_unknown: bool = False,
    technical_failure: bool = False,
) -> bool:
    return (
        required_question_count > 0
        and explicitly_skipped
        and not answered_unknown
        and not technical_failure
    )


def evaluate_recommendation(
    final_fit_score: Decimal,
    *,
    seniority: SeniorityAlignment,
    eligibility: EligibilityStatus,
    readiness: AnalysisReadiness,
    critical_gap_count: int,
    confidence: Confidence,
    forced_continue: bool,
) -> RecommendationDecision:
    if readiness is AnalysisReadiness.CLARIFICATION_REQUIRED:
        raise DecisionNotFinalizableError(
            "A formal recommendation requires clarification or explicit skip."
        )
    if eligibility is EligibilityStatus.PENDING and not forced_continue:
        raise DecisionNotFinalizableError(
            "Pending eligibility requires clarification before recommendation."
        )
    score_recommendation, score_reason = _score_band(final_fit_score)
    ranks = {
        Recommendation.NOT_RECOMMENDED: 0,
        Recommendation.CHALLENGE: 1,
        Recommendation.SUGGESTED: 2,
        Recommendation.PRIORITY: 3,
    }
    caps = [score_recommendation]
    reasons: list[ReasonCode] = []
    if seniority is SeniorityAlignment.MISALIGNED:
        caps.append(Recommendation.NOT_RECOMMENDED)
        reasons.append(ReasonCode.SENIORITY_MISMATCH)
    elif seniority is SeniorityAlignment.BORDERLINE:
        caps.append(Recommendation.SUGGESTED)
        reasons.append(ReasonCode.SENIORITY_BORDERLINE)

    if eligibility is EligibilityStatus.BLOCKED:
        caps.append(Recommendation.NOT_RECOMMENDED)
        reasons.append(ReasonCode.HARD_BLOCKER)
    elif eligibility is EligibilityStatus.PENDING:
        caps.append(Recommendation.CHALLENGE)
        reasons.append(ReasonCode.HARD_PENDING)

    if forced_continue:
        reasons.append(ReasonCode.FORCED_CONTINUE)
    reasons.append(score_reason)

    if critical_gap_count >= 2:
        caps.append(Recommendation.CHALLENGE)
        reasons.append(ReasonCode.CRITICAL_GAP_MULTIPLE)
    elif critical_gap_count == 1:
        caps.append(Recommendation.SUGGESTED)
        reasons.append(ReasonCode.CRITICAL_GAP_ONE)

    if confidence is Confidence.LOW:
        caps.append(Recommendation.SUGGESTED)
        reasons.append(ReasonCode.LOW_CONFIDENCE)
    if readiness is AnalysisReadiness.CLARIFICATION_RECOMMENDED:
        caps.append(Recommendation.SUGGESTED)
        if ReasonCode.CLARIFICATION_RECOMMENDED not in reasons:
            reasons.insert(
                reasons.index(score_reason),
                ReasonCode.CLARIFICATION_RECOMMENDED,
            )
    recommendation = min(caps, key=ranks.__getitem__)
    return RecommendationDecision(
        recommendation=recommendation,
        reason_codes=tuple(dict.fromkeys(reasons)),
    )


def _match_map(
    matches: Sequence[RequirementMatch],
) -> dict[str, RequirementMatch]:
    result: dict[str, RequirementMatch] = {}
    for match in matches:
        if match.requirement_id in result:
            raise DecisionInputError(
                f"Duplicate requirement match for {match.requirement_id!r}."
            )
        result[match.requirement_id] = match
    return result


def _required_match(
    requirement_id: str,
    matches: Mapping[str, RequirementMatch],
) -> RequirementMatch:
    try:
        return matches[requirement_id]
    except KeyError as exc:
        raise DecisionInputError(
            f"Requirement {requirement_id!r} has no match."
        ) from exc


def _is_explicit_jd(
    requirement: Requirement,
    requirement_type: RequirementType,
) -> bool:
    return (
        requirement.source is RequirementSource.JD
        and requirement.requirement_type is requirement_type
    )


def _is_critical_core(requirement: Requirement) -> bool:
    return (
        _is_explicit_jd(requirement, RequirementType.CORE)
        and requirement.importance is Importance.CRITICAL
        and requirement.critical_status is CriticalStatus.CONFIRMED
    )


def _is_borderline_critical_relation(
    relation: object,
    level: EvidenceLevel,
    coverage: MatchCoverage,
) -> bool:
    if not hasattr(relation, "support_type") or not hasattr(relation, "relevance"):
        return False
    if relation.support_type is SupportType.DIRECT:
        return level is EvidenceLevel.L2 or (
            level in {EvidenceLevel.L3, EvidenceLevel.L4}
            and relation.relevance is Relevance.LOW
        )
    return (
        relation.support_type is SupportType.TRANSFERABLE
        and level in {EvidenceLevel.L3, EvidenceLevel.L4}
        and relation.relevance in {Relevance.MEDIUM, Relevance.HIGH}
        and coverage in {MatchCoverage.SUBSTANTIAL, MatchCoverage.FULL}
    )


def _score_band(score: Decimal) -> tuple[Recommendation, ReasonCode]:
    if score >= Decimal("85.00"):
        return Recommendation.PRIORITY, ReasonCode.HIGH_FIT_SCORE
    if score >= Decimal("70.00"):
        return Recommendation.SUGGESTED, ReasonCode.MEDIUM_FIT_SCORE
    if score >= Decimal("55.00"):
        return Recommendation.CHALLENGE, ReasonCode.LOW_FIT_SCORE
    return Recommendation.NOT_RECOMMENDED, ReasonCode.LOW_FIT_SCORE
