"""Strict contracts and boundary checks for versioned knowledge seeds."""

from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from tests.knowledge.seed_factory import valid_seed_payload


def _models():
    from jobfit.knowledge.seed_models import KnowledgeSeedBundle

    return KnowledgeSeedBundle


def test_valid_seed_bundle_is_frozen_and_serializable() -> None:
    bundle = _models().model_validate(valid_seed_payload())

    assert bundle.schema_version == "1.0"
    assert bundle.knowledge_base_version.status.value == "draft"
    assert _models().model_validate_json(bundle.model_dump_json()) == bundle
    with pytest.raises(ValidationError):
        bundle.schema_version = "2.0"


@pytest.mark.parametrize(
    ("collection", "field"),
    [
        ("job_families", "id"),
        ("role_profiles", "id"),
        ("competency_dimensions", "id"),
        ("role_requirements", "id"),
        ("evidence_patterns", "id"),
        ("knowledge_sources", "id"),
        ("knowledge_chunks", "id"),
        ("interview_questions", "id"),
    ],
)
def test_duplicate_entity_id_is_rejected(collection: str, field: str) -> None:
    payload = valid_seed_payload()
    payload[collection].append(deepcopy(payload[collection][0]))

    with pytest.raises(ValidationError, match="duplicate"):
        _models().model_validate(payload)


@pytest.mark.parametrize(
    ("collection", "field", "value"),
    [
        ("job_families", "id", "bad-id"),
        ("role_profiles", "id", "bad-id"),
        ("competency_dimensions", "id", "bad-id"),
        ("role_requirements", "id", "bad-id"),
        ("evidence_patterns", "id", "bad-id"),
        ("knowledge_sources", "id", "bad-id"),
        ("knowledge_chunks", "id", "bad-id"),
        ("interview_questions", "id", "bad-id"),
    ],
)
def test_stable_id_prefixes_are_required(
    collection: str,
    field: str,
    value: str,
) -> None:
    payload = valid_seed_payload()
    payload[collection][0][field] = value

    with pytest.raises(ValidationError):
        _models().model_validate(payload)


def test_seed_version_must_be_draft() -> None:
    payload = valid_seed_payload()
    payload["knowledge_base_version"]["status"] = "published"

    with pytest.raises(ValidationError, match="draft"):
        _models().model_validate(payload)


def test_unknown_fields_are_rejected() -> None:
    payload = valid_seed_payload()
    payload["role_profiles"][0]["candidate_has_skill"] = True

    with pytest.raises(ValidationError, match="extra"):
        _models().model_validate(payload)


def test_seed_contract_has_no_candidate_or_score_fields() -> None:
    bundle = _models().model_validate(valid_seed_payload())
    dumped = bundle.model_dump()
    serialized = repr(dumped)

    for forbidden in (
        "candidate_has_skill",
        "resume_start_char",
        "resume_end_char",
        "final_score",
        "recommendation_level",
    ):
        assert forbidden not in serialized


def test_public_api_exposes_services_without_write_internals() -> None:
    import jobfit.knowledge as knowledge

    for public_name in (
        "KnowledgeSeedBundle",
        "KnowledgeSeedImporter",
        "KnowledgeVersionPublisher",
        "SeedImportResult",
        "SeedPublishResult",
        "load_knowledge_seed",
        "calculate_seed_content_hash",
    ):
        assert public_name in knowledge.__all__
    for internal_name in ("Session", "Engine", "Base", "execute_sql"):
        assert internal_name not in knowledge.__all__
    assert not hasattr(knowledge.KnowledgeDatabase, "session_scope")
