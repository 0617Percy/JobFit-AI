"""Release-gate end-to-end checks across every supported resume input."""

from __future__ import annotations

import json
from decimal import Decimal
from io import BytesIO
from pathlib import Path

import pytest
from docx import Document

from jobfit.config import Settings
from jobfit.demo import (
    DEMO_COMPANY_NAME,
    DEMO_JOB_TEXT,
    DEMO_JOB_TITLE,
    DEMO_RESUME_TEXT,
    DemoRuntime,
    _advice_payload,
    _evidence_catalog,
    _job_payload,
    _json,
    _match_payload,
    _requirement_catalog,
    _resume_payload,
    build_demo_runtime,
)
from jobfit.llm import LLMTask, MockLLMClient, MockLLMProvider
from jobfit.models import (
    AnalysisReport,
    AnalysisRequest,
    EvidenceSourceType,
    MatchStatus,
    UploadedDocumentInput,
    WorkflowStage,
)
from jobfit.parsers import DocumentParserRouter
from jobfit.parsers.text import TextDocumentParser
from jobfit.scoring import ScoringEngine
from jobfit.workflow.factory import build_workflow_orchestrator


def _docx_bytes() -> bytes:
    document = Document()
    for line in DEMO_RESUME_TEXT.splitlines():
        document.add_paragraph(line)
    output = BytesIO()
    document.save(output)
    return output.getvalue()


def _pdf_bytes() -> bytes:
    return (
        Path(__file__).parents[1] / "fixtures" / "demo_resume.pdf"
    ).read_bytes()


def _request(
    request_id: str,
    *,
    pasted_text: str | None = None,
    upload: UploadedDocumentInput | None = None,
) -> AnalysisRequest:
    return AnalysisRequest(
        request_id=request_id,
        resume_file=upload,
        pasted_resume_text=pasted_text,
        job_description_text=DEMO_JOB_TEXT,
        job_title=DEMO_JOB_TITLE,
        company_name=DEMO_COMPANY_NAME,
        llm_mode="mock",
    )


def _runtime_for_upload(
    filename: str,
    media_type: str,
    content: bytes,
) -> DemoRuntime:
    parser = DocumentParserRouter().resolve(filename, media_type)
    resume_document = parser.parse(
        content,
        filename,
        media_type=media_type,
    )
    job_document = TextDocumentParser().parse_text(DEMO_JOB_TEXT)
    evidence = _evidence_catalog(resume_document)
    requirements = _requirement_catalog(job_document)
    provider = MockLLMProvider(
        {
            LLMTask.EXTRACT_RESUME: [_json(_resume_payload())],
            LLMTask.EXTRACT_JOB: [_json(_job_payload())],
            LLMTask.MATCH_EVIDENCE: [
                _json(_match_payload(requirements, evidence))
            ],
            LLMTask.GENERATE_ADVICE_BUNDLE: [
                _json(_advice_payload(requirements, evidence))
            ],
        }
    )
    settings = Settings(
        app_env="test",
        llm_provider="mock",
        llm_model="mock-model",
        llm_api_key=None,
        demo_mode=True,
    )
    return DemoRuntime(
        orchestrator=build_workflow_orchestrator(
            settings,
            client=MockLLMClient(provider),
        ),
        provider=provider,
    )


@pytest.mark.parametrize(
    ("case_name", "selected_source", "pasted_text", "filename", "media_type", "content"),
    [
        ("pasted", "text", DEMO_RESUME_TEXT, None, None, None),
        (
            "txt",
            "file",
            None,
            "anonymous-resume.txt",
            "text/plain",
            DEMO_RESUME_TEXT.encode("utf-8"),
        ),
        (
            "docx",
            "file",
            None,
            "anonymous-resume.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            _docx_bytes(),
        ),
        (
            "pdf",
            "file",
            None,
            "anonymous-resume.pdf",
            "application/pdf",
            _pdf_bytes(),
        ),
    ],
    ids=["pasted-text", "txt-file", "docx-file", "pdf-file"],
)
def test_all_supported_resume_inputs_complete_the_same_grounded_workflow(
    case_name: str,
    selected_source: str,
    pasted_text: str | None,
    filename: str | None,
    media_type: str | None,
    content: bytes | None,
) -> None:
    runtime = (
        _runtime_for_upload(filename, media_type, content)
        if filename and media_type and content is not None
        else build_demo_runtime()
    )
    upload = (
        UploadedDocumentInput(
            filename=filename,
            media_type=media_type,
            content=content,
            size_bytes=len(content),
        )
        if filename and media_type and content is not None
        else None
    )

    result = runtime.orchestrator.run(
        _request(
            f"release-{case_name}",
            pasted_text=pasted_text,
            upload=upload,
        ),
        selected_source=selected_source,
    )

    assert result.success is True
    assert result.stage is WorkflowStage.COMPLETED
    assert result.report is not None
    assert result.report.validation.valid is True
    assert runtime.provider.call_count == 4
    assert len(result.report.job_profile.requirements.items) == len(result.report.matches)
    assert {
        item.requirement_id for item in result.report.job_profile.requirements.items
    } == {item.requirement_id for item in result.report.matches}
    for match in result.report.matches:
        if match.match_status in {MatchStatus.MATCHED, MatchStatus.PARTIAL_MATCH}:
            assert match.evidence_items
            assert all(
                item.source_type is EvidenceSourceType.RESUME
                for item in match.evidence_items
            )
    assert sum(
        (
            requirement.weight
            for requirement in result.report.job_profile.requirements.items
        ),
        Decimal("0"),
    ) == Decimal("100.00")
    recalculated = ScoringEngine().score(
        result.report.job_profile.requirements.items,
        result.report.matches,
    )
    assert recalculated == result.report.score_summary
    assert result.report.recommendation.level is recalculated.recommendation_level
    assert len(result.report.strengths) <= 3
    assert len(result.report.gaps) <= 3
    assert len(result.report.interview_questions) == 5
    assert result.markdown is not None
    assert result.json_text is not None
    reloaded = AnalysisReport.model_validate_json(result.json_text)
    assert reloaded == result.report
    assert str(result.report.score_summary.final_score) in result.markdown
    assert result.report.recommendation.level.value in result.json_text


def test_identical_success_is_cached_and_exports_do_not_call_the_model() -> None:
    runtime = build_demo_runtime()
    first = runtime.orchestrator.run(
        _request("release-cache-one", pasted_text=DEMO_RESUME_TEXT),
        selected_source="text",
    )
    call_count = runtime.provider.call_count

    second = runtime.orchestrator.run(
        _request("release-cache-two", pasted_text=DEMO_RESUME_TEXT),
        selected_source="text",
    )
    markdown_copy = str(second.markdown)
    json_copy = json.dumps(
        json.loads(second.json_text or "{}"),
        ensure_ascii=False,
        sort_keys=True,
    )

    assert first.success is True
    assert second.success is True
    assert second.cache_hit is True
    assert second.report is first.report
    assert second.markdown == first.markdown
    assert second.json_text == first.json_text
    assert markdown_copy == first.markdown
    assert json.loads(json_copy)["report_id"] == first.report.report_id
    assert runtime.provider.call_count == call_count == 4


def test_repeated_fresh_runs_keep_business_results_stable() -> None:
    first_runtime = build_demo_runtime()
    second_runtime = build_demo_runtime()
    first = first_runtime.orchestrator.run(
        _request("release-stable-one", pasted_text=DEMO_RESUME_TEXT),
        selected_source="text",
    )
    second = second_runtime.orchestrator.run(
        _request("release-stable-two", pasted_text=DEMO_RESUME_TEXT),
        selected_source="text",
    )

    assert first.report is not None
    assert second.report is not None
    assert first.report.job_profile == second.report.job_profile
    assert first.report.resume_profile == second.report.resume_profile
    assert first.report.matches == second.report.matches
    assert first.report.score_summary == second.report.score_summary
    assert first.report.recommendation == second.report.recommendation
    assert first.report.rewrite_suggestions == second.report.rewrite_suggestions
    assert first.report.interview_questions == second.report.interview_questions
