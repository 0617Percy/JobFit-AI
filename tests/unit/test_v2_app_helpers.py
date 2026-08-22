"""Focused branch coverage for the side-by-side v2 Streamlit entrypoint."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import app_v2
from jobfit.errors import ErrorCode, InputError, LLMError
from jobfit.llm.exceptions import (
    ProviderAuthenticationError,
    ProviderConnectionError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTimeoutError,
)
from jobfit.models.v2 import ClarificationAnswerType
from jobfit.semantic.v2 import SemanticPromptError
from jobfit.semantic.v2.contracts import PromptAttemptRecord
from jobfit.semantic.v2.severity import (
    SemanticValidationIssue,
    SemanticValidationSeverity,
)


class _State(dict):
    def __getattr__(self, name: str):
        return self[name]

    def __setattr__(self, name: str, value: object) -> None:
        self[name] = value


class _FakeStreamlit:
    def __init__(self, state: _State | None = None) -> None:
        self.session_state = state or _State()
        self.errors: list[str] = []
        self.widgets: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)

    def caption(self, message: str) -> None:
        del message

    def info(self, message: str) -> None:
        del message

    def code(self, message: str) -> None:
        del message

    def write(self, message: str) -> None:
        del message

    def subheader(self, message: str) -> None:
        del message

    def expander(self, label: str, *, expanded: bool = False):
        del label, expanded
        return self

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        del exc_type, exc, traceback

    def rerun(self) -> None:
        return None

    def _widget(self, _label: str, *args, key: str, **kwargs):
        del args, kwargs
        self.widgets.append(key)
        return self.session_state.get(key)

    checkbox = _widget
    button = _widget
    multiselect = _widget
    number_input = _widget
    text_input = _widget
    text_area = _widget
    selectbox = _widget


def test_state_initialization_demo_loading_and_error_display(
    monkeypatch,
    tmp_path,
) -> None:
    database_path = tmp_path / "analysis.sqlite3"
    monkeypatch.setenv("JOBFIT_ANALYSIS_DB_PATH", str(database_path))
    fake = _FakeStreamlit()
    monkeypatch.setattr(app_v2, "st", fake)

    app_v2._initialize_state()
    initial_history = fake.session_state.v2_history
    app_v2._initialize_state()
    assert fake.session_state.v2_history is initial_history
    assert database_path.exists()
    assert initial_history.__class__.__name__ == "SQLiteAnalysisRepository"

    app_v2._load_demo()
    assert "Python model API" in fake.session_state.v2_resume_text
    assert "AI Application Intern" in fake.session_state.v2_jd_text

    fake.session_state.v2_error = "safe message"
    app_v2._show_error()
    assert fake.errors == ["safe message"]


def test_resume_parser_handles_paste_upload_and_empty_boundaries(monkeypatch) -> None:
    state = _State(v2_resume_source="粘贴文本", v2_resume_text="Synthetic resume")
    monkeypatch.setattr(app_v2, "st", _FakeStreamlit(state))

    assert app_v2._parse_resume(None).normalized_text == "Synthetic resume"
    state.v2_resume_text = ""
    with pytest.raises(ValueError, match="empty"):
        app_v2._parse_resume(None)

    state.v2_resume_source = "上传文件"
    with pytest.raises(ValueError, match="missing"):
        app_v2._parse_resume(None)

    upload = SimpleNamespace(
        name="synthetic-resume.txt",
        type="text/plain",
        getvalue=lambda: b"Synthetic uploaded resume",
    )
    assert app_v2._parse_resume(upload).normalized_text == "Synthetic uploaded resume"


def test_prepare_analysis_rejects_missing_resume_and_empty_jd(monkeypatch) -> None:
    state = _State(v2_resume_document=None, v2_jd_text="")
    monkeypatch.setattr(app_v2, "st", _FakeStreamlit(state))
    with pytest.raises(InputError, match="Resume document"):
        app_v2._prepare_analysis()

    state.v2_resume_document = app_v2.TextDocumentParser().parse_text(
        "Synthetic resume"
    )
    with pytest.raises(InputError, match="JD is empty"):
        app_v2._prepare_analysis()


@pytest.mark.parametrize(
    ("code", "expected_category"),
    (
        ("INVALID_JSON", "结构化校验"),
        ("SCHEMA_INVALID", "结构化校验"),
        ("BUSINESS_VALIDATION_FAILED", "JobFit业务校验"),
        ("CROSS_OBJECT_VALIDATION_FAILED", "JobFit业务校验"),
    ),
)
def test_analysis_error_message_preserves_safe_semantic_stage_and_category(
    code: str,
    expected_category: str,
) -> None:
    error = SemanticPromptError("P01", code)

    message = app_v2._analysis_error_message(error)

    assert "P01简历事实提取阶段" in message
    assert expected_category in message
    assert "请核对简历和岗位描述" not in message
    assert code not in message


def test_analysis_error_message_shows_only_safe_p01_schema_diagnostics() -> None:
    attempt = PromptAttemptRecord(
        attempt=1,
        stage="normal",
        syntax_valid=True,
        schema_valid=False,
        business_valid=False,
        cross_object_valid=False,
        error_code="SCHEMA_INVALID",
        validation_error_count=2,
        validation_paths=("projects[0].evidence_local_ids", "candidate_profile.current_status"),
        validation_types=("missing", "literal_error"),
        finish_reason="stop",
        output_char_count=321,
    )
    error = SemanticPromptError("P01", "SCHEMA_INVALID", attempts=(attempt,))

    message = app_v2._analysis_error_message(error)

    assert "projects[0].evidence_local_ids — missing" in message
    assert "candidate_profile.current_status — literal_error" in message
    assert "321" not in message
    assert "private resume" not in message


@pytest.mark.parametrize(
    ("category", "severity"),
    (
        ("EVIDENCE_QUOTE_NOT_FOUND", SemanticValidationSeverity.HARD_BLOCK),
        ("EVIDENCE_QUOTE_AMBIGUOUS", SemanticValidationSeverity.RECOVERABLE_ERROR),
    ),
)
def test_analysis_error_message_shows_safe_p01_severity(
    category: str,
    severity: SemanticValidationSeverity,
) -> None:
    issue = SemanticValidationIssue(
        stage="P01",
        category=category,
        severity=severity,
        safe_path="evidence_items[0]",
    )
    attempt = PromptAttemptRecord(
        attempt=1,
        stage="normal",
        syntax_valid=True,
        schema_valid=True,
        business_valid=False,
        cross_object_valid=False,
        error_code="EVIDENCE_ANCHORING_FAILED",
        validation_error_count=1,
        validation_paths=(issue.safe_path,),
        validation_types=("value_error",),
        validation_categories=(issue.category,),
        validation_issues=(issue,),
    )

    message = app_v2._analysis_error_message(
        SemanticPromptError(
            "P01",
            "EVIDENCE_ANCHORING_FAILED",
            attempts=(attempt,),
        )
    )

    assert category in message
    assert severity.value in message
    assert issue.safe_path in message
    assert "private resume" not in message


@pytest.mark.parametrize(
    ("prompt_id", "expected_stage"),
    (
        ("P06", "P06行动建议生成阶段"),
        ("P07", "P07面试准备生成阶段"),
        ("P08", "P08报告生成阶段"),
    ),
)
def test_analysis_error_message_distinguishes_downstream_stage(
    prompt_id: str,
    expected_stage: str,
) -> None:
    attempt = PromptAttemptRecord(
        attempt=1,
        stage="normal",
        syntax_valid=True,
        schema_valid=True,
        business_valid=False,
        cross_object_valid=False,
        error_code="BUSINESS_VALIDATION_FAILED",
        validation_error_count=1,
        validation_paths=("items[0].reference_ids",),
        validation_types=("value_error",),
        validation_categories=("UNKNOWN_REQUIREMENT_REFERENCE",),
    )

    message = app_v2._analysis_error_message(
        SemanticPromptError(
            prompt_id,
            "BUSINESS_VALIDATION_FAILED",
            attempts=(attempt,),
        )
    )

    assert expected_stage in message
    assert "UNKNOWN_REQUIREMENT_REFERENCE" in message
    assert "items[0].reference_ids" in message
    assert "建议或报告未通过验证" not in message


def test_analyzing_failure_preserves_upstream_session_and_retries_downstream(
    monkeypatch,
) -> None:
    original_session = SimpleNamespace(
        run=SimpleNamespace(lifecycle=SimpleNamespace(status=SimpleNamespace(value="analyzing")))
    )
    completed_session = SimpleNamespace(run=SimpleNamespace())

    class _Application:
        def __init__(self) -> None:
            self.calls: list[object] = []

        def finish_analysis(self, session):
            self.calls.append(session)
            if len(self.calls) == 1:
                raise SemanticPromptError("P07", "SCHEMA_INVALID")
            return completed_session

    application = _Application()
    state = _State(
        v2_error=None,
        v2_analysis_attempted=False,
        v2_retry_analysis=False,
        v2_stage="analyzing",
        v2_session=original_session,
        v2_application=application,
    )
    monkeypatch.setattr(app_v2, "st", _FakeStreamlit(state))

    app_v2._render_analyzing()

    assert state.v2_session is original_session
    assert state.v2_stage == "analyzing"
    assert "P07面试准备生成阶段" in state.v2_error

    state.v2_retry_analysis = True
    app_v2._render_analyzing()
    state.v2_retry_analysis = False
    app_v2._render_analyzing()

    assert application.calls == [original_session, original_session]
    assert state.v2_session is completed_session
    assert state.v2_stage == "report"


@pytest.mark.parametrize(
    ("cause", "expected_category"),
    (
        (ProviderAuthenticationError("private detail"), "API Key验证失败"),
        (ProviderConnectionError("private detail"), "连接失败"),
        (ProviderTimeoutError("private detail"), "请求超时"),
        (ProviderRateLimitError("private detail"), "请求频率受限"),
        (ProviderResponseError("private detail"), "有效结构化内容"),
    ),
)
def test_analysis_error_message_routes_provider_failures_without_private_details(
    cause: Exception,
    expected_category: str,
) -> None:
    error = LLMError(
        code=(
            ErrorCode.LLM_AUTH_FAILED
            if isinstance(cause, ProviderAuthenticationError)
            else ErrorCode.LLM_TRANSIENT_ERROR
        ),
        user_message="generic provider failure",
        recoverable=True,
        cause=cause,
    )

    message = app_v2._analysis_error_message(error)

    assert expected_category in message
    assert "private detail" not in message
    assert "generic provider failure" not in message


def test_jd_stage_routes_semantic_failure_instead_of_blaming_user_input(
    monkeypatch,
) -> None:
    state = _State(v2_error=None, v2_continue_jd=True)
    monkeypatch.setattr(app_v2, "st", _FakeStreamlit(state))

    def fail_prepare() -> None:
        raise SemanticPromptError("P01", "SCHEMA_INVALID")

    monkeypatch.setattr(app_v2, "_prepare_analysis", fail_prepare)

    app_v2._render_jd()

    assert "P01简历事实提取阶段" in state.v2_error
    assert "结构化校验" in state.v2_error
    assert "请核对简历和岗位描述" not in state.v2_error


@pytest.mark.parametrize(
    ("prompt_id", "code", "expected_stage"),
    (
        ("P01", "EVIDENCE_ANCHORING_FAILED", "P01简历事实提取阶段"),
        ("P02", "JD_SOURCE_ANCHORING_FAILED", "P02岗位描述解析阶段"),
    ),
)
def test_jd_stage_preserves_deterministic_anchoring_stage(
    monkeypatch,
    prompt_id: str,
    code: str,
    expected_stage: str,
) -> None:
    state = _State(v2_error=None, v2_continue_jd=True)
    monkeypatch.setattr(app_v2, "st", _FakeStreamlit(state))
    safe_category = (
        "EVIDENCE_QUOTE_NOT_FOUND"
        if prompt_id == "P01"
        else "JD_SOURCE_TEXT_AMBIGUOUS"
    )
    attempt = PromptAttemptRecord(
        attempt=1,
        stage="normal",
        syntax_valid=True,
        schema_valid=True,
        business_valid=False,
        cross_object_valid=False,
        error_code=code,
        validation_error_count=1,
        validation_paths=("source_items[0]",),
        validation_types=("value_error",),
        validation_categories=(safe_category,),
    )

    def fail_prepare() -> None:
        raise SemanticPromptError(prompt_id, code, attempts=(attempt,))

    monkeypatch.setattr(app_v2, "_prepare_analysis", fail_prepare)

    app_v2._render_jd()

    assert expected_stage in state.v2_error
    assert safe_category in state.v2_error
    assert "请核对简历和岗位描述" not in state.v2_error


def test_jd_stage_routes_only_typed_input_failure_to_input_message(monkeypatch) -> None:
    state = _State(v2_error=None, v2_continue_jd=True)
    monkeypatch.setattr(app_v2, "st", _FakeStreamlit(state))

    def fail_prepare() -> None:
        raise InputError(
            code=ErrorCode.INPUT_EMPTY,
            user_message="private input detail",
            recoverable=True,
        )

    monkeypatch.setattr(app_v2, "_prepare_analysis", fail_prepare)

    app_v2._render_jd()

    assert state.v2_error == "输入未能通过v2结构化校验，请核对简历和岗位描述。"
    assert "private input detail" not in state.v2_error


def test_jd_stage_does_not_mask_unclassified_value_error_as_input(monkeypatch) -> None:
    state = _State(v2_error=None, v2_continue_jd=True)
    monkeypatch.setattr(app_v2, "st", _FakeStreamlit(state))

    def fail_prepare() -> None:
        raise ValueError("private deterministic failure")

    monkeypatch.setattr(app_v2, "_prepare_analysis", fail_prepare)

    with pytest.raises(ValueError, match="private deterministic failure"):
        app_v2._render_jd()

    assert state.v2_error is None


@pytest.mark.parametrize(
    "answer_type",
    list(ClarificationAnswerType),
)
def test_answer_controls_cover_every_frozen_schema_type(
    monkeypatch,
    answer_type: ClarificationAnswerType,
) -> None:
    fake = _FakeStreamlit()
    monkeypatch.setattr(app_v2, "st", fake)
    question = SimpleNamespace(
        question_id=f"question-{answer_type.value}",
        answer_schema=SimpleNamespace(
            answer_type=answer_type,
            allowed_values=("one", "two"),
            minimum=0,
            maximum=10,
        ),
    )

    app_v2._render_answer_controls(question)

    assert f"v2_answer_status_{question.question_id}" in fake.widgets
    assert f"v2_answer_value_{question.question_id}" in fake.widgets


def test_apply_answers_preserves_answered_skipped_and_unable_statuses(monkeypatch) -> None:
    questions = tuple(
        SimpleNamespace(question_id=f"question_{index}") for index in range(1, 4)
    )
    state = _State(
        v2_answer_status_question_1="answered",
        v2_answer_value_question_1="confirmed",
        v2_answer_status_question_2="skipped",
        v2_answer_status_question_3="unable_to_confirm",
    )
    captured = []
    session = SimpleNamespace(run=SimpleNamespace(analysis_id="analysis-1"))

    class _Application:
        @staticmethod
        def answer_clarification(current, *, question_id, answer):
            captured.append((question_id, answer))
            return current

    state.v2_application = _Application()
    fake = _FakeStreamlit(state)
    monkeypatch.setattr(app_v2, "st", fake)

    assert app_v2._apply_answers(session, questions) is session
    assert [item[1].status.value for item in captured] == [
        "answered",
        "skipped",
        "unable_to_confirm",
    ]
    assert captured[0][1].raw_text == "confirmed"
    assert captured[1][1].raw_text is None
    assert state.v2_session is session
