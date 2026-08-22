"""R01-R07 deterministic evidence and match behavior."""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from jobfit.models.v2 import (
    AbilityStatus,
    ClarityLevel,
    Evidence,
    EvidenceLevel,
    EvidenceStatus,
    MatchCoverage,
    MatchedEvidence,
    PersonalContribution,
    Relevance,
    RequirementMatch,
    SupportType,
)
from jobfit.scoring.v2.errors import DecisionInputError, DecisionNotFinalizableError

EVIDENCE_COEFFICIENTS = {
    EvidenceLevel.L1: Decimal("0.30"),
    EvidenceLevel.L2: Decimal("0.60"),
    EvidenceLevel.L3: Decimal("0.85"),
    EvidenceLevel.L4: Decimal("1.00"),
}
RELEVANCE_COEFFICIENTS = {
    Relevance.LOW: Decimal("0.40"),
    Relevance.MEDIUM: Decimal("0.75"),
    Relevance.HIGH: Decimal("1.00"),
}
_LEVEL_RANK = {
    EvidenceLevel.L1: 1,
    EvidenceLevel.L2: 2,
    EvidenceLevel.L3: 3,
    EvidenceLevel.L4: 4,
}
_RELEVANCE_RANK = {
    Relevance.LOW: 1,
    Relevance.MEDIUM: 2,
    Relevance.HIGH: 3,
}
_SUPPORT_RANK = {
    SupportType.CONTEXTUAL: 1,
    SupportType.TRANSFERABLE: 2,
    SupportType.DIRECT: 3,
}
_POSITIVE_CLARITY = {ClarityLevel.HIGH, ClarityLevel.MEDIUM}
_COMPONENT_QUANTUM = Decimal("0.0001")


@dataclass(frozen=True)
class MatchComputation:
    match: RequirementMatch
    selected_evidence_id: str | None


def determine_evidence_level(evidence: Evidence) -> EvidenceLevel:
    method_or_practical = (
        evidence.method_tool_clarity in _POSITIVE_CLARITY
        or evidence.practical_use in _POSITIVE_CLARITY
    )
    result_or_verification = (
        evidence.result_clarity in _POSITIVE_CLARITY
        or evidence.verification_strength in _POSITIVE_CLARITY
    )
    if (
        evidence.personal_contribution is PersonalContribution.CLEAR
        and not evidence.ambiguity
        and evidence.task_clarity is ClarityLevel.HIGH
        and evidence.method_tool_clarity in _POSITIVE_CLARITY
        and result_or_verification
    ):
        level = EvidenceLevel.L4
    elif (
        evidence.personal_contribution
        in {PersonalContribution.CLEAR, PersonalContribution.PARTIAL}
        and not evidence.ambiguity
        and evidence.task_clarity in _POSITIVE_CLARITY
        and method_or_practical
    ):
        level = EvidenceLevel.L3
    elif _has_actual_use_signal(evidence):
        level = EvidenceLevel.L2
    else:
        level = EvidenceLevel.L1

    if (
        evidence.personal_contribution is PersonalContribution.NOT_APPLICABLE
        and _has_actual_use_signal(evidence)
    ):
        return EvidenceLevel.L1
    if evidence.ambiguity or (
        evidence.personal_contribution is PersonalContribution.UNCLEAR
    ):
        return _cap_level(level, EvidenceLevel.L2)
    if evidence.personal_contribution is PersonalContribution.PARTIAL:
        return _cap_level(level, EvidenceLevel.L3)
    return level


def validate_evidence_level(evidence: Evidence) -> Evidence:
    computed = determine_evidence_level(evidence)
    if evidence.evidence_level is not computed:
        raise DecisionInputError(
            f"Evidence {evidence.evidence_id!r} has an invalid evidence level."
        )
    return evidence


def compute_requirement_match(
    match: RequirementMatch,
    evidence_by_id: Mapping[str, Evidence],
    *,
    forced_continue: bool = False,
) -> MatchComputation:
    relations = _validated_relations(match, evidence_by_id)
    zero_component = Decimal("0").quantize(
        _COMPONENT_QUANTUM,
        rounding=ROUND_HALF_UP,
    )
    if match.evidence_status is EvidenceStatus.CONFLICT:
        if not forced_continue:
            raise DecisionNotFinalizableError(
                f"Requirement {match.requirement_id!r} has unresolved evidence conflict."
            )
        return MatchComputation(
            match=match.model_copy(
                update={
                    "best_evidence_level": None,
                    "match_score_component": zero_component,
                }
            ),
            selected_evidence_id=None,
        )
    if (
        match.evidence_status is EvidenceStatus.MISSING
        or match.coverage is MatchCoverage.NONE
        or match.ability_status is AbilityStatus.CONFIRMED_GAP
    ):
        return MatchComputation(
            match=match.model_copy(
                update={
                    "best_evidence_level": None,
                    "match_score_component": zero_component,
                }
            ),
            selected_evidence_id=None,
        )

    selected_relation, evidence, component = min(
        (
            (
                relation,
                evidence_by_id[relation.evidence_id],
                _component(relation, evidence_by_id[relation.evidence_id]),
            )
            for relation in relations
        ),
        key=lambda item: (
            -item[2],
            -_SUPPORT_RANK[item[0].support_type],
            -_LEVEL_RANK[item[1].evidence_level],
            -_RELEVANCE_RANK[item[0].relevance],
            item[0].evidence_id,
        ),
    )
    return MatchComputation(
        match=match.model_copy(
            update={
                "best_evidence_level": evidence.evidence_level,
                "match_score_component": component.quantize(
                    _COMPONENT_QUANTUM,
                    rounding=ROUND_HALF_UP,
                ),
            }
        ),
        selected_evidence_id=selected_relation.evidence_id,
    )


def _has_actual_use_signal(evidence: Evidence) -> bool:
    return any(
        value is not ClarityLevel.UNKNOWN
        for value in (
            evidence.task_clarity,
            evidence.method_tool_clarity,
            evidence.result_clarity,
            evidence.verification_strength,
            evidence.practical_use,
        )
    )


def _cap_level(level: EvidenceLevel, cap: EvidenceLevel) -> EvidenceLevel:
    return level if _LEVEL_RANK[level] <= _LEVEL_RANK[cap] else cap


def _validated_relations(
    match: RequirementMatch,
    evidence_by_id: Mapping[str, Evidence],
) -> list[MatchedEvidence]:
    for relation in match.matched_evidence:
        evidence = evidence_by_id.get(relation.evidence_id)
        if evidence is None:
            raise DecisionInputError(
                f"Requirement match references unknown evidence {relation.evidence_id!r}."
            )
        validate_evidence_level(evidence)
    return match.matched_evidence


def _component(relation: MatchedEvidence, evidence: Evidence) -> Decimal:
    return (
        EVIDENCE_COEFFICIENTS[evidence.evidence_level]
        * RELEVANCE_COEFFICIENTS[relation.relevance]
    )
