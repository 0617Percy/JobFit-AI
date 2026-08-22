"""The existing UI stale signature includes safe knowledge runtime identity."""

from __future__ import annotations

from app import _build_input_signature


def _signature(**overrides: str) -> str:
    values = {
        "run_mode": "生产模型",
        "resume_source": "粘贴文本",
        "resume_text": "匿名简历",
        "file_digest": "",
        "jd_text": "匿名岗位描述",
        "job_title": "Synthetic AI Assistant",
        "company_name": "匿名公司",
        "runtime_identity": "a" * 64,
    }
    values.update(overrides)
    return _build_input_signature(**values)


def test_knowledge_runtime_change_marks_same_inputs_as_different() -> None:
    assert _signature() != _signature(runtime_identity="b" * 64)


def test_job_change_that_can_change_selected_role_invalidates_result() -> None:
    assert _signature() != _signature(job_title="Sample Strategy Profile")


def test_database_path_is_not_part_of_ui_signature() -> None:
    baseline = _signature()

    assert "C:\\Users\\" not in baseline
    assert "knowledge.sqlite3" not in baseline
