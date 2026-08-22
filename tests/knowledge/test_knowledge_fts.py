"""FTS5 capability probing and rebuildable auxiliary search index."""

from __future__ import annotations

import sqlite3

import pytest
from sqlalchemy import func, select

from jobfit.errors import ErrorCode, JobFitError
from jobfit.knowledge.fts import (
    KNOWLEDGE_SEARCH_INDEX_VERSION,
    KnowledgeSearchIndex,
    detect_fts5_capability,
)
from jobfit.knowledge.orm import KnowledgeBaseVersionRecord
from jobfit.models.knowledge import KnowledgeSearchCapabilityStatus


def test_runtime_probe_uses_and_cleans_a_temporary_fts_table() -> None:
    connection = sqlite3.connect(":memory:")
    try:
        status = detect_fts5_capability(connection=connection)
        temp_names = connection.execute(
            "SELECT name FROM sqlite_temp_master WHERE name LIKE 'jobfit_fts_probe%'"
        ).fetchall()
    finally:
        connection.close()

    assert status in {
        KnowledgeSearchCapabilityStatus.AVAILABLE,
        KnowledgeSearchCapabilityStatus.UNAVAILABLE,
    }
    assert temp_names == []


def test_probe_distinguishes_unavailable_from_unexpected_failure() -> None:
    def unavailable() -> None:
        raise sqlite3.OperationalError("no such module: fts5")

    def failed() -> None:
        raise RuntimeError("synthetic probe failure")

    assert detect_fts5_capability(probe=unavailable) is (
        KnowledgeSearchCapabilityStatus.UNAVAILABLE
    )
    assert detect_fts5_capability(probe=failed) is (
        KnowledgeSearchCapabilityStatus.PROBE_FAILED
    )


def test_probe_does_not_create_a_persistent_database(tmp_path) -> None:
    assert detect_fts5_capability() in {
        KnowledgeSearchCapabilityStatus.AVAILABLE,
        KnowledgeSearchCapabilityStatus.UNAVAILABLE,
    }
    assert list(tmp_path.iterdir()) == []


def test_index_rebuild_is_idempotent_versioned_and_does_not_change_core_hash(
    seeded_database,
    knowledge_modules,
) -> None:
    index = KnowledgeSearchIndex(
        seeded_database,
        capability_override=KnowledgeSearchCapabilityStatus.AVAILABLE,
    )
    before_hash = None
    with seeded_database._session_scope() as session:
        before_hash = session.scalar(
            select(KnowledgeBaseVersionRecord.content_hash).where(
                KnowledgeBaseVersionRecord.id == "kbv-2026-07-1"
            )
        )

    first = index.rebuild_version("kbv-2026-07-1")
    second = index.rebuild_version("kbv-2026-07-1")
    verification = index.verify_version("kbv-2026-07-1")
    with seeded_database._session_scope() as session:
        after_hash = session.scalar(
            select(KnowledgeBaseVersionRecord.content_hash).where(
                KnowledgeBaseVersionRecord.id == "kbv-2026-07-1"
            )
        )
        core_versions = session.scalar(
            select(func.count()).select_from(KnowledgeBaseVersionRecord)
        )

    assert first.counts.model_dump() == {
        "role_profiles": 1,
        "role_requirements": 1,
        "knowledge_chunks": 1,
        "interview_questions": 1,
    }
    assert second == first
    assert verification.consistent is True
    assert verification.index_version == KNOWLEDGE_SEARCH_INDEX_VERSION
    assert before_hash == after_hash == "a" * 64
    assert core_versions == 1
    assert seeded_database.schema_version() == 1


def test_index_contains_only_published_approved_active_core_rows(
    seeded_database,
    knowledge_modules,
) -> None:
    orm = knowledge_modules["orm"]
    with seeded_database._session_scope() as session:
        role = session.get(orm.RoleProfileRecord, "rp-ai-application-intern")
        role.is_active = False
    index = KnowledgeSearchIndex(
        seeded_database,
        capability_override=KnowledgeSearchCapabilityStatus.AVAILABLE,
    )

    report = index.rebuild_version("kbv-2026-07-1")

    assert report.counts.model_dump() == {
        "role_profiles": 0,
        "role_requirements": 0,
        "knowledge_chunks": 0,
        "interview_questions": 0,
    }


def test_index_recalls_chunk_candidates_without_exposing_chunk_text(
    seeded_database,
) -> None:
    index = KnowledgeSearchIndex(
        seeded_database,
        capability_override=KnowledgeSearchCapabilityStatus.AVAILABLE,
    )
    index.rebuild_version("kbv-2026-07-1")

    candidates = index.search_candidates(
        version_id="kbv-2026-07-1",
        entity_types=("knowledge_chunk",),
        tokens=("python",),
        role_profile_ids=("rp-ai-application-intern",),
        limit=5,
    )

    assert [candidate.entity_id for candidate in candidates] == [
        "kc-ai-role-summary"
    ]
    assert not hasattr(candidates[0], "chunk_text")


def test_index_only_accepts_published_versions(knowledge_database) -> None:
    index = KnowledgeSearchIndex(
        knowledge_database,
        capability_override=KnowledgeSearchCapabilityStatus.AVAILABLE,
    )

    with pytest.raises(JobFitError) as exc_info:
        index.rebuild_version("kbv-missing")

    assert exc_info.value.code is ErrorCode.KNOWLEDGE_SEARCH_UNAVAILABLE
    assert str(knowledge_database.path) not in exc_info.value.user_message


def test_index_remove_makes_version_unavailable_without_touching_core_data(
    seeded_database,
) -> None:
    index = KnowledgeSearchIndex(
        seeded_database,
        capability_override=KnowledgeSearchCapabilityStatus.AVAILABLE,
    )
    index.rebuild_version("kbv-2026-07-1")

    index.remove_version("kbv-2026-07-1")

    assert index.verify_version("kbv-2026-07-1").consistent is False
    assert index.search_candidates(
        version_id="kbv-2026-07-1",
        entity_types=("role_profile",),
        tokens=("python",),
        limit=10,
    ) == []


def test_index_verification_detects_orphan_records(seeded_database) -> None:
    index = KnowledgeSearchIndex(
        seeded_database,
        capability_override=KnowledgeSearchCapabilityStatus.AVAILABLE,
    )
    index.rebuild_version("kbv-2026-07-1")
    with seeded_database._engine.begin() as connection:
        connection.exec_driver_sql(
            """
            DELETE FROM knowledge_search_fts
            WHERE entity_type = ? AND entity_id = ?
            """,
            ("role_profile", "rp-ai-application-intern"),
        )
        connection.exec_driver_sql(
            """
            INSERT INTO knowledge_search_fts(
                entity_type, entity_id, knowledge_version_id,
                role_profile_id, job_family_code, search_text
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "role_profile",
                "rp-orphan",
                "kbv-2026-07-1",
                "rp-orphan",
                "synthetic",
                "orphan",
            ),
        )

    assert index.verify_version("kbv-2026-07-1").consistent is False


def test_failed_rebuild_preserves_previous_index_rows(
    seeded_database,
    knowledge_modules,
) -> None:
    index = KnowledgeSearchIndex(
        seeded_database,
        capability_override=KnowledgeSearchCapabilityStatus.AVAILABLE,
    )
    index.rebuild_version("kbv-2026-07-1")
    orm = knowledge_modules["orm"]
    with seeded_database._session_scope() as session:
        role = session.get(orm.RoleProfileRecord, "rp-ai-application-intern")
        role.aliases_json = "{broken"

    with pytest.raises(JobFitError):
        index.rebuild_version("kbv-2026-07-1")

    with seeded_database._engine.connect() as connection:
        count = connection.exec_driver_sql(
            """
            SELECT count(*) FROM knowledge_search_fts
            WHERE knowledge_version_id = ?
            """,
            ("kbv-2026-07-1",),
        ).scalar_one()
    assert count == 4


def test_retired_version_is_not_verified_or_selected(
    seeded_database,
    knowledge_modules,
) -> None:
    index = KnowledgeSearchIndex(
        seeded_database,
        capability_override=KnowledgeSearchCapabilityStatus.AVAILABLE,
    )
    index.rebuild_version("kbv-2026-07-1")
    orm = knowledge_modules["orm"]
    with seeded_database._session_scope() as session:
        version = session.get(
            orm.KnowledgeBaseVersionRecord,
            "kbv-2026-07-1",
        )
        version.status = "retired"

    assert index.verify_version("kbv-2026-07-1").consistent is False
