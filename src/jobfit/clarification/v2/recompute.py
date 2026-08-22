"""Bounded P04/P05-local updates for accepted B4 clarification facts."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from jobfit.clarification.v2.validation import ClarificationValidationError
from jobfit.models.v2 import (
    AbilityStatus,
    ClarificationAnswer,
    ClarificationQuestion,
    ClarificationQuestionType,
    Evidence,
    EvidenceStatus,
    MatchCoverage,
    PersonalContribution,
    RequirementMatch,
    ResumeProfile,
)
from jobfit.scoring.v2 import determine_evidence_level


@dataclass(frozen=True)
class BoundedRecomputeResult:
    resume_profile: ResumeProfile
    matches: tuple[RequirementMatch, ...]
    evidence: tuple[Evidence, ...]
    affected_requirement_ids: tuple[str, ...]
    affected_evidence_ids: tuple[str, ...]


def apply_bounded_clarification_update(
    *,
    resume_profile: ResumeProfile,
    matches: Sequence[RequirementMatch],
    evidence: Sequence[Evidence],
    question: ClarificationQuestion,
    answer: ClarificationAnswer,
    clarification_id: str,
) -> BoundedRecomputeResult:
    """Apply only the explicitly targeted derived fact and its P04/P05 chain."""
    if question.question_type is ClarificationQuestionType.ROLE_SENIORITY:
        years = Decimal(str(answer.value))
        candidate = resume_profile.candidate_profile.model_copy(
            update={"years_of_full_time_experience": years}
        )
        return BoundedRecomputeResult(
            resume_profile=resume_profile.model_copy(
                update={"candidate_profile": candidate}
            ),
            matches=tuple(matches),
            evidence=tuple(evidence),
            affected_requirement_ids=tuple(question.source_requirement_ids),
            affected_evidence_ids=(),
        )

    if question.question_type not in {
        ClarificationQuestionType.EVIDENCE_OWNERSHIP,
        ClarificationQuestionType.CRITICAL_EVIDENCE,
    }:
        raise ClarificationValidationError(
            "Clarification type has no approved bounded update."
        )
    if len(question.source_evidence_ids) != 1:
        raise ClarificationValidationError(
            "Evidence clarification must target exactly one evidence object."
        )
    contribution = {
        "clear": PersonalContribution.CLEAR,
        "partial": PersonalContribution.PARTIAL,
        "unclear": PersonalContribution.UNCLEAR,
    }.get(str(answer.value))
    if contribution is None:
        raise ClarificationValidationError("Unsupported evidence ownership answer.")

    target_id = question.source_evidence_ids[0]
    updated_evidence = list(evidence)
    indexes = [
        index for index, item in enumerate(updated_evidence) if item.evidence_id == target_id
    ]
    if len(indexes) != 1:
        raise ClarificationValidationError(
            "Evidence clarification target is missing or duplicated."
        )
    original = updated_evidence[indexes[0]]
    del clarification_id
    changed = original.model_copy(
        update={
            "personal_contribution": contribution,
            "ambiguity": contribution is PersonalContribution.UNCLEAR,
        }
    )
    changed = changed.model_copy(
        update={"evidence_level": determine_evidence_level(changed)}
    )
    updated_evidence[indexes[0]] = changed

    requirement_ids = set(question.source_requirement_ids)
    updated_matches: list[RequirementMatch] = []
    for match in matches:
        if match.requirement_id not in requirement_ids:
            updated_matches.append(match)
            continue
        relation_ids = {item.evidence_id for item in match.matched_evidence}
        if target_id not in relation_ids:
            raise ClarificationValidationError(
                "Evidence clarification does not belong to the target match."
            )
        updated_matches.append(
            match.model_copy(
                update={
                    "coverage": (
                        MatchCoverage.FULL
                        if contribution is PersonalContribution.CLEAR
                        else MatchCoverage.PARTIAL
                    ),
                    "evidence_status": (
                        EvidenceStatus.PRESENT
                        if contribution is PersonalContribution.CLEAR
                        else EvidenceStatus.WEAK
                    ),
                    "ability_status": AbilityStatus.CONFIRMED,
                }
            )
        )
    return BoundedRecomputeResult(
        resume_profile=resume_profile,
        matches=tuple(updated_matches),
        evidence=tuple(updated_evidence),
        affected_requirement_ids=tuple(question.source_requirement_ids),
        affected_evidence_ids=(target_id,),
    )
