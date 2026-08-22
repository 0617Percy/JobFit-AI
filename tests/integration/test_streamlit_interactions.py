"""Core offline demo interactions, session deduplication, and downloads."""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

_APP_PATH = Path(__file__).parents[2] / "app.py"
_TAB_LABELS = [
    "综合结论",
    "逐项匹配",
    "简历优化",
    "面试准备",
    "岗位知识参考",
    "结构化数据",
]


def _loaded_demo() -> AppTest:
    app = AppTest.from_file(_APP_PATH, default_timeout=30).run()
    app.button(key="load_demo").click().run()
    return app


def _analyzed_demo() -> AppTest:
    app = _loaded_demo()
    app.button(key="analyze").click().run(timeout=30)
    assert not app.exception
    return app


def test_example_resume_and_jd_load_without_starting_analysis() -> None:
    app = _loaded_demo()

    assert "匿名候选人" in app.text_area(key="resume_text").value
    assert "AI应用开发实习生" in app.text_area(key="jd_text").value
    assert app.text_input(key="job_title").value == "AI应用开发实习生"
    assert app.text_input(key="company_name").value == "匿名公司"
    assert app.radio(key="resume_source").value == "粘贴文本"
    assert app.session_state["demo_call_count"] == 0
    assert not app.tabs


def test_valid_mock_input_completes_and_renders_all_result_tabs() -> None:
    app = _analyzed_demo()

    assert [tab.label for tab in app.tabs] == _TAB_LABELS
    assert [metric.label for metric in app.metric[:3]] == [
        "最终匹配分",
        "原始分",
        "分数上限",
    ]
    assert app.session_state["analysis_report"].validation.valid is True
    assert len(app.session_state["analysis_report"].matches) == 4
    assert len(app.session_state["analysis_report"].interview_questions) == 5
    assert app.session_state["demo_call_count"] == 4


def test_rewrites_questions_and_unknown_semantics_are_visible() -> None:
    app = _analyzed_demo()
    rendered = "\n".join(item.value for item in app.markdown)
    warnings = "\n".join(item.value for item in app.warning)
    captions = "\n".join(item.value for item in app.caption)

    assert "可直接采用" in rendered
    assert "需用户确认" in rendered
    assert "未经核实不得直接写入简历" in warnings
    assert "当前简历证据不足" in captions
    assert rendered.count("面试题 ") == 5


def test_markdown_and_json_downloads_exist_and_do_not_rerun_models() -> None:
    app = _analyzed_demo()
    before = app.session_state["demo_call_count"]

    assert [button.label for button in app.download_button] == [
        "下载 Markdown",
        "下载 JSON",
    ]
    app.download_button[0].click().run()
    app.download_button[1].click().run()

    assert not app.exception
    assert app.session_state["demo_call_count"] == before
    assert app.session_state["analysis_markdown"].startswith("# JobFit Agent")
    assert '"schema_version": "1.1"' in app.session_state["analysis_json"]
    assert '"status": "disabled"' in app.session_state["analysis_json"]


def test_repeated_analysis_reuses_successful_session_result() -> None:
    app = _analyzed_demo()
    before = app.session_state["demo_call_count"]

    app.button(key="analyze").click().run(timeout=30)

    assert not app.exception
    assert app.session_state["demo_call_count"] == before
    assert app.session_state["analysis_cache_hit"] is True


def test_input_change_marks_old_report_stale_without_deleting_it() -> None:
    app = _analyzed_demo()
    report = app.session_state["analysis_report"]

    app.text_area(key="jd_text").input(
        app.text_area(key="jd_text").value + "\n新增要求：了解数据可视化。"
    ).run()

    assert not app.exception
    assert app.session_state["analysis_report"] is report
    assert app.session_state["analysis_stale"] is True
    assert any("结果已过期" in item.value for item in app.warning)
    assert [tab.label for tab in app.tabs] == _TAB_LABELS


def test_corrupt_pdf_shows_safe_recoverable_message() -> None:
    app = AppTest.from_file(_APP_PATH, default_timeout=20).run()
    app.file_uploader(key="resume_file").set_value(
        ("resume.pdf", b"not-a-pdf", "application/pdf")
    ).run()
    app.radio(key="resume_source").set_value("上传文件").run()
    app.text_area(key="jd_text").input("匿名岗位要求：熟悉Python。").run()

    app.button(key="analyze").click().run()

    assert not app.exception
    assert app.error
    visible = "\n".join(item.value for item in app.error)
    assert "无法解析" in visible or "文本" in visible
    assert "traceback" not in visible.casefold()
    assert "C:\\Users" not in visible
    assert not app.download_button


def test_page_never_renders_secret_prompt_or_local_path() -> None:
    app = _analyzed_demo()
    visible = "\n".join(
        [item.value for item in app.markdown]
        + [item.value for item in app.info]
        + [item.value for item in app.warning]
        + [item.value for item in app.error]
    )

    assert "system_prompt" not in visible.casefold()
    assert "raw_model_response" not in visible.casefold()
    assert "sk-" not in visible
    assert "C:\\Users\\" not in visible
