"""Final, independently testable anti-fabrication rewrite validation."""

from __future__ import annotations

import pytest

from jobfit.models import RewriteSuggestion, ValidationSeverity
from jobfit.validators.rewrite import RewriteValidator


def test_safe_rewrite_passes_final_validation(report_case) -> None:
    suggestion = report_case.advice.direct_rewrites[0]

    result = RewriteValidator().validate(
        suggestion,
        report_case.registry,
        report_case.job.requirements.items,
        direct=True,
    )

    assert result.valid is True
    assert not _errors(result)


def test_original_text_must_exactly_trace_to_evidence(report_case) -> None:
    suggestion = _copy_rewrite(
        report_case,
        original_text="无法在证据中精确定位的原句",
    )

    result = RewriteValidator().validate(
        suggestion,
        report_case.registry,
        report_case.job.requirements.items,
    )

    assert result.valid is False
    assert "REWRITE_ORIGINAL_UNTRACEABLE" in _codes(result)


def test_unknown_evidence_or_requirement_is_rejected(report_case) -> None:
    unknown_evidence = _copy_rewrite(
        report_case,
        evidence_ids=["ev-invented"],
    )
    unknown_requirement = _copy_rewrite(
        report_case,
        requirement_ids=["req-invented"],
    )
    validator = RewriteValidator()

    evidence_result = validator.validate(
        unknown_evidence,
        report_case.registry,
        report_case.job.requirements.items,
    )
    requirement_result = validator.validate(
        unknown_requirement,
        report_case.registry,
        report_case.job.requirements.items,
    )

    assert "REWRITE_EVIDENCE_UNKNOWN" in _codes(evidence_result)
    assert "REWRITE_REQUIREMENT_UNKNOWN" in _codes(requirement_result)


@pytest.mark.parametrize(
    ("rewritten", "marker"),
    [
        ("使用Python完成数据处理，效率提升30%。", "数字"),
        ("使用Python和Docker完成数据处理。", "技术"),
        ("在星海科技公司为客户完成Python数据处理。", "组织"),
        ("主导Python数据处理并管理5人团队。", "职责"),
        ("使用Python完成生产部署、上线和商业化。", "落地"),
        ("获得Python专业认证和一等奖。", "获奖或证书"),
        ("熟练掌握并精通Python数据处理。", "能力等级"),
        ("使用Python处理100万元业务数据。", "金额"),
        ("于2026-07-23完成Python项目。", "日期"),
    ],
)
def test_new_claims_require_explicit_confirmation(
    report_case,
    rewritten: str,
    marker: str,
) -> None:
    suggestion = _copy_rewrite(
        report_case,
        rewritten_text=rewritten,
        introduced_claims=[f"新增{marker}主张"],
        user_confirmation_needed=[f"请确认新增{marker}主张"],
    )

    result = RewriteValidator().validate(
        suggestion,
        report_case.registry,
        report_case.job.requirements.items,
        direct=False,
    )

    assert result.valid is True
    assert "REWRITE_CONFIRMATION_REQUIRED" in _codes(result)
    assert all(issue.severity is not ValidationSeverity.ERROR for issue in result.issues)


def test_high_risk_rewrite_cannot_enter_direct_collection(report_case) -> None:
    suggestion = _copy_rewrite(
        report_case,
        rewritten_text="主导Python生产部署。",
        introduced_claims=["职责强化：主导", "新增落地范围：生产部署"],
        user_confirmation_needed=["确认职责", "确认是否部署"],
    )

    result = RewriteValidator().validate(
        suggestion,
        report_case.registry,
        report_case.job.requirements.items,
        direct=True,
    )

    assert result.valid is False
    assert "REWRITE_DIRECT_HIGH_RISK" in _codes(result)


@pytest.mark.parametrize(
    ("claims", "confirmations", "expected_code"),
    [
        (["新增数字主张"], [], "REWRITE_CONFIRMATION_MISSING"),
        ([], ["请确认不存在的主张"], "REWRITE_CONFIRMATION_WITHOUT_CLAIM"),
    ],
)
def test_claim_and_confirmation_lists_must_stay_consistent(
    report_case,
    claims: list[str],
    confirmations: list[str],
    expected_code: str,
) -> None:
    suggestion = _copy_rewrite(
        report_case,
        introduced_claims=claims,
        user_confirmation_needed=confirmations,
    )

    result = RewriteValidator().validate(
        suggestion,
        report_case.registry,
        report_case.job.requirements.items,
    )

    assert result.valid is False
    assert expected_code in _codes(result)


def test_undeclared_detected_claim_is_rejected(report_case) -> None:
    suggestion = _copy_rewrite(
        report_case,
        rewritten_text="主导Python生产部署并提升效率50%。",
        introduced_claims=[],
        user_confirmation_needed=[],
    )

    result = RewriteValidator().validate(
        suggestion,
        report_case.registry,
        report_case.job.requirements.items,
    )

    assert result.valid is False
    assert "REWRITE_CLAIMS_UNDECLARED" in _codes(result)


def _copy_rewrite(report_case, **updates) -> RewriteSuggestion:
    return report_case.advice.direct_rewrites[0].model_copy(update=updates)


def _codes(result) -> set[str]:
    return {issue.code for issue in result.issues}


def _errors(result):
    return [
        issue
        for issue in result.issues
        if issue.severity is ValidationSeverity.ERROR
    ]
