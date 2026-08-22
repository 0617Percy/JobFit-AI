"""Publishing, immutability, retirement, and persisted hash verification."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta, timezone

import pytest

from jobfit.errors import ErrorCode, KnowledgeSeedError
from tests.knowledge.seed_factory import valid_seed_payload


def _services(database):
    from jobfit.knowledge.importer import KnowledgeSeedImporter
    from jobfit.knowledge.versioning import KnowledgeVersionPublisher

    return KnowledgeSeedImporter(database), KnowledgeVersionPublisher(database)


def _bundle(payload=None):
    from jobfit.knowledge.seed_models import KnowledgeSeedBundle

    return KnowledgeSeedBundle.model_validate(payload or valid_seed_payload())


def test_draft_is_not_visible_to_published_repository(knowledge_database) -> None:
    from jobfit.knowledge.repository import SqliteKnowledgeRepository

    importer, _ = _services(knowledge_database)
    importer.import_seed(_bundle())

    assert SqliteKnowledgeRepository(knowledge_database).get_published_version() is None


def test_publish_valid_draft_and_repository_can_read_it(knowledge_database) -> None:
    from jobfit.knowledge.repository import SqliteKnowledgeRepository

    importer, publisher = _services(knowledge_database)
    imported = importer.import_seed(_bundle())
    published_at = datetime(2099, 1, 3, tzinfo=UTC)

    result = publisher.publish(
        imported.version_id,
        published_at=published_at,
    )
    visible = SqliteKnowledgeRepository(knowledge_database).get_published_version("2099.01.1")

    assert result.status.value == "published"
    assert result.published_at == published_at
    assert result.content_hash == imported.content_hash
    assert visible is not None
    assert visible.content_hash == imported.content_hash
    assert result.published_at.utcoffset().total_seconds() == 0


def test_publish_normalizes_aware_timestamp_to_utc(knowledge_database) -> None:
    importer, publisher = _services(knowledge_database)
    imported = importer.import_seed(_bundle())

    result = publisher.publish(
        imported.version_id,
        published_at=datetime(
            2099,
            1,
            3,
            8,
            tzinfo=timezone(timedelta(hours=8)),
        ),
    )

    assert result.published_at == datetime(2099, 1, 3, tzinfo=UTC)
    assert result.published_at.utcoffset().total_seconds() == 0


@pytest.mark.parametrize(
    ("collection", "field", "value"),
    [
        ("role_profiles", "review_status", "pending"),
        ("role_requirements", "review_status", "rejected"),
        ("role_profiles", "is_active", False),
        ("role_requirements", "is_active", False),
        ("knowledge_sources", "review_status", "pending"),
        ("knowledge_sources", "license_note", None),
    ],
)
def test_publish_gate_rejects_unreviewed_or_unlicensed_content(
    knowledge_database,
    collection: str,
    field: str,
    value,
) -> None:
    payload = valid_seed_payload()
    payload[collection][0][field] = value
    importer, publisher = _services(knowledge_database)
    imported = importer.import_seed(_bundle(payload))

    with pytest.raises(KnowledgeSeedError) as exc_info:
        publisher.publish(imported.version_id)

    assert exc_info.value.code is ErrorCode.KNOWLEDGE_VERSION_NOT_PUBLISHABLE
    from jobfit.knowledge.repository import SqliteKnowledgeRepository

    version = SqliteKnowledgeRepository(knowledge_database).get_version(imported.version_id)
    assert version is not None
    assert version.status.value == "draft"


@pytest.mark.parametrize("empty_kind", ["family", "role"])
def test_publish_gate_rejects_empty_family_or_role(
    knowledge_database,
    empty_kind: str,
) -> None:
    payload = valid_seed_payload()
    if empty_kind == "family":
        family = deepcopy(payload["job_families"][0])
        family["id"] = "jf-synthetic-empty"
        family["code"] = "synthetic_empty"
        payload["job_families"].append(family)
    else:
        role = deepcopy(payload["role_profiles"][0])
        role["id"] = "rp-synthetic-empty"
        role["code"] = "synthetic_empty"
        payload["role_profiles"].append(role)
    importer, publisher = _services(knowledge_database)
    imported = importer.import_seed(_bundle(payload))

    with pytest.raises(KnowledgeSeedError) as exc_info:
        publisher.publish(imported.version_id)

    assert exc_info.value.code is ErrorCode.KNOWLEDGE_VERSION_NOT_PUBLISHABLE


def test_persisted_tampering_is_detected_before_publish(
    knowledge_database,
) -> None:
    from jobfit.knowledge.orm import RoleRequirementRecord

    importer, publisher = _services(knowledge_database)
    imported = importer.import_seed(_bundle())
    with knowledge_database._session_scope() as session:
        requirement = session.get(RoleRequirementRecord, "kr-synthetic-method")
        requirement.description = "Tampered after import."

    with pytest.raises(KnowledgeSeedError) as exc_info:
        publisher.publish(imported.version_id)

    assert exc_info.value.code is ErrorCode.KNOWLEDGE_SEED_HASH_MISMATCH


def test_seed_and_persisted_database_hash_are_identical(
    knowledge_database,
) -> None:
    from jobfit.knowledge.versioning import calculate_persisted_version_hash

    importer, _ = _services(knowledge_database)
    imported = importer.import_seed(_bundle())

    assert (
        calculate_persisted_version_hash(
            knowledge_database,
            imported.version_id,
        )
        == imported.content_hash
    )


def test_retire_preserves_hash_content_and_publication_time(
    knowledge_database,
) -> None:
    from jobfit.knowledge.orm import RoleRequirementRecord

    importer, publisher = _services(knowledge_database)
    imported = importer.import_seed(_bundle())
    published = publisher.publish(imported.version_id)
    retired = publisher.retire(imported.version_id)

    assert retired.status.value == "retired"
    assert retired.content_hash == published.content_hash
    assert retired.published_at == published.published_at
    with knowledge_database._session_scope() as session:
        requirement = session.get(RoleRequirementRecord, "kr-synthetic-method")
        assert requirement.description == ("Describe a method and how it was validated.")


def test_retire_requires_published_version(knowledge_database) -> None:
    importer, publisher = _services(knowledge_database)
    imported = importer.import_seed(_bundle())

    with pytest.raises(KnowledgeSeedError) as exc_info:
        publisher.retire(imported.version_id)

    assert exc_info.value.code is ErrorCode.KNOWLEDGE_VERSION_RETIRE_INVALID


def test_retired_version_cannot_retire_or_publish_again(
    knowledge_database,
) -> None:
    from jobfit.knowledge.repository import SqliteKnowledgeRepository
    from jobfit.knowledge.seed_models import SeedImportMode

    importer, publisher = _services(knowledge_database)
    imported = importer.import_seed(_bundle())
    publisher.publish(imported.version_id)
    publisher.retire(imported.version_id)

    with pytest.raises(KnowledgeSeedError):
        publisher.retire(imported.version_id)
    with pytest.raises(KnowledgeSeedError):
        publisher.publish(imported.version_id)
    with pytest.raises(KnowledgeSeedError):
        importer.import_seed(
            _bundle(),
            mode=SeedImportMode.REPLACE_DRAFT,
        )
    retired = SqliteKnowledgeRepository(knowledge_database).get_version(
        imported.version_id
    )
    assert retired is not None
    assert retired.status.value == "retired"


def test_published_version_cannot_be_imported_or_published_again(
    knowledge_database,
) -> None:
    importer, publisher = _services(knowledge_database)
    imported = importer.import_seed(_bundle())
    publisher.publish(imported.version_id)

    with pytest.raises(KnowledgeSeedError):
        importer.import_seed(_bundle())
    with pytest.raises(KnowledgeSeedError):
        publisher.publish(imported.version_id)


def test_hash_is_stable_after_collection_order_changes(knowledge_database) -> None:
    from jobfit.knowledge.seed_loader import calculate_seed_content_hash

    payload = valid_seed_payload()
    first = _bundle(payload)
    changed = deepcopy(payload)
    changed["role_profiles"][0]["keywords"].reverse()
    second = _bundle(changed)

    assert calculate_seed_content_hash(first) == calculate_seed_content_hash(second)
