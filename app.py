"""Streamlit entry point for the JobFit Agent product workflow."""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import streamlit as st

from jobfit.config import Settings
from jobfit.demo import (
    DEMO_COMPANY_NAME,
    DEMO_JOB_TEXT,
    DEMO_JOB_TITLE,
    DEMO_RESUME_TEXT,
    DemoRuntime,
    build_demo_runtime,
)
from jobfit.errors import JobFitError
from jobfit.models import (
    AnalysisReport,
    AnalysisRequest,
    KnowledgeRetrievalStatus,
    ProgressEvent,
    ReportCitationStatus,
    ReportKnowledgeSection,
    UploadedDocumentInput,
)
from jobfit.workflow import WorkflowCache, WorkflowOrchestrator
from jobfit.workflow.factory import (
    build_knowledge_retriever,
    build_knowledge_runtime_identity,
    build_workflow_orchestrator,
)

_MODE_MOCK = "离线Mock演示"
_MODE_PROVIDER = "生产模型"
_SOURCE_TEXT = "粘贴文本"
_SOURCE_FILE = "上传文件"
_STAGE_MESSAGES = {
    "workflow.validating_input": "正在校验输入",
    "workflow.parsing_resume": "正在解析简历",
    "workflow.extracting_resume": "正在提取简历信息",
    "workflow.extracting_job": "正在提取岗位要求",
    "workflow.retrieving_knowledge": "正在检索岗位知识",
    "workflow.matching_evidence": "正在匹配简历证据",
    "workflow.validating_matches": "正在校验证据引用",
    "workflow.scoring": "正在计算确定性匹配分",
    "workflow.generating_advice": "正在生成诊断与面试建议",
    "workflow.validating_report": "正在校验最终报告",
    "workflow.completed": "分析完成",
}
_RECOMMENDATION_LABELS = {
    "priority_apply": "建议优先投递",
    "optimize_then_apply": "可以投递，但应先优化简历",
    "try_apply": "可以尝试投递，整体匹配一般",
    "not_priority": "不建议作为当前优先岗位",
}
_MATCH_STATUS_LABELS = {
    "matched": "已匹配",
    "partial": "部分匹配",
    "unknown": "当前简历证据不足",
    "not_matched": "未匹配（存在明确冲突）",
}
_PII_EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
_PII_PHONE = re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)")
_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9\u4e00-\u9fff._-]+")


class StreamlitProgressSink:
    """Display safe stage messages without reading workflow business objects."""

    def __init__(self, progress_bar: Any, status_box: Any) -> None:
        self._progress_bar = progress_bar
        self._status_box = status_box

    def publish(self, event: ProgressEvent) -> None:
        self._progress_bar.progress(event.progress_percent)
        message = _STAGE_MESSAGES.get(event.message_key, "正在处理分析任务")
        self._status_box.info(message)


def main() -> None:
    st.set_page_config(
        page_title="JobFit Agent",
        page_icon="🎯",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    _apply_design_system()
    _initialize_session()
    _render_header()

    top_left, top_right = st.columns([1, 1], gap="large")
    with top_left:
        st.subheader("Step 1 · 简历输入")
        uploaded = st.file_uploader(
            "上传简历文件",
            type=["pdf", "docx", "txt"],
            key="resume_file",
            help="支持普通文本型PDF、DOCX和TXT；文件不会写入项目目录。",
        )
        st.radio(
            "选择简历证据源",
            [_SOURCE_TEXT, _SOURCE_FILE],
            horizontal=True,
            key="resume_source",
        )
        st.text_area(
            "粘贴简历文本",
            height=190,
            key="resume_text",
            placeholder="文件解析失败时，可在此粘贴简历文本继续分析。",
        )
        _render_resume_preview(uploaded)

    with top_right:
        st.subheader("Step 2 · 岗位信息")
        field_left, field_right = st.columns(2)
        with field_left:
            st.text_input("岗位名称（可选）", key="job_title")
        with field_right:
            st.text_input("公司名称（可选）", key="company_name")
        st.text_area(
            "岗位JD",
            height=250,
            key="jd_text",
            placeholder="粘贴完整岗位描述和任职要求。",
        )
        jd_length = len(st.session_state.jd_text)
        st.caption(f"JD字符数：{jd_length} / 30,000")
        st.button(
            "加载匿名示例",
            key="load_demo",
            width="stretch",
            on_click=_load_demo_inputs,
        )

    current_signature = _current_input_signature(
        uploaded,
        runtime_identity=_current_runtime_identity(),
    )
    _update_stale_state(current_signature)
    _render_action_area(uploaded, current_signature)
    _render_error()

    report = st.session_state.analysis_report
    if report is not None:
        if st.session_state.analysis_stale:
            st.warning(
                "输入已变化，当前结果已过期。旧报告仍保留供参考；"
                "请重新点击“开始分析”生成新结果。"
            )
        _render_results(report)


def _initialize_session() -> None:
    defaults = {
        "run_mode": _MODE_MOCK,
        "resume_source": _SOURCE_TEXT,
        "resume_text": "",
        "job_title": "",
        "company_name": "",
        "jd_text": "",
        "request_id": None,
        "parsed_preview": "",
        "analysis_report": None,
        "analysis_markdown": None,
        "analysis_json": None,
        "analysis_error": None,
        "analysis_running": False,
        "analysis_events": (),
        "analysis_fingerprint": None,
        "analysis_input_signature": None,
        "analysis_cache_hit": False,
        "analysis_stale": False,
        "last_success_at": None,
        "workflow_caches": {
            "mock": WorkflowCache(),
            "provider": WorkflowCache(),
        },
        "demo_runtime": None,
        "provider_orchestrator": None,
        "provider_knowledge_retriever": None,
        "provider_runtime_signature": None,
        "demo_call_count": 0,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _render_header() -> None:
    header_left, header_right = st.columns([3, 1])
    with header_left:
        st.title("JobFit Agent")
        st.markdown(
            "基于简历证据的岗位匹配、简历诊断与面试准备助手。"
        )
    with header_right:
        st.radio(
            "运行模式",
            [_MODE_MOCK, _MODE_PROVIDER],
            key="run_mode",
        )
    st.markdown(
        """
        <div class="jobfit-notice">
          <strong>匹配分不是录用概率。</strong>
          简历内容仅在当前会话处理；数据可能发送至你配置的模型服务。
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.session_state.run_mode == _MODE_MOCK:
        st.info(
            "当前为离线Mock演示：无需API密钥、不会访问外部网络。"
            "匿名示例可完成全流程；自定义文本可能因固定Mock证据不一致而安全失败。"
        )
    else:
        st.info(
            "生产模式只从环境变量读取模型配置；页面不会要求输入或显示密钥。"
        )
        try:
            Settings.load(demo_mode=False).validate_runtime("provider")
        except JobFitError:
            st.warning(
                "生产模式配置未完成：请在本地环境变量中设置 "
                "JOBFIT_LLM_MODEL 和 JOBFIT_LLM_API_KEY。"
            )


def _render_resume_preview(uploaded: Any) -> None:
    source = st.session_state.resume_source
    if source == _SOURCE_FILE and uploaded is not None:
        st.caption(
            f"已选择：{Path(uploaded.name).name} · "
            f"{uploaded.type or '未知类型'} · {uploaded.size} bytes"
        )
        preview = "文件将在点击分析后于内存中解析。"
    elif source == _SOURCE_TEXT and st.session_state.resume_text.strip():
        preview = _redact_preview(st.session_state.resume_text)
    else:
        preview = "尚未提供可预览的简历内容。"
    st.session_state.parsed_preview = preview
    with st.expander("有限脱敏预览", expanded=False):
        st.text(preview[:600])


def _render_action_area(uploaded: Any, current_signature: str) -> None:
    st.divider()
    st.subheader("Step 3 · 开始分析")
    progress_bar = st.progress(0)
    status_box = st.empty()
    action_left, action_right = st.columns([1, 3])
    with action_left:
        clicked = st.button(
            "开始分析",
            type="primary",
            key="analyze",
            disabled=st.session_state.analysis_running,
            width="stretch",
        )
    with action_right:
        if st.session_state.last_success_at:
            reused = " · 已复用会话缓存" if st.session_state.analysis_cache_hit else ""
            st.caption(
                f"最近成功：{st.session_state.last_success_at}{reused}"
            )
        else:
            st.caption("分析仅在明确点击后开始；页面重跑不会自动调用模型。")
    if not clicked:
        if st.session_state.analysis_events:
            latest = st.session_state.analysis_events[-1]
            progress_bar.progress(latest.progress_percent)
            status_box.info(
                _STAGE_MESSAGES.get(latest.message_key, "分析状态已保留")
            )
        return

    st.session_state.analysis_error = None
    try:
        request, selected_source = _build_request(uploaded)
        orchestrator = _get_orchestrator()
    except JobFitError as exc:
        _record_error(
            request_id=st.session_state.request_id or "未创建",
            message=exc.user_message,
            recoverable=exc.recoverable,
        )
        return
    except ValueError as exc:
        _record_error(
            request_id=st.session_state.request_id or "未创建",
            message=str(exc),
            recoverable=True,
        )
        return

    st.session_state.analysis_running = True
    sink = StreamlitProgressSink(progress_bar, status_box)
    result = orchestrator.run(
        request,
        selected_source=selected_source,
        progress=sink,
    )
    st.session_state.analysis_running = False
    st.session_state.analysis_events = result.events
    st.session_state.analysis_fingerprint = result.fingerprint
    st.session_state.analysis_cache_hit = result.cache_hit
    if st.session_state.demo_runtime is not None:
        st.session_state.demo_call_count = (
            st.session_state.demo_runtime.provider.call_count
        )
    if result.success and result.report is not None:
        st.session_state.analysis_report = result.report
        st.session_state.analysis_markdown = result.markdown
        st.session_state.analysis_json = result.json_text
        st.session_state.analysis_input_signature = current_signature
        st.session_state.analysis_stale = False
        st.session_state.last_success_at = datetime.now(UTC).strftime(
            "%Y-%m-%d %H:%M UTC"
        )
        status_box.success("分析完成，报告已通过最终一致性校验。")
    else:
        error = result.error
        _record_error(
            request_id=result.request_id,
            message=error.message if error else "分析未完成。",
            recoverable=result.recoverable,
        )


def _build_request(uploaded: Any) -> tuple[AnalysisRequest, str]:
    selected_source = (
        "text" if st.session_state.resume_source == _SOURCE_TEXT else "file"
    )
    resume_text = st.session_state.resume_text
    if selected_source == "text" and not resume_text.strip():
        raise ValueError("请先提供简历粘贴文本，或选择上传文件作为证据源。")
    if selected_source == "file" and uploaded is None:
        raise ValueError("请先上传简历文件，或选择粘贴文本作为证据源。")
    jd_text = st.session_state.jd_text
    if not jd_text.strip():
        raise ValueError("请先提供岗位JD。")
    if len(resume_text) > 50_000:
        raise ValueError("简历文本超过50,000字符限制，请精简后重试。")
    if len(jd_text) > 30_000:
        raise ValueError("岗位JD超过30,000字符限制，请精简后重试。")

    request_id = f"req-{uuid.uuid4().hex[:12]}"
    st.session_state.request_id = request_id
    upload_model = None
    if uploaded is not None:
        content = uploaded.getvalue()
        upload_model = UploadedDocumentInput(
            filename=Path(uploaded.name).name,
            media_type=uploaded.type or "application/octet-stream",
            content=content,
            size_bytes=len(content),
        )
    request = AnalysisRequest(
        request_id=request_id,
        resume_file=upload_model,
        pasted_resume_text=resume_text or None,
        job_description_text=jd_text,
        job_title=st.session_state.job_title or None,
        company_name=st.session_state.company_name or None,
        llm_mode=(
            "mock"
            if st.session_state.run_mode == _MODE_MOCK
            else "provider"
        ),
    )
    return request, selected_source


def _get_orchestrator() -> WorkflowOrchestrator:
    if st.session_state.run_mode == _MODE_MOCK:
        runtime: DemoRuntime | None = st.session_state.demo_runtime
        if runtime is None:
            runtime = build_demo_runtime(
                cache=st.session_state.workflow_caches["mock"]
            )
            st.session_state.demo_runtime = runtime
        return runtime.orchestrator

    settings = Settings.load(demo_mode=False)
    settings.validate_runtime("provider")
    runtime_signature = hashlib.sha256(
        (
            f"{settings.llm_provider}|{settings.llm_model}|"
            f"{settings.llm_base_url or ''}|"
            f"{build_knowledge_runtime_identity(settings)}"
        ).encode()
    ).hexdigest()
    if (
        st.session_state.provider_orchestrator is None
        or st.session_state.provider_runtime_signature != runtime_signature
    ):
        previous_retriever = st.session_state.provider_knowledge_retriever
        close = getattr(previous_retriever, "close", None)
        if callable(close):
            close()
        knowledge_retriever = build_knowledge_retriever(settings)
        st.session_state.provider_orchestrator = build_workflow_orchestrator(
            settings,
            cache=st.session_state.workflow_caches["provider"],
            knowledge_retriever=knowledge_retriever,
        )
        st.session_state.provider_knowledge_retriever = knowledge_retriever
        st.session_state.provider_runtime_signature = runtime_signature
    return st.session_state.provider_orchestrator


def _record_error(
    *,
    request_id: str,
    message: str,
    recoverable: bool,
) -> None:
    st.session_state.analysis_error = {
        "message": message,
        "request_id": request_id[:16],
        "recoverable": recoverable,
    }


def _render_error() -> None:
    error = st.session_state.analysis_error
    if not error:
        return
    st.error(f"分析未完成：{error['message']}")
    st.caption(f"请求ID：{error['request_id']}")
    if error["recoverable"]:
        st.info("可以修改输入后重新点击；PDF无文本层时请改用粘贴文本。")
    else:
        st.info("系统已禁止生成和下载未通过校验的报告。")


def _render_results(report: AnalysisReport) -> None:
    tabs = st.tabs(
        [
            "综合结论",
            "逐项匹配",
            "简历优化",
            "面试准备",
            "岗位知识参考",
            "结构化数据",
        ]
    )
    with tabs[0]:
        _render_summary(report)
    with tabs[1]:
        _render_matches(report)
    with tabs[2]:
        _render_rewrites(report)
    with tabs[3]:
        _render_interviews(report)
    with tabs[4]:
        _render_knowledge_reference(report.knowledge)
    with tabs[5]:
        st.caption("以下JSON来自已脱敏并通过最终校验的同一报告对象。")
        st.json(report.model_dump(mode="json"), expanded=1)

    if report.validation.valid and not st.session_state.analysis_stale:
        st.subheader("报告下载")
        download_left, download_right = st.columns(2)
        filename = _safe_report_filename(report)
        with download_left:
            st.download_button(
                "下载 Markdown",
                data=(st.session_state.analysis_markdown or "").encode("utf-8"),
                file_name=f"{filename}.md",
                mime="text/markdown; charset=utf-8",
                key="download_markdown",
                on_click="ignore",
                width="stretch",
            )
        with download_right:
            st.download_button(
                "下载 JSON",
                data=(st.session_state.analysis_json or "").encode("utf-8"),
                file_name=f"{filename}.json",
                mime="application/json; charset=utf-8",
                key="download_json",
                on_click="ignore",
                width="stretch",
            )


def _render_summary(report: AnalysisReport) -> None:
    score = report.score_summary
    metric_columns = st.columns(3)
    metric_columns[0].metric("最终匹配分", f"{score.final_score} / 100")
    metric_columns[1].metric("原始分", f"{score.raw_score} / 100")
    metric_columns[2].metric("分数上限", f"{score.score_cap} / 100")
    level = report.recommendation.level.value
    st.subheader(_RECOMMENDATION_LABELS[level])
    st.caption(f"确定性推荐等级：{level}")
    for reason in report.recommendation.reasoning:
        st.markdown(f"- {reason}")
    if report.recommendation.blocking_requirement_ids:
        st.warning(
            "阻塞或待确认要求："
            + "、".join(report.recommendation.blocking_requirement_ids)
        )
    st.markdown("#### 分维度评分")
    for dimension in score.dimension_scores:
        if dimension.active:
            st.markdown(
                f"**{dimension.category.value}** · "
                f"{dimension.earned_points}/{dimension.effective_points}"
            )
            ratio = (
                float(dimension.earned_points / dimension.effective_points)
                if dimension.effective_points
                else 0.0
            )
            st.progress(min(max(ratio, 0.0), 1.0))


def _render_matches(report: AnalysisReport) -> None:
    st.caption(
        "状态说明：unknown 表示当前简历证据不足，不等同于候选人确定不具备该能力。"
    )
    requirement_by_id = {
        item.requirement_id: item
        for item in report.job_profile.requirements.items
    }
    rows = []
    for match in report.matches:
        requirement = requirement_by_id[match.requirement_id]
        evidence = "；".join(
            " ".join(item.quote.split())[:100]
            for item in match.evidence_items
        )
        rows.append(
            {
                "岗位要求": requirement.requirement_text,
                "类型": requirement.requirement_type.value,
                "Mandatory": "是" if requirement.mandatory else "否",
                "权重": str(requirement.weight),
                "匹配状态": _MATCH_STATUS_LABELS[match.match_status.value],
                "Evidence摘要": evidence
                or match.missing_evidence_note
                or "未找到简历证据",
                "判断理由": match.reasoning,
                "改进建议": match.improvement_suggestion,
            }
        )
    st.dataframe(rows, hide_index=True, width="stretch")


def _render_rewrites(report: AnalysisReport) -> None:
    direct = [
        item
        for item in report.rewrite_suggestions
        if not item.introduced_claims and not item.user_confirmation_needed
    ]
    confirmation = [
        item
        for item in report.rewrite_suggestions
        if item.introduced_claims or item.user_confirmation_needed
    ]
    st.markdown("### 可直接采用")
    if not direct:
        st.caption("暂无可直接采用的改写。")
    for item in direct:
        with st.container(border=True):
            st.markdown(f"**原始表述：** {item.original_text}")
            st.markdown(f"**优化表述：** {item.rewritten_text}")
            st.caption(item.reason)

    st.markdown("### 需用户确认")
    st.warning("需确认内容未经核实不得直接写入简历。")
    if not confirmation:
        st.caption("当前报告没有需确认改写。")
    for item in confirmation:
        with st.container(border=True):
            st.markdown(f"**原始表述：** {item.original_text}")
            st.markdown(f"**建议表述：** {item.rewritten_text}")
            for confirmation_item in item.user_confirmation_needed:
                st.markdown(f"- {confirmation_item}")


def _render_interviews(report: AnalysisReport) -> None:
    for index, question in enumerate(report.interview_questions, start=1):
        st.markdown(f"### 面试题 {index}")
        st.markdown(question.question)
        st.caption(f"考察意图：{question.intent}")
        st.markdown("**回答框架**")
        for step in question.answer_framework:
            st.markdown(f"- {step}")
        if question.emphasis:
            st.markdown("**建议强调：** " + "；".join(question.emphasis))
        if question.risks_to_avoid:
            st.warning("风险提示：" + "；".join(question.risks_to_avoid))


def _render_knowledge_reference(
    knowledge: ReportKnowledgeSection | None,
) -> None:
    st.subheader("岗位知识参考")
    if knowledge is None:
        st.info("历史报告未记录岗位知识增强信息。")
        return

    if knowledge.status is KnowledgeRetrievalStatus.DISABLED:
        st.info("本次未启用岗位知识增强，报告仍基于简历与岗位描述完成。")
        return
    if knowledge.status is KnowledgeRetrievalStatus.UNAVAILABLE:
        st.info("岗位知识库暂不可用，本次报告仍基于简历与岗位描述完成。")
        _render_knowledge_warnings(knowledge)
        return
    if knowledge.status is KnowledgeRetrievalStatus.NO_MATCH:
        st.info("未识别到足够明确的岗位画像，本次未注入岗位专属知识。")
        _render_knowledge_warnings(knowledge)
        return
    if knowledge.status is KnowledgeRetrievalStatus.AMBIGUOUS:
        st.info(
            "当前岗位可能对应多个接近的岗位画像。"
            "为避免跨岗位知识污染，本次未注入岗位专属知识。"
        )
        st.caption("相关度不是候选人匹配分；未选定任何最终岗位画像。")
        for candidate in knowledge.role_candidates:
            st.text(
                f"{candidate.name} · 岗位族 {candidate.job_family_code} · "
                f"检索相关度 {candidate.relevance_score}"
            )
        _render_knowledge_warnings(knowledge)
        return

    st.warning(
        "以下内容用于解释岗位要求，不代表候选人已具备相关能力，"
        "也不参与本次匹配评分。"
    )
    role = knowledge.selected_role_profile
    if role is None:
        st.error("岗位知识摘要未通过完整性校验。")
        return

    info_columns = st.columns(3)
    info_columns[0].metric("知识库版本", knowledge.knowledge_version or "-")
    info_columns[1].metric("岗位画像", role.name)
    info_columns[2].metric("检索模式", knowledge.retrieval_mode.value)
    st.caption(
        f"岗位族：{role.job_family_code} · 职级：{role.seniority} · "
        f"检索相关度：{role.relevance_score}（不是候选人匹配分）"
    )
    if knowledge.knowledge_content_hash:
        st.caption(
            "版本校验信息："
            f"{knowledge.knowledge_content_hash[:10]}… · "
            f"策略 {knowledge.retrieval_strategy_version}"
        )
    if knowledge.fallback_used:
        st.warning("知识增强建议已安全回退；未通过验证的引用不会显示。")

    if knowledge.requirements:
        st.markdown("### 岗位要求参考")
        for index, requirement in enumerate(knowledge.requirements, start=1):
            with st.expander(f"岗位要求参考 {index}", expanded=False):
                st.text(requirement.title)
                st.write(requirement.description)
                st.caption(
                    f"类型：{requirement.requirement_type.value} · "
                    f"重要程度：{requirement.importance.value}"
                )
                if requirement.expected_evidence:
                    st.caption("岗位通常认可的证据形式，不是候选人现有证据：")
                    for evidence in requirement.expected_evidence:
                        st.text(f"• {evidence}")
                if requirement.is_common_hard_blocker:
                    st.caption("岗位常见门槛提示；不会自动触发本次评分封顶。")

    if knowledge.evidence_patterns:
        st.markdown("### 证据观察角度")
        st.caption("这是岗位通常认可的证据形式，不是候选人现有证据。")
        for pattern in knowledge.evidence_patterns:
            st.text(f"• [{pattern.strength.value}] {pattern.description}")

    if knowledge.interview_references:
        st.markdown("### 面试参考")
        st.caption("以下是岗位知识参考，不代表企业一定会提出这些问题。")
        for reference in knowledge.interview_references:
            st.text(f"• {reference.question}")
            st.caption(
                f"维度：{reference.competency_dimension_code} · "
                f"类型：{reference.question_type.value}"
            )

    if knowledge.citations:
        st.markdown("### 来源与引用")
        for citation in knowledge.citations:
            with st.container(border=True):
                st.text(citation.source_title)
                st.caption(
                    f"来源类型：{citation.source_type.value} · "
                    f"可靠性：{citation.reliability_level.value}"
                )
                st.write(citation.short_summary)
                if citation.source_url is not None:
                    st.link_button("打开来源", str(citation.source_url))
                with st.expander("引用详情", expanded=False):
                    st.text(f"Citation ID：{citation.citation_id}")
                    if (
                        citation.validation_status
                        is ReportCitationStatus.VALIDATED_ADVICE
                    ):
                        st.caption("以下已验证建议实际参考了此来源：")
                        for target in citation.used_by:
                            st.text(f"• {target}")
                    else:
                        st.caption("岗位参考来源；未声明为建议的实际引用。")

    _render_knowledge_warnings(knowledge)


def _render_knowledge_warnings(knowledge: ReportKnowledgeSection) -> None:
    for warning in knowledge.warnings:
        st.warning(warning.message)


def _load_demo_inputs() -> None:
    st.session_state.resume_source = _SOURCE_TEXT
    st.session_state.resume_text = DEMO_RESUME_TEXT
    st.session_state.jd_text = DEMO_JOB_TEXT
    st.session_state.job_title = DEMO_JOB_TITLE
    st.session_state.company_name = DEMO_COMPANY_NAME


def _current_runtime_identity() -> str:
    if st.session_state.run_mode == _MODE_MOCK:
        return hashlib.sha256(b"mock|knowledge-disabled").hexdigest()
    try:
        return build_knowledge_runtime_identity(Settings.load(demo_mode=False))
    except JobFitError:
        return hashlib.sha256(b"provider|knowledge-unavailable").hexdigest()


def _current_input_signature(
    uploaded: Any,
    *,
    runtime_identity: str,
) -> str:
    file_digest = ""
    if uploaded is not None:
        file_digest = hashlib.sha256(uploaded.getvalue()).hexdigest()
    return _build_input_signature(
        run_mode=st.session_state.run_mode,
        resume_source=st.session_state.resume_source,
        resume_text=st.session_state.resume_text,
        file_digest=file_digest,
        jd_text=st.session_state.jd_text,
        job_title=st.session_state.job_title,
        company_name=st.session_state.company_name,
        runtime_identity=runtime_identity,
    )


def _build_input_signature(
    *,
    run_mode: str,
    resume_source: str,
    resume_text: str,
    file_digest: str,
    jd_text: str,
    job_title: str,
    company_name: str,
    runtime_identity: str,
) -> str:
    payload = "|".join(
        [
            run_mode,
            resume_source,
            hashlib.sha256(resume_text.encode("utf-8")).hexdigest(),
            file_digest,
            hashlib.sha256(jd_text.encode("utf-8")).hexdigest(),
            job_title,
            company_name,
            runtime_identity,
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _update_stale_state(current_signature: str) -> None:
    previous = st.session_state.analysis_input_signature
    st.session_state.analysis_stale = bool(
        st.session_state.analysis_report is not None
        and previous is not None
        and current_signature != previous
    )


def _redact_preview(text: str) -> str:
    preview = _PII_EMAIL.sub("[邮箱已隐藏]", text)
    preview = _PII_PHONE.sub("[手机号已隐藏]", preview)
    return preview[:600]


def _safe_report_filename(report: AnalysisReport) -> str:
    title = report.job_profile.title or "job"
    safe_title = _SAFE_FILENAME.sub("-", title).strip("-._") or "job"
    date = report.generated_at.astimezone(UTC).strftime("%Y%m%d")
    return f"jobfit-{safe_title[:40]}-{date}"


def _apply_design_system() -> None:
    st.markdown(
        """
        <style>
        :root {
          --jobfit-accent: #1d4ed8;
          --jobfit-text: #0f172a;
          --jobfit-muted: #475569;
          --jobfit-border: #dbe3ef;
          --jobfit-surface: #f8fafc;
        }
        .stApp { background: #ffffff; color: var(--jobfit-text); }
        .block-container { max-width: 1220px; padding-top: 2rem; }
        h1, h2, h3 { letter-spacing: -0.02em; }
        .jobfit-notice {
          border: 1px solid var(--jobfit-border);
          border-left: 4px solid var(--jobfit-accent);
          background: var(--jobfit-surface);
          padding: 0.8rem 1rem;
          margin: 0.75rem 0 1rem;
          color: var(--jobfit-muted);
          border-radius: 0.35rem;
        }
        div[data-testid="stMetric"] {
          border: 1px solid var(--jobfit-border);
          padding: 0.85rem 1rem;
          border-radius: 0.5rem;
          background: #ffffff;
        }
        div[data-testid="stDownloadButton"] button {
          border-color: var(--jobfit-accent);
          color: var(--jobfit-accent);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
