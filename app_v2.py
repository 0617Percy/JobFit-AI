"""Public Beta Streamlit UI for the validated v2 analysis pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit as st

from jobfit.config import Settings
from jobfit.demo_v2 import DEMO_JD_TEXT, DEMO_RESUME_TEXT, build_demo_runtime
from jobfit.errors import (
    ConfigurationError,
    DocumentParseError,
    ErrorCode,
    InputError,
    JobFitError,
    LLMError,
)
from jobfit.llm.deepseek_provider import DEEPSEEK_MODELS, DeepSeekProvider
from jobfit.llm.exceptions import (
    ProviderAuthenticationError,
    ProviderConnectionError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTimeoutError,
)
from jobfit.models.v2 import (
    ClarificationAnswer,
    ClarificationAnswerStatus,
    ClarificationAnswerType,
)
from jobfit.parsers.router import DocumentParserRouter
from jobfit.parsers.text import TextDocumentParser
from jobfit.runtime_v2 import build_deepseek_runtime
from jobfit.scoring.v2 import SeniorityFacts
from jobfit.semantic.v2 import SemanticPromptError
from jobfit.semantic.v2.severity import SemanticValidationSeverity
from jobfit.ui.presentation_translation import (
    DeepSeekPresentationTranslator,
    PresentationTranslationError,
    presentation_translation_cache_key,
)
from jobfit.ui.v2 import build_presentation_translation_items, render_v2_report
from jobfit.workflow.v2 import (
    AnalysisRepository,
    build_analysis_repository,
    stable_run_identity,
)

_STAGES = ("home", "clarification", "analyzing", "report")
_STAGE_LABELS = {
    "home": "① 上传材料",
    "resume": "① 上传材料",
    "jd": "① 上传材料",
    "clarification": "② 信息确认",
    "analyzing": "③ 分析结果",
    "report": "③ 分析结果",
    "update": "① 上传材料",
}


def main() -> None:
    st.set_page_config(page_title="JobFit AI｜岗位适配分析助手", layout="wide")
    _initialize_state()
    _render_page_style()
    st.title("JobFit AI")
    st.markdown('<span class="jobfit-beta">Beta</span>', unsafe_allow_html=True)
    st.markdown("### 岗位适配分析助手")
    _render_runtime_settings()
    st.caption("上传你的简历和目标岗位，获得岗位匹配、投递建议、简历优化与面试准备。")
    stage = st.session_state.v2_stage
    st.progress(
        {
            "home": 1 / 3,
            "clarification": 2 / 3,
            "analyzing": 1.0,
            "report": 1.0,
        }[stage]
    )
    st.caption(_STAGE_LABELS[stage])
    {
        "home": _render_home,
        "clarification": _render_clarification,
        "analyzing": _render_analyzing,
        "report": _render_report,
    }[stage]()
    st.divider()
    st.caption(
        "JobFit AI 当前为 Beta 版本。分析结果用于辅助求职决策，"
        "请结合岗位实际要求与个人情况判断。"
    )


def _render_page_style() -> None:
    st.markdown(
        """
        <style>
        .block-container {max-width: 1160px; padding-top: 2rem; padding-bottom: 3rem;}
        .jobfit-beta {
            display: inline-block; padding: .15rem .55rem; border-radius: 999px;
            background: #eef2ff; color: #4338ca; font-size: .78rem; font-weight: 700;
            border: 1px solid #c7d2fe;
        }
        [data-testid="stMetric"] {
            background: #f8fafc; border: 1px solid #e2e8f0;
            border-radius: .75rem; padding: .75rem 1rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _initialize_state() -> None:
    if "v2_history" not in st.session_state:
        st.session_state.v2_history = _build_history()
    defaults: dict[str, Any] = {
        "v2_stage": "home",
        "v2_resume_source": "粘贴文本",
        "v2_resume_text": "",
        "v2_jd_text": "",
        "v2_application": None,
        "v2_session": None,
        "v2_resume_document": None,
        "v2_parent_analysis_id": None,
        "v2_revision": len(st.session_state.v2_history.list_analyses()),
        "v2_error": None,
        "v2_runtime_mode": "Offline Demo / Mock",
        "v2_deepseek_api_key": "",
        "v2_deepseek_model": "deepseek-v4-flash",
        "v2_deepseek_thinking": False,
        "v2_deepseek_consent": False,
        "v2_runtime_provider": "mock",
        "v2_runtime_model": "jobfit-v2-rc-mock",
        "v2_analysis_attempted": False,
        "v2_presentation_translator": None,
        "v2_presentation_translation_cache": {},
        "v2_presentation_translation_failures": set(),
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _build_history() -> AnalysisRepository:
    settings = Settings.load()
    return build_analysis_repository(
        settings,
        repository_root=Path(__file__).resolve().parent,
    )


def _render_runtime_settings() -> None:
    with st.sidebar:
        st.subheader("模型设置")
        st.radio(
            "分析模式",
            ("Offline Demo / Mock", "DeepSeek BYOK"),
            key="v2_runtime_mode",
            format_func=lambda value: {
                "Offline Demo / Mock": "演示模式",
                "DeepSeek BYOK": "DeepSeek 分析",
            }[value],
        )
        st.text_input(
            "DeepSeek API Key",
            type="password",
            key="v2_deepseek_api_key",
            help="仅保留在当前Streamlit会话内；请勿写入源码或.env。",
        )
        st.caption("API Key仅保存在当前会话，请勿写入源码或.env。")
        if st.session_state.v2_deepseek_api_key.strip():
            st.caption("当前会话已配置API Key。")
        else:
            st.caption("当前会话未配置API Key。")
        st.selectbox(
            "模型",
            DEEPSEEK_MODELS,
            key="v2_deepseek_model",
            format_func=lambda value: {
                "deepseek-v4-flash": "DeepSeek V4 Flash",
                "deepseek-v4-pro": "DeepSeek V4 Pro",
            }[value],
        )
        st.checkbox("启用思考模式", key="v2_deepseek_thinking")
        if st.button("验证DeepSeek连接", key="v2_deepseek_check"):
            _check_deepseek_connection()
        st.button(
            "清除API Key",
            key="v2_deepseek_clear",
            on_click=_clear_deepseek_key,
        )
        if st.session_state.v2_runtime_mode == "DeepSeek BYOK":
            st.warning(
                "本次分析将把完成分析所需的简历、岗位描述及相关分析上下文"
                "发送至DeepSeek API处理。"
            )
            st.checkbox(
                "我已了解并同意本次分析使用DeepSeek API处理上述内容",
                key="v2_deepseek_consent",
            )


def _check_deepseek_connection() -> None:
    api_key = st.session_state.v2_deepseek_api_key.strip()
    if not api_key:
        st.warning("请先输入DeepSeek API Key。")
        return
    try:
        DeepSeekProvider(api_key=api_key).check_connection()
    except LLMError as exc:
        st.error(_deepseek_connection_error(exc))
    else:
        st.success("DeepSeek连接成功")


def _deepseek_connection_error(error: LLMError) -> str:
    cause = error.cause
    if error.code is ErrorCode.LLM_AUTH_FAILED or isinstance(
        cause, ProviderAuthenticationError
    ):
        return "API Key无效。"
    if isinstance(cause, ProviderTimeoutError):
        return "DeepSeek请求超时，请稍后重试。"
    if isinstance(cause, ProviderConnectionError):
        return "DeepSeek网络连接失败，请检查网络后重试。"
    if isinstance(cause, ProviderRateLimitError):
        return "DeepSeek请求频率受限，请稍后重试。"
    return "DeepSeek服务返回异常响应，请稍后重试。"


def _clear_deepseek_key() -> None:
    st.session_state.v2_deepseek_api_key = ""
    st.session_state.v2_deepseek_consent = False
    st.session_state.v2_application = None
    st.session_state.v2_session = None
    st.session_state.v2_runtime_provider = "mock"
    st.session_state.v2_presentation_translator = None
    st.session_state.v2_presentation_translation_cache = {}
    st.session_state.v2_presentation_translation_failures = set()
    st.session_state.v2_runtime_model = "jobfit-v2-rc-mock"


def _render_home() -> None:
    st.subheader("上传材料")
    st.write(
        "上传你的简历和目标岗位，AI 会先提取关键信息；"
        "你可以在生成最终结果前进行确认。"
    )
    st.radio(
        "简历来源",
        ["粘贴文本", "上传文件"],
        horizontal=True,
        key="v2_resume_source",
    )
    uploaded = None
    if st.session_state.v2_resume_source == "粘贴文本":
        st.text_area("简历", height=220, key="v2_resume_text")
    else:
        uploaded = st.file_uploader(
            "上传 PDF、DOCX 或 TXT 简历",
            type=["pdf", "docx", "txt"],
            key="v2_resume_file",
        )
    st.text_area("目标岗位 JD", height=240, key="v2_jd_text")
    st.button("加载匿名演示", key="v2_load_demo", on_click=_load_demo)
    _show_error()
    if st.button("开始岗位分析", type="primary", key="v2_start_analysis"):
        try:
            st.session_state.v2_resume_document = _parse_resume(uploaded)
            _prepare_analysis()
        except (OSError, ValueError, InputError, DocumentParseError) as exc:
            del exc
            st.session_state.v2_error = "请检查简历和岗位描述是否完整、格式是否可读取。"
        except (JobFitError, SemanticPromptError) as exc:
            st.session_state.v2_error = _analysis_error_message(exc)
        else:
            st.session_state.v2_error = None
            st.session_state.v2_analysis_attempted = False
            st.session_state.v2_stage = "clarification"
        st.rerun()


def _delete_analysis_chain(analysis_id: str) -> int:
    deleted = st.session_state.v2_history.delete_analysis_chain(analysis_id)
    session = st.session_state.v2_session
    if session is not None and st.session_state.v2_history.get_analysis(
        session.run.analysis_id
    ) is None:
        st.session_state.v2_session = None
        st.session_state.v2_application = None
        st.session_state.v2_parent_analysis_id = None
    return deleted


def _delete_all_history() -> int:
    deleted = st.session_state.v2_history.delete_all_analysis_data()
    st.session_state.v2_session = None
    st.session_state.v2_application = None
    st.session_state.v2_parent_analysis_id = None
    st.session_state.v2_revision = 0
    return deleted


def _render_resume() -> None:
    st.subheader(_STAGE_LABELS["resume"])
    st.radio(
        "简历来源",
        ["粘贴文本", "上传文件"],
        horizontal=True,
        key="v2_resume_source",
    )
    uploaded = st.file_uploader(
        "上传PDF、DOCX或TXT",
        type=["pdf", "docx", "txt"],
        key="v2_resume_file",
    )
    st.text_area("简历文本", height=240, key="v2_resume_text")
    st.button("加载匿名演示", key="v2_load_demo", on_click=_load_demo)
    _show_error()
    if st.button("继续到岗位描述", type="primary", key="v2_continue_resume"):
        try:
            st.session_state.v2_resume_document = _parse_resume(uploaded)
        except (OSError, ValueError) as exc:
            del exc
            st.session_state.v2_error = "无法安全解析简历，请检查文件或改用粘贴文本。"
        else:
            st.session_state.v2_error = None
            st.session_state.v2_stage = "jd"
        st.rerun()


def _render_jd() -> None:
    st.subheader(_STAGE_LABELS["jd"])
    st.caption("一次分析只处理一个岗位；系统将从当前 JD 中识别岗位方向。")
    st.text_area("岗位描述（JD）", height=280, key="v2_jd_text")
    _show_error()
    if st.button("解析并进入确认", type="primary", key="v2_continue_jd"):
        try:
            _prepare_analysis()
        except (InputError, DocumentParseError) as exc:
            del exc
            st.session_state.v2_error = "输入未能通过v2结构化校验，请核对简历和岗位描述。"
        except (JobFitError, SemanticPromptError) as exc:
            st.session_state.v2_error = _analysis_error_message(exc)
        else:
            st.session_state.v2_error = None
            st.session_state.v2_stage = "clarification"
        st.rerun()


def _analysis_error_message(error: JobFitError | SemanticPromptError) -> str:
    if isinstance(error, SemanticPromptError):
        stage = {
            "P01": "P01简历事实提取阶段",
            "P02": "P02岗位描述解析阶段",
            "P03": "P03岗位要求分类阶段",
            "P04": "P04简历证据规范化阶段",
            "P05": "P05语义匹配阶段",
            "P06": "P06行动建议生成阶段",
            "P07": "P07面试准备生成阶段",
            "P08": "P08报告生成阶段",
            "PIPELINE": "P01-P05联合校验阶段",
        }.get(error.prompt_id, "语义分析阶段")
        severity = _semantic_error_severity(error)
        if error.code in {"INVALID_JSON", "SCHEMA_INVALID"} or error.code.startswith(
            "STRICT_"
        ):
            category = "模型返回结果未通过结构化校验"
        elif severity is SemanticValidationSeverity.HARD_BLOCK:
            category = "模型结果未通过安全校验"
        elif (
            severity is SemanticValidationSeverity.RECOVERABLE_ERROR
            or error.code
            in {
                "BUSINESS_VALIDATION_FAILED",
                "CROSS_OBJECT_VALIDATION_FAILED",
                "FOUR_LAYER_VALIDATION_FAILED",
                "REPORT_ASSEMBLY_VALIDATION_FAILED",
            }
        ):
            category = "模型结果未通过JobFit业务校验"
        else:
            category = "模型结果未通过安全校验"
        message = f"DeepSeek调用失败：{stage}；{category}，本次分析未完成，请重试。"
        diagnostics = _safe_schema_diagnostic(error)
        return f"{message} {diagnostics}" if diagnostics else message

    if isinstance(error, LLMError):
        cause = error.cause
        if error.code is ErrorCode.LLM_AUTH_FAILED or isinstance(
            cause, ProviderAuthenticationError
        ):
            return "DeepSeek API Key验证失败，请检查后重试。"
        if isinstance(cause, ProviderTimeoutError):
            return "DeepSeek请求超时，请稍后重试。"
        if isinstance(cause, ProviderConnectionError):
            return "DeepSeek连接失败，请检查网络后重试。"
        if isinstance(cause, ProviderRateLimitError):
            return "DeepSeek请求频率受限，请稍后重试。"
        if isinstance(cause, ProviderResponseError):
            return "DeepSeek未返回有效结构化内容，本次分析未完成，请重试。"
        return "DeepSeek服务暂时不可用，本次分析未完成，请稍后重试。"

    return error.user_message


def _safe_schema_diagnostic(error: SemanticPromptError) -> str:
    attempts: list[str] = []
    for attempt in error.attempts:
        if attempt.validation_issues:
            summary = "；".join(
                (
                    f"{issue.safe_path} — {issue.category} "
                    f"[{issue.severity.value}]"
                )
                for issue in attempt.validation_issues
            )
            attempts.append(f"第{attempt.attempt}次（{attempt.stage}）：{summary}")
            continue
        safe_categories = (
            attempt.validation_categories
            if attempt.validation_categories
            else attempt.validation_types
        )
        issues = tuple(
            zip(attempt.validation_paths, safe_categories, strict=True)
        )
        if not issues:
            continue
        summary = "；".join(f"{path} — {error_type}" for path, error_type in issues)
        attempts.append(f"第{attempt.attempt}次（{attempt.stage}）：{summary}")
    if not attempts:
        return ""
    return "安全诊断（仅字段路径与错误类型）：" + "；".join(attempts)


def _semantic_error_severity(
    error: SemanticPromptError,
) -> SemanticValidationSeverity | None:
    issues = tuple(
        issue
        for attempt in error.attempts
        for issue in attempt.validation_issues
    )
    if not issues:
        return None
    if any(issue.severity is SemanticValidationSeverity.HARD_BLOCK for issue in issues):
        return SemanticValidationSeverity.HARD_BLOCK
    if any(
        issue.severity is SemanticValidationSeverity.RECOVERABLE_ERROR
        for issue in issues
    ):
        return SemanticValidationSeverity.RECOVERABLE_ERROR
    return SemanticValidationSeverity.QUALITY_WARNING


def _prepare_analysis() -> None:
    resume_document = st.session_state.v2_resume_document
    if resume_document is None:
        raise InputError(
            code=ErrorCode.INPUT_EMPTY,
            user_message="Resume document is missing.",
            recoverable=True,
        )
    jd_text = st.session_state.v2_jd_text.strip()
    if not jd_text:
        raise InputError(
            code=ErrorCode.INPUT_EMPTY,
            user_message="JD is empty.",
            recoverable=True,
        )
    jd_document = TextDocumentParser().parse_text(jd_text)
    revision = int(st.session_state.v2_revision) + 1
    st.session_state.v2_revision = revision
    resume_version_id = f"resume-{resume_document.content_sha256[:16]}-{revision}"
    jd_snapshot_id = f"jd-{jd_document.content_sha256[:16]}-{revision}"
    analysis_id = stable_run_identity(
        resume_version_id,
        jd_snapshot_id,
        str(revision),
    )
    runtime = _build_selected_runtime(
        resume_document=resume_document,
        jd_document=jd_document,
        resume_version_id=resume_version_id,
        jd_snapshot_id=jd_snapshot_id,
    )
    session = runtime.application.prepare_analysis(
        analysis_id=analysis_id,
        resume_version_id=resume_version_id,
        jd_snapshot_id=jd_snapshot_id,
        resume_document=resume_document,
        jd_document=jd_document,
        seniority_facts=SeniorityFacts(explicit_entry_scope=True),
        parent_analysis_id=st.session_state.v2_parent_analysis_id,
        reanalysis_reason="User requested a new resume or JD analysis.",
    )
    st.session_state.v2_application = runtime.application
    st.session_state.v2_session = session
    st.session_state.v2_presentation_translation_cache = {}
    st.session_state.v2_presentation_translation_failures = set()
    st.session_state.v2_presentation_translator = (
        DeepSeekPresentationTranslator(
            provider=runtime.provider,
            model=st.session_state.v2_runtime_model,
        )
        if st.session_state.v2_runtime_provider == "deepseek"
        else None
    )


def _build_selected_runtime(
    *,
    resume_document,
    jd_document,
    resume_version_id: str,
    jd_snapshot_id: str,
):
    if st.session_state.v2_runtime_mode == "Offline Demo / Mock":
        st.session_state.v2_runtime_provider = "mock"
        st.session_state.v2_runtime_model = "jobfit-v2-rc-mock"
        return build_demo_runtime(
            resume_document=resume_document,
            jd_document=jd_document,
            history=st.session_state.v2_history,
            resume_version_id=resume_version_id,
            jd_snapshot_id=jd_snapshot_id,
        )
    if not st.session_state.v2_deepseek_consent:
        raise ConfigurationError(
            code=ErrorCode.CONFIG_INVALID,
            user_message="请先确认同意本次分析使用DeepSeek API处理所述内容。",
            recoverable=True,
        )
    api_key = st.session_state.v2_deepseek_api_key.strip()
    if not api_key:
        raise ConfigurationError(
            code=ErrorCode.LLM_CREDENTIALS_MISSING,
            user_message="请先输入DeepSeek API Key。",
            recoverable=True,
        )
    model = st.session_state.v2_deepseek_model
    st.session_state.v2_runtime_provider = "deepseek"
    st.session_state.v2_runtime_model = model
    return build_deepseek_runtime(
        api_key=api_key,
        model=model,
        thinking_enabled=st.session_state.v2_deepseek_thinking,
        history=st.session_state.v2_history,
    )


def _render_clarification() -> None:
    st.subheader("信息确认")
    st.write("在生成完整分析前，请确认 AI 对你的简历和岗位要求理解是否准确。")
    session = st.session_state.v2_session
    if session is None:
        st.error("没有可确认的分析，请重新开始。")
        return
    _render_confirmation_summary(session)
    questions = session.pending_questions[:3]
    if not questions:
        st.success("结构化输入已确认；本次没有必须补充的问题。")
    else:
        st.caption(f"需要确认 {len(questions)} 项；最多展示3项。")
        for question in questions:
            st.markdown(f"**{question.prompt_text}**")
            st.caption(question.why_this_question_exists)
            _render_answer_controls(question)
    action_columns = st.columns([2, 1])
    if action_columns[0].button(
        "确认并生成完整报告", type="primary", key="v2_confirm_continue"
    ):
        try:
            session = _apply_answers(session, questions)
            if session.pending_questions:
                st.session_state.v2_error = "仍有问题未解决；可选择跳过后继续。"
            else:
                session = st.session_state.v2_application.begin_analysis(session)
                st.session_state.v2_session = session
                st.session_state.v2_stage = "analyzing"
                st.session_state.v2_error = None
                st.session_state.v2_analysis_attempted = False
        except ValueError as exc:
            del exc
            st.session_state.v2_error = "澄清内容未通过边界校验，请检查回答状态。"
        st.rerun()
    if action_columns[1].button("返回修改", key="v2_back_to_inputs"):
        st.session_state.v2_stage = "home"
        st.session_state.v2_error = None
        st.rerun()
    _show_error()


def _render_confirmation_summary(session) -> None:
    st.markdown("#### 简历信息")
    profile = session.resume_profile
    candidate = profile.candidate_profile
    profile_columns = st.columns(3)
    profile_columns[0].metric("教育背景", candidate.education_level or "待确认")
    profile_columns[1].metric("当前阶段", candidate.current_status.value)
    profile_columns[2].metric(
        "全职经验",
        _experience_label(candidate.years_of_full_time_experience),
    )
    for label, records in (
        ("项目经历", profile.projects),
        ("实习 / 工作经历", [*profile.internships, *profile.work_experience]),
        ("技能与工具", profile.skills),
        ("竞赛 / 其他经历", [*profile.competitions, *profile.achievements]),
    ):
        st.markdown(f"**{label}**")
        rendered = [_friendly_resume_item(item) for item in records]
        rendered = [item for item in rendered if item]
        if rendered:
            for item in rendered:
                st.markdown(f"- {item}")
        else:
            st.caption("当前材料中未提取到明确内容。")

    st.markdown("#### 岗位要求")
    st.markdown(f"**目标岗位：** {session.job_profile.job_title}")
    for requirement in session.requirements:
        requirement_type = {
            "hard": "关键门槛",
            "core": "核心能力",
            "preferred": "加分项",
            "supporting": "其他要求",
            "implicit": "岗位背景参考",
        }.get(requirement.requirement_type.value, "岗位要求")
        st.markdown(f"- **{requirement_type}** · {requirement.normalized_capability}")


def _experience_label(value) -> str:
    return "待确认" if value is None else f"{value} 年"


def _friendly_resume_item(value: object) -> str:
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        return ""
    label = value.get("label") or value.get("title") or value.get("name")
    details = value.get("details")
    detail = ""
    if isinstance(details, dict):
        detail = str(details.get("summary") or details.get("source") or "")
    if label and detail:
        return f"{label}：{detail}"
    return str(label or detail)


def _render_answer_controls(question) -> None:
    status_key = f"v2_answer_status_{question.question_id}"
    st.selectbox(
        "处理方式",
        ["answered", "skipped", "unable_to_confirm"],
        key=status_key,
    )
    schema = question.answer_schema
    value_key = f"v2_answer_value_{question.question_id}"
    if schema.answer_type is ClarificationAnswerType.BOOLEAN:
        st.checkbox("确认符合", key=value_key)
    elif schema.answer_type is ClarificationAnswerType.ENUM:
        st.selectbox("答案", schema.allowed_values, key=value_key)
    elif schema.answer_type is ClarificationAnswerType.MULTI_SELECT:
        st.multiselect("答案", schema.allowed_values, key=value_key)
    elif schema.answer_type is ClarificationAnswerType.NUMBER_RANGE:
        st.number_input(
            "答案",
            min_value=float(schema.minimum),
            max_value=float(schema.maximum),
            key=value_key,
        )
    else:
        st.text_input("简短事实", key=value_key)


def _apply_answers(session, questions):
    for index, question in enumerate(questions, start=1):
        status = ClarificationAnswerStatus(
            st.session_state[f"v2_answer_status_{question.question_id}"]
        )
        value = (
            st.session_state.get(f"v2_answer_value_{question.question_id}")
            if status is ClarificationAnswerStatus.ANSWERED
            else None
        )
        answer = ClarificationAnswer(
            question_id=question.question_id,
            analysis_id=session.run.analysis_id,
            status=status,
            value=value,
            raw_text=str(value) if status is ClarificationAnswerStatus.ANSWERED else None,
            answer_sequence=index,
        )
        session = st.session_state.v2_application.answer_clarification(
            session,
            question_id=question.question_id,
            answer=answer,
        )
    st.session_state.v2_session = session
    return session


def _render_analyzing() -> None:
    st.subheader("正在生成完整分析")
    session = st.session_state.v2_session
    if session is None:
        st.error("分析状态缺失。")
        return
    for message in (
        "正在计算岗位匹配情况…",
        "正在整理优势与待补强项…",
        "正在生成简历优化建议…",
        "正在准备面试问题…",
        "正在生成完整分析报告…",
    ):
        st.write(message)
    if st.session_state.v2_error:
        _show_analysis_error()
        return
    if not st.session_state.get("v2_analysis_attempted", False):
        st.session_state.v2_analysis_attempted = True
        try:
            st.session_state.v2_session = st.session_state.v2_application.finish_analysis(
                session
            )
        except (JobFitError, SemanticPromptError) as exc:
            st.session_state.v2_error = _analysis_error_message(exc)
        except ValueError as exc:
            del exc
            st.session_state.v2_error = "建议或报告未通过验证，未生成部分可信结果。"
        else:
            st.session_state.v2_stage = "report"
            st.session_state.v2_error = None
        st.rerun()


def _show_analysis_error() -> None:
    st.error("本次分析未能完成，请重新尝试。")
    with st.expander("技术诊断信息", expanded=False):
        st.code(st.session_state.v2_error)
    if st.button("重新分析", type="primary", key="v2_retry_analysis"):
        st.session_state.v2_error = None
        st.session_state.v2_analysis_attempted = False
        st.rerun()


def _render_report() -> None:
    st.subheader("分析结果")
    session = st.session_state.v2_session
    if session is None or session.advisory_result is None:
        st.error("已验证报告不可用。")
        return
    report = session.advisory_result.report
    translations = _presentation_translations(report)
    render_v2_report(report, translations=translations)
    serialized = report.model_dump_json(indent=2)
    st.download_button(
        "下载v2 JSON",
        serialized,
        file_name=f"{report.report_id}.json",
        mime="application/json",
        key="v2_download_json",
    )
    st.divider()
    if st.button("分析另一个岗位", type="primary", key="v2_analyze_another_job"):
        _reset_for_new_analysis()
        st.rerun()


def _reset_for_new_analysis() -> None:
    st.session_state.v2_stage = "home"
    st.session_state.v2_application = None
    st.session_state.v2_session = None
    st.session_state.v2_resume_document = None
    st.session_state.v2_parent_analysis_id = None
    st.session_state.v2_error = None
    st.session_state.v2_analysis_attempted = False
    st.session_state.v2_presentation_translator = None
    st.session_state.v2_presentation_translation_cache = {}
    st.session_state.v2_presentation_translation_failures = set()
    st.session_state.v2_resume_text = ""
    st.session_state.v2_jd_text = ""


def _presentation_translations(report) -> dict[str, str]:
    items = build_presentation_translation_items(report)
    translator = st.session_state.v2_presentation_translator
    if translator is None or not items:
        return {}
    cache_key = presentation_translation_cache_key(report.report_id, items)
    cache = st.session_state.v2_presentation_translation_cache
    if cache_key in cache:
        return dict(cache[cache_key])
    failures = st.session_state.v2_presentation_translation_failures
    if cache_key not in failures:
        try:
            translations = translator.translate(items)
        except PresentationTranslationError:
            failures.add(cache_key)
        else:
            cache[cache_key] = dict(translations)
            return dict(translations)
    st.warning("部分分析说明暂未完成中文转换，可重新尝试中文化显示。")
    if st.button(
        "重新生成中文显示",
        key="v2_retry_presentation_translation",
    ):
        failures.discard(cache_key)
        st.rerun()
    return {}


def _render_update() -> None:
    st.subheader(_STAGE_LABELS["update"])
    st.info("更新会创建新的Analysis Run，不会覆盖已完成结果。")
    history = st.session_state.v2_history.list_analysis_versions()
    st.caption(f"本机已保留 {len(history)} 个不可变终态版本。")
    if st.button("编辑新版简历", type="primary", key="v2_edit_resume"):
        st.session_state.v2_stage = "resume"
        st.rerun()
    if st.button("编辑岗位描述", key="v2_edit_jd"):
        st.session_state.v2_stage = "jd"
        st.rerun()


def _parse_resume(uploaded: Any):
    if st.session_state.v2_resume_source == "粘贴文本":
        text = st.session_state.v2_resume_text.strip()
        if not text:
            raise ValueError("Resume is empty.")
        return TextDocumentParser().parse_text(text)
    if uploaded is None:
        raise ValueError("Resume upload is missing.")
    filename = Path(uploaded.name).name
    parser = DocumentParserRouter().resolve(filename, uploaded.type)
    return parser.parse(uploaded.getvalue(), filename, media_type=uploaded.type)


def _show_error() -> None:
    if st.session_state.v2_error:
        st.error(st.session_state.v2_error)


def _load_demo() -> None:
    st.session_state.v2_resume_source = "粘贴文本"
    st.session_state.v2_resume_text = DEMO_RESUME_TEXT
    st.session_state.v2_jd_text = DEMO_JD_TEXT


if __name__ == "__main__":
    main()
