"""Publisher-approved formal Seed lifecycle, retrieval, report and UI gates."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from jobfit.errors import ErrorCode, KnowledgeSeedError
from jobfit.knowledge.db import KnowledgeDatabase, initialize_knowledge_schema
from jobfit.knowledge.fts import KnowledgeSearchIndex
from jobfit.knowledge.importer import KnowledgeSeedImporter
from jobfit.knowledge.repository import SqliteKnowledgeRepository
from jobfit.knowledge.retriever import DefaultKnowledgeRetriever
from jobfit.knowledge.seed_loader import load_knowledge_seed
from jobfit.knowledge.versioning import KnowledgeVersionPublisher
from jobfit.models import (
    HardConditionKind,
    Importance,
    JobProfile,
    JobRequirement,
    JobRequirementCollection,
    KnowledgeRetrievalStatus,
    KnowledgeSearchCapabilityStatus,
    KnowledgeSearchMode,
    LanguageCode,
    RequirementCategory,
    RequirementType,
)
from jobfit.reporting import render_json, render_markdown
from jobfit.validators.report import build_analysis_report

SEED_ROOT = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "knowledge"
    / "versions"
    / "2026.08.1"
)
APP_PATH = Path(__file__).resolve().parents[2] / "app.py"
EXPECTED_CONTENT_HASH = (
    "346542eb0c405643a08ebc4bffdab9b5"
    "bce22a1b7227f5ad2b27f12e3d1ef7f4"
)
ROLE_CASES = (
    (
        "AI应用实习生",
        "人工智能应用、Python、LLM API、Agent工作流与评估",
        "rp-ai-application-intern",
        "kr-ai-",
    ),
    (
        "数据分析实习生",
        "数据分析、SQL、指标、可视化、Dashboard与业务洞察",
        "rp-data-analyst-intern",
        "kr-da-",
    ),
    (
        "技术战略实习生",
        "技术战略、竞争情报、技术趋势、情景分析与路线图",
        "rp-technology-strategy-intern",
        "kr-ts-",
    ),
)


def _job_profile(title: str, summary: str) -> JobProfile:
    requirement_text = summary.split("、", maxsplit=1)[0]
    return JobProfile(
        job_id=f"job-{title}",
        title=title,
        language=LanguageCode.ZH,
        jd_text=summary,
        summary=summary,
        keywords=[part for part in summary.replace("与", "、").split("、") if part],
        requirements=JobRequirementCollection(
            items=[
                JobRequirement(
                    requirement_id=f"req-{title}",
                    requirement_text=requirement_text,
                    source_text=requirement_text,
                    source_start_char=0,
                    source_end_char=len(requirement_text),
                    requirement_type=RequirementType.RESPONSIBILITY,
                    category=RequirementCategory.DOMAIN_BUSINESS,
                    importance=Importance.MEDIUM,
                    mandatory=False,
                    hard_condition_kind=HardConditionKind.NONE,
                    normalized_key=f"key-{title}",
                    priority_factor=Decimal("0"),
                    weight=Decimal("0"),
                )
            ],
            source_coverage_ratio=Decimal("1"),
        ),
    )


def _published_repository(tmp_path: Path):
    database = KnowledgeDatabase(tmp_path / "official-published.sqlite3")
    initialize_knowledge_schema(database)
    bundle = load_knowledge_seed(SEED_ROOT)
    importer = KnowledgeSeedImporter(database)
    first = importer.import_seed(bundle)
    second = importer.import_seed(bundle)
    published = KnowledgeVersionPublisher(database).publish(
        first.version_id,
        published_at=datetime(2026, 8, 5, 10, 0, tzinfo=UTC),
    )
    search_index = KnowledgeSearchIndex(database)
    if search_index.detect() is KnowledgeSearchCapabilityStatus.AVAILABLE:
        report = search_index.rebuild_version(first.version_id)
        assert report.consistent is True
    repository = SqliteKnowledgeRepository(
        database,
        search_mode=KnowledgeSearchMode.AUTO,
        search_index=search_index,
    )
    return database, first, second, published, repository


def _visible(app) -> str:
    values = []
    for collection in (
        app.markdown,
        app.caption,
        app.info,
        app.warning,
        app.success,
        app.subheader,
        app.text,
    ):
        values.extend(item.value for item in collection)
    values.extend(str(item.value) for item in app.metric)
    return "\n".join(values)


def test_official_approved_seed_publishes_idempotently_and_is_immutable(
    tmp_path: Path,
) -> None:
    database, first, second, published, repository = _published_repository(tmp_path)
    try:
        visible = repository.get_published_version("2026.08.1")

        assert first.created is True
        assert first.idempotent is False
        assert second.created is False
        assert second.idempotent is True
        assert first.content_hash == second.content_hash == EXPECTED_CONTENT_HASH
        assert published.status == "published"
        assert published.content_hash == EXPECTED_CONTENT_HASH
        assert visible is not None
        assert visible.version == "2026.08.1"
        assert visible.content_hash == EXPECTED_CONTENT_HASH

        with pytest.raises(KnowledgeSeedError) as exc_info:
            KnowledgeVersionPublisher(database).publish(first.version_id)
        assert exc_info.value.code is ErrorCode.KNOWLEDGE_PUBLISHED_IMMUTABLE
    finally:
        database.dispose()


@pytest.mark.parametrize(
    ("title", "summary", "expected_role_id", "requirement_prefix"),
    ROLE_CASES,
)
def test_official_roles_are_retrievable_without_cross_role_contamination(
    tmp_path: Path,
    title: str,
    summary: str,
    expected_role_id: str,
    requirement_prefix: str,
) -> None:
    database, first, _second, published, repository = _published_repository(tmp_path)
    retriever = DefaultKnowledgeRetriever(
        repository,
        requested_version=published.version,
        search_mode=KnowledgeSearchMode.AUTO,
    )
    try:
        context = retriever.retrieve_for_job(_job_profile(title, summary))

        assert context.status is KnowledgeRetrievalStatus.AVAILABLE
        assert context.version is not None
        assert context.version.id == first.version_id
        assert context.version.content_hash == EXPECTED_CONTENT_HASH
        assert len(context.inferred_role_profiles) == 1
        assert context.inferred_role_profiles[0].role_profile_id == expected_role_id
        assert context.requirements
        assert all(
            item.role_profile_id == expected_role_id
            and item.knowledge_requirement_id.startswith(requirement_prefix)
            for item in context.requirements
        )
        assert all(
            item.knowledge_requirement_id.startswith(requirement_prefix)
            for item in context.evidence_patterns
        )
        assert all(
            item.role_profile_id == expected_role_id
            for item in context.interview_questions
        )
        assert context.citations
        assert all(
            citation.knowledge_version_id == first.version_id
            and repository.citation_exists(
                citation,
                version_id=first.version_id,
            )
            for citation in context.citations
        )
    finally:
        database.dispose()


def test_official_approved_seed_reaches_report_and_streamlit_ui(
    tmp_path: Path,
    report_case,
) -> None:
    streamlit_testing = pytest.importorskip("streamlit.testing.v1")
    AppTest = streamlit_testing.AppTest
    database, _first, _second, published, repository = _published_repository(tmp_path)
    retriever = DefaultKnowledgeRetriever(
        repository,
        requested_version=published.version,
        search_mode=KnowledgeSearchMode.AUTO,
    )
    try:
        context = retriever.retrieve_for_job(
            _job_profile(
                "AI应用实习生",
                "人工智能应用、Python、LLM API、Agent工作流与评估",
            )
        )
    finally:
        database.dispose()

    report = build_analysis_report(
        document=report_case.document,
        resume=report_case.resume,
        job=report_case.job,
        matches=report_case.matches,
        score=report_case.score,
        advice=report_case.advice,
        registry=report_case.registry,
        limitations=report_case.limitations,
        knowledge_context=context,
        report_id="report-official-approved-knowledge",
        generated_at=datetime(2026, 8, 5, 10, 30, tzinfo=UTC),
    )
    markdown = render_markdown(report)
    json_text = render_json(report)
    payload = json.loads(json_text)

    assert report.validation.valid is True
    assert report.score_summary == report_case.score
    assert report.recommendation.level == report_case.score.recommendation_level
    assert report.knowledge is not None
    assert report.knowledge.status is KnowledgeRetrievalStatus.AVAILABLE
    assert report.knowledge.selected_role_profile is not None
    assert report.knowledge.selected_role_profile.role_profile_id == (
        "rp-ai-application-intern"
    )
    assert report.knowledge.citations
    assert "岗位知识参考" in markdown
    assert payload["knowledge"]["status"] == "available"

    app = AppTest.from_file(APP_PATH, default_timeout=20).run()
    app.session_state["analysis_report"] = report
    app.session_state["analysis_markdown"] = markdown
    app.session_state["analysis_json"] = json_text
    app = app.run()
    visible = _visible(app)

    assert not app.exception
    assert "岗位知识参考" in [tab.label for tab in app.tabs]
    assert "AI应用实习生" in visible
    assert "2026.08.1" in visible
    assert "不参与本次匹配评分" in visible
    assert [button.label for button in app.download_button] == [
        "下载 Markdown",
        "下载 JSON",
    ]
