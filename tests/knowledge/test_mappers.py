"""ORM rows must be revalidated into pure Pydantic knowledge contracts."""

from __future__ import annotations

import importlib
from decimal import Decimal

import pytest

from jobfit.errors import ErrorCode, JobFitError
from jobfit.models import EvidenceItem
from jobfit.models.knowledge import (
    KnowledgeCitation,
    RetrievedEvidencePattern,
    RetrievedInterviewQuestion,
    RetrievedRequirement,
    RetrievedRoleProfile,
)


def mapper_module():
    return importlib.import_module("jobfit.knowledge.mappers")


def test_version_mapper_returns_pure_domain_object(
    seeded_database,
    knowledge_modules,
) -> None:
    orm = knowledge_modules["orm"]
    with seeded_database._session_scope() as session:
        record = session.get(orm.KnowledgeBaseVersionRecord, "kbv-2026-07-1")
        result = mapper_module().map_version(record)

    assert result.version == "2026.07.1"
    assert result.status.value == "published"
    assert not hasattr(result, "_sa_instance_state")


def test_source_mapper_generates_stable_citation_without_resume_fields(
    seeded_database,
    knowledge_modules,
) -> None:
    orm = knowledge_modules["orm"]
    with seeded_database._session_scope() as session:
        source = session.get(orm.KnowledgeSourceRecord, "ks-public-ai-role")
        first = mapper_module().map_source_citation(
            source,
            version_id="kbv-2026-07-1",
        )
        second = mapper_module().map_source_citation(
            source,
            version_id="kbv-2026-07-1",
        )

    assert isinstance(first, KnowledgeCitation)
    assert first == second
    assert first.citation_id.startswith("cite-")
    assert not isinstance(first, EvidenceItem)
    assert {"start_char", "end_char", "document_id"}.isdisjoint(
        type(first).model_fields
    )


def test_all_read_mappers_return_domain_types(
    seeded_database,
    knowledge_modules,
) -> None:
    orm = knowledge_modules["orm"]
    maps = mapper_module()
    with seeded_database._session_scope() as session:
        source = session.get(orm.KnowledgeSourceRecord, "ks-public-ai-role")
        citation = maps.map_source_citation(source, version_id="kbv-2026-07-1")
        role = session.get(orm.RoleProfileRecord, "rp-ai-application-intern")
        requirement = session.get(
            orm.RoleRequirementRecord,
            "kr-python-application",
        )
        pattern = session.get(orm.EvidencePatternRecord, "ep-python-project")
        question = session.get(orm.InterviewQuestionRecord, "iq-ai-project")

        mapped_role = maps.map_role_profile(
            role,
            job_family_code="ai_application",
            citation_ids=[citation.citation_id],
            matched_terms=["AI application intern"],
            relevance_score=Decimal("1.0000"),
        )
        mapped_requirement = maps.map_requirement(
            requirement,
            competency_dimension_code="application_engineering",
            citation_ids=[citation.citation_id],
            relevance_score=Decimal("1.0000"),
        )
        mapped_pattern = maps.map_evidence_pattern(
            pattern,
            citation_ids=[citation.citation_id],
        )
        mapped_question = maps.map_interview_question(
            question,
            competency_dimension_code="application_engineering",
            citation_ids=[citation.citation_id],
            relevance_score=Decimal("1.0000"),
        )

    assert isinstance(mapped_role, RetrievedRoleProfile)
    assert isinstance(mapped_requirement, RetrievedRequirement)
    assert isinstance(mapped_pattern, RetrievedEvidencePattern)
    assert isinstance(mapped_question, RetrievedInterviewQuestion)
    assert mapped_requirement.expected_evidence == [
        "implemented a Python project"
    ]
    assert mapped_question.expected_points == ["context", "action", "validation"]


def test_invalid_json_fails_closed_with_safe_domain_error(
    seeded_database,
    knowledge_modules,
) -> None:
    orm = knowledge_modules["orm"]
    with seeded_database._session_scope() as session:
        requirement = session.get(
            orm.RoleRequirementRecord,
            "kr-python-application",
        )
        requirement.expected_evidence_json = '{"not":"a list"}'
        session.flush()

        with pytest.raises(JobFitError) as exc_info:
            mapper_module().map_requirement(
                requirement,
                competency_dimension_code="application_engineering",
                citation_ids=["cite-0123456789abcdef"],
                relevance_score=Decimal("1.0000"),
            )

    assert exc_info.value.code is ErrorCode.KNOWLEDGE_DB_UNAVAILABLE
    assert "SELECT" not in exc_info.value.user_message


def test_invalid_url_is_revalidated_and_rejected(
    seeded_database,
    knowledge_modules,
) -> None:
    orm = knowledge_modules["orm"]
    with seeded_database._session_scope() as session:
        source = session.get(orm.KnowledgeSourceRecord, "ks-public-ai-role")
        source.source_url = r"C:\private\source.txt"

        with pytest.raises(JobFitError) as exc_info:
            mapper_module().map_source_citation(
                source,
                version_id="kbv-2026-07-1",
            )
        session.rollback()

    assert exc_info.value.code is ErrorCode.KNOWLEDGE_DB_UNAVAILABLE


def test_mapper_module_exposes_no_scoring_or_evidence_conversion() -> None:
    module = mapper_module()

    assert not hasattr(module, "to_evidence_item")
    assert not hasattr(module, "score_requirement")
