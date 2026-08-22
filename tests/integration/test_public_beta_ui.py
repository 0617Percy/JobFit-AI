"""Public Beta product-flow acceptance for the isolated Streamlit UI."""

from dataclasses import replace
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from jobfit.models.v2 import JobFitReport
from jobfit.semantic.v2 import SemanticPromptError
from jobfit.semantic.v2.contracts import PromptAttemptRecord
from jobfit.ui.presentation_translation import PresentationTranslationError

_APP_PATH = Path(__file__).parents[2] / "app_v2.py"


@pytest.fixture(autouse=True)
def isolate_v2_analysis_database(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("JOBFIT_ANALYSIS_DB_PATH", str(tmp_path / "analysis.sqlite3"))


def _app() -> AppTest:
    return AppTest.from_file(_APP_PATH, default_timeout=30).run()


def _visible_text(app: AppTest) -> str:
    collections = (
        app.title,
        app.header,
        app.subheader,
        app.markdown,
        app.caption,
        app.info,
        app.warning,
        app.success,
        app.error,
        app.text,
    )
    return "\n".join(str(item.value) for collection in collections for item in collection)


def _block_text(block) -> str:
    collections = (
        block.markdown,
        block.caption,
        block.info,
        block.warning,
        block.success,
        block.error,
        block.text,
    )
    return "\n".join(str(item.value) for collection in collections for item in collection)


def _completed_demo() -> AppTest:
    app = _app()
    app.button(key="v2_load_demo").click().run()
    app.button(key="v2_start_analysis").click().run(timeout=30)
    assert app.session_state["v2_stage"] == "clarification"
    app.button(key="v2_confirm_continue").click().run(timeout=30)
    assert app.session_state["v2_stage"] == "report"
    return app


def test_public_beta_uses_upload_confirm_auto_analysis_report_flow() -> None:
    app = _app()

    assert app.title[0].value == "JobFit AI"
    assert "岗位适配分析助手" in _visible_text(app)
    assert "Beta" in _visible_text(app)
    assert app.button(key="v2_start_analysis").label == "开始岗位分析"

    app.button(key="v2_load_demo").click().run()
    app.button(key="v2_start_analysis").click().run(timeout=30)

    assert app.session_state["v2_stage"] == "clarification"
    assert "信息确认" in _visible_text(app)
    assert app.button(key="v2_confirm_continue").label == "确认并生成完整报告"
    assert app.button(key="v2_back_to_inputs").label == "返回修改"
    assert "v2_run_analysis" not in [button.key for button in app.button]

    app.button(key="v2_confirm_continue").click().run(timeout=30)

    assert not app.exception
    assert app.session_state["v2_stage"] == "report"
    assert app.session_state["v2_session"].run.lifecycle.status.value == "completed"
    visible = "\n".join(
        [_visible_text(app), *(_block_text(item) for item in app.expander)]
    )
    for heading in (
        "总体结论",
        "岗位优势",
        "需要确认或补强的地方",
        "岗位要求逐项匹配",
        "简历优化建议",
        "下一步行动建议",
        "面试准备",
        "分析依据与边界",
    ):
        assert heading in visible


def test_public_beta_hides_pipeline_terms_and_internal_ids_from_report() -> None:
    app = _completed_demo()
    visible = "\n".join(
        [_visible_text(app), *(_block_text(item) for item in app.expander)]
    )

    for forbidden in (
        "运行P06-P08",
        "Rule Engine",
        "targeted repair",
        "full retry",
        "analysis_id",
        "report_id",
        "requirement_id",
        "evidence_id",
        "match_id",
        "action_id",
        "question_id",
        "requirement-",
        "evidence-",
        "action-",
        "question-",
    ):
        assert forbidden not in visible


def test_public_beta_failure_is_friendly_and_keeps_safe_diagnostics_collapsed() -> None:
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
    app.session_state["v2_application"] = _FailingApplication()

    app.button(key="v2_confirm_continue").click().run(timeout=30)

    assert not app.exception
    assert app.session_state["v2_stage"] == "analyzing"
    assert [item.value for item in app.error] == ["本次分析未能完成，请重新尝试。"]
    assert app.expander[0].label == "技术诊断信息"
    assert app.expander[0].proto.expanded is False
    assert app.button(key="v2_retry_analysis").label == "重新分析"


def test_public_beta_can_return_from_result_to_fresh_upload_state() -> None:
    app = _completed_demo()

    app.button(key="v2_analyze_another_job").click().run()

    assert app.session_state["v2_stage"] == "home"
    assert app.session_state["v2_session"] is None
    assert app.button(key="v2_start_analysis").label == "开始岗位分析"


def test_public_beta_sidebar_keeps_session_only_byok_controls() -> None:
    app = _app()

    assert app.text_input(key="v2_deepseek_api_key").proto.type == 1
    assert app.session_state["v2_deepseek_api_key"] == ""
    assert "API Key仅保存在当前会话" in _visible_text(app)


def test_public_beta_sanitizes_known_internal_ids_in_prose_without_mutation() -> None:
    app = _completed_demo()
    session = app.session_state["v2_session"]
    report = session.advisory_result.report
    payload = report.model_dump(mode="python")
    requirement = payload["job_profile"]["explicit_requirements"][0]
    evidence = payload["resume_evidence_profile"]["candidate_evidence"][0]
    action = payload["build_recommendations"][0]
    requirement_id = requirement["requirement_id"]
    evidence_id = evidence["evidence_id"]
    action_id = action["action_id"]
    requirement_label = requirement["normalized_capability"]
    evidence_label = evidence["source_text"]
    action_label = action["title"]
    fixture_text = (
        f"请结合 {evidence_id} 说明 {requirement_id}，并参考 {action_id}；"
        "保留 evidence-based reasoning、requirement-driven design 和 "
        "citation-backed explanation，以及 Python / AI / LLM。"
    )
    payload["job_profile"]["job_explanations"] = [
        {"text": fixture_text, "knowledge_citation_ids": []}
    ]
    payload["requirement_match"][0]["reason"] = fixture_text
    payload["interview_preparation"][0]["why_likely"] = fixture_text
    fixture_report = JobFitReport.model_validate(payload)
    stored_json = fixture_report.model_dump_json(indent=2)
    fixture_advisory = replace(session.advisory_result, report=fixture_report)
    app.session_state["v2_session"] = replace(
        session,
        advisory_result=fixture_advisory,
    )

    app.run(timeout=30)

    visible = "\n".join(
        [_visible_text(app), *(_block_text(item) for item in app.expander)]
    )
    for internal_id in (requirement_id, evidence_id, action_id):
        assert internal_id not in visible
        assert internal_id in stored_json
    for readable_label in (requirement_label, evidence_label, action_label):
        assert readable_label in visible
    for ordinary_phrase in (
        "evidence-based reasoning",
        "requirement-driven design",
        "citation-backed explanation",
        "Python / AI / LLM",
    ):
        assert ordinary_phrase in visible
    assert app.session_state["v2_session"].advisory_result.report is fixture_report
    assert fixture_report.model_dump_json(indent=2) == stored_json
    assert app.download_button(key="v2_download_json").label == "下载v2 JSON"


def test_public_beta_resume_source_selector_controls_visible_and_used_input() -> None:
    app = _app()

    assert app.radio(key="v2_resume_source").value == "粘贴文本"
    assert app.text_area(key="v2_resume_text")
    assert not app.file_uploader

    app.radio(key="v2_resume_source").set_value("上传文件").run()

    assert app.file_uploader(key="v2_resume_file")
    assert not [item for item in app.text_area if item.key == "v2_resume_text"]
    assert app.text_area(key="v2_jd_text")


def test_public_beta_sidebar_uses_friendly_labels_without_changing_mode_values() -> None:
    app = _app()
    mode = app.radio(key="v2_runtime_mode")

    assert mode.options == ["演示模式", "DeepSeek 分析"]
    assert mode.value == "Offline Demo / Mock"

    mode.set_value("DeepSeek BYOK").run()

    assert app.session_state["v2_runtime_mode"] == "DeepSeek BYOK"


def test_public_beta_localizes_and_deduplicates_unknown_gap_presentation() -> None:
    app = _completed_demo()
    session = app.session_state["v2_session"]
    report = session.advisory_result.report
    payload = report.model_dump(mode="python")
    requirement = payload["job_profile"]["explicit_requirements"][0]
    requirement_id = requirement["requirement_id"]
    evidence_id = payload["resume_evidence_profile"]["candidate_evidence"][0][
        "evidence_id"
    ]
    common_note = "Current evidence is insufficient; ability remains unknown."
    payload["strengths_and_gaps"] = {
        "strength_requirement_ids": [],
        "gaps": [
            {
                "requirement_id": requirement_id,
                "gap_kind": "missing_evidence",
                "evidence_status": "missing",
                "ability_status": "unknown",
                "safe_note": common_note,
            }
            for _index in range(8)
        ],
    }
    payload["requirement_match"][0].update(
        {
            "coverage": "partial",
            "evidence_status": "missing",
            "ability_status": "unknown",
            "matched_evidence": [],
            "reason": (
                f"请结合 {evidence_id} 核验 Python / AI / LLM 相关经历。"
            ),
        }
    )
    fixture_report = JobFitReport.model_validate(payload)
    stored_json = fixture_report.model_dump_json(indent=2)
    app.session_state["v2_session"] = replace(
        session,
        advisory_result=replace(session.advisory_result, report=fixture_report),
    )

    app.run(timeout=30)

    visible = "\n".join(
        [_visible_text(app), *(_block_text(item) for item in app.expander)]
    )
    summary_notice = (
        "部分岗位要求目前缺少充分证据，相关能力仍处于待确认状态。"
        "这并不代表你不具备这些能力，只表示当前简历材料不足以完成确认。"
    )
    assert visible.count(summary_notice) == 1
    assert common_note not in visible
    assert "[]" not in visible
    assert "当前尚未识别到可明确确认的优势项。" in visible
    for label, value in (
        ("匹配程度", "部分匹配"),
        ("证据状态", "缺少证据"),
        ("能力状态", "待确认"),
    ):
        assert label in visible
        assert value in visible
    for raw_display in (
        "**匹配程度：** partial",
        "**证据状态：** missing",
        "**能力状态：** unknown",
        "覆盖: partial",
        "证据: missing",
        "能力: unknown",
    ):
        assert raw_display not in visible
    assert evidence_id not in visible
    assert "Python / AI / LLM" in visible
    assert app.session_state["v2_session"].advisory_result.report is fixture_report
    assert fixture_report.model_dump_json(indent=2) == stored_json
    assert evidence_id in stored_json
    assert app.download_button(key="v2_download_json").label == "下载v2 JSON"


def test_public_beta_translates_generated_report_prose_without_mutating_report() -> None:
    class _RecordingTranslator:
        def __init__(self, leaked_id: str) -> None:
            self.calls = []
            self.leaked_id = leaked_id

        def translate(self, items):
            self.calls.append(tuple(items))
            translations = {
                "Requirement analysis is evidence-based.": "岗位要求分析以证据为基础。",
                "Improve the Python project description.": "完善 Python 项目描述。",
                "This makes the LLM work easier to verify.": (
                    "这能让 LLM 工作更容易验证。"
                ),
                "Describe the validated project outcome.": "说明已验证的项目结果。",
                "A reviewer can confirm the evidence.": "审核者可以确认相关证据。",
                "How did you validate the AI workflow?": (
                    "你如何验证 AI 工作流？"
                ),
                "The role requires reliable AI delivery.": (
                    "该岗位要求可靠交付 AI 应用。"
                ),
                "Explain the Python checks and verified result.": (
                    "说明 Python 检查方法和已验证结果。"
                ),
                "Graduation year 2028 cannot be confirmed.": (
                    "2028 年毕业时间无法确认。"
                ),
            }
            result = {
                item.key: translations.get(item.text, "已转换为中文显示。")
                for item in items
            }
            result["requirement_match.0.reason"] += f" {self.leaked_id}"
            return result

    app = _completed_demo()
    session = app.session_state["v2_session"]
    report = session.advisory_result.report
    payload = report.model_dump(mode="python")
    payload["requirement_match"][0]["reason"] = (
        "Requirement analysis is evidence-based."
    )
    action = payload["build_recommendations"][0]
    action.update(
        {
            "title": "Improve the Python project description.",
            "why_it_matters": "This makes the LLM work easier to verify.",
            "recommended_action": "Describe the validated project outcome.",
            "completion_criteria": "A reviewer can confirm the evidence.",
        }
    )
    question = payload["interview_preparation"][0]
    question.update(
        {
            "question": "How did you validate the AI workflow?",
            "why_likely": "The role requires reliable AI delivery.",
            "preparation_points": [
                "Explain the Python checks and verified result.",
                "Graduation year 2028 cannot be confirmed.",
            ],
        }
    )
    fixture_report = JobFitReport.model_validate(payload)
    stored_json = fixture_report.model_dump_json(indent=2)
    leaked_id = payload["job_profile"]["explicit_requirements"][0][
        "requirement_id"
    ]
    translator = _RecordingTranslator(leaked_id)
    app.session_state["v2_session"] = replace(
        session,
        advisory_result=replace(session.advisory_result, report=fixture_report),
    )
    app.session_state["v2_presentation_translator"] = translator
    app.session_state["v2_presentation_translation_cache"] = {}

    app.run(timeout=30)

    visible = "\n".join(
        [_visible_text(app), *(_block_text(item) for item in app.expander)]
    )
    for translated in (
        "岗位要求分析以证据为基础。",
        "完善 Python 项目描述。",
        "这能让 LLM 工作更容易验证。",
        "说明已验证的项目结果。",
        "审核者可以确认相关证据。",
        "你如何验证 AI 工作流？",
        "该岗位要求可靠交付 AI 应用。",
        "说明 Python 检查方法和已验证结果。",
        "2028 年毕业时间无法确认。",
    ):
        assert translated in visible
    assert "cannot be confirmed" not in visible
    assert leaked_id not in visible
    assert len(translator.calls) == 1
    requested_text = {item.text for item in translator.calls[0]}
    assert "当前证据不足，相关能力仍待确认。" not in requested_text
    assert fixture_report.model_dump_json(indent=2) == stored_json
    assert app.session_state["v2_session"].advisory_result.report is fixture_report
    assert app.download_button(key="v2_download_json").label == "下载v2 JSON"

    app.run(timeout=30)

    assert len(translator.calls) == 1


def test_public_beta_translation_failure_keeps_completed_report_available() -> None:
    class _FailingTranslator:
        def __init__(self) -> None:
            self.calls = 0

        def translate(self, items):
            assert items
            self.calls += 1
            raise PresentationTranslationError("private provider detail")

    app = _completed_demo()
    session = app.session_state["v2_session"]
    report = session.advisory_result.report
    payload = report.model_dump(mode="python")
    payload["requirement_match"][0]["reason"] = "English explanation."
    fixture_report = JobFitReport.model_validate(payload)
    stored_json = fixture_report.model_dump_json(indent=2)
    translator = _FailingTranslator()
    app.session_state["v2_session"] = replace(
        session,
        advisory_result=replace(session.advisory_result, report=fixture_report),
    )
    app.session_state["v2_presentation_translator"] = translator
    app.session_state["v2_presentation_translation_cache"] = {}

    app.run(timeout=30)

    assert not app.exception
    assert app.session_state["v2_stage"] == "report"
    assert app.session_state["v2_session"].run.lifecycle.status.value == "completed"
    assert any(
        "部分分析说明暂未完成中文转换" in item.value for item in app.warning
    )
    assert app.button(key="v2_retry_presentation_translation").label == (
        "重新生成中文显示"
    )
    assert "private provider detail" not in _visible_text(app)
    assert translator.calls == 1
    assert fixture_report.model_dump_json(indent=2) == stored_json
    assert app.download_button(key="v2_download_json").label == "下载v2 JSON"
