"""Canonical JSON export for validated AnalysisReport objects."""

from __future__ import annotations

from jobfit.models import AnalysisReport
from jobfit.reporting._guards import ensure_exportable


def render_json(report: AnalysisReport) -> str:
    """Serialize one validated report through its official Pydantic model."""

    ensure_exportable(report)
    return report.model_dump_json(indent=2, ensure_ascii=False)
