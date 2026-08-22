"""Stable JSON export contract for validated reports."""

from __future__ import annotations

import json

import pytest

from jobfit.errors import ErrorCode, ReportGenerationError
from jobfit.models import (
    AnalysisReport,
    ValidationIssue,
    ValidationResult,
    ValidationSeverity,
)
from jobfit.reporting.json_export import render_json


def test_json_export_is_utf8_readable_and_preserves_chinese(
    analysis_report: AnalysisReport,
) -> None:
    rendered = render_json(analysis_report)

    assert rendered.encode("utf-8").decode("utf-8") == rendered
    assert analysis_report.job_profile.title in rendered
    assert "\\u719f\\u6089" not in rendered


def test_json_export_uses_stable_official_model_serialization(
    analysis_report: AnalysisReport,
) -> None:
    rendered = render_json(analysis_report)
    payload = json.loads(rendered)

    assert payload["schema_version"] == "1.1"
    assert payload["knowledge"]["status"] == "disabled"
    assert payload["generated_at"] == "2026-07-23T10:00:00Z"
    assert payload["score_summary"]["final_score"] == str(
        analysis_report.score_summary.final_score
    )
    assert rendered.startswith("{\n  ")


def test_json_export_round_trips_to_analysis_report(
    analysis_report: AnalysisReport,
) -> None:
    restored = AnalysisReport.model_validate_json(render_json(analysis_report))

    assert restored == analysis_report


def test_json_export_excludes_internal_and_secret_fields(
    analysis_report: AnalysisReport,
) -> None:
    rendered = render_json(analysis_report)

    assert "system_prompt" not in rendered.casefold()
    assert "raw_model_response" not in rendered.casefold()
    assert "api_key" not in rendered.casefold()
    assert "C:\\Users\\" not in rendered
    assert analysis_report.job_profile.jd_text == "[完整JD原文已从最终报告中省略]"


def test_invalid_report_cannot_be_exported(
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
        render_json(invalid)

    assert exc_info.value.code is ErrorCode.REPORT_VALIDATION_FAILED
