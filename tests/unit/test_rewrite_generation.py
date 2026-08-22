"""Tests for evidence-bound resume rewrite post-processing."""

from __future__ import annotations

import pytest

from jobfit.errors import ErrorCode, JobFitError
from jobfit.generators.rewrite import partition_rewrites
from jobfit.models import RewriteSuggestionDraft


def test_safe_rewrite_is_directly_usable_and_gets_stable_id(advice_case) -> None:
    draft = _rewrite(
        original="使用Python完成数据处理",
        rewritten="使用 Python 完成数据处理，清晰呈现技术行动。",
    )

    direct, confirmation = partition_rewrites(
        [draft],
        advice_case.job.requirements.items,
        advice_case.registry,
    )
    repeated, _ = partition_rewrites(
        [draft],
        advice_case.job.requirements.items,
        advice_case.registry,
    )

    assert len(direct) == 1
    assert confirmation == []
    assert direct[0].suggestion_id == repeated[0].suggestion_id
    assert direct[0].introduced_claims == []


@pytest.mark.parametrize(
    ("rewritten", "expected_marker"),
    [
        ("使用Python完成数据处理，效率提升30%。", "新增数字"),
        ("使用Python和Docker完成数据处理。", "新增技术"),
        ("主导Python数据处理项目。", "职责强化"),
        ("使用Python完成生产部署并上线商业化。", "落地范围"),
        ("为某公司客户使用Python完成数据处理。", "组织或客户"),
    ],
)
def test_high_risk_claims_are_detected_and_require_confirmation(
    advice_case,
    rewritten: str,
    expected_marker: str,
) -> None:
    draft = _rewrite(
        original="使用Python完成数据处理",
        rewritten=rewritten,
    )

    direct, confirmation = partition_rewrites(
        [draft],
        advice_case.job.requirements.items,
        advice_case.registry,
    )

    assert direct == []
    assert len(confirmation) == 1
    assert any(expected_marker in claim for claim in confirmation[0].introduced_claims)
    assert confirmation[0].user_confirmation_needed


def test_llm_introduced_claims_always_require_confirmation(advice_case) -> None:
    draft = _rewrite(
        original="使用Python完成数据处理",
        rewritten="使用Python完成数据处理。",
        introduced_claims=["模型声称存在新增影响范围"],
    )

    direct, confirmation = partition_rewrites(
        [draft],
        advice_case.job.requirements.items,
        advice_case.registry,
    )

    assert direct == []
    assert confirmation[0].introduced_claims
    assert confirmation[0].user_confirmation_needed


def test_rewrite_without_traceable_original_is_rejected(advice_case) -> None:
    draft = _rewrite(
        original="简历中不存在的原句",
        rewritten="优化后的虚构内容",
    )

    with pytest.raises(JobFitError) as exc_info:
        partition_rewrites(
            [draft],
            advice_case.job.requirements.items,
            advice_case.registry,
        )

    assert exc_info.value.code is ErrorCode.ADVICE_VALIDATION_FAILED


def test_rewrite_with_unknown_evidence_is_rejected(advice_case) -> None:
    draft = _rewrite(
        original="使用Python完成数据处理",
        rewritten="使用Python完成数据处理。",
        evidence_ids=["ev-unknown"],
    )

    with pytest.raises(JobFitError) as exc_info:
        partition_rewrites(
            [draft],
            advice_case.job.requirements.items,
            advice_case.registry,
        )

    assert exc_info.value.code is ErrorCode.ADVICE_VALIDATION_FAILED


def test_partition_does_not_mutate_registry_evidence(advice_case) -> None:
    before = advice_case.registry.get("ev-python").model_copy(deep=True)
    draft = _rewrite(
        original="使用Python完成数据处理",
        rewritten="使用 Python 完成数据处理。",
    )

    partition_rewrites(
        [draft],
        advice_case.job.requirements.items,
        advice_case.registry,
    )

    assert advice_case.registry.get("ev-python") == before


def _rewrite(
    *,
    original: str,
    rewritten: str,
    evidence_ids: list[str] | None = None,
    introduced_claims: list[str] | None = None,
) -> RewriteSuggestionDraft:
    return RewriteSuggestionDraft(
        original_text=original,
        rewritten_text=rewritten,
        reason="在不改变事实的前提下提高表达清晰度。",
        requirement_ids=["req-python"],
        evidence_ids=evidence_ids or ["ev-python"],
        introduced_claims=introduced_claims or [],
    )
