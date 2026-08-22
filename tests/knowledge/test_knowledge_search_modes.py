"""Published knowledge search is deterministic across FTS and keyword recall."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from jobfit.errors import ErrorCode, JobFitError, KnowledgeDatabaseError
from jobfit.knowledge.fts import KnowledgeSearchIndex
from jobfit.knowledge.orm import (
    CompetencyDimensionRecord,
    InterviewQuestionRecord,
    JobFamilyRecord,
    KnowledgeSourceRecord,
    RoleProfileRecord,
    RoleRequirementRecord,
    SourceRoleLinkRecord,
)
from jobfit.knowledge.query import KnowledgeSearchQuery, RoleProfileQuery
from jobfit.knowledge.repository import SqliteKnowledgeRepository
from jobfit.models.knowledge import (
    KnowledgeSearchBackend,
    KnowledgeSearchCapabilityStatus,
    KnowledgeSearchMode,
)


def _add_chinese_role(database) -> None:
    now = datetime(2026, 7, 25, 9, 0, tzinfo=UTC)
    with database._session_scope() as session:
        session.add(
            KnowledgeSourceRecord(
                id="ks-synthetic-cn",
                title="Synthetic Chinese role guide",
                source_type="internal_template",
                publisher="JobFit test fixture",
                source_url="https://example.test/knowledge/cn-role",
                published_at=now,
                collected_at=now,
                license_note="Original synthetic content for offline tests.",
                reliability_level="medium",
                review_status="approved",
                checksum="d" * 64,
            )
        )
        session.add(
            JobFamilyRecord(
                id="jf-synthetic-data",
                code="synthetic_data",
                name="Synthetic data",
                description="Anonymous data family.",
                aliases_json='["sample data"]',
                knowledge_version_id="kbv-2026-07-1",
                is_active=True,
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            CompetencyDimensionRecord(
                id="cd-synthetic-data",
                code="synthetic_data_method",
                name="Synthetic data method",
                description="Analyze anonymous sample data.",
                scoring_category_hint=None,
                display_order=2,
                knowledge_version_id="kbv-2026-07-1",
                review_status="approved",
                is_active=True,
            )
        )
        session.flush()
        session.add(
            RoleProfileRecord(
                id="rp-synthetic-data-intern",
                job_family_id="jf-synthetic-data",
                code="synthetic_data_intern",
                name="示例数据分析实习生",
                seniority="intern",
                industry="technology",
                description="使用结构化方法分析匿名示例数据。",
                aliases_json='["sample data analyst"]',
                keywords_json='["数据分析","sql"]',
                knowledge_version_id="kbv-2026-07-1",
                review_status="approved",
                is_active=True,
                created_at=now,
                updated_at=now,
            )
        )
        session.flush()
        session.add(
            RoleRequirementRecord(
                id="kr-synthetic-sql",
                role_profile_id="rp-synthetic-data-intern",
                competency_dimension_id="cd-synthetic-data",
                title="SQL数据分析",
                description="使用 SQL 完成匿名数据分析与结果验证。",
                requirement_type="must_have",
                importance="high",
                is_common_hard_blocker=False,
                expected_evidence_json='["描述分析步骤"]',
                weak_evidence_json='["只列出SQL"]',
                negative_signals_json='[]',
                keywords_json='["sql","数据分析"]',
                source_id="ks-synthetic-cn",
                knowledge_version_id="kbv-2026-07-1",
                review_status="approved",
                is_active=True,
            )
        )
        session.add(
            InterviewQuestionRecord(
                id="iq-synthetic-sql",
                role_profile_id="rp-synthetic-data-intern",
                competency_dimension_id="cd-synthetic-data",
                question="请说明你会如何验证一项 SQL 数据分析结果？",
                question_type="technical",
                expected_points_json='["步骤","验证"]',
                follow_up_questions_json='[]',
                difficulty="medium",
                source_id="ks-synthetic-cn",
                knowledge_version_id="kbv-2026-07-1",
                review_status="approved",
                is_active=True,
            )
        )
        session.add(
            SourceRoleLinkRecord(
                source_id="ks-synthetic-cn",
                role_profile_id="rp-synthetic-data-intern",
                knowledge_version_id="kbv-2026-07-1",
                relation_type="supports",
                created_at=now,
            )
        )


def _repository(database, *, mode, capability):
    index = KnowledgeSearchIndex(database, capability_override=capability)
    return (
        SqliteKnowledgeRepository(
            database,
            search_mode=mode,
            search_index=index,
        ),
        index,
    )


def test_keyword_mode_supports_chinese_aliases_and_structured_filters(
    seeded_database,
) -> None:
    _add_chinese_role(seeded_database)
    repository, _ = _repository(
        seeded_database,
        mode=KnowledgeSearchMode.KEYWORD,
        capability=KnowledgeSearchCapabilityStatus.AVAILABLE,
    )

    roles = repository.search_role_profiles(
        RoleProfileQuery(
            title="数据分析",
            aliases=("sample data analyst",),
            seniority="intern",
            industry="technology",
            keywords=("SQL",),
            job_family_codes=("synthetic_data",),
        ),
        version_id="kbv-2026-07-1",
        limit=5,
    )
    requirements = repository.search_requirements(
        KnowledgeSearchQuery(
            role_profile_ids=("rp-synthetic-data-intern",),
            terms=("SQL", "数据分析"),
            source_ids=("ks-synthetic-cn",),
        ),
        version_id="kbv-2026-07-1",
        limit=5,
    )

    assert [item.role_profile_id for item in roles] == [
        "rp-synthetic-data-intern"
    ]
    assert [item.knowledge_requirement_id for item in requirements] == [
        "kr-synthetic-sql"
    ]
    assert roles[0].matched_fields
    assert requirements[0].matched_fields == [
        "title",
        "keywords",
        "description",
        "expected_evidence",
        "importance",
    ]
    assert repository.get_search_capabilities().mode is (
        KnowledgeSearchBackend.KEYWORD_FALLBACK
    )


def test_structured_family_and_source_filters_exclude_cross_role_results(
    seeded_database,
) -> None:
    _add_chinese_role(seeded_database)
    repository, _ = _repository(
        seeded_database,
        mode=KnowledgeSearchMode.KEYWORD,
        capability=KnowledgeSearchCapabilityStatus.AVAILABLE,
    )

    roles = repository.search_role_profiles(
        RoleProfileQuery(
            title="数据分析",
            keywords=("sql",),
            job_family_codes=("ai_application",),
        ),
        version_id="kbv-2026-07-1",
        limit=5,
    )
    requirements = repository.search_requirements(
        KnowledgeSearchQuery(
            role_profile_ids=("rp-synthetic-data-intern",),
            terms=("sql",),
            source_ids=("ks-public-ai-role",),
        ),
        version_id="kbv-2026-07-1",
        limit=5,
    )

    assert roles == []
    assert requirements == []


def test_auto_mode_falls_back_when_fts_is_unavailable(seeded_database) -> None:
    repository, _ = _repository(
        seeded_database,
        mode=KnowledgeSearchMode.AUTO,
        capability=KnowledgeSearchCapabilityStatus.UNAVAILABLE,
    )

    results = repository.search_role_profiles(
        RoleProfileQuery(title="AI application intern", keywords=("python",)),
        version_id="kbv-2026-07-1",
        limit=3,
    )

    assert [item.role_profile_id for item in results] == [
        "rp-ai-application-intern"
    ]
    assert repository.get_search_capabilities().mode is (
        KnowledgeSearchBackend.KEYWORD_FALLBACK
    )


def test_auto_mode_falls_back_when_fts_index_has_not_been_built(
    seeded_database,
) -> None:
    repository, _ = _repository(
        seeded_database,
        mode=KnowledgeSearchMode.AUTO,
        capability=KnowledgeSearchCapabilityStatus.AVAILABLE,
    )

    results = repository.search_role_profiles(
        RoleProfileQuery(title="AI application intern"),
        version_id="kbv-2026-07-1",
        limit=3,
    )

    assert [item.role_profile_id for item in results] == [
        "rp-ai-application-intern"
    ]


def test_auto_mode_falls_back_when_fts_query_fails(
    seeded_database,
    monkeypatch,
) -> None:
    repository, index = _repository(
        seeded_database,
        mode=KnowledgeSearchMode.AUTO,
        capability=KnowledgeSearchCapabilityStatus.AVAILABLE,
    )
    index.rebuild_version("kbv-2026-07-1")

    def fail_search(**_kwargs):
        raise KnowledgeDatabaseError(
            code=ErrorCode.KNOWLEDGE_SEARCH_FAILED,
            user_message="Knowledge search is temporarily unavailable.",
            recoverable=True,
        )

    monkeypatch.setattr(index, "search_candidates", fail_search)

    results = repository.search_role_profiles(
        RoleProfileQuery(title="AI application intern"),
        version_id="kbv-2026-07-1",
        limit=3,
    )

    assert [item.role_profile_id for item in results] == [
        "rp-ai-application-intern"
    ]


def test_forced_fts_mode_surfaces_runtime_query_failure(
    seeded_database,
    monkeypatch,
) -> None:
    repository, index = _repository(
        seeded_database,
        mode=KnowledgeSearchMode.FTS5,
        capability=KnowledgeSearchCapabilityStatus.AVAILABLE,
    )
    index.rebuild_version("kbv-2026-07-1")
    failure = KnowledgeDatabaseError(
        code=ErrorCode.KNOWLEDGE_SEARCH_FAILED,
        user_message="Knowledge search is temporarily unavailable.",
        recoverable=True,
    )

    def fail_search(**_kwargs):
        raise failure

    monkeypatch.setattr(index, "search_candidates", fail_search)

    with pytest.raises(KnowledgeDatabaseError) as exc_info:
        repository.search_role_profiles(
            RoleProfileQuery(title="AI application intern"),
            version_id="kbv-2026-07-1",
            limit=3,
        )

    assert exc_info.value is failure


def test_forced_fts_mode_fails_recoverably_when_unavailable(
    seeded_database,
) -> None:
    repository, _ = _repository(
        seeded_database,
        mode=KnowledgeSearchMode.FTS5,
        capability=KnowledgeSearchCapabilityStatus.UNAVAILABLE,
    )

    with pytest.raises(JobFitError) as exc_info:
        repository.search_role_profiles(
            RoleProfileQuery(title="AI application intern"),
            version_id="kbv-2026-07-1",
            limit=3,
        )

    assert exc_info.value.code is ErrorCode.KNOWLEDGE_SEARCH_UNAVAILABLE
    assert exc_info.value.recoverable is True


def test_forced_fts_mode_requires_an_explicitly_built_index(
    seeded_database,
) -> None:
    repository, _ = _repository(
        seeded_database,
        mode=KnowledgeSearchMode.FTS5,
        capability=KnowledgeSearchCapabilityStatus.AVAILABLE,
    )

    with pytest.raises(JobFitError) as exc_info:
        repository.search_role_profiles(
            RoleProfileQuery(title="AI application intern"),
            version_id="kbv-2026-07-1",
            limit=3,
        )

    assert exc_info.value.code is ErrorCode.KNOWLEDGE_SEARCH_UNAVAILABLE


def test_keyword_mode_never_creates_fts_objects(seeded_database) -> None:
    repository, index = _repository(
        seeded_database,
        mode=KnowledgeSearchMode.KEYWORD,
        capability=KnowledgeSearchCapabilityStatus.AVAILABLE,
    )
    repository.search_role_profiles(
        RoleProfileQuery(title="AI application intern"),
        version_id="kbv-2026-07-1",
        limit=3,
    )

    assert index.has_index_objects() is False


def test_disabled_search_returns_no_results_without_creating_index(
    seeded_database,
) -> None:
    index = KnowledgeSearchIndex(
        seeded_database,
        capability_override=KnowledgeSearchCapabilityStatus.AVAILABLE,
    )
    repository = SqliteKnowledgeRepository(
        seeded_database,
        search_mode=KnowledgeSearchMode.AUTO,
        search_index=index,
        search_enabled=False,
    )

    results = repository.search_role_profiles(
        RoleProfileQuery(title="AI application intern"),
        version_id="kbv-2026-07-1",
        limit=3,
    )

    assert results == []
    assert repository.get_search_capabilities().mode is (
        KnowledgeSearchBackend.DISABLED
    )
    assert index.has_index_objects() is False


def test_fts_and_keyword_recall_share_identical_final_ranking(
    seeded_database,
) -> None:
    _add_chinese_role(seeded_database)
    keyword, _ = _repository(
        seeded_database,
        mode=KnowledgeSearchMode.KEYWORD,
        capability=KnowledgeSearchCapabilityStatus.AVAILABLE,
    )
    fts, index = _repository(
        seeded_database,
        mode=KnowledgeSearchMode.FTS5,
        capability=KnowledgeSearchCapabilityStatus.AVAILABLE,
    )
    index.rebuild_version("kbv-2026-07-1")
    query = RoleProfileQuery(
        title="示例数据分析实习生",
        aliases=("sample data analyst",),
        seniority="intern",
        keywords=("SQL", "数据分析"),
    )

    keyword_results = keyword.search_role_profiles(
        query,
        version_id="kbv-2026-07-1",
        limit=5,
    )
    fts_results = fts.search_role_profiles(
        query,
        version_id="kbv-2026-07-1",
        limit=5,
    )

    assert fts_results == keyword_results
    assert fts.get_search_capabilities().mode is KnowledgeSearchBackend.FTS5


def test_fts_and_keyword_share_requirement_and_question_ranking(
    seeded_database,
) -> None:
    keyword, _ = _repository(
        seeded_database,
        mode=KnowledgeSearchMode.KEYWORD,
        capability=KnowledgeSearchCapabilityStatus.AVAILABLE,
    )
    fts, index = _repository(
        seeded_database,
        mode=KnowledgeSearchMode.FTS5,
        capability=KnowledgeSearchCapabilityStatus.AVAILABLE,
    )
    index.rebuild_version("kbv-2026-07-1")
    query = KnowledgeSearchQuery(
        role_profile_ids=("rp-ai-application-intern",),
        terms=("Python", "application"),
    )

    assert fts.search_requirements(
        query,
        version_id="kbv-2026-07-1",
        limit=5,
    ) == keyword.search_requirements(
        query,
        version_id="kbv-2026-07-1",
        limit=5,
    )
    assert fts.search_interview_questions(
        query,
        version_id="kbv-2026-07-1",
        limit=5,
    ) == keyword.search_interview_questions(
        query,
        version_id="kbv-2026-07-1",
        limit=5,
    )


def test_stale_fts_candidate_is_rechecked_against_core_tables(
    seeded_database,
) -> None:
    repository, index = _repository(
        seeded_database,
        mode=KnowledgeSearchMode.FTS5,
        capability=KnowledgeSearchCapabilityStatus.AVAILABLE,
    )
    index.rebuild_version("kbv-2026-07-1")
    with seeded_database._engine.begin() as connection:
        connection.exec_driver_sql(
            """
            INSERT INTO knowledge_search_fts(
                entity_type, entity_id, knowledge_version_id,
                role_profile_id, job_family_code, search_text
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "role_profile",
                "rp-stale",
                "kbv-2026-07-1",
                "rp-stale",
                "ai_application",
                "python application",
            ),
        )

    results = repository.search_role_profiles(
        RoleProfileQuery(
            title="AI application intern",
            keywords=("python",),
        ),
        version_id="kbv-2026-07-1",
        limit=5,
    )

    assert [item.role_profile_id for item in results] == [
        "rp-ai-application-intern"
    ]


def test_search_does_not_persist_query_text(seeded_database) -> None:
    repository, index = _repository(
        seeded_database,
        mode=KnowledgeSearchMode.FTS5,
        capability=KnowledgeSearchCapabilityStatus.AVAILABLE,
    )
    index.rebuild_version("kbv-2026-07-1")
    with seeded_database._engine.connect() as connection:
        before = connection.exec_driver_sql(
            "SELECT count(*) FROM knowledge_search_fts"
        ).scalar_one()

    repository.search_role_profiles(
        RoleProfileQuery(title="private query marker zzz123"),
        version_id="kbv-2026-07-1",
        limit=3,
    )

    with seeded_database._engine.connect() as connection:
        after = connection.exec_driver_sql(
            "SELECT count(*) FROM knowledge_search_fts"
        ).scalar_one()
        persisted = connection.exec_driver_sql(
            """
            SELECT count(*) FROM knowledge_search_fts
            WHERE search_text MATCH ?
            """,
            ('"zzz123"',),
        ).scalar_one()
    assert after == before
    assert persisted == 0


def test_sql_and_fts_special_characters_are_plain_search_text(
    seeded_database,
) -> None:
    keyword, _ = _repository(
        seeded_database,
        mode=KnowledgeSearchMode.KEYWORD,
        capability=KnowledgeSearchCapabilityStatus.AVAILABLE,
    )

    result = keyword.search_requirements(
        KnowledgeSearchQuery(
            role_profile_ids=("rp-ai-application-intern",),
            terms=('Python%" OR NOT NEAR(delete)',),
        ),
        version_id="kbv-2026-07-1",
        limit=5,
    )

    assert [item.knowledge_requirement_id for item in result] == [
        "kr-python-application"
    ]
