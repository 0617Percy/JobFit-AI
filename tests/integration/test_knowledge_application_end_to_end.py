"""Synthetic seed-to-Streamlit report path with no network or repository data."""

from __future__ import annotations

import json
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
    _build_scripts,
)
from jobfit.knowledge import (
    DefaultKnowledgeRetriever,
    KnowledgeDatabase,
    KnowledgeSearchIndex,
    KnowledgeSeedBundle,
    KnowledgeSeedImporter,
    KnowledgeVersionPublisher,
    SqliteKnowledgeRepository,
    initialize_knowledge_schema,
)
from jobfit.knowledge.mappers import citation_id_for
from jobfit.llm import LLMTask, MockLLMClient, MockLLMProvider
from jobfit.models import (
    AnalysisRequest,
    EvidenceSourceType,
    KnowledgeRetrievalStatus,
    KnowledgeSearchCapabilityStatus,
    KnowledgeSearchMode,
    MatchStatus,
    UploadedDocumentInput,
)
from jobfit.parsers import DocumentParserRouter
from jobfit.parsers.text import TextDocumentParser
from jobfit.reporting import render_json, render_markdown
from jobfit.scoring import ScoringEngine
from jobfit.workflow.factory import (
    build_knowledge_retriever,
    build_workflow_orchestrator,
)
from tests.knowledge.seed_factory import synthetic_workflow_seed_payload


@pytest.mark.parametrize(
    ("search_mode", "build_fts"),
    [
        (KnowledgeSearchMode.KEYWORD, False),
        (KnowledgeSearchMode.AUTO, True),
    ],
)
def test_synthetic_seed_reaches_validated_report_and_exports(
    tmp_path,
    search_mode,
    build_fts,
) -> None:
    database = KnowledgeDatabase(tmp_path / "knowledge.sqlite3")
    initialize_knowledge_schema(database)
    bundle = KnowledgeSeedBundle.model_validate(
        synthetic_workflow_seed_payload()
    )
    imported = KnowledgeSeedImporter(database).import_seed(bundle)
    published = KnowledgeVersionPublisher(database).publish(imported.version_id)

    search_index = KnowledgeSearchIndex(database)
    if build_fts:
        if search_index.detect() is not KnowledgeSearchCapabilityStatus.AVAILABLE:
            database.dispose()
            pytest.skip("This Python SQLite build does not provide FTS5")
        index_report = search_index.rebuild_version(imported.version_id)
        assert index_report.consistent is True

    repository = SqliteKnowledgeRepository(
        database,
        search_mode=search_mode,
        search_index=search_index,
    )
    retriever = DefaultKnowledgeRetriever(
        repository,
        requested_version=published.version,
        search_mode=search_mode,
    )
    citation_id = citation_id_for(
        version_id=imported.version_id,
        source_id="ks-synthetic-guide",
        chunk_id=None,
    )
    scripts = _build_scripts()
    advice_payload = json.loads(
        scripts[LLMTask.GENERATE_ADVICE_BUNDLE][0]
    )
    advice_payload["knowledge_citation_uses"] = [
        {
            "citation_id": citation_id,
            "target_type": "recommendation",
            "target_index": 0,
            "purpose": "role_requirement_context",
        }
    ]
    scripts[LLMTask.GENERATE_ADVICE_BUNDLE] = [
        json.dumps(advice_payload, ensure_ascii=False)
    ]
    provider = MockLLMProvider(scripts)
    settings = Settings(
        _env_file=None,
        app_env="test",
        llm_provider="mock",
        llm_model="mock-model",
        demo_mode=True,
        knowledge_enabled=True,
        knowledge_version=published.version,
        knowledge_db_path=database.path,
        knowledge_search_mode=search_mode,
    )
    orchestrator = build_workflow_orchestrator(
        settings,
        client=MockLLMClient(provider),
        knowledge_retriever=retriever,
    )
    request = AnalysisRequest(
        request_id=f"synthetic-e2e-{search_mode.value}",
        pasted_resume_text=DEMO_RESUME_TEXT,
        job_description_text=DEMO_JOB_TEXT,
        job_title=DEMO_JOB_TITLE,
        company_name=DEMO_COMPANY_NAME,
        llm_mode="mock",
    )
    try:
        result = orchestrator.run(request, selected_source="text")
    finally:
        database.dispose()

    assert result.success is True
    assert result.report is not None
    assert result.report.schema_version == "1.1"
    assert result.report.knowledge is not None
    assert result.report.knowledge.status is KnowledgeRetrievalStatus.AVAILABLE
    assert result.report.knowledge.selected_role_profile is not None
    assert result.report.knowledge.selected_role_profile.name == (
        "Synthetic AI Assistant"
    )
    assert result.report.knowledge.citations[0].used_by == ["recommendation:0"]
    assert provider.call_count == 4
    assert result.report.validation.valid is True
    assert result.markdown == render_markdown(result.report)
    assert result.json_text == render_json(result.report)
    assert "岗位知识参考" in result.markdown
    payload = json.loads(result.json_text)
    assert payload["knowledge"]["status"] == "available"
    assert payload["knowledge"]["selected_role_profile"]["name"] == (
        "Synthetic AI Assistant"
    )
    assert "knowledge_context" not in payload
    assert "knowledge_advice_trace" not in payload


def test_missing_runtime_database_keeps_mock_base_analysis_available(
    tmp_path,
) -> None:
    path = tmp_path / "missing" / "knowledge.sqlite3"
    settings = Settings(
        _env_file=None,
        app_env="test",
        llm_provider="mock",
        llm_model="mock-model",
        demo_mode=True,
        knowledge_enabled=True,
        knowledge_db_path=path,
    )
    provider = MockLLMProvider(_build_scripts())
    orchestrator = build_workflow_orchestrator(
        settings,
        client=MockLLMClient(provider),
        knowledge_retriever=build_knowledge_retriever(settings),
    )

    result = orchestrator.run(
        AnalysisRequest(
            request_id="synthetic-missing-database",
            pasted_resume_text=DEMO_RESUME_TEXT,
            job_description_text=DEMO_JOB_TEXT,
            job_title=DEMO_JOB_TITLE,
            company_name=DEMO_COMPANY_NAME,
            llm_mode="mock",
        ),
        selected_source="text",
    )

    assert result.success is True
    assert result.report is not None
    assert result.report.knowledge is not None
    assert result.report.knowledge.status is KnowledgeRetrievalStatus.UNAVAILABLE
    assert provider.call_count == 4
    assert not path.exists()



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


def _analysis_request(
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


def _scripts_for_resume_document(
    resume_document,
    *,
    citation_id: str | None = None,
) -> dict[LLMTask, list[str]]:
    from jobfit.demo import (
        _advice_payload,
        _evidence_catalog,
        _job_payload,
        _json,
        _match_payload,
        _requirement_catalog,
        _resume_payload,
    )

    job_document = TextDocumentParser().parse_text(DEMO_JOB_TEXT)
    evidence = _evidence_catalog(resume_document)
    requirements = _requirement_catalog(job_document)
    advice_payload = _advice_payload(requirements, evidence)
    if citation_id is not None:
        advice_payload["knowledge_citation_uses"] = [
            {
                "citation_id": citation_id,
                "target_type": "recommendation",
                "target_index": 0,
                "purpose": "role_requirement_context",
            }
        ]
    return {
        LLMTask.EXTRACT_RESUME: [_json(_resume_payload())],
        LLMTask.EXTRACT_JOB: [_json(_job_payload())],
        LLMTask.MATCH_EVIDENCE: [_json(_match_payload(requirements, evidence))],
        LLMTask.GENERATE_ADVICE_BUNDLE: [
            json.dumps(advice_payload, ensure_ascii=False)
        ],
    }


def _published_retriever(
    tmp_path,
    *,
    common_hard_blocker: bool = False,
):
    database = KnowledgeDatabase(tmp_path / "knowledge.sqlite3")
    initialize_knowledge_schema(database)
    payload = synthetic_workflow_seed_payload()
    payload["role_requirements"][0]["is_common_hard_blocker"] = (
        common_hard_blocker
    )
    bundle = KnowledgeSeedBundle.model_validate(payload)
    imported = KnowledgeSeedImporter(database).import_seed(bundle)
    published = KnowledgeVersionPublisher(database).publish(imported.version_id)
    repository = SqliteKnowledgeRepository(
        database,
        search_mode=KnowledgeSearchMode.KEYWORD,
    )
    retriever = DefaultKnowledgeRetriever(
        repository,
        requested_version=published.version,
        search_mode=KnowledgeSearchMode.KEYWORD,
    )
    citation_id = citation_id_for(
        version_id=imported.version_id,
        source_id="ks-synthetic-guide",
        chunk_id=None,
    )
    return database, published, retriever, citation_id


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
def test_published_knowledge_supports_every_resume_input_without_replacing_evidence(
    tmp_path,
    case_name: str,
    selected_source: str,
    pasted_text: str | None,
    filename: str | None,
    media_type: str | None,
    content: bytes | None,
) -> None:
    if filename and media_type and content is not None:
        resume_document = DocumentParserRouter().resolve(
            filename,
            media_type,
        ).parse(content, filename, media_type=media_type)
        upload = UploadedDocumentInput(
            filename=filename,
            media_type=media_type,
            content=content,
            size_bytes=len(content),
        )
    else:
        resume_document = TextDocumentParser().parse_text(DEMO_RESUME_TEXT)
        upload = None

    database, published, retriever, citation_id = _published_retriever(
        tmp_path
    )
    provider = MockLLMProvider(
        _scripts_for_resume_document(
            resume_document,
            citation_id=citation_id,
        )
    )
    settings = Settings(
        _env_file=None,
        app_env="test",
        llm_provider="mock",
        llm_model="mock-model",
        demo_mode=True,
        knowledge_enabled=True,
        knowledge_version=published.version,
        knowledge_db_path=database.path,
        knowledge_search_mode=KnowledgeSearchMode.KEYWORD,
    )
    orchestrator = build_workflow_orchestrator(
        settings,
        client=MockLLMClient(provider),
        knowledge_retriever=retriever,
    )
    try:
        result = orchestrator.run(
            _analysis_request(
                f"knowledge-input-{case_name}",
                pasted_text=pasted_text,
                upload=upload,
            ),
            selected_source=selected_source,
        )
    finally:
        database.dispose()

    assert result.success is True
    assert result.report is not None
    assert result.report.knowledge is not None
    assert result.report.knowledge.status is KnowledgeRetrievalStatus.AVAILABLE
    assert result.report.knowledge.advice_trace is not None
    assert result.report.knowledge.advice_trace.validated is True
    assert any(
        citation.validation_status.value == "validated_advice"
        for citation in result.report.knowledge.citations
    )
    for match in result.report.matches:
        if match.match_status in {MatchStatus.MATCHED, MatchStatus.PARTIAL_MATCH}:
            assert match.evidence_items
            assert all(
                evidence.source_type is EvidenceSourceType.RESUME
                for evidence in match.evidence_items
            )
    assert ScoringEngine().score(
        result.report.job_profile.requirements.items,
        result.report.matches,
    ) == result.report.score_summary
    assert provider.call_count == 4


def test_knowledge_and_common_hard_blocker_do_not_change_scoring_or_recommendation(
    tmp_path,
) -> None:
    resume_document = TextDocumentParser().parse_text(DEMO_RESUME_TEXT)
    disabled_provider = MockLLMProvider(
        _scripts_for_resume_document(resume_document)
    )
    disabled_settings = Settings(
        _env_file=None,
        app_env="test",
        llm_provider="mock",
        llm_model="mock-model",
        demo_mode=True,
        knowledge_enabled=False,
    )
    disabled = build_workflow_orchestrator(
        disabled_settings,
        client=MockLLMClient(disabled_provider),
    ).run(
        _analysis_request(
            "knowledge-disabled-score",
            pasted_text=DEMO_RESUME_TEXT,
        ),
        selected_source="text",
    )

    database, published, retriever, citation_id = _published_retriever(
        tmp_path,
        common_hard_blocker=True,
    )
    enabled_provider = MockLLMProvider(
        _scripts_for_resume_document(
            resume_document,
            citation_id=citation_id,
        )
    )
    enabled_settings = Settings(
        _env_file=None,
        app_env="test",
        llm_provider="mock",
        llm_model="mock-model",
        demo_mode=True,
        knowledge_enabled=True,
        knowledge_version=published.version,
        knowledge_db_path=database.path,
        knowledge_search_mode=KnowledgeSearchMode.KEYWORD,
    )
    try:
        enabled = build_workflow_orchestrator(
            enabled_settings,
            client=MockLLMClient(enabled_provider),
            knowledge_retriever=retriever,
        ).run(
            _analysis_request(
                "knowledge-enabled-score",
                pasted_text=DEMO_RESUME_TEXT,
            ),
            selected_source="text",
        )
    finally:
        database.dispose()

    assert disabled.success is True
    assert enabled.success is True
    assert disabled.report is not None
    assert enabled.report is not None
    assert enabled.report.knowledge is not None
    assert any(
        requirement.is_common_hard_blocker
        for requirement in enabled.report.knowledge.requirements
    )
    assert enabled.report.job_profile == disabled.report.job_profile
    assert enabled.report.matches == disabled.report.matches
    assert enabled.report.score_summary == disabled.report.score_summary
    assert enabled.report.recommendation == disabled.report.recommendation
