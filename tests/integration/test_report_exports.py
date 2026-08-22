"""Markdown and JSON exports share one validated AnalysisReport source."""

from __future__ import annotations

import json

from jobfit.models import AnalysisReport
from jobfit.reporting.json_export import render_json
from jobfit.reporting.markdown import render_markdown


def test_exports_share_core_values_and_counts(
    analysis_report: AnalysisReport,
) -> None:
    markdown = render_markdown(analysis_report)
    payload = json.loads(render_json(analysis_report))

    assert str(payload["score_summary"]["final_score"]) in markdown
    assert payload["recommendation"]["level"] in markdown
    assert len(payload["job_profile"]["requirements"]["items"]) == len(
        analysis_report.job_profile.requirements.items
    )
    assert len(payload["matches"]) == len(
        analysis_report.matches
    )
    assert len(payload["rewrite_suggestions"]) == len(
        analysis_report.rewrite_suggestions
    )
    assert len(payload["interview_questions"]) == 5
    assert markdown.count("### 面试题 ") == 5


def test_renderers_do_not_modify_report(
    analysis_report: AnalysisReport,
) -> None:
    before = analysis_report.model_dump_json()

    render_json(analysis_report)
    render_markdown(analysis_report)

    assert analysis_report.model_dump_json() == before


def test_repeated_exports_are_stable(
    analysis_report: AnalysisReport,
) -> None:
    assert render_json(analysis_report) == render_json(analysis_report)
    assert render_markdown(analysis_report) == render_markdown(analysis_report)
