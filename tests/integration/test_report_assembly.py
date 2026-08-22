"""Final immutable AnalysisReport assembly and fail-closed behavior."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from jobfit.errors import ErrorCode, JobFitError
from jobfit.models import AnalysisReport, ValidationSeverity
from jobfit.validators.report import ReportValidator, build_analysis_report

_GENERATED_AT = datetime(2026, 7, 23, 8, 30, tzinfo=UTC)


def test_valid_inputs_build_frozen_roundtrippable_report(report_case) -> None:
    report = _build(report_case)

    assert report.validation.valid is True
    assert report.schema_version == "1.1"
    assert report.knowledge is not None
    assert report.report_id == "report-test"
    assert report.generated_at == _GENERATED_AT
    assert report.job_profile.jd_text == "[完整JD原文已从最终报告中省略]"
    assert report.resume_profile.basic_info.email is None
    assert AnalysisReport.model_validate_json(report.model_dump_json()) == report
    with pytest.raises(ValidationError):
        report.report_id = "changed"


def test_invalid_validation_prevents_report_creation(report_case) -> None:
    advice = replace(
        report_case.advice,
        interview_questions=report_case.advice.interview_questions[:-1],
    )

    with pytest.raises(JobFitError) as exc_info:
        _build(report_case, advice=advice)

    assert exc_info.value.code is ErrorCode.REPORT_VALIDATION_FAILED


def test_same_business_input_is_stable_except_metadata(report_case) -> None:
    first = _build(
        report_case,
        report_id="report-one",
        generated_at=_GENERATED_AT,
    )
    second = _build(
        report_case,
        report_id="report-two",
        generated_at=datetime(2026, 7, 23, 9, 30, tzinfo=UTC),
    )
    first_payload = first.model_dump(exclude={"report_id", "generated_at"})
    second_payload = second.model_dump(exclude={"report_id", "generated_at"})

    assert first_payload == second_payload


def test_built_analysis_report_can_be_revalidated(report_case) -> None:
    report = _build(report_case)

    result = ReportValidator().validate(
        report,
        document=report_case.document,
        registry=report_case.registry,
    )

    assert result.valid is True
    assert all(
        issue.severity is not ValidationSeverity.ERROR for issue in result.issues
    )


def test_invalid_rewrite_is_not_silently_included(report_case) -> None:
    unsafe = report_case.advice.direct_rewrites[0].model_copy(
        update={
            "rewritten_text": "主导生产部署并提升效率80%。",
            "introduced_claims": [],
            "user_confirmation_needed": [],
        }
    )
    advice = replace(report_case.advice, direct_rewrites=[unsafe])

    with pytest.raises(JobFitError):
        _build(report_case, advice=advice)


def _build(report_case, **updates) -> AnalysisReport:
    return build_analysis_report(
        document=report_case.document,
        resume=report_case.resume,
        job=report_case.job,
        matches=report_case.matches,
        score=report_case.score,
        advice=updates.get("advice", report_case.advice),
        registry=report_case.registry,
        limitations=report_case.limitations,
        report_id=updates.get("report_id", "report-test"),
        generated_at=updates.get("generated_at", _GENERATED_AT),
    )
