"""Regression boundary between v2 contracts and v1.1 production reports."""

from __future__ import annotations

from jobfit.models import AnalysisReport


def test_analysis_report_1_0_remains_readable(analysis_report: AnalysisReport) -> None:
    payload = analysis_report.model_dump(mode="json")
    payload["schema_version"] = "1.0"
    payload.pop("knowledge", None)

    restored = AnalysisReport.model_validate(payload)

    assert restored.schema_version == "1.0"
    assert restored.knowledge is None


def test_analysis_report_1_1_remains_readable(analysis_report: AnalysisReport) -> None:
    payload = analysis_report.model_dump(mode="json")

    restored = AnalysisReport.model_validate(payload)

    assert restored.schema_version == "1.1"
    assert restored.knowledge is not None
    assert restored.score_summary == analysis_report.score_summary
    assert restored.recommendation == analysis_report.recommendation
