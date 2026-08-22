"""Read-only structured queries over reviewed, published SQLite knowledge."""

from __future__ import annotations

import importlib
from datetime import UTC, datetime, timedelta

import pytest

from jobfit.errors import ErrorCode, JobFitError
from jobfit.knowledge.protocol import KnowledgeRepository
from jobfit.knowledge.query import KnowledgeSearchQuery, RoleProfileQuery
from jobfit.models import Importance, RequirementType
from jobfit.models.knowledge import (
    KnowledgeCitation,
    KnowledgeSearchBackend,
    KnowledgeSearchCapabilityStatus,
    RetrievedEvidencePattern,
    RetrievedInterviewQuestion,
    RetrievedRequirement,
    RetrievedRoleProfile,
)


def repository_for(database):
    module = importlib.import_module("jobfit.knowledge.repository")
    return module.SqliteKnowledgeRepository(database)


def test_repository_satisfies_protocol_and_reports_structured_capability(
    seeded_database,
) -> None:
    repository = repository_for(seeded_database)

    assert isinstance(repository, KnowledgeRepository)
    capabilities = repository.get_search_capabilities()
    assert capabilities.mode in {
        KnowledgeSearchBackend.FTS5,
        KnowledgeSearchBackend.KEYWORD_FALLBACK,
    }
    assert capabilities.status in {
        KnowledgeSearchCapabilityStatus.AVAILABLE,
        KnowledgeSearchCapabilityStatus.UNAVAILABLE,
        KnowledgeSearchCapabilityStatus.PROBE_FAILED,
    }


def test_get_published_version_by_value_and_latest(seeded_database) -> None:
    repository = repository_for(seeded_database)

    explicit = repository.get_published_version("2026.07.1")
    latest = repository.get_published_version()

    assert explicit is not None
    assert latest == explicit
    assert explicit.id == "kbv-2026-07-1"


def test_get_version_can_read_published_metadata(seeded_database) -> None:
    result = repository_for(seeded_database).get_version("kbv-2026-07-1")

    assert result is not None
    assert result.status.value == "published"


def test_draft_is_not_returned_as_published(knowledge_database, knowledge_modules) -> None:
    orm = knowledge_modules["orm"]
    now = datetime(2026, 7, 25, 8, 0, tzinfo=UTC)
    with knowledge_database._session_scope() as session:
        session.add(
            orm.KnowledgeBaseVersionRecord(
                id="kbv-draft-only",
                version="2026.08.1",
                name="Draft",
                description="",
                status="draft",
                created_at=now,
                content_hash="d" * 64,
            )
        )

    repository = repository_for(knowledge_database)
    assert repository.get_version("kbv-draft-only") is not None
    assert repository.get_published_version("2026.08.1") is None
    assert repository.get_published_version() is None


def test_latest_published_version_uses_time_then_stable_id(
    seeded_database,
    knowledge_modules,
) -> None:
    orm = knowledge_modules["orm"]
    later = datetime(2026, 8, 1, 8, 0, tzinfo=UTC)
    with seeded_database._session_scope() as session:
        session.add(
            orm.KnowledgeBaseVersionRecord(
                id="kbv-2026-08-1",
                version="2026.08.1",
                name="Later",
                description="",
                status="published",
                published_at=later,
                created_at=later,
                content_hash="d" * 64,
            )
        )

    assert (
        repository_for(seeded_database).get_published_version().id
        == "kbv-2026-08-1"
    )


def test_search_role_profiles_returns_domain_model_with_stable_citation(
    seeded_database,
) -> None:
    results = repository_for(seeded_database).search_role_profiles(
        RoleProfileQuery(
            title="AI application intern",
            seniority="intern",
        ),
        version_id="kbv-2026-07-1",
        limit=12,
    )

    assert len(results) == 1
    assert isinstance(results[0], RetrievedRoleProfile)
    assert results[0].role_profile_id == "rp-ai-application-intern"
    assert results[0].citation_ids[0].startswith("cite-")
    assert not hasattr(results[0], "_sa_instance_state")


def test_get_role_profile_and_missing_result(seeded_database) -> None:
    repository = repository_for(seeded_database)

    result = repository.get_role_profile(
        "rp-ai-application-intern",
        version_id="kbv-2026-07-1",
    )
    missing = repository.get_role_profile(
        "rp-missing",
        version_id="kbv-2026-07-1",
    )

    assert isinstance(result, RetrievedRoleProfile)
    assert missing is None


def test_search_requirements_filters_role_type_and_importance(
    seeded_database,
) -> None:
    results = repository_for(seeded_database).search_requirements(
        KnowledgeSearchQuery(
            role_profile_ids=("rp-ai-application-intern",),
            terms=(),
            requirement_types=(RequirementType.MUST_HAVE,),
            importance_levels=(Importance.HIGH,),
        ),
        version_id="kbv-2026-07-1",
        limit=12,
    )

    assert len(results) == 1
    assert isinstance(results[0], RetrievedRequirement)
    assert results[0].is_common_hard_blocker is True
    assert not hasattr(results[0], "final_score")


def test_search_evidence_patterns_returns_approved_active_domain_rows(
    seeded_database,
) -> None:
    results = repository_for(seeded_database).search_evidence_patterns(
        ["kr-python-application"],
        version_id="kbv-2026-07-1",
        limit=12,
    )

    assert len(results) == 1
    assert isinstance(results[0], RetrievedEvidencePattern)


def test_search_interview_questions_returns_domain_rows(seeded_database) -> None:
    results = repository_for(seeded_database).search_interview_questions(
        KnowledgeSearchQuery(
            role_profile_ids=("rp-ai-application-intern",),
            terms=(),
        ),
        version_id="kbv-2026-07-1",
        limit=12,
    )

    assert len(results) == 1
    assert isinstance(results[0], RetrievedInterviewQuestion)


def test_get_sources_returns_stable_domain_citations(seeded_database) -> None:
    repository = repository_for(seeded_database)
    first = repository.get_sources(
        ["ks-public-ai-role"],
        version_id="kbv-2026-07-1",
    )
    second = repository.get_sources(
        ["ks-public-ai-role"],
        version_id="kbv-2026-07-1",
    )

    assert first == second
    assert len(first) == 1
    assert isinstance(first[0], KnowledgeCitation)


def test_citation_exists_checks_version_source_and_stable_id(seeded_database) -> None:
    repository = repository_for(seeded_database)
    citation = repository.get_sources(
        ["ks-public-ai-role"],
        version_id="kbv-2026-07-1",
    )[0]

    assert repository.citation_exists(
        citation,
        version_id="kbv-2026-07-1",
    )
    assert not repository.citation_exists(
        citation,
        version_id="kbv-missing",
    )


@pytest.mark.parametrize("invalid_limit", [0, -1, 21, True])
def test_repository_rejects_invalid_limits(
    seeded_database,
    invalid_limit,
) -> None:
    repository = repository_for(seeded_database)

    with pytest.raises(ValueError):
        repository.search_role_profiles(
            RoleProfileQuery(title="AI application intern"),
            version_id="kbv-2026-07-1",
            limit=invalid_limit,
        )


def test_repository_applies_limit_in_query_and_stable_order(
    seeded_database,
    knowledge_modules,
) -> None:
    orm = knowledge_modules["orm"]
    now = datetime(2026, 7, 25, 8, 0, tzinfo=UTC)
    with seeded_database._session_scope() as session:
        session.add(
            orm.RoleProfileRecord(
                id="rp-ai-application-junior",
                job_family_id="jf-ai-application",
                code="ai_application_junior",
                name="AI application intern",
                seniority="intern",
                industry=None,
                description="Second stable anonymous profile.",
                aliases_json="[]",
                keywords_json="[]",
                knowledge_version_id="kbv-2026-07-1",
                review_status="approved",
                is_active=True,
                created_at=now + timedelta(seconds=1),
                updated_at=now + timedelta(seconds=1),
            )
        )
        session.add(
            orm.SourceRoleLinkRecord(
                source_id="ks-public-ai-role",
                role_profile_id="rp-ai-application-junior",
                knowledge_version_id="kbv-2026-07-1",
                relation_type="supports",
                created_at=now,
            )
        )

    results = repository_for(seeded_database).search_role_profiles(
        RoleProfileQuery(title="AI application intern"),
        version_id="kbv-2026-07-1",
        limit=1,
    )

    assert [item.role_profile_id for item in results] == [
        "rp-ai-application-intern"
    ]


def test_rejected_or_inactive_rows_are_not_returned(
    seeded_database,
    knowledge_modules,
) -> None:
    orm = knowledge_modules["orm"]
    now = datetime(2026, 7, 25, 8, 0, tzinfo=UTC)
    with seeded_database._session_scope() as session:
        session.add(
            orm.RoleProfileRecord(
                id="rp-rejected",
                job_family_id="jf-ai-application",
                code="rejected",
                name="Rejected role",
                seniority="intern",
                industry=None,
                description="Must not be returned.",
                aliases_json="[]",
                keywords_json="[]",
                knowledge_version_id="kbv-2026-07-1",
                review_status="rejected",
                is_active=True,
                created_at=now,
                updated_at=now,
            )
        )

    results = repository_for(seeded_database).search_role_profiles(
        RoleProfileQuery(title="Rejected role"),
        version_id="kbv-2026-07-1",
        limit=12,
    )

    assert results == []


def test_missing_and_corrupt_database_fail_safely_without_creation(
    tmp_path,
    knowledge_modules,
) -> None:
    db = knowledge_modules["db"]
    missing_path = tmp_path / "missing.sqlite3"
    missing_repository = repository_for(db.KnowledgeDatabase(missing_path))

    with pytest.raises(JobFitError) as missing_error:
        missing_repository.get_published_version()
    assert missing_error.value.code is ErrorCode.KNOWLEDGE_DB_UNAVAILABLE
    assert not missing_path.exists()

    corrupt_path = tmp_path / "corrupt.sqlite3"
    corrupt_path.write_bytes(b"not sqlite")
    corrupt_repository = repository_for(db.KnowledgeDatabase(corrupt_path))
    with pytest.raises(JobFitError) as corrupt_error:
        corrupt_repository.get_published_version()
    assert corrupt_error.value.code is ErrorCode.KNOWLEDGE_DB_UNAVAILABLE
    assert str(corrupt_path) not in corrupt_error.value.user_message


def test_repository_module_does_not_depend_on_matching_or_scoring() -> None:
    module = importlib.import_module("jobfit.knowledge.repository")

    assert "ScoringEngine" not in module.__dict__
    assert "EvidenceMatcher" not in module.__dict__
