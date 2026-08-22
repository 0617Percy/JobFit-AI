"""Release-gate failure paths using real workflow boundaries and offline Mock LLM."""

from __future__ import annotations

import json
from copy import deepcopy
from decimal import Decimal

import pytest

from jobfit.config import Settings
from jobfit.demo import (
    DEMO_COMPANY_NAME,
    DEMO_JOB_TEXT,
    DEMO_JOB_TITLE,
    DEMO_RESUME_TEXT,
    _build_scripts,
)
from jobfit.errors import ConfigurationError, ErrorCode
from jobfit.llm import LLMTask, MockLLMClient, MockLLMProvider
from jobfit.llm.exceptions import (
    ProviderAuthenticationError,
    ProviderTimeoutError,
)
from jobfit.models import AnalysisRequest, UploadedDocumentInput, WorkflowStage
from jobfit.scoring import ScoringEngine
from jobfit.workflow.factory import build_workflow_orchestrator
from tests.pdf_fixtures import make_blank_pdf_bytes


def _settings() -> Settings:
    return Settings(
        app_env="test",
        llm_provider="mock",
        llm_model="mock-model",
        llm_api_key=None,
        demo_mode=True,
        llm_max_retries=0,
    )


def _orchestrator(
    scripts: dict[LLMTask, list[object]] | None = None,
):
    provider = MockLLMProvider(scripts or _build_scripts())
    return (
        provider,
        build_workflow_orchestrator(
            _settings(),
            client=MockLLMClient(provider),
        ),
    )


def _request(
    *,
    request_id: str,
    text: str | None = DEMO_RESUME_TEXT,
    jd: str = DEMO_JOB_TEXT,
    upload: UploadedDocumentInput | None = None,
) -> AnalysisRequest:
    return AnalysisRequest(
        request_id=request_id,
        resume_file=upload,
        pasted_resume_text=text,
        job_description_text=jd,
        job_title=DEMO_JOB_TITLE,
        company_name=DEMO_COMPANY_NAME,
        llm_mode="mock",
    )


def _upload(filename: str, media_type: str, content: bytes) -> UploadedDocumentInput:
    return UploadedDocumentInput(
        filename=filename,
        media_type=media_type,
        content=content,
        size_bytes=len(content),
    )


def _assert_failed_closed(result, code: ErrorCode) -> None:
    assert result.success is False
    assert result.stage is WorkflowStage.FAILED
    assert result.report is None
    assert result.markdown is None
    assert result.json_text is None
    assert result.error is not None
    assert result.error.code == code.value
    rendered = repr(result.error) + repr(result.events)
    assert DEMO_RESUME_TEXT not in rendered
    assert DEMO_JOB_TEXT not in rendered
    assert "sk-" not in rendered
    assert "C:\\Users\\" not in rendered


@pytest.mark.parametrize(
    ("analysis_request", "selected_source", "expected_code"),
    [
        (
            _request(
                request_id="empty-resume",
                text=None,
                upload=_upload(
                    "unused-resume.txt",
                    "text/plain",
                    b"unused upload",
                ),
            ),
            "text",
            ErrorCode.INPUT_EMPTY,
        ),
        (
            _request(request_id="empty-jd", jd="   "),
            "text",
            ErrorCode.INPUT_EMPTY,
        ),
        (
            _request(
                request_id="oversized-text",
                text="简" * 50_001,
            ),
            "text",
            ErrorCode.INPUT_TOO_LARGE,
        ),
        (
            _request(
                request_id="unsupported-file",
                text=None,
                upload=_upload(
                    "anonymous-resume.rtf",
                    "application/rtf",
                    b"{\\rtf1 anonymous}",
                ),
            ),
            "file",
            ErrorCode.FILE_TYPE_UNSUPPORTED,
        ),
        (
            _request(
                request_id="corrupt-docx",
                text=None,
                upload=_upload(
                    "anonymous-resume.docx",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    b"not-a-docx",
                ),
            ),
            "file",
            ErrorCode.DOCUMENT_PARSE_FAILED,
        ),
        (
            _request(
                request_id="corrupt-pdf",
                text=None,
                upload=_upload(
                    "anonymous-resume.pdf",
                    "application/pdf",
                    b"not-a-pdf",
                ),
            ),
            "file",
            ErrorCode.DOCUMENT_PARSE_FAILED,
        ),
    ],
)
def test_invalid_inputs_fail_closed_before_report_export(
    analysis_request: AnalysisRequest,
    selected_source: str,
    expected_code: ErrorCode,
) -> None:
    provider, orchestrator = _orchestrator()

    result = orchestrator.run(
        analysis_request,
        selected_source=selected_source,
    )

    _assert_failed_closed(result, expected_code)
    assert provider.call_count == 0


def test_file_over_limit_fails_before_parser_or_model() -> None:
    provider, orchestrator = _orchestrator()
    content = b"x" * (10 * 1024 * 1024 + 1)
    request = _request(
        request_id="oversized-file",
        text=None,
        upload=_upload("anonymous-resume.txt", "text/plain", content),
    )

    result = orchestrator.run(request, selected_source="file")

    _assert_failed_closed(result, ErrorCode.INPUT_TOO_LARGE)
    assert provider.call_count == 0


def test_pdf_without_text_layer_returns_ocr_fallback_message() -> None:
    provider, orchestrator = _orchestrator()
    request = _request(
        request_id="blank-pdf",
        text=None,
        upload=_upload(
            "anonymous-resume.pdf",
            "application/pdf",
            make_blank_pdf_bytes(),
        ),
    )

    result = orchestrator.run(request, selected_source="file")

    _assert_failed_closed(result, ErrorCode.PDF_TEXT_EMPTY)
    assert result.error is not None
    assert "OCR" in result.error.message
    assert provider.call_count == 0


def test_provider_mode_requires_environment_credentials(monkeypatch) -> None:
    monkeypatch.setenv("JOBFIT_LLM_PROVIDER", "openai")
    monkeypatch.delenv("JOBFIT_LLM_MODEL", raising=False)
    monkeypatch.delenv("JOBFIT_LLM_API_KEY", raising=False)

    with pytest.raises(ConfigurationError) as exc:
        build_workflow_orchestrator(Settings.load(demo_mode=False))

    assert exc.value.code is ErrorCode.CONFIG_INVALID


@pytest.mark.parametrize(
    ("outcome", "expected_code", "recoverable"),
    [
        (
            ProviderAuthenticationError("invalid credential"),
            ErrorCode.LLM_AUTH_FAILED,
            False,
        ),
        (
            ProviderTimeoutError("timeout"),
            ErrorCode.LLM_TRANSIENT_ERROR,
            True,
        ),
    ],
)
def test_provider_failures_are_translated_without_partial_output(
    outcome: Exception,
    expected_code: ErrorCode,
    recoverable: bool,
) -> None:
    scripts = _build_scripts()
    scripts[LLMTask.EXTRACT_RESUME] = [outcome]
    _, orchestrator = _orchestrator(scripts)

    result = orchestrator.run(
        _request(request_id=f"provider-{expected_code.value}"),
        selected_source="text",
    )

    _assert_failed_closed(result, expected_code)
    assert result.recoverable is recoverable


def test_schema_repair_exhaustion_fails_closed() -> None:
    scripts = _build_scripts()
    scripts[LLMTask.EXTRACT_RESUME] = ['{"language":"invalid"}']
    provider, orchestrator = _orchestrator(scripts)

    result = orchestrator.run(
        _request(request_id="schema-invalid"),
        selected_source="text",
    )

    _assert_failed_closed(result, ErrorCode.LLM_SCHEMA_INVALID)
    assert provider.call_count == 3


def test_extractor_grounding_failure_blocks_matching_and_scoring() -> None:
    scripts = _build_scripts()
    payload = json.loads(str(scripts[LLMTask.EXTRACT_RESUME][0]))
    payload["facts"][0]["evidence_candidates"][0]["start_char"] += 1
    payload["facts"][0]["evidence_candidates"][0]["end_char"] += 1
    scripts[LLMTask.EXTRACT_RESUME] = [
        json.dumps(payload, ensure_ascii=False)
    ]
    provider, orchestrator = _orchestrator(scripts)

    result = orchestrator.run(
        _request(request_id="extractor-grounding"),
        selected_source="text",
    )

    _assert_failed_closed(result, ErrorCode.SCHEMA_VALIDATION_FAILED)
    assert provider.call_count == 1


def test_duplicate_requirement_match_blocks_scoring() -> None:
    scripts = _build_scripts()
    payload = json.loads(str(scripts[LLMTask.MATCH_EVIDENCE][0]))
    payload["matches"][1]["requirement_id"] = payload["matches"][0][
        "requirement_id"
    ]
    scripts[LLMTask.MATCH_EVIDENCE] = [
        json.dumps(payload, ensure_ascii=False)
    ]
    provider, orchestrator = _orchestrator(scripts)

    result = orchestrator.run(
        _request(request_id="duplicate-requirement"),
        selected_source="text",
    )

    _assert_failed_closed(result, ErrorCode.EVIDENCE_INVALID)
    assert provider.call_count == 4


def test_invalid_evidence_reference_blocks_scoring() -> None:
    scripts = _build_scripts()
    payload = json.loads(str(scripts[LLMTask.MATCH_EVIDENCE][0]))
    payload["matches"][0]["evidence_items"][0]["document_id"] = "forged-document"
    scripts[LLMTask.MATCH_EVIDENCE] = [
        json.dumps(payload, ensure_ascii=False)
    ]
    _, orchestrator = _orchestrator(scripts)

    result = orchestrator.run(
        _request(request_id="invalid-evidence"),
        selected_source="text",
    )

    _assert_failed_closed(result, ErrorCode.EVIDENCE_INVALID)


def test_invalid_advice_reference_blocks_report() -> None:
    scripts = _build_scripts()
    payload = json.loads(str(scripts[LLMTask.GENERATE_ADVICE_BUNDLE][0]))
    payload["strengths"][0]["requirement_ids"] = ["req-forged"]
    scripts[LLMTask.GENERATE_ADVICE_BUNDLE] = [
        json.dumps(payload, ensure_ascii=False)
    ]
    _, orchestrator = _orchestrator(scripts)

    result = orchestrator.run(
        _request(request_id="invalid-advice"),
        selected_source="text",
    )

    _assert_failed_closed(result, ErrorCode.ADVICE_VALIDATION_FAILED)


class _TamperingScorer:
    def score(self, requirements, matches):
        score = ScoringEngine().score(requirements, matches)
        return score.model_copy(
            update={
                "raw_score": score.raw_score + Decimal("1.00"),
                "final_score": min(
                    score.raw_score + Decimal("1.00"),
                    score.score_cap,
                ),
            }
        )


def test_scoring_invariant_mismatch_blocks_advice_and_exports() -> None:
    _, orchestrator = _orchestrator()
    orchestrator._scoring_engine = _TamperingScorer()

    result = orchestrator.run(
        _request(request_id="tampered-score"),
        selected_source="text",
    )

    _assert_failed_closed(result, ErrorCode.ADVICE_VALIDATION_FAILED)


def test_unsupported_role_and_deployment_claims_require_confirmation() -> None:
    scripts = deepcopy(_build_scripts())
    payload = json.loads(str(scripts[LLMTask.GENERATE_ADVICE_BUNDLE][0]))
    payload["rewrite_suggestions"][0]["rewritten_text"] = (
        "主导Python生产部署并实现商业化"
    )
    payload["rewrite_suggestions"][0]["introduced_claims"] = []
    payload["rewrite_suggestions"][0]["user_confirmation_needed"] = []
    scripts[LLMTask.GENERATE_ADVICE_BUNDLE] = [
        json.dumps(payload, ensure_ascii=False)
    ]
    _, orchestrator = _orchestrator(scripts)

    result = orchestrator.run(
        _request(request_id="unsafe-rewrite"),
        selected_source="text",
    )

    assert result.success is True
    assert result.report is not None
    suggestion = result.report.rewrite_suggestions[0]
    assert suggestion.introduced_claims
    assert suggestion.user_confirmation_needed
    assert any("职责强化" in item for item in suggestion.introduced_claims)
    assert any("落地范围" in item for item in suggestion.introduced_claims)
