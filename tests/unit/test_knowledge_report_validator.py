"""Fail-closed validation for AnalysisReport knowledge metadata."""

from __future__ import annotations

from jobfit.models import (
    KnowledgeAdviceTargetType,
    KnowledgeAdviceTrace,
    KnowledgeCitationPurpose,
    KnowledgeCitationUse,
    KnowledgeRetrievalStatus,
    ValidationSeverity,
)
from jobfit.validators.report import ReportValidator, build_analysis_report


def _codes(result) -> set[str]:
    return {
        issue.code
        for issue in result.issues
        if issue.severity is ValidationSeverity.ERROR
    }


def test_valid_disabled_knowledge_report_revalidates(report_case) -> None:
    report = build_analysis_report(
        document=report_case.document,
        resume=report_case.resume,
        job=report_case.job,
        matches=report_case.matches,
        score=report_case.score,
        advice=report_case.advice,
        registry=report_case.registry,
        limitations=report_case.limitations,
    )

    result = ReportValidator().validate(
        report,
        document=report_case.document,
        registry=report_case.registry,
    )

    assert report.knowledge is not None
    assert report.knowledge.status is KnowledgeRetrievalStatus.DISABLED
    assert result.valid is True
    assert "knowledge_report_consistency" in result.checked_rules


def test_tampered_available_knowledge_identity_fails_closed(
    analysis_report,
    report_case,
) -> None:
    section = analysis_report.knowledge.model_copy(
        update={
            "status": KnowledgeRetrievalStatus.AVAILABLE,
            "enabled": True,
            "knowledge_version": "2026.07.1",
            "knowledge_content_hash": None,
        }
    )
    report = analysis_report.model_copy(update={"knowledge": section})

    result = ReportValidator().validate(
        report,
        document=report_case.document,
        registry=report_case.registry,
    )

    assert result.valid is False
    assert "KNOWLEDGE_REPORT_IDENTITY_INVALID" in _codes(result)


def test_unknown_used_by_target_is_rejected(
    available_knowledge_context,
    report_case,
) -> None:
    trace = KnowledgeAdviceTrace(
        knowledge_version="2026.07.1",
        content_hash="a" * 64,
        selected_role_profile_id="rp-synthetic-ai",
        citation_uses=[
            KnowledgeCitationUse(
                citation_id="cite-1111111111111111",
                target_type=KnowledgeAdviceTargetType.RECOMMENDATION,
                target_index=0,
                purpose=KnowledgeCitationPurpose.ROLE_REQUIREMENT_CONTEXT,
                output_reference="recommendation:0",
            )
        ],
        validated=True,
        fallback_used=False,
        prompt_version="1.2",
        validator_version="1.0",
        generation_strategy_version="1.0",
    )
    report = build_analysis_report(
        document=report_case.document,
        resume=report_case.resume,
        job=report_case.job,
        matches=report_case.matches,
        score=report_case.score,
        advice=report_case.advice,
        registry=report_case.registry,
        knowledge_context=available_knowledge_context,
        knowledge_advice_trace=trace,
    )
    citation = report.knowledge.citations[0].model_copy(
        update={"used_by": ["interview_question:99"]}
    )
    section = report.knowledge.model_copy(update={"citations": [citation]})
    report = report.model_copy(update={"knowledge": section})

    result = ReportValidator().validate(
        report,
        document=report_case.document,
        registry=report_case.registry,
    )

    assert result.valid is False
    assert "KNOWLEDGE_CITATION_TARGET_INVALID" in _codes(result)


def test_advice_trace_and_citation_usage_must_remain_consistent(
    available_knowledge_context,
    report_case,
) -> None:
    trace = KnowledgeAdviceTrace(
        knowledge_version="2026.07.1",
        content_hash="a" * 64,
        selected_role_profile_id="rp-synthetic-ai",
        citation_uses=[],
        validated=True,
        fallback_used=False,
        prompt_version="1.2",
        validator_version="1.0",
        generation_strategy_version="1.0",
    )
    report = build_analysis_report(
        document=report_case.document,
        resume=report_case.resume,
        job=report_case.job,
        matches=report_case.matches,
        score=report_case.score,
        advice=report_case.advice,
        registry=report_case.registry,
        knowledge_context=available_knowledge_context,
        knowledge_advice_trace=trace,
    )
    bad_trace = report.knowledge.advice_trace.model_copy(
        update={"fallback_used": True, "validated": True}
    )
    section = report.knowledge.model_copy(
        update={"advice_trace": bad_trace, "fallback_used": True}
    )
    report = report.model_copy(update={"knowledge": section})

    result = ReportValidator().validate(
        report,
        document=report_case.document,
        registry=report_case.registry,
    )

    assert result.valid is False
    assert "KNOWLEDGE_FALLBACK_CITATION_INVALID" in _codes(result)
