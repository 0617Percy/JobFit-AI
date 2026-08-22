"""Streamlit renders only the validated report knowledge view."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from jobfit.models import (
    KnowledgeAdviceTargetType,
    KnowledgeAdviceTrace,
    KnowledgeCitationPurpose,
    KnowledgeCitationUse,
    KnowledgeContext,
    KnowledgeRetrievalStatus,
)
from jobfit.reporting import render_json, render_markdown
from jobfit.validators.report import build_analysis_report

_APP_PATH = Path(__file__).parents[2] / "app.py"
_DISCLAIMER = (
    "以下内容用于解释岗位要求，不代表候选人已具备相关能力，也不参与本次匹配评分。"
)


def _report(report_case, *, context=None, trace=None):
    return build_analysis_report(
        document=report_case.document,
        resume=report_case.resume,
        job=report_case.job,
        matches=report_case.matches,
        score=report_case.score,
        advice=report_case.advice,
        registry=report_case.registry,
        limitations=report_case.limitations,
        knowledge_context=context,
        knowledge_advice_trace=trace,
    )


def _app_with_report(report) -> AppTest:
    app = AppTest.from_file(_APP_PATH, default_timeout=20).run()
    app.session_state["analysis_report"] = report
    app.session_state["analysis_markdown"] = render_markdown(report)
    app.session_state["analysis_json"] = render_json(report)
    return app.run()


def _visible(app: AppTest) -> str:
    values = []
    for collection in (
        app.markdown,
        app.caption,
        app.info,
        app.warning,
        app.success,
        app.subheader,
        app.text,
    ):
        values.extend(item.value for item in collection)
    values.extend(str(item.value) for item in app.metric)
    return "\n".join(values)


def test_available_knowledge_has_dedicated_safe_report_tab(
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
                target_type=KnowledgeAdviceTargetType.GAP,
                target_index=0,
                purpose=KnowledgeCitationPurpose.ROLE_REQUIREMENT_CONTEXT,
                output_reference="gap:0",
            )
        ],
        validated=True,
        fallback_used=False,
        prompt_version="1.0",
        validator_version="1.0",
        generation_strategy_version="1.0",
    )
    app = _app_with_report(
        _report(
            report_case,
            context=available_knowledge_context,
            trace=trace,
        )
    )

    assert not app.exception
    assert [tab.label for tab in app.tabs] == [
        "综合结论",
        "逐项匹配",
        "简历优化",
        "面试准备",
        "岗位知识参考",
        "结构化数据",
    ]
    visible = _visible(app)
    assert _DISCLAIMER in visible
    assert "Synthetic AI application intern" in visible
    assert "Python application development" in visible
    assert "岗位通常认可的证据形式，不是候选人现有证据" in visible
    assert "Describe an application implementation." in visible
    assert "Synthetic reviewed role source" in visible
    assert "gap:0" in visible
    link_buttons = app.get("link_button")
    assert link_buttons
    assert str(link_buttons[0].url) == "https://example.test/knowledge/source"
    assert "knowledge_context" not in visible
    assert "knowledge_advice_trace" not in visible


@pytest.mark.parametrize(
    ("status", "message"),
    [
        (
            KnowledgeRetrievalStatus.DISABLED,
            "本次未启用岗位知识增强，报告仍基于简历与岗位描述完成。",
        ),
        (
            KnowledgeRetrievalStatus.UNAVAILABLE,
            "岗位知识库暂不可用，本次报告仍基于简历与岗位描述完成。",
        ),
        (
            KnowledgeRetrievalStatus.NO_MATCH,
            "未识别到足够明确的岗位画像，本次未注入岗位专属知识。",
        ),
    ],
)
def test_non_available_knowledge_has_compact_safe_state(
    status,
    message,
    available_knowledge_context,
    report_case,
) -> None:
    if status is KnowledgeRetrievalStatus.DISABLED:
        context = KnowledgeContext()
    else:
        context = KnowledgeContext(
            status=status,
            version=(
                available_knowledge_context.version
                if status is KnowledgeRetrievalStatus.NO_MATCH
                else None
            ),
            capabilities=available_knowledge_context.capabilities,
        )
    app = _app_with_report(_report(report_case, context=context))
    visible = _visible(app)

    assert message in visible
    assert "岗位要求参考" not in visible
    assert "C:\\Users\\" not in visible
    assert "SELECT " not in visible


def test_ambiguous_knowledge_shows_candidates_without_selecting_one(
    available_knowledge_context,
    report_case,
) -> None:
    first = available_knowledge_context.inferred_role_profiles[0]
    second = first.model_copy(
        update={
            "role_profile_id": "rp-synthetic-data",
            "job_family_code": "synthetic_data",
            "name": "Synthetic data intern",
            "relevance_score": Decimal("0.8800"),
        }
    )
    context = KnowledgeContext(
        status=KnowledgeRetrievalStatus.AMBIGUOUS,
        version=available_knowledge_context.version,
        inferred_role_profiles=[first, second],
        citations=available_knowledge_context.citations,
        capabilities=available_knowledge_context.capabilities,
    )
    app = _app_with_report(_report(report_case, context=context))
    visible = _visible(app)

    assert "当前岗位可能对应多个接近的岗位画像" in visible
    assert "相关度不是候选人匹配分" in visible
    assert "未选定任何最终岗位画像" in visible
    assert "Synthetic AI application intern" in visible
    assert "Synthetic data intern" in visible
    assert "岗位要求参考" not in visible


def test_fallback_and_downloads_use_the_same_validated_report(
    available_knowledge_context,
    report_case,
) -> None:
    trace = KnowledgeAdviceTrace(
        knowledge_version="2026.07.1",
        content_hash="a" * 64,
        selected_role_profile_id="rp-synthetic-ai",
        citation_uses=[],
        validated=False,
        fallback_used=True,
        prompt_version="1.0",
        validator_version="1.0",
        generation_strategy_version="1.0",
    )
    report = _report(
        report_case,
        context=available_knowledge_context,
        trace=trace,
    )
    app = _app_with_report(report)

    assert "知识增强建议已安全回退" in _visible(app)
    assert [button.label for button in app.download_button] == [
        "下载 Markdown",
        "下载 JSON",
    ]
    assert app.session_state["analysis_report"] is report
    assert "岗位知识参考" in app.session_state["analysis_markdown"]
    assert '"status": "available"' in app.session_state["analysis_json"]
    assert "knowledge_advice_trace" not in app.session_state["analysis_json"]
    app.download_button[0].click().run()
    app.download_button[1].click().run()
    assert not app.exception
    assert app.session_state["analysis_report"] is report
