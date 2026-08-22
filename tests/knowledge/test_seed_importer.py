"""Transactional and idempotent imports into draft knowledge versions."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from jobfit.errors import ErrorCode, KnowledgeSeedError
from tests.knowledge.seed_factory import valid_seed_payload


def _bundle(payload=None):
    from jobfit.knowledge.seed_models import KnowledgeSeedBundle

    return KnowledgeSeedBundle.model_validate(payload or valid_seed_payload())


def _importer(database):
    from jobfit.knowledge.importer import KnowledgeSeedImporter

    return KnowledgeSeedImporter(database)


def _add_orphan_source(database, *, source_id: str, checksum: str) -> None:
    from jobfit.knowledge.orm import KnowledgeSourceRecord

    with database._session_scope() as session:
        session.add(
            KnowledgeSourceRecord(
                id=source_id,
                title="Synthetic pre-existing source",
                source_type="internal_template",
                publisher="JobFit test fixture",
                source_url="https://example.test/knowledge/pre-existing",
                published_at=None,
                collected_at=datetime(2099, 1, 1, tzinfo=UTC),
                license_note="Original synthetic test fixture.",
                reliability_level="medium",
                review_status="approved",
                checksum=checksum,
            )
        )


def test_import_creates_draft_and_all_ten_entity_sets(knowledge_database) -> None:
    result = _importer(knowledge_database).import_seed(_bundle())

    assert result.created is True
    assert result.idempotent is False
    assert result.status.value == "draft"
    assert result.content_hash
    assert result.counts.total == 10


def test_same_version_and_hash_is_idempotent(knowledge_database) -> None:
    from jobfit.knowledge.orm import SourceRoleLinkRecord

    importer = _importer(knowledge_database)
    first = importer.import_seed(_bundle())
    second = importer.import_seed(_bundle())

    assert second.idempotent is True
    assert second.created is False
    assert second.content_hash == first.content_hash
    assert second.created_at == first.created_at
    with knowledge_database._session_scope() as session:
        assert session.scalar(select(func.count(SourceRoleLinkRecord.source_id))) == 1


def test_importer_rejects_unvalidated_mapping_input(knowledge_database) -> None:
    with pytest.raises(KnowledgeSeedError) as exc_info:
        _importer(knowledge_database).import_seed(valid_seed_payload())

    assert exc_info.value.code is ErrorCode.KNOWLEDGE_SEED_SCHEMA_INVALID


def test_tampered_draft_is_not_misreported_as_idempotent(
    knowledge_database,
) -> None:
    from jobfit.knowledge.orm import RoleRequirementRecord

    importer = _importer(knowledge_database)
    importer.import_seed(_bundle())
    with knowledge_database._session_scope() as session:
        requirement = session.get(RoleRequirementRecord, "kr-synthetic-method")
        requirement.description = "Tampered draft."

    with pytest.raises(KnowledgeSeedError) as exc_info:
        importer.import_seed(_bundle())

    assert exc_info.value.code is ErrorCode.KNOWLEDGE_SEED_HASH_MISMATCH


def test_same_version_different_hash_conflicts_by_default(knowledge_database) -> None:
    importer = _importer(knowledge_database)
    importer.import_seed(_bundle())
    payload = valid_seed_payload()
    payload["role_requirements"][0]["description"] += " Changed."

    with pytest.raises(KnowledgeSeedError) as exc_info:
        importer.import_seed(_bundle(payload))

    assert exc_info.value.code is ErrorCode.KNOWLEDGE_DRAFT_CONFLICT


def test_explicit_replace_draft_replaces_atomically(knowledge_database) -> None:
    from jobfit.knowledge.seed_models import SeedImportMode

    importer = _importer(knowledge_database)
    first = importer.import_seed(_bundle())
    payload = valid_seed_payload()
    payload["role_requirements"][0]["description"] += " Changed."
    second = importer.import_seed(
        _bundle(payload),
        mode=SeedImportMode.REPLACE_DRAFT,
    )

    assert second.replaced_draft is True
    assert second.content_hash != first.content_hash


def test_invalid_seed_never_writes_partial_rows(knowledge_database) -> None:
    from jobfit.knowledge.orm import KnowledgeBaseVersionRecord

    payload = valid_seed_payload()
    payload["role_requirements"][0]["source_id"] = "ks-missing"

    with pytest.raises(KnowledgeSeedError):
        _importer(knowledge_database).import_seed(_bundle(payload))

    with knowledge_database._session_scope() as session:
        count = session.scalar(select(func.count(KnowledgeBaseVersionRecord.id)))
    assert count == 0


def test_database_constraint_failure_rolls_back_everything(
    knowledge_database,
) -> None:
    from jobfit.knowledge.orm import KnowledgeBaseVersionRecord

    _add_orphan_source(
        knowledge_database,
        source_id="ks-synthetic-preexisting",
        checksum="b" * 64,
    )
    payload = valid_seed_payload()
    bundle = _bundle(payload)

    with pytest.raises(KnowledgeSeedError):
        _importer(knowledge_database).import_seed(bundle)

    with knowledge_database._session_scope() as session:
        count = session.scalar(select(func.count(KnowledgeBaseVersionRecord.id)))
    assert count == 0


def test_failed_draft_replacement_restores_original_transaction(
    knowledge_database,
) -> None:
    from jobfit.knowledge.orm import (
        KnowledgeBaseVersionRecord,
        RoleRequirementRecord,
    )
    from jobfit.knowledge.seed_models import SeedImportMode

    importer = _importer(knowledge_database)
    original = importer.import_seed(_bundle())
    _add_orphan_source(
        knowledge_database,
        source_id="ks-synthetic-preexisting",
        checksum="d" * 64,
    )
    payload = valid_seed_payload()
    payload["role_requirements"][0]["description"] += " Changed."
    duplicate_checksum = deepcopy(payload["knowledge_sources"][0])
    duplicate_checksum["id"] = "ks-synthetic-duplicate"
    duplicate_checksum["checksum"] = "d" * 64
    payload["knowledge_sources"].append(duplicate_checksum)

    with pytest.raises(KnowledgeSeedError):
        importer.import_seed(
            _bundle(payload),
            mode=SeedImportMode.REPLACE_DRAFT,
        )

    with knowledge_database._session_scope() as session:
        version = session.get(
            KnowledgeBaseVersionRecord,
            "kbv-synthetic-2099-01-1",
        )
        requirement = session.get(
            RoleRequirementRecord,
            "kr-synthetic-method",
        )
        assert version.content_hash == original.content_hash
        assert requirement.description == ("Describe a method and how it was validated.")


def test_import_result_contains_no_storage_path(knowledge_database) -> None:
    result = _importer(knowledge_database).import_seed(_bundle())

    dumped = repr(result.model_dump()).casefold()
    assert "path" not in dumped
    assert "sql" not in dumped


def test_published_version_cannot_be_replaced(
    knowledge_database,
    seeded_database,
) -> None:
    from jobfit.knowledge.seed_models import SeedImportMode

    payload = valid_seed_payload()
    payload["knowledge_base_version"]["id"] = "kbv-2026-07-1"
    payload["knowledge_base_version"]["version"] = "2026.07.1"
    for collection in (
        "job_families",
        "role_profiles",
        "competency_dimensions",
        "role_requirements",
        "evidence_patterns",
        "knowledge_chunks",
        "interview_questions",
        "source_role_links",
    ):
        for item in payload[collection]:
            if "knowledge_version_id" in item:
                item["knowledge_version_id"] = "kbv-2026-07-1"

    with pytest.raises(KnowledgeSeedError) as exc_info:
        _importer(knowledge_database).import_seed(
            _bundle(payload),
            mode=SeedImportMode.REPLACE_DRAFT,
        )

    assert exc_info.value.code is ErrorCode.KNOWLEDGE_PUBLISHED_IMMUTABLE
