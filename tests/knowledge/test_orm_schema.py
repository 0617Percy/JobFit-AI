"""Database constraints for the ten knowledge source-of-truth tables."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from jobfit.errors import ErrorCode, JobFitError


def test_orm_metadata_has_only_the_ten_approved_domain_tables(knowledge_modules) -> None:
    orm = knowledge_modules["orm"]

    assert set(orm.Base.metadata.tables) == {
        "knowledge_base_versions",
        "job_families",
        "role_profiles",
        "competency_dimensions",
        "role_requirements",
        "evidence_patterns",
        "knowledge_sources",
        "knowledge_chunks",
        "interview_questions",
        "source_role_links",
    }


def test_orm_tables_have_no_candidate_or_report_columns(knowledge_modules) -> None:
    forbidden = {
        "resume",
        "resume_text",
        "job_description",
        "jd_text",
        "candidate",
        "analysis_report",
        "final_score",
        "recommendation_level",
    }

    for table in knowledge_modules["orm"].Base.metadata.tables.values():
        assert forbidden.isdisjoint(table.columns.keys())


def test_public_package_does_not_export_orm_or_engine_details() -> None:
    from jobfit import knowledge

    assert {"Base", "Engine", "Session"}.isdisjoint(knowledge.__all__)
    assert not hasattr(knowledge.KnowledgeDatabase, "engine")


def test_duplicate_version_and_hash_are_rejected(knowledge_database, knowledge_modules) -> None:
    orm = knowledge_modules["orm"]
    now = datetime(2026, 7, 25, 8, 0, tzinfo=UTC)

    with knowledge_database._session_scope() as session:
        session.add(
            orm.KnowledgeBaseVersionRecord(
                id="kbv-one",
                version="2026.07.1",
                name="One",
                description="",
                status="draft",
                created_at=now,
                content_hash="a" * 64,
            )
        )

    with (
        pytest.raises(JobFitError) as exc_info,
        knowledge_database._session_scope() as session,
    ):
        session.add(
            orm.KnowledgeBaseVersionRecord(
                id="kbv-two",
                version="2026.07.1",
                name="Two",
                description="",
                status="draft",
                created_at=now,
                content_hash="b" * 64,
            )
        )

    assert exc_info.value.code is ErrorCode.KNOWLEDGE_DB_UNAVAILABLE


@pytest.mark.parametrize(
    ("table_name", "column_name", "invalid_value"),
    [
        ("knowledge_base_versions", "status", "invalid"),
        ("role_profiles", "review_status", "invalid"),
        ("role_requirements", "requirement_type", "invalid"),
        ("role_requirements", "importance", "invalid"),
        ("evidence_patterns", "strength", "invalid"),
        ("knowledge_sources", "source_type", "invalid"),
        ("knowledge_sources", "reliability_level", "invalid"),
        ("interview_questions", "question_type", "invalid"),
        ("interview_questions", "difficulty", "invalid"),
        ("source_role_links", "relation_type", "invalid"),
    ],
)
def test_enum_columns_expose_database_check_constraints(
    knowledge_modules,
    table_name,
    column_name,
    invalid_value,
) -> None:
    table = knowledge_modules["orm"].Base.metadata.tables[table_name]
    checks = [
        str(constraint.sqltext)
        for constraint in table.constraints
        if constraint.__class__.__name__ == "CheckConstraint"
    ]

    assert any(
        column_name in expression and invalid_value not in expression
        for expression in checks
    )


def test_chunk_offsets_have_pair_and_order_constraint(knowledge_modules) -> None:
    table = knowledge_modules["orm"].Base.metadata.tables["knowledge_chunks"]
    checks = " ".join(
        str(constraint.sqltext)
        for constraint in table.constraints
        if constraint.__class__.__name__ == "CheckConstraint"
    )

    assert "start_offset" in checks
    assert "end_offset" in checks


def test_source_url_and_hash_have_database_constraints(knowledge_modules) -> None:
    source_table = knowledge_modules["orm"].Base.metadata.tables["knowledge_sources"]
    version_table = knowledge_modules["orm"].Base.metadata.tables[
        "knowledge_base_versions"
    ]
    source_checks = " ".join(
        str(constraint.sqltext)
        for constraint in source_table.constraints
        if constraint.__class__.__name__ == "CheckConstraint"
    )
    version_checks = " ".join(
        str(constraint.sqltext)
        for constraint in version_table.constraints
        if constraint.__class__.__name__ == "CheckConstraint"
    )

    assert "http" in source_checks.lower()
    assert "64" in source_checks
    assert "64" in version_checks


def test_foreign_keys_restrict_or_nullify_without_cascade(knowledge_modules) -> None:
    metadata = knowledge_modules["orm"].Base.metadata

    for table in metadata.tables.values():
        for foreign_key in table.foreign_keys:
            assert foreign_key.ondelete in {"RESTRICT", "SET NULL"}


def test_source_role_link_uses_composite_primary_key(knowledge_modules) -> None:
    table = knowledge_modules["orm"].Base.metadata.tables["source_role_links"]

    assert [column.name for column in table.primary_key.columns] == [
        "source_id",
        "role_profile_id",
        "knowledge_version_id",
    ]


def test_required_indexes_have_stable_names(knowledge_modules) -> None:
    metadata = knowledge_modules["orm"].Base.metadata
    index_names = {
        index.name
        for table in metadata.tables.values()
        for index in table.indexes
    }

    assert {
        "ix_role_profiles_version_status_active_code",
        "ix_role_requirements_version_role_status_active",
        "ix_interview_questions_version_role_status_active",
    }.issubset(index_names)


def test_published_version_requires_published_timestamp_at_database_boundary(
    knowledge_database,
    knowledge_modules,
) -> None:
    orm = knowledge_modules["orm"]
    now = datetime(2026, 7, 25, 8, 0, tzinfo=UTC)

    with (
        pytest.raises(JobFitError),
        knowledge_database._session_scope() as session,
    ):
        session.add(
            orm.KnowledgeBaseVersionRecord(
                id="kbv-invalid-published",
                version="2026.09.1",
                name="Invalid",
                description="",
                status="published",
                published_at=None,
                created_at=now,
                content_hash="f" * 64,
            )
        )


def test_restrict_delete_prevents_removing_referenced_source(
    seeded_database,
    knowledge_modules,
) -> None:
    orm = knowledge_modules["orm"]

    with (
        pytest.raises(JobFitError),
        seeded_database._session_scope() as session,
    ):
        source = session.get(orm.KnowledgeSourceRecord, "ks-public-ai-role")
        session.delete(source)
