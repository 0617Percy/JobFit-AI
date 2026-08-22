"""Shared fail-closed guards for report renderers."""

from __future__ import annotations

from jobfit.errors import ErrorCode, ReportGenerationError
from jobfit.models import AnalysisReport, ValidationSeverity


def ensure_exportable(report: AnalysisReport) -> None:
    """Reject any report that did not pass the final validation gate."""

    has_error = any(
        issue.severity is ValidationSeverity.ERROR
        for issue in report.validation.issues
    )
    if not report.validation.valid or has_error:
        raise ReportGenerationError(
            code=ErrorCode.REPORT_VALIDATION_FAILED,
            user_message="最终报告未通过一致性校验，已禁止导出。",
            recoverable=True,
        )
    from jobfit.validators.report_knowledge import KnowledgeReportValidator

    knowledge_issues = KnowledgeReportValidator().validate(report)
    if any(
        issue.severity is ValidationSeverity.ERROR for issue in knowledge_issues
    ):
        raise ReportGenerationError(
            code=ErrorCode.REPORT_VALIDATION_FAILED,
            user_message="岗位知识报告未通过一致性校验，已禁止导出。",
            recoverable=True,
        )
