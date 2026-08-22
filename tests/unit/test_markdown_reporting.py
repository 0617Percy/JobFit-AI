"""Readable and safe Markdown report rendering."""

from __future__ import annotations

import pytest

from jobfit.errors import ErrorCode, ReportGenerationError
from jobfit.models import (
    AnalysisReport,
    ValidationIssue,
    ValidationResult,
    ValidationSeverity,
)
from jobfit.reporting.markdown import render_markdown

_REQUIRED_SECTIONS = (
    "## 1. 报告信息与使用说明",
    "## 2. 岗位基本信息",
    "## 3. 综合结论",
    "## 4. 综合评分",
    "## 5. 分维度评分",
    "## 6. 岗位要求逐项匹配",
    "## 7. 核心优势",
    "## 8. 主要缺口",
    "## 9. 投递建议与投递前行动",
    "## 10. 简历内容策略",
    "## 11. 可直接采用的改写",
    "## 12. 需要用户确认的改写",
    "## 13. 面试准备",
    "## 14. 岗位知识参考",
    "## 15. 分析限制与核对提醒",
)


def test_markdown_contains_all_required_sections_and_core_values(
    analysis_report: AnalysisReport,
) -> None:
    rendered = render_markdown(analysis_report)

    for section in _REQUIRED_SECTIONS:
        assert section in rendered
    assert f"{analysis_report.score_summary.final_score}" in rendered
    assert analysis_report.recommendation.level.value in rendered
    assert "匹配分不是录用概率" in rendered
    assert "总分由确定性规则计算" in rendered
    assert "unknown表示简历证据不足" in rendered


def test_markdown_match_table_has_one_row_per_requirement(
    analysis_report: AnalysisReport,
) -> None:
    rendered = render_markdown(analysis_report)

    for requirement in analysis_report.job_profile.requirements.items:
        assert rendered.count(requirement.requirement_id) >= 1
        assert requirement.requirement_text in rendered


def test_markdown_separates_direct_and_confirmation_rewrites(
    analysis_report: AnalysisReport,
) -> None:
    confirmation_item = analysis_report.rewrite_suggestions[0].model_copy(
        update={
            "suggestion_id": "rewrite-confirmation-test",
            "rewritten_text": "主导 Python 数据处理。",
            "introduced_claims": ["职责级别强化：主导"],
            "user_confirmation_needed": ["请确认是否确实主导该工作。"],
        }
    )
    report = analysis_report.model_copy(
        update={
            "rewrite_suggestions": [
                *analysis_report.rewrite_suggestions,
                confirmation_item,
            ]
        }
    )
    rendered = render_markdown(report)
    direct = [
        item
        for item in report.rewrite_suggestions
        if not item.introduced_claims and not item.user_confirmation_needed
    ]
    confirmation = [
        item
        for item in report.rewrite_suggestions
        if item.introduced_claims or item.user_confirmation_needed
    ]

    assert direct
    assert confirmation
    for item in direct:
        direct_section = rendered.split(
            "## 11. 可直接采用的改写", 1
        )[1].split("## 12.", 1)[0]
        assert item.rewritten_text in direct_section
    for item in confirmation:
        confirmation_section = rendered.split(
            "## 12. 需要用户确认的改写", 1
        )[1].split("## 13.", 1)[0]
        assert item.rewritten_text in confirmation_section
        assert "职责级别强化：主导" in confirmation_section
        assert "请确认是否确实主导该工作。" in confirmation_section


def test_markdown_contains_exactly_five_interview_questions(
    analysis_report: AnalysisReport,
) -> None:
    rendered = render_markdown(analysis_report)

    assert rendered.count("### 面试题 ") == 5
    for question in analysis_report.interview_questions:
        assert question.question in rendered


def test_markdown_explains_unknown_as_evidence_gap(
    analysis_report: AnalysisReport,
) -> None:
    rendered = render_markdown(analysis_report)

    assert "无法判断（简历证据不足）" in rendered
    assert "当前简历未提供足够证据确认该能力" in rendered


def test_markdown_escapes_table_pipes_and_newlines(
    analysis_report: AnalysisReport,
) -> None:
    first_requirement = analysis_report.job_profile.requirements.items[0]
    escaped_requirement = first_requirement.model_copy(
        update={"requirement_text": "熟悉 Python | pandas\n并能解释"}
    )
    requirements = analysis_report.job_profile.requirements.model_copy(
        update={
            "items": [
                escaped_requirement,
                *analysis_report.job_profile.requirements.items[1:],
            ]
        }
    )
    job = analysis_report.job_profile.model_copy(
        update={"requirements": requirements}
    )
    report = analysis_report.model_copy(update={"job_profile": job})

    rendered = render_markdown(report)

    assert "熟悉 Python \\| pandas<br>并能解释" in rendered
    assert "| 熟悉 Python | pandas" not in rendered


def test_markdown_excludes_full_sources_paths_and_internal_offsets(
    analysis_report: AnalysisReport,
    report_case,
) -> None:
    rendered = render_markdown(analysis_report)

    assert report_case.document.normalized_text not in rendered
    assert report_case.job.jd_text not in rendered
    assert "start_char" not in rendered
    assert "end_char" not in rendered
    assert "C:\\Users\\" not in rendered


def test_markdown_displays_cap_reasons_when_present(
    analysis_report: AnalysisReport,
) -> None:
    score = analysis_report.score_summary.model_copy(
        update={"cap_reasons": ["存在待确认硬门槛。"]}
    )
    report = analysis_report.model_copy(update={"score_summary": score})

    rendered = render_markdown(report)

    assert "存在待确认硬门槛。" in rendered


def test_invalid_report_cannot_render_markdown(
    analysis_report: AnalysisReport,
) -> None:
    invalid = analysis_report.model_copy(
        update={
            "validation": ValidationResult(
                valid=False,
                issues=[
                    ValidationIssue(
                        code="TEST_REPORT_INVALID",
                        severity=ValidationSeverity.ERROR,
                        message="测试报告未通过校验。",
                        object_ref="report",
                    )
                ],
                checked_rules=["test_export_guard"],
            )
        }
    )

    with pytest.raises(ReportGenerationError) as exc_info:
        render_markdown(invalid)

    assert exc_info.value.code is ErrorCode.REPORT_VALIDATION_FAILED
