"""AnalysisReport 1.1 knowledge summary and backward compatibility."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from jobfit.errors import ReportGenerationError
from jobfit.models import (
    AnalysisReport,
    KnowledgeAdviceTargetType,
    KnowledgeAdviceTrace,
    KnowledgeCitationPurpose,
    KnowledgeCitationUse,
    KnowledgeContext,
    KnowledgeRetrievalStatus,
)
from jobfit.reporting.knowledge import build_report_knowledge_section
from jobfit.validators.report import build_analysis_report


def _trace() -> KnowledgeAdviceTrace:
    return KnowledgeAdviceTrace(
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


def test_new_reports_are_schema_1_1_with_disabled_knowledge_by_default(
    report_case,
) -> None:
    report = build_analysis_report(
        document=report_case.document,
        resume=report_case.resume,
        job=report_case.job,
        matches=report_case.matches,
        score=report_case.score,
        advice=report_case.advice,
        registry=report_case.registry,
        limitations=report_case.limitations,
        report_id="report-schema-1-1",
        generated_at=datetime(2026, 7, 25, 10, 0, tzinfo=UTC),
    )

    assert report.schema_version == "1.1"
    assert report.knowledge is not None
    assert report.knowledge.status is KnowledgeRetrievalStatus.DISABLED
    assert report.knowledge.enabled is False


def test_schema_1_0_payload_without_knowledge_remains_loadable(
    analysis_report: AnalysisReport,
) -> None:
    payload = analysis_report.model_dump(mode="json")
    payload["schema_version"] = "1.0"
    payload.pop("knowledge", None)

    restored = AnalysisReport.model_validate(payload)

    assert restored.schema_version == "1.0"
    assert restored.knowledge is None


def test_schema_1_0_cannot_claim_schema_1_1_knowledge(
    analysis_report: AnalysisReport,
) -> None:
    payload = analysis_report.model_dump(mode="json")
    payload["schema_version"] = "1.0"

    with pytest.raises(ValidationError):
        AnalysisReport.model_validate(payload)


def test_available_context_and_validated_trace_map_to_compact_report_models(
    available_knowledge_context,
    report_case,
) -> None:
    section = build_report_knowledge_section(
        available_knowledge_context,
        _trace(),
        report_case.advice,
    )

    assert section.status is KnowledgeRetrievalStatus.AVAILABLE
    assert section.knowledge_version == "2026.07.1"
    assert section.selected_role_profile is not None
    assert section.selected_role_profile.role_profile_id == "rp-synthetic-ai"
    assert len(section.requirements) == 1
    assert len(section.evidence_patterns) == 1
    assert len(section.interview_references) == 1
    assert section.citations[0].used_by == ["recommendation:0"]
    assert section.advice_trace is not None
    assert section.advice_trace.validated is True


def test_report_builder_persists_only_validated_advice_citations(
    available_knowledge_context,
    report_case,
) -> None:
    report = build_analysis_report(
        document=report_case.document,
        resume=report_case.resume,
        job=report_case.job,
        matches=report_case.matches,
        score=report_case.score,
        advice=report_case.advice,
        registry=report_case.registry,
        limitations=report_case.limitations,
        knowledge_context=available_knowledge_context,
        knowledge_advice_trace=_trace(),
    )

    assert report.validation.valid is True
    assert report.knowledge.citations[0].used_by == ["recommendation:0"]
    assert report.knowledge.advice_trace.used_citation_ids == [
        "cite-1111111111111111"
    ]


def test_fallback_trace_excludes_rejected_citations(
    available_knowledge_context,
    report_case,
) -> None:
    trace = _trace().model_copy(
        update={
            "citation_uses": [],
            "validated": False,
            "fallback_used": True,
        }
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

    assert report.knowledge.fallback_used is True
    assert report.knowledge.advice_trace.used_citation_ids == []
    assert all(not item.used_by for item in report.knowledge.citations)


def test_trace_from_another_knowledge_version_is_rejected(
    available_knowledge_context,
    report_case,
) -> None:
    trace = _trace().model_copy(update={"knowledge_version": "2026.07.2"})

    with pytest.raises(ReportGenerationError):
        build_report_knowledge_section(
            available_knowledge_context,
            trace,
            report_case.advice,
        )


@pytest.mark.parametrize(
    "context",
    [
        KnowledgeContext(),
        KnowledgeContext(status=KnowledgeRetrievalStatus.UNAVAILABLE),
        KnowledgeContext(status=KnowledgeRetrievalStatus.NO_MATCH),
    ],
)
def test_non_available_contexts_never_expose_role_specific_content(
    context: KnowledgeContext,
    report_case,
) -> None:
    section = build_report_knowledge_section(context, None, report_case.advice)

    assert section.selected_role_profile is None
    assert section.requirements == []
    assert section.evidence_patterns == []
    assert section.interview_references == []
    assert section.citations == []
