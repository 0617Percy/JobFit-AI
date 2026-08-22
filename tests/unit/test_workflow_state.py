"""Workflow state machine, progress, fingerprint, and session cache tests."""

from __future__ import annotations

from dataclasses import replace

import pytest

from jobfit.models import AnalysisRequest, UploadedDocumentInput, WorkflowStage
from jobfit.workflow import (
    WorkflowCache,
    WorkflowFingerprintContext,
    WorkflowResult,
    WorkflowState,
    build_analysis_fingerprint,
    build_knowledge_advice_cache_identity,
    build_request_fingerprint,
)

_STAGES = [
    WorkflowStage.VALIDATING_INPUT,
    WorkflowStage.PARSING_RESUME,
    WorkflowStage.EXTRACTING_RESUME,
    WorkflowStage.EXTRACTING_JOB,
    WorkflowStage.RETRIEVING_KNOWLEDGE,
    WorkflowStage.MATCHING_EVIDENCE,
    WorkflowStage.VALIDATING_MATCHES,
    WorkflowStage.SCORING,
    WorkflowStage.GENERATING_ADVICE,
    WorkflowStage.VALIDATING_REPORT,
    WorkflowStage.COMPLETED,
]


def _request(**updates: object) -> AnalysisRequest:
    values: dict[str, object] = {
        "request_id": "request-state-test",
        "pasted_resume_text": "技能：Python",
        "job_description_text": "要求：熟悉Python",
        "job_title": "AI应用开发实习生",
        "company_name": "匿名公司",
        "llm_mode": "mock",
    }
    values.update(updates)
    return AnalysisRequest(**values)


def _context(**updates: object) -> WorkflowFingerprintContext:
    values: dict[str, object] = {
        "provider": "mock",
        "model": "mock-model",
        "prompt_versions": {
            "extract_resume": "1.0",
            "extract_job": "1.0",
            "match_evidence": "1.0",
            "generate_advice_bundle": "1.1",
        },
        "schema_version": "1.0",
    }
    values.update(updates)
    return WorkflowFingerprintContext(**values)


def test_state_machine_allows_only_the_complete_forward_sequence() -> None:
    state = WorkflowState(_request())

    for stage in _STAGES:
        state.advance(stage)

    assert state.stage is WorkflowStage.COMPLETED
    assert [event.stage for event in state.events] == _STAGES
    assert [event.progress_percent for event in state.events] == sorted(
        event.progress_percent for event in state.events
    )
    assert state.events[-1].progress_percent == 100


def test_state_machine_rejects_skipped_or_post_terminal_stages() -> None:
    state = WorkflowState(_request())

    with pytest.raises(ValueError, match="transition"):
        state.advance(WorkflowStage.EXTRACTING_RESUME)

    state.advance(WorkflowStage.VALIDATING_INPUT)
    state.fail(code="TEST_FAILURE", message="安全错误。", recoverable=True)
    with pytest.raises(ValueError, match="terminal"):
        state.advance(WorkflowStage.PARSING_RESUME)


def test_completed_state_cannot_be_failed() -> None:
    state = WorkflowState(_request())
    for stage in _STAGES:
        state.advance(stage)

    with pytest.raises(ValueError, match="terminal"):
        state.fail(code="LATE_FAILURE", message="不应写入。", recoverable=False)


def test_failure_event_is_monotonic_and_contains_only_safe_error() -> None:
    state = WorkflowState(_request())
    state.advance(WorkflowStage.VALIDATING_INPUT)
    state.advance(WorkflowStage.PARSING_RESUME)

    state.fail(
        code="DOCUMENT_PARSE_FAILED",
        message="无法解析简历，请改用粘贴文本。",
        recoverable=True,
    )

    assert state.stage is WorkflowStage.FAILED
    assert state.error is not None
    assert state.error.recoverable is True
    assert state.events[-1].stage is WorkflowStage.FAILED
    assert state.events[-1].progress_percent >= state.events[-2].progress_percent
    serialized = repr(state.error) + repr(state.events[-1])
    assert "技能：Python" not in serialized
    assert "要求：熟悉Python" not in serialized


def test_request_fingerprint_is_stable_order_independent_and_secret_free() -> None:
    request = _request()
    first = build_request_fingerprint(
        request,
        selected_source="text",
        context=_context(),
    )
    second = build_request_fingerprint(
        request,
        selected_source="text",
        context=_context(
            prompt_versions={
                "generate_advice_bundle": "1.1",
                "match_evidence": "1.0",
                "extract_job": "1.0",
                "extract_resume": "1.0",
            }
        ),
    )

    assert first == second
    assert len(first) == 64
    assert "Python" not in first
    assert "匿名公司" not in first
    assert "api" not in first


def test_analysis_fingerprint_binds_base_request_to_knowledge_identity() -> None:
    base = "a" * 64
    knowledge = "b" * 64

    first = build_analysis_fingerprint(base, knowledge)
    second = build_analysis_fingerprint(base, knowledge)

    assert first == second
    assert len(first) == 64
    assert first != build_analysis_fingerprint(base, "c" * 64)
    assert first != build_analysis_fingerprint("d" * 64, knowledge)


@pytest.mark.parametrize(
    ("field", "changed"),
    [
        ("prompt_version", "1.3"),
        ("validator_version", "2.0"),
        ("strategy_version", "2.0"),
    ],
)
def test_knowledge_advice_cache_identity_binds_all_rule_versions(
    field: str,
    changed: str,
) -> None:
    values = {
        "prompt_version": "1.2",
        "validator_version": "1.0",
        "strategy_version": "1.0",
    }
    baseline = build_knowledge_advice_cache_identity(
        "a" * 64,
        **values,
    )
    values[field] = changed

    assert baseline != build_knowledge_advice_cache_identity(
        "a" * 64,
        **values,
    )
    assert len(baseline) == 64


@pytest.mark.parametrize(
    ("input_request", "context"),
    [
        (_request(pasted_resume_text="技能：Python和SQL"), _context()),
        (_request(job_description_text="要求：熟悉SQL"), _context()),
        (_request(job_title="数据分析实习生"), _context()),
        (_request(company_name="另一匿名公司"), _context()),
        (_request(llm_mode="provider"), _context(provider="openai")),
        (_request(), _context(model="another-model")),
        (
            _request(),
            _context(
                prompt_versions={
                    "extract_resume": "2.0",
                    "extract_job": "1.0",
                    "match_evidence": "1.0",
                    "generate_advice_bundle": "1.1",
                }
            ),
        ),
        (_request(), _context(schema_version="2.0")),
    ],
)
def test_request_fingerprint_changes_with_business_or_runtime_input(
    input_request: AnalysisRequest,
    context: WorkflowFingerprintContext,
) -> None:
    baseline = build_request_fingerprint(
        _request(),
        selected_source="text",
        context=_context(),
    )

    assert (
        build_request_fingerprint(
            input_request,
            selected_source="text",
            context=context,
        )
        != baseline
    )


def test_session_cache_keeps_only_success_and_tracks_in_flight_requests() -> None:
    cache = WorkflowCache()
    successful = WorkflowResult.successful(
        request_id="request-one",
        fingerprint="a" * 64,
        report=None,
        markdown="report",
        json_text="{}",
        events=(),
    )
    failed = WorkflowResult.failed(
        request_id="request-two",
        fingerprint="b" * 64,
        events=(),
        code="TEST_FAILURE",
        message="安全失败。",
        recoverable=True,
    )

    assert cache.begin("a" * 64) is True
    assert cache.begin("a" * 64) is False
    cache.finish(successful)
    assert cache.get_success("a" * 64) == successful
    assert cache.begin("b" * 64) is True
    cache.finish(failed)
    assert cache.get_success("b" * 64) is None
    assert cache.begin("b" * 64) is True
    cache.clear()
    assert cache.get_success("a" * 64) is None
    assert cache.begin("b" * 64) is True


def test_file_and_invalid_source_fingerprints_are_stable_and_distinct() -> None:
    upload = UploadedDocumentInput(
        filename="resume.txt",
        media_type="text/plain",
        content=b"anonymous resume",
        size_bytes=len(b"anonymous resume"),
    )
    request = _request(resume_file=upload)

    file_fingerprint = build_request_fingerprint(
        request,
        selected_source="file",
        context=_context(),
    )
    invalid_fingerprint = build_request_fingerprint(
        request,
        selected_source="invalid",
        context=_context(),
    )

    assert len(file_fingerprint) == 64
    assert file_fingerprint != invalid_fingerprint


def test_cache_hit_result_preserves_business_output() -> None:
    original = WorkflowResult.successful(
        request_id="request-one",
        fingerprint="c" * 64,
        report=None,
        markdown="same markdown",
        json_text='{"same": true}',
        events=(),
    )

    cached = replace(original, cache_hit=True)

    assert cached.markdown == original.markdown
    assert cached.json_text == original.json_text
    assert cached.cache_hit is True
