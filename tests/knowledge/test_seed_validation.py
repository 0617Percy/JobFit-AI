"""Cross-entity referential and integrity validation for seed bundles."""

from __future__ import annotations

from copy import deepcopy

import pytest

from jobfit.errors import ErrorCode, KnowledgeSeedError
from tests.knowledge.seed_factory import valid_seed_payload


def _bundle(payload):
    from jobfit.knowledge.seed_models import KnowledgeSeedBundle

    return KnowledgeSeedBundle.model_validate(payload)


def _validate(payload):
    from jobfit.knowledge.seed_loader import validate_knowledge_seed

    return validate_knowledge_seed(_bundle(payload))


@pytest.mark.parametrize(
    ("collection", "field", "value"),
    [
        ("role_profiles", "job_family_id", "jf-missing"),
        ("role_requirements", "role_profile_id", "rp-missing"),
        ("role_requirements", "competency_dimension_id", "cd-missing"),
        ("role_requirements", "source_id", "ks-missing"),
        ("evidence_patterns", "role_requirement_id", "kr-missing"),
        ("knowledge_chunks", "source_id", "ks-missing"),
        ("interview_questions", "role_profile_id", "rp-missing"),
        ("source_role_links", "source_id", "ks-missing"),
    ],
)
def test_dangling_references_are_rejected(
    collection: str,
    field: str,
    value: str,
) -> None:
    payload = valid_seed_payload()
    payload[collection][0][field] = value

    with pytest.raises(KnowledgeSeedError) as exc_info:
        _validate(payload)

    assert exc_info.value.code is ErrorCode.KNOWLEDGE_SEED_REFERENCE_INVALID


def test_cross_version_reference_is_rejected() -> None:
    payload = valid_seed_payload()
    payload["role_profiles"][0]["knowledge_version_id"] = "kbv-other-version"

    with pytest.raises(KnowledgeSeedError):
        _validate(payload)


@pytest.mark.parametrize(
    ("collection", "field"),
    [
        ("job_families", "code"),
        ("role_profiles", "code"),
        ("competency_dimensions", "code"),
        ("knowledge_sources", "checksum"),
    ],
)
def test_duplicate_business_keys_are_rejected(
    collection: str,
    field: str,
) -> None:
    payload = valid_seed_payload()
    duplicate = deepcopy(payload[collection][0])
    duplicate["id"] = {
        "job_families": "jf-synthetic-other",
        "role_profiles": "rp-synthetic-other",
        "competency_dimensions": "cd-synthetic-other",
        "knowledge_sources": "ks-synthetic-other",
    }[collection]
    payload[collection].append(duplicate)

    with pytest.raises(KnowledgeSeedError):
        _validate(payload)


def test_chunk_offsets_and_hash_must_match_content() -> None:
    payload = valid_seed_payload()
    payload["knowledge_chunks"][0]["end_offset"] += 1
    with pytest.raises(KnowledgeSeedError):
        _validate(payload)

    payload = valid_seed_payload()
    payload["knowledge_chunks"][0]["content_hash"] = "d" * 64
    with pytest.raises(KnowledgeSeedError):
        _validate(payload)


def test_duplicate_relationship_is_rejected() -> None:
    payload = valid_seed_payload()
    payload["source_role_links"].append(deepcopy(payload["source_role_links"][0]))

    with pytest.raises(Exception, match="duplicate"):
        _bundle(payload)


def test_source_must_be_linked_to_the_role_it_supports() -> None:
    payload = valid_seed_payload()
    payload["source_role_links"] = []

    with pytest.raises(KnowledgeSeedError) as exc_info:
        _validate(payload)

    assert exc_info.value.code is ErrorCode.KNOWLEDGE_SEED_REFERENCE_INVALID


def test_unreferenced_source_is_rejected_before_import() -> None:
    payload = valid_seed_payload()
    source = deepcopy(payload["knowledge_sources"][0])
    source["id"] = "ks-synthetic-unused"
    source["checksum"] = "d" * 64
    payload["knowledge_sources"].append(source)

    with pytest.raises(KnowledgeSeedError) as exc_info:
        _validate(payload)

    assert exc_info.value.code is ErrorCode.KNOWLEDGE_SEED_REFERENCE_INVALID


def test_valid_bundle_passes_integrity_validation() -> None:
    bundle = _validate(valid_seed_payload())

    assert bundle.knowledge_base_version.id == "kbv-synthetic-2099-01-1"
