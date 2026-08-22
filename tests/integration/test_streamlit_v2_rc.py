"""Streamlit acceptance for the Public Beta v2 entrypoint."""

import hashlib
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from jobfit.demo_v2 import DEMO_JD_TEXT, DEMO_RESUME_TEXT
from jobfit.llm.deepseek_provider import DeepSeekProvider
from jobfit.semantic.v2 import SemanticPromptError
from jobfit.semantic.v2.contracts import PromptAttemptRecord

_APP_PATH = Path(__file__).parents[2] / "app_v2.py"


@pytest.fixture(autouse=True)
def isolate_v2_analysis_database(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv(
        "JOBFIT_ANALYSIS_DB_PATH",
        str(tmp_path / "analysis.sqlite3"),
    )


def _app() -> AppTest:
    return AppTest.from_file(_APP_PATH, default_timeout=30).run()


def _completed_demo() -> AppTest:
    app = _app()
    app.button(key="v2_load_demo").click().run()
    app.button(key="v2_start_analysis").click().run(timeout=30)
    app.button(key="v2_confirm_continue").click().run(timeout=30)
    return app


def test_v2_public_beta_walks_three_user_stages_with_real_lifecycle() -> None:
    app = _app()

    assert not app.exception
    assert app.title[0].value == "JobFit AI"
    assert app.session_state["v2_stage"] == "home"

    app.button(key="v2_load_demo").click().run()
    assert "Python model API" in app.text_area(key="v2_resume_text").value
    app.button(key="v2_start_analysis").click().run(timeout=30)
    assert app.session_state["v2_stage"] == "clarification"
    assert len(app.get("text_input")) <= 3

    app.button(key="v2_confirm_continue").click().run(timeout=30)
    assert app.session_state["v2_stage"] == "report"
    assert app.session_state["v2_session"].run.lifecycle.status.value == "completed"


def test_v2_report_is_recommendation_first_and_preserves_action_boundaries() -> None:
    app = _completed_demo()

    assert not app.exception
    headings = [item.value for item in app.subheader]
    assert headings.index("总体结论") < headings.index("岗位要求逐项匹配")
    assert "简历优化建议" in headings
    assert "下一步行动建议" in headings
    assert "面试准备" in headings
    visible = "\n".join(
        [item.value for item in app.markdown]
        + [item.value for item in app.caption]
        + [item.value for item in app.info]
        + [item.value for item in app.warning]
    )
    assert "不计入当前匹配分" in visible
    assert "为什么现在做" in visible
    assert "预计投入" in visible
    assert "回答准备要点" in visible
    assert "不得编造" in visible
    assert len(app.session_state["v2_session"].advisory_result.report.build_recommendations) <= 3
    assert app.button(key="v2_analyze_another_job").label == "分析另一个岗位"


def test_v2_reanalysis_keeps_completed_history_immutable() -> None:
    app = _completed_demo()
    original = app.session_state["v2_session"].run

    app.button(key="v2_analyze_another_job").click().run()

    assert app.session_state["v2_stage"] == "home"
    history = app.session_state["v2_history"].list_analysis_versions()
    assert len(history) == 1
    assert history[0] == original
    assert history[0] is not original


def test_v2_rc_shows_safe_input_errors_and_missing_stage_state() -> None:
    app = _app()
    app.button(key="v2_start_analysis").click().run()
    assert app.session_state["v2_stage"] == "home"
    assert app.error

    for stage in ("clarification", "analyzing", "report"):
        app.session_state["v2_stage"] = stage
        app.session_state["v2_session"] = None
        app.run()
        assert app.error


def test_v2_rc_downstream_failure_shows_safe_stage_and_preserves_session() -> None:
    class _FailingApplication:
        def begin_analysis(self, session):
            return session

        def finish_analysis(self, session):
            del session
            attempt = PromptAttemptRecord(
                attempt=1,
                stage="normal",
                syntax_valid=True,
                schema_valid=True,
                business_valid=True,
                cross_object_valid=False,
                error_code="CROSS_OBJECT_VALIDATION_FAILED",
                validation_error_count=1,
                validation_paths=("implicit_explanations[0].requirement_id",),
                validation_types=("value_error",),
                validation_categories=("INVALID_IMPLICIT_REQUIREMENT_REFERENCE",),
            )
            raise SemanticPromptError(
                "P08",
                "CROSS_OBJECT_VALIDATION_FAILED",
                attempts=(attempt,),
            )

    app = _app()
    app.button(key="v2_load_demo").click().run()
    app.button(key="v2_start_analysis").click().run(timeout=30)
    original_session = app.session_state["v2_session"]
    app.session_state["v2_application"] = _FailingApplication()

    app.button(key="v2_confirm_continue").click().run(timeout=30)

    assert not app.exception
    assert app.session_state["v2_stage"] == "analyzing"
    assert app.session_state["v2_session"] is original_session
    message = app.session_state["v2_error"]
    assert "P08报告生成阶段" in message
    assert "INVALID_IMPLICIT_REQUIREMENT_REFERENCE" in message
    assert "implicit_explanations[0].requirement_id" in message
    assert "建议或报告未通过验证" not in message


def test_v2_public_beta_has_only_one_result_restart_action() -> None:
    app = _completed_demo()

    result_action_keys = [
        item.key for item in app.button if item.key == "v2_analyze_another_job"
    ]
    assert result_action_keys == ["v2_analyze_another_job"]


def test_v2_public_beta_restart_keeps_completed_history_without_exposing_ids() -> None:
    app = _completed_demo()
    analysis_id = app.session_state["v2_session"].run.analysis_id
    app.button(key="v2_analyze_another_job").click().run()
    visible = "\n".join(
        item.value
        for collection in (app.markdown, app.caption, app.info, app.warning)
        for item in collection
    )
    assert app.session_state["v2_history"].get_analysis(analysis_id) is not None
    assert analysis_id not in visible


def test_v2_rc_exposes_session_only_deepseek_byok_controls() -> None:
    app = _app()

    assert app.radio(key="v2_runtime_mode").value == "Offline Demo / Mock"
    assert app.text_input(key="v2_deepseek_api_key").proto.type == 1
    assert app.selectbox(key="v2_deepseek_model").value == "deepseek-v4-flash"
    assert app.checkbox(key="v2_deepseek_thinking").value is False
    assert app.button(key="v2_deepseek_check").label == "验证DeepSeek连接"
    assert app.button(key="v2_deepseek_clear").label == "清除API Key"
    assert app.session_state["v2_deepseek_api_key"] == ""
    visible = "\n".join(
        item.value
        for collection in (app.markdown, app.caption, app.info, app.warning)
        for item in collection
    )
    assert "请勿写入源码或.env" in visible
    assert "当前会话未配置API Key" in visible


def test_v2_rc_requires_disclosure_consent_before_deepseek_analysis() -> None:
    app = _app()
    app.radio(key="v2_runtime_mode").set_value("DeepSeek BYOK").run()
    app.text_input(key="v2_deepseek_api_key").input("session-secret").run()
    assert app.checkbox(key="v2_deepseek_consent").value is False

    app.text_area(key="v2_resume_text").input(DEMO_RESUME_TEXT).run()
    app.text_area(key="v2_jd_text").input(DEMO_JD_TEXT).run()
    app.button(key="v2_start_analysis").click().run()

    assert app.session_state["v2_stage"] == "home"
    visible_errors = "\n".join(item.value for item in app.error)
    assert "同意" in visible_errors
    assert "session-secret" not in visible_errors
    assert app.session_state["v2_session"] is None


def test_v2_rc_clear_removes_deepseek_key_from_current_session() -> None:
    app = _app()
    app.radio(key="v2_runtime_mode").set_value("DeepSeek BYOK").run()
    app.text_input(key="v2_deepseek_api_key").input("session-secret").run()

    app.button(key="v2_deepseek_clear").click().run()

    assert app.session_state["v2_deepseek_api_key"] == ""
    assert app.text_input(key="v2_deepseek_api_key").value == ""
    assert "session-secret" not in "\n".join(
        item.value
        for collection in (app.markdown, app.caption, app.info, app.warning, app.success)
        for item in collection
    )


def test_v2_rc_byok_ui_connection_and_clear_never_mutate_source(
    monkeypatch,
) -> None:
    source_before = hashlib.sha256(_APP_PATH.read_bytes()).digest()
    monkeypatch.setattr(DeepSeekProvider, "check_connection", lambda self: None)
    app = _app()

    app.radio(key="v2_runtime_mode").set_value("DeepSeek BYOK").run()
    app.text_input(key="v2_deepseek_api_key").input("synthetic-session-key").run()
    app.selectbox(key="v2_deepseek_model").set_value("deepseek-v4-pro").run()
    app.checkbox(key="v2_deepseek_thinking").check().run()
    assert "当前会话已配置API Key" in "\n".join(
        item.value for item in app.caption
    )
    app.button(key="v2_deepseek_check").click().run()
    app.button(key="v2_deepseek_clear").click().run()

    assert source_before == hashlib.sha256(_APP_PATH.read_bytes()).digest()
    assert app.session_state["v2_deepseek_api_key"] == ""
    assert "当前会话未配置API Key" in "\n".join(
        item.value for item in app.caption
    )
