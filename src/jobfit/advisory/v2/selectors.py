"""Deterministic selection for the main report's top three actions."""

from __future__ import annotations

from collections.abc import Sequence

from jobfit.models import Importance
from jobfit.models.v2 import (
    ActionRecommendation,
    ActionTiming,
    ActionType,
    AnalysisCore,
    EvidenceStatus,
    Priority,
    Requirement,
    RequirementMatch,
)

_PRIORITY_RANK = {Priority.P0: 0, Priority.P1: 1, Priority.P2: 2}
_ACTION_RANK = {ActionType.REWRITE: 0, ActionType.RECOVER: 1, ActionType.BUILD: 2}
_IMPORTANCE_RANK = {
    Importance.CRITICAL: 0,
    Importance.HIGH: 1,
    Importance.MEDIUM: 2,
    Importance.LOW: 3,
}
_TIMING_RANK = {
    ActionTiming.BEFORE_APPLY: 0,
    ActionTiming.PARALLEL_WITH_APPLICATIONS: 1,
    ActionTiming.LONG_TERM: 2,
    None: 3,
}


def select_top_actions(
    actions: Sequence[ActionRecommendation],
    *,
    analysis_core: AnalysisCore,
    requirements: Sequence[Requirement],
    requirement_matches: Sequence[RequirementMatch],
    limit: int = 3,
) -> tuple[ActionRecommendation, ...]:
    """Deduplicate and rank from frozen gap facts before model priority."""

    if limit < 0 or limit > 3:
        raise ValueError("P06 top-action limit must be between zero and three.")
    unique = {item.action_id: item for item in actions}
    requirement_by_id = {
        item.requirement_id: item for item in requirements
    }
    match_by_requirement_id = {
        item.requirement_id: item for item in requirement_matches
    }
    hard_ids = {
        *analysis_core.hard_blocker_ids,
        *analysis_core.hard_pending_ids,
    }
    critical_ids = set(analysis_core.critical_gap_requirement_ids)

    def decision_rank(item: ActionRecommendation) -> tuple[int, int]:
        requirement_ids = set(item.related_requirement_ids)
        if requirement_ids & hard_ids:
            return (0, 0)
        if requirement_ids & critical_ids:
            return (1, 0)
        if any(
            match_by_requirement_id.get(requirement_id) is not None
            and match_by_requirement_id[requirement_id].evidence_status
            is EvidenceStatus.MISSING
            for requirement_id in requirement_ids
        ):
            return (2, 0)
        importance = min(
            (
                _IMPORTANCE_RANK[requirement_by_id[requirement_id].importance]
                for requirement_id in requirement_ids
                if requirement_id in requirement_by_id
            ),
            default=len(_IMPORTANCE_RANK),
        )
        return (3, importance)

    ordered = sorted(
        unique.values(),
        key=lambda item: (
            *decision_rank(item),
            _PRIORITY_RANK[item.priority],
            _ACTION_RANK[item.action_type],
            _TIMING_RANK[item.timing],
            item.action_id,
        ),
    )
    return tuple(ordered[:limit])
