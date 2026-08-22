"""Deterministic Decimal-only requirement weighting and scoring."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal

from jobfit.errors import ErrorCode, ScoringError
from jobfit.models import (
    DimensionScore,
    EvidenceKind,
    HardConditionKind,
    Importance,
    JobRequirement,
    MatchScoreSummary,
    MatchStatus,
    RequirementMatch,
    RequirementType,
)
from jobfit.scoring.policy import (
    BASE_POINTS,
    IMPLICIT_WEIGHT_CAP,
    STATUS_VALUES,
    STRONG_EVIDENCE_CONFIDENCE,
    calculate_priority_factor,
    determine_score_cap,
    select_recommendation,
)

_CENT = Decimal("0.01")
_INTERNAL = Decimal("0.00000001")
_RATIO = Decimal("0.0001")
_ZERO = Decimal("0")
_HUNDRED = Decimal("100.00")


class ScoringEngine:
    """Recompute every numeric field from validated requirements and matches."""

    def score(
        self,
        requirements: Sequence[JobRequirement],
        matches: Sequence[RequirementMatch],
    ) -> MatchScoreSummary:
        self._validate_inputs(requirements, matches)
        factors = {
            item.requirement_id: calculate_priority_factor(item)
            for item in requirements
        }
        weights = self._calculate_weights(requirements, factors)

        for requirement in requirements:
            requirement.priority_factor = factors[requirement.requirement_id]
            requirement.weight = weights[requirement.requirement_id]

        match_by_id = {item.requirement_id: item for item in matches}
        earned = {
            item.requirement_id: _money(
                weights[item.requirement_id]
                * STATUS_VALUES[match_by_id[item.requirement_id].match_status]
            )
            for item in requirements
        }
        raw_score = _money(sum(earned.values(), _ZERO))
        dimensions = self._dimension_scores(
            requirements,
            earned,
        )
        mandatory_coverage = self._mandatory_coverage(
            requirements,
            earned,
        )
        strong_evidence_coverage = self._strong_evidence_coverage(
            requirements,
            match_by_id,
        )
        cap = determine_score_cap(requirements, matches)
        final_score = min(raw_score, cap.score_cap)
        has_critical_gap = any(
            item.mandatory
            and item.importance is Importance.CRITICAL
            and match_by_id[item.requirement_id].match_status
            is not MatchStatus.MATCHED
            for item in requirements
        )
        recommendation = select_recommendation(
            final_score=final_score,
            mandatory_coverage_ratio=mandatory_coverage,
            strong_evidence_coverage_ratio=strong_evidence_coverage,
            confirmed_hard_blockers=cap.confirmed_hard_blockers,
            unverified_hard_blockers=cap.unverified_hard_blockers,
            has_critical_mandatory_gap=has_critical_gap,
        )
        return MatchScoreSummary(
            raw_score=raw_score,
            score_cap=cap.score_cap,
            final_score=final_score,
            dimension_scores=dimensions,
            mandatory_coverage_ratio=mandatory_coverage,
            strong_evidence_coverage_ratio=strong_evidence_coverage,
            confirmed_hard_blockers=cap.confirmed_hard_blockers,
            unverified_hard_blockers=cap.unverified_hard_blockers,
            cap_reasons=cap.cap_reasons,
            recommendation_level=recommendation,
        )

    @staticmethod
    def _validate_inputs(
        requirements: Sequence[JobRequirement],
        matches: Sequence[RequirementMatch],
    ) -> None:
        if not requirements:
            raise _scoring_error("岗位要求不能为空。")
        requirement_ids = [item.requirement_id for item in requirements]
        match_ids = [item.requirement_id for item in matches]
        if (
            len(requirement_ids) != len(set(requirement_ids))
            or len(match_ids) != len(set(match_ids))
            or set(requirement_ids) != set(match_ids)
        ):
            raise _scoring_error("岗位要求与匹配结果必须一一对应。")
        if all(
            item.requirement_type is RequirementType.IMPLICIT
            for item in requirements
        ):
            raise _scoring_error("不能仅根据隐性要求生成总分。")

        for requirement in requirements:
            if requirement.requirement_type is RequirementType.IMPLICIT and (
                requirement.mandatory
                or requirement.hard_condition_kind is not HardConditionKind.NONE
            ):
                raise _scoring_error("隐性要求不能成为mandatory或硬门槛。")
        for match in matches:
            if match.match_score != STATUS_VALUES[match.match_status]:
                raise _scoring_error("匹配状态分值未通过固定映射校验。")
            if match.match_status is MatchStatus.MATCHED and not any(
                evidence.evidence_kind is EvidenceKind.DIRECT
                for evidence in match.evidence_items
            ):
                raise _scoring_error("完全匹配缺少直接证据。")
            if (
                match.match_status is MatchStatus.PARTIAL_MATCH
                and not match.evidence_items
            ):
                raise _scoring_error("部分匹配缺少证据。")

    def _calculate_weights(
        self,
        requirements: Sequence[JobRequirement],
        factors: dict[str, Decimal],
    ) -> dict[str, Decimal]:
        by_category: dict[object, list[JobRequirement]] = defaultdict(list)
        for requirement in requirements:
            by_category[requirement.category].append(requirement)
        active_categories = [
            category for category in BASE_POINTS if by_category[category]
        ]
        effective_points = _allocate_total(
            active_categories,
            _HUNDRED,
            {category: BASE_POINTS[category] for category in active_categories},
        )

        weights: dict[str, Decimal] = {}
        for category in active_categories:
            items = sorted(
                by_category[category],
                key=lambda item: item.requirement_id,
            )
            item_ids = [item.requirement_id for item in items]
            dimension_weights = _allocate_total(
                item_ids,
                effective_points[category],
                {
                    item.requirement_id: factors[item.requirement_id]
                    for item in items
                },
            )
            weights.update(dimension_weights)

        self._cap_implicit_weights(requirements, weights)
        if sum(weights.values(), _ZERO) != _HUNDRED:
            raise _scoring_error("岗位要求权重合计不等于100.00。")
        return weights

    @staticmethod
    def _cap_implicit_weights(
        requirements: Sequence[JobRequirement],
        weights: dict[str, Decimal],
    ) -> None:
        implicit = sorted(
            (
                item
                for item in requirements
                if item.requirement_type is RequirementType.IMPLICIT
            ),
            key=lambda item: item.requirement_id,
        )
        implicit_total = sum(
            (weights[item.requirement_id] for item in implicit),
            _ZERO,
        )
        if implicit_total <= IMPLICIT_WEIGHT_CAP:
            return
        non_implicit = sorted(
            (
                item
                for item in requirements
                if item.requirement_type is not RequirementType.IMPLICIT
            ),
            key=lambda item: item.requirement_id,
        )
        if not non_implicit:
            raise _scoring_error("隐性要求释放的权重没有可分配目标。")

        compressed = _allocate_total(
            [item.requirement_id for item in implicit],
            IMPLICIT_WEIGHT_CAP,
            {
                item.requirement_id: weights[item.requirement_id]
                for item in implicit
            },
        )
        released = implicit_total - IMPLICIT_WEIGHT_CAP
        redistributed = _allocate_total(
            [item.requirement_id for item in non_implicit],
            released,
            {
                item.requirement_id: weights[item.requirement_id]
                for item in non_implicit
            },
        )
        for item in implicit:
            weights[item.requirement_id] = compressed[item.requirement_id]
        for item in non_implicit:
            weights[item.requirement_id] += redistributed[item.requirement_id]

    @staticmethod
    def _dimension_scores(
        requirements: Sequence[JobRequirement],
        earned: dict[str, Decimal],
    ) -> list[DimensionScore]:
        by_category: dict[object, list[JobRequirement]] = defaultdict(list)
        for requirement in requirements:
            by_category[requirement.category].append(requirement)

        scores: list[DimensionScore] = []
        for category, base_points in BASE_POINTS.items():
            items = sorted(
                by_category[category],
                key=lambda item: item.requirement_id,
            )
            if not items:
                scores.append(
                    DimensionScore(
                        category=category,
                        base_points=base_points,
                        effective_points=_ZERO,
                        earned_points=_ZERO,
                        active=False,
                        requirement_ids=[],
                        coverage_ratio=_ZERO,
                    )
                )
                continue
            effective = sum((item.weight for item in items), _ZERO)
            dimension_earned = sum(
                (earned[item.requirement_id] for item in items),
                _ZERO,
            )
            scores.append(
                DimensionScore(
                    category=category,
                    base_points=base_points,
                    effective_points=effective,
                    earned_points=dimension_earned,
                    active=True,
                    requirement_ids=[item.requirement_id for item in items],
                    coverage_ratio=_ratio(dimension_earned, effective),
                )
            )
        return scores

    @staticmethod
    def _mandatory_coverage(
        requirements: Sequence[JobRequirement],
        earned: dict[str, Decimal],
    ) -> Decimal:
        mandatory = [item for item in requirements if item.mandatory]
        if not mandatory:
            return Decimal("1.0000")
        denominator = sum((item.weight for item in mandatory), _ZERO)
        numerator = sum(
            (earned[item.requirement_id] for item in mandatory),
            _ZERO,
        )
        return _ratio(numerator, denominator)

    @staticmethod
    def _strong_evidence_coverage(
        requirements: Sequence[JobRequirement],
        matches: dict[str, RequirementMatch],
    ) -> Decimal:
        numerator = sum(
            (
                item.weight
                for item in requirements
                if matches[item.requirement_id].match_status
                in {MatchStatus.MATCHED, MatchStatus.PARTIAL_MATCH}
                and matches[item.requirement_id].evidence_items
                and matches[item.requirement_id].confidence
                >= STRONG_EVIDENCE_CONFIDENCE
            ),
            _ZERO,
        )
        denominator = sum((item.weight for item in requirements), _ZERO)
        return _ratio(numerator, denominator)


def _allocate_total(
    items: Sequence[object],
    total: Decimal,
    basis: dict[object, Decimal],
) -> dict[object, Decimal]:
    ordered = list(items)
    basis_total = sum((basis[item] for item in ordered), _ZERO)
    if not ordered or basis_total <= 0:
        raise _scoring_error("权重分配缺少有效因子。")
    allocated: dict[object, Decimal] = {}
    running = _ZERO
    for item in ordered[:-1]:
        intermediate = (total * basis[item] / basis_total).quantize(
            _INTERNAL,
            rounding=ROUND_HALF_UP,
        )
        value = _money(intermediate)
        allocated[item] = value
        running += value
    last_value = total - running
    if last_value < 0:
        raise _scoring_error("权重舍入差额导致负数。")
    allocated[ordered[-1]] = last_value
    return allocated


def _money(value: Decimal) -> Decimal:
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def _ratio(numerator: Decimal, denominator: Decimal) -> Decimal:
    if denominator == 0:
        return _ZERO
    return (numerator / denominator).quantize(
        _RATIO,
        rounding=ROUND_HALF_UP,
    )


def _scoring_error(message: str) -> ScoringError:
    return ScoringError(
        code=ErrorCode.SCORING_INVARIANT_FAILED,
        user_message=message,
        recoverable=False,
    )
