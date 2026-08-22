"""R08-R20 deterministic score calculation."""

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from jobfit.models.common import Importance
from jobfit.models.v2 import (
    Evidence,
    EvidenceLevel,
    Relevance,
    Requirement,
    RequirementMatch,
    RequirementSource,
    RequirementType,
    SupportType,
)
from jobfit.scoring.v2.errors import DecisionInputError, DecisionNotFinalizableError
from jobfit.scoring.v2.evidence import compute_requirement_match

IMPORTANCE_WEIGHTS = {
    Importance.LOW: Decimal("1"),
    Importance.MEDIUM: Decimal("2"),
    Importance.HIGH: Decimal("3"),
    Importance.CRITICAL: Decimal("4"),
}
_SCORE_QUANTUM = Decimal("0.01")
_MAX_SCORE = Decimal("100")
_MAX_BONUS = Decimal("5")


@dataclass(frozen=True)
class ScoreComputation:
    core_ratio: Decimal
    supporting_ratio: Decimal | None
    base_fit_score: Decimal
    preferred_bonus: Decimal
    final_fit_score: Decimal
    computed_matches: tuple[RequirementMatch, ...]


def compute_scores(
    requirements: Sequence[Requirement],
    matches: Sequence[RequirementMatch],
    evidence_by_id: Mapping[str, Evidence],
    *,
    forced_continue: bool = False,
) -> ScoreComputation:
    requirement_by_id = _unique_requirements(requirements)
    match_by_requirement = _unique_matches(matches, requirement_by_id)
    computed: list[RequirementMatch] = []
    selected_ids: dict[str, str | None] = {}

    for requirement in requirements:
        match = match_by_requirement[requirement.requirement_id]
        excluded = requirement.requirement_type in {
            RequirementType.HARD,
            RequirementType.IMPLICIT,
        }
        computation = compute_requirement_match(
            match,
            evidence_by_id,
            forced_continue=(
                forced_continue
                or excluded
                or requirement.requirement_type is RequirementType.PREFERRED
            ),
        )
        computed_match = computation.match
        if excluded:
            if match.match_score_component is not None:
                raise DecisionInputError(
                    "Excluded requirement "
                    f"{requirement.requirement_id!r} carries a score component."
                )
            computed_match = computed_match.model_copy(
                update={"match_score_component": None}
            )
        computed.append(computed_match)
        selected_ids[requirement.requirement_id] = computation.selected_evidence_id

    computed_by_requirement = {
        match.requirement_id: match for match in computed
    }
    core = [
        item
        for item in requirements
        if _is_explicit_jd(item, RequirementType.CORE)
    ]
    supporting = [
        item
        for item in requirements
        if _is_explicit_jd(item, RequirementType.SUPPORTING)
    ]
    preferred = [
        item
        for item in requirements
        if _is_explicit_jd(item, RequirementType.PREFERRED)
    ]
    if not core:
        raise DecisionNotFinalizableError(
            "A formal score requires at least one explicit JD Core requirement."
        )

    core_ratio = _group_ratio(core, computed_by_requirement)
    supporting_ratio = (
        _group_ratio(supporting, computed_by_requirement) if supporting else None
    )
    if supporting_ratio is None:
        base_unrounded = _MAX_SCORE * core_ratio
    else:
        base_unrounded = _MAX_SCORE * (
            Decimal("0.80") * core_ratio
            + Decimal("0.20") * supporting_ratio
        )
    base = base_unrounded.quantize(_SCORE_QUANTUM, rounding=ROUND_HALF_UP)
    bonus = min(
        _MAX_BONUS,
        sum(
            (
                _preferred_credit(
                    requirement,
                    computed_by_requirement[requirement.requirement_id],
                    selected_ids[requirement.requirement_id],
                    evidence_by_id,
                )
                for requirement in preferred
            ),
            start=Decimal("0"),
        ),
    )
    final = min(_MAX_SCORE, base + bonus).quantize(
        _SCORE_QUANTUM,
        rounding=ROUND_HALF_UP,
    )
    return ScoreComputation(
        core_ratio=core_ratio,
        supporting_ratio=supporting_ratio,
        base_fit_score=base,
        preferred_bonus=bonus,
        final_fit_score=final,
        computed_matches=tuple(computed),
    )


def _unique_requirements(
    requirements: Sequence[Requirement],
) -> dict[str, Requirement]:
    counts = Counter(item.requirement_id for item in requirements)
    duplicate = sorted(key for key, count in counts.items() if count > 1)
    if duplicate:
        raise DecisionInputError(f"Requirement IDs are duplicate: {duplicate!r}.")
    return {item.requirement_id: item for item in requirements}


def _unique_matches(
    matches: Sequence[RequirementMatch],
    requirement_by_id: Mapping[str, Requirement],
) -> dict[str, RequirementMatch]:
    counts = Counter(item.requirement_id for item in matches)
    duplicate = sorted(key for key, count in counts.items() if count > 1)
    if duplicate:
        raise DecisionInputError(
            f"Requirement matches contain duplicate requirement IDs: {duplicate!r}."
        )
    unknown = sorted(set(counts) - set(requirement_by_id))
    if unknown:
        raise DecisionInputError(
            f"Requirement matches reference unknown requirements: {unknown!r}."
        )
    missing = sorted(set(requirement_by_id) - set(counts))
    if missing:
        raise DecisionInputError(
            "Every requirement requires exactly one match; missing "
            f"{missing!r}."
        )
    return {item.requirement_id: item for item in matches}


def _is_explicit_jd(
    requirement: Requirement,
    requirement_type: RequirementType,
) -> bool:
    return (
        requirement.requirement_type is requirement_type
        and requirement.source is RequirementSource.JD
    )


def _group_ratio(
    requirements: Sequence[Requirement],
    match_by_requirement: Mapping[str, RequirementMatch],
) -> Decimal:
    denominator = sum(
        (IMPORTANCE_WEIGHTS[item.importance] for item in requirements),
        start=Decimal("0"),
    )
    numerator = sum(
        (
            IMPORTANCE_WEIGHTS[item.importance]
            * (match_by_requirement[item.requirement_id].match_score_component or Decimal("0"))
            for item in requirements
        ),
        start=Decimal("0"),
    )
    return numerator / denominator


def _preferred_credit(
    requirement: Requirement,
    match: RequirementMatch,
    selected_evidence_id: str | None,
    evidence_by_id: Mapping[str, Evidence],
) -> Decimal:
    if selected_evidence_id is None:
        return Decimal("0")
    relation = next(
        item
        for item in match.matched_evidence
        if item.evidence_id == selected_evidence_id
    )
    if relation.support_type is SupportType.CONTEXTUAL:
        return Decimal("0")
    level = evidence_by_id[selected_evidence_id].evidence_level
    if (
        requirement.importance in {Importance.CRITICAL, Importance.HIGH}
        and level in {EvidenceLevel.L3, EvidenceLevel.L4}
        and relation.relevance in {Relevance.MEDIUM, Relevance.HIGH}
    ):
        return Decimal("2")
    if (
        (
            requirement.importance in {Importance.MEDIUM, Importance.LOW}
            and level in {EvidenceLevel.L3, EvidenceLevel.L4}
            and relation.relevance in {Relevance.MEDIUM, Relevance.HIGH}
        )
        or (
            level is EvidenceLevel.L2
            and relation.relevance in {Relevance.MEDIUM, Relevance.HIGH}
        )
        or (
            level in {EvidenceLevel.L3, EvidenceLevel.L4}
            and relation.relevance is Relevance.LOW
        )
    ):
        return Decimal("1")
    return Decimal("0")
