"""Streamlit application startup and safe empty-state smoke tests."""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

_APP_PATH = Path(__file__).parents[2] / "app.py"


def _app() -> AppTest:
    return AppTest.from_file(_APP_PATH, default_timeout=20).run()


def test_app_starts_without_api_key_in_mock_mode(monkeypatch) -> None:
    monkeypatch.setenv("JOBFIT_DEMO_MODE", "true")
    monkeypatch.delenv("JOBFIT_LLM_API_KEY", raising=False)

    app = _app()

    assert not app.exception
    assert app.title[0].value == "JobFit Agent"
    assert app.radio(key="run_mode").value == "离线Mock演示"
    visible_text = "\n".join(item.value for item in app.markdown)
    assert "匹配分不是录用概率" in visible_text
    assert "简历内容仅在当前会话处理" in visible_text
    assert app.button(key="load_demo").label == "加载匿名示例"
    assert app.button(key="analyze").label == "开始分析"


def test_empty_input_is_blocked_without_report_or_download() -> None:
    app = _app()

    app.button(key="analyze").click().run()

    assert not app.exception
    assert app.error
    assert "请先提供简历" in app.error[0].value
    assert not app.tabs
    assert not app.download_button


def test_missing_production_configuration_is_safe(monkeypatch) -> None:
    monkeypatch.delenv("JOBFIT_LLM_API_KEY", raising=False)
    monkeypatch.delenv("JOBFIT_LLM_MODEL", raising=False)
    app = _app()

    app.radio(key="run_mode").set_value("生产模型").run()

    assert not app.exception
    visible = "\n".join(
        [item.value for item in app.info]
        + [item.value for item in app.warning]
        + [item.value for item in app.error]
    )
    assert "环境变量" in visible
    assert "API Key" not in visible
    assert "JOBFIT_LLM_API_KEY" in visible
    assert not app.download_button
