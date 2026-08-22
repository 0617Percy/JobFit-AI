"""Knowledge metadata uses the same validated report for Markdown and JSON."""

from __future__ import annotations

import json
from decimal import Decimal

from jobfit.models import KnowledgeRetrievalStatus
from jobfit.reporting import render_json, render_markdown
from jobfit.reporting.knowledge import build_report_knowledge_section
from jobfit.validators.report import build_analysis_report


def test_disabled_knowledge_is_explicit_in_both_exports(report_case) -> None:
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

    markdown = render_markdown(report)
    payload = json.loads(render_json(report))

    assert "## 14. 岗位知识参考" in markdown
    assert "本次未启用岗位知识增强" in markdown
    assert payload["schema_version"] == "1.1"
    assert payload["knowledge"]["status"] == "disabled"
    assert payload["knowledge"]["citations"] == []


def test_available_knowledge_markdown_has_disclaimer_and_source(
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
    )

    markdown = render_markdown(report)
    payload = json.loads(render_json(report))

    assert "不代表候选人已具备相关能力" in markdown
    assert "不参与本次匹配评分" in markdown
    assert "Synthetic reviewed role source" in markdown
    assert payload["knowledge"]["status"] == "available"
    assert payload["knowledge"]["selected_role_profile"]["role_profile_id"] == (
        "rp-synthetic-ai"
    )
    assert "knowledge_context" not in payload
    assert "knowledge_advice_trace" not in payload


def test_knowledge_metadata_does_not_change_deterministic_business_results(
    available_knowledge_context,
    report_case,
) -> None:
    common = {
        "document": report_case.document,
        "resume": report_case.resume,
        "job": report_case.job,
        "matches": report_case.matches,
        "score": report_case.score,
        "advice": report_case.advice,
        "registry": report_case.registry,
        "limitations": report_case.limitations,
    }
    disabled = build_analysis_report(**common)
    available = build_analysis_report(
        **common,
        knowledge_context=available_knowledge_context,
    )

    assert available.score_summary == disabled.score_summary
    assert available.matches == disabled.matches
    assert available.recommendation == disabled.recommendation
    assert available.job_profile.requirements == disabled.job_profile.requirements


def test_schema_1_0_markdown_and_json_remain_exportable(analysis_report) -> None:
    payload = analysis_report.model_dump(mode="json")
    payload["schema_version"] = "1.0"
    payload.pop("knowledge")
    legacy = analysis_report.__class__.model_validate(payload)

    assert "历史报告未记录岗位知识增强信息" in render_markdown(legacy)
    exported = json.loads(render_json(legacy))
    assert exported["schema_version"] == "1.0"
    assert exported["knowledge"] is None


def test_non_available_knowledge_states_render_without_empty_tables(
    analysis_report,
    available_knowledge_context,
    report_case,
) -> None:
    messages = {
        KnowledgeRetrievalStatus.DISABLED: "本次未启用岗位知识增强",
        KnowledgeRetrievalStatus.UNAVAILABLE: "知识库暂不可用",
        KnowledgeRetrievalStatus.NO_MATCH: "未识别到足够明确的岗位画像",
        KnowledgeRetrievalStatus.AMBIGUOUS: "岗位画像存在歧义",
    }
    first_role = available_knowledge_context.inferred_role_profiles[0]
    contexts = {
        KnowledgeRetrievalStatus.DISABLED: available_knowledge_context.__class__(),
        KnowledgeRetrievalStatus.UNAVAILABLE: available_knowledge_context.__class__(
            status=KnowledgeRetrievalStatus.UNAVAILABLE
        ),
        KnowledgeRetrievalStatus.NO_MATCH: available_knowledge_context.__class__(
            status=KnowledgeRetrievalStatus.NO_MATCH,
            version=available_knowledge_context.version,
            capabilities=available_knowledge_context.capabilities,
        ),
        KnowledgeRetrievalStatus.AMBIGUOUS: available_knowledge_context.__class__(
            status=KnowledgeRetrievalStatus.AMBIGUOUS,
            version=available_knowledge_context.version,
            inferred_role_profiles=[
                first_role,
                first_role.model_copy(
                    update={
                        "role_profile_id": "rp-synthetic-data",
                        "name": "Synthetic data intern",
                        "relevance_score": Decimal("0.8800"),
                    }
                ),
            ],
            citations=available_knowledge_context.citations,
            capabilities=available_knowledge_context.capabilities,
        ),
    }
    for status, message in messages.items():
        section = build_report_knowledge_section(
            contexts[status],
            None,
            report_case.advice,
        )
        report = analysis_report.model_copy(update={"knowledge": section})
        rendered = render_markdown(report)
        knowledge_part = rendered.split("## 14. 岗位知识参考", 1)[1]
        assert message in knowledge_part
        assert "| 岗位要求 |" not in knowledge_part
