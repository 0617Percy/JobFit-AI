"""Grounded strength, gap, and recommendation assembly."""

from __future__ import annotations

import re
from collections.abc import Sequence
from decimal import Decimal

from jobfit.generators.common import (
    advice_error,
    normalized_phrase,
    require_requirement_ids,
    require_resume_evidence,
    requirement_index,
)
from jobfit.models import (
    AdviceBundleDraft,
    ApplicationRecommendation,
    EvidenceRegistry,
    GapItem,
    GapRemediability,
    HardConditionKind,
    Importance,
    JobProfile,
    MatchScoreSummary,
    MatchStatus,
    RequirementMatch,
    StrengthItem,
)

_STATUS_RANK = {
    MatchStatus.MATCHED: 2,
    MatchStatus.PARTIAL_MATCH: 1,
    MatchStatus.UNKNOWN: 0,
    MatchStatus.NOT_MATCHED: 0,
}
_RISK_RANK = {
    Importance.CRITICAL: 4,
    Importance.HIGH: 3,
    Importance.MEDIUM: 2,
    Importance.LOW: 1,
}
_UNKNOWN_OVERCLAIMS = (
    "一定不会",
    "确定不会",
    "不具备",
    "完全不具备",
    "没有能力",
    "无法胜任",
    "明确不满足",
)
_PARTIAL_OVERCLAIMS = ("完全匹配", "充分满足", "精通", "完全具备")
_LOW_CONFIDENCE_CERTAINTY = ("明确", "充分证明", "确定具备", "肯定", "精通")
_REQUIREMENT_REFERENCE = re.compile(r"\[([A-Za-z0-9_-]+)\]")


def finalize_diagnosis(
    draft: AdviceBundleDraft,
    job: JobProfile,
    matches: Sequence[RequirementMatch],
    score: MatchScoreSummary,
    registry: EvidenceRegistry,
) -> tuple[list[StrengthItem], list[GapItem], ApplicationRecommendation]:
    requirements = requirement_index(job.requirements.items)
    match_by_id = {item.requirement_id: item for item in matches}
    if len(match_by_id) != len(matches) or set(match_by_id) != set(requirements):
        raise advice_error("岗位要求与匹配结果不是严格一一对应。")

    strengths = _finalize_strengths(
        draft.strengths,
        requirements,
        match_by_id,
        registry,
    )
    gaps = _finalize_gaps(
        draft.gaps,
        requirements,
        match_by_id,
    )
    recommendation = _build_recommendation(
        draft.recommendation_reasoning,
        requirements,
        gaps,
        score,
    )
    return strengths, gaps, recommendation


def _finalize_strengths(
    items: Sequence[StrengthItem],
    requirements: dict[str, object],
    matches: dict[str, RequirementMatch],
    registry: EvidenceRegistry,
) -> list[StrengthItem]:
    ranked: list[tuple[object, StrengthItem]] = []
    seen_capabilities: set[str] = set()
    for item in items:
        linked_requirements = require_requirement_ids(
            item.requirement_ids,
            requirements,
        )
        evidence = require_resume_evidence(item.evidence_ids, registry)
        linked_matches = [
            matches[requirement.requirement_id]
            for requirement in linked_requirements
        ]
        if any(
            match.match_status
            not in {MatchStatus.MATCHED, MatchStatus.PARTIAL_MATCH}
            for match in linked_matches
        ):
            raise advice_error("优势只能来自已匹配或部分匹配的岗位要求。")
        allowed_evidence = {
            evidence_item.evidence_id
            for match in linked_matches
            for evidence_item in match.evidence_items
        }
        if not set(item.evidence_ids).issubset(allowed_evidence):
            raise advice_error("优势引用的证据与对应岗位匹配结果无关。")
        if any(
            match.match_status is MatchStatus.PARTIAL_MATCH
            for match in linked_matches
        ) and any(
            token in f"{item.title}{item.summary}{item.why_it_matters}"
            for token in _PARTIAL_OVERCLAIMS
        ):
            raise advice_error("部分匹配不能被包装为完全优势。")
        if max(item.confidence for item in evidence) < Decimal("0.70") and any(
            token in f"{item.title}{item.summary}{item.why_it_matters}"
            for token in _LOW_CONFIDENCE_CERTAINTY
        ):
            raise advice_error("低置信度证据不能被写成确定性优势。")

        capability_key = normalized_phrase(item.title)
        if capability_key in seen_capabilities:
            continue
        seen_capabilities.add(capability_key)
        ranked.append(
            (
                (
                    -max(requirement.weight for requirement in linked_requirements),
                    -max(_STATUS_RANK[match.match_status] for match in linked_matches),
                    -max(evidence_item.confidence for evidence_item in evidence),
                    capability_key,
                ),
                item,
            )
        )
    ranked.sort(key=lambda entry: entry[0])
    return [item for _, item in ranked[:3]]


def _finalize_gaps(
    items: Sequence[GapItem],
    requirements: dict[str, object],
    matches: dict[str, RequirementMatch],
) -> list[GapItem]:
    ranked: list[tuple[object, GapItem]] = []
    seen: set[tuple[str, ...]] = set()
    for item in items:
        linked_requirements = require_requirement_ids(
            item.requirement_ids,
            requirements,
        )
        signature = tuple(sorted(item.requirement_ids))
        if signature in seen:
            continue
        seen.add(signature)
        linked_matches = [
            matches[requirement.requirement_id]
            for requirement in linked_requirements
        ]
        statuses = {match.match_status for match in linked_matches}
        if MatchStatus.UNKNOWN in statuses and any(
            token in f"{item.title}{item.summary}" for token in _UNKNOWN_OVERCLAIMS
        ):
            raise advice_error("unknown缺口不能描述为用户确定不具备该能力。")

        has_hard_condition = any(
            requirement.hard_condition_kind is not HardConditionKind.NONE
            for requirement in linked_requirements
        )
        if has_hard_condition:
            remediability = GapRemediability.HARD_TO_FIX_SHORT_TERM
        elif statuses == {MatchStatus.UNKNOWN}:
            remediability = GapRemediability.EVIDENCE_NEEDED
        elif MatchStatus.NOT_MATCHED in statuses:
            remediability = GapRemediability.LEARNING_PRACTICE
        else:
            remediability = item.remediability
        confirmation_needed = (
            item.user_confirmation_needed
            or MatchStatus.UNKNOWN in statuses
            or has_hard_condition
        )
        finalized = item.model_copy(
            update={
                "remediability": remediability,
                "user_confirmation_needed": confirmation_needed,
            }
        )
        ranked.append(
            (
                (
                    -int(has_hard_condition),
                    -_RISK_RANK[finalized.risk_level],
                    -max(requirement.weight for requirement in linked_requirements),
                    normalized_phrase(finalized.title),
                ),
                finalized,
            )
        )
    ranked.sort(key=lambda entry: entry[0])
    return [item for _, item in ranked[:3]]


def _build_recommendation(
    reasoning: Sequence[str],
    requirements: dict[str, object],
    gaps: Sequence[GapItem],
    score: MatchScoreSummary,
) -> ApplicationRecommendation:
    for statement in reasoning:
        referenced = _REQUIREMENT_REFERENCE.findall(statement)
        if not referenced or any(item not in requirements for item in referenced):
            raise advice_error("投递建议理由必须引用有效的岗位要求ID。")

    blockers = list(
        dict.fromkeys(
            [
                *score.confirmed_hard_blockers,
                *score.unverified_hard_blockers,
            ]
        )
    )
    if any(requirement_id not in requirements for requirement_id in blockers):
        raise advice_error("评分结果包含不存在的阻塞要求ID。")

    actions: list[str] = []
    for requirement_id in score.unverified_hard_blockers:
        actions.append(f"投递前确认硬性条件 [{requirement_id}] 是否真实满足。")
    actions.extend(
        item.recommended_action
        for item in gaps
        if item.recommended_action not in actions
    )
    return ApplicationRecommendation(
        level=score.recommendation_level,
        reasoning=list(reasoning),
        blocking_requirement_ids=blockers,
        before_applying_actions=list(dict.fromkeys(actions)),
    )
