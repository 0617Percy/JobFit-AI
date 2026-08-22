"""Pure synchronous protocols for future knowledge persistence and retrieval."""

from __future__ import annotations

import importlib
import inspect
from collections.abc import Sequence
from decimal import Decimal
from typing import get_type_hints

import pytest

import jobfit.knowledge as public_knowledge
import jobfit.models as public_models
from jobfit.models import (
    HardConditionKind,
    Importance,
    JobProfile,
    JobRequirement,
    JobRequirementCollection,
    LanguageCode,
    RequirementCategory,
    RequirementType,
)


def knowledge_module():
    return importlib.import_module("jobfit.models.knowledge")


def protocol_module():
    return importlib.import_module("jobfit.knowledge.protocol")


def query_module():
    return importlib.import_module("jobfit.knowledge.query")


def make_job_profile() -> JobProfile:
    requirement = JobRequirement(
        requirement_id="req-python",
        requirement_text="熟悉 Python",
        source_text="熟悉 Python",
        source_start_char=0,
        source_end_char=9,
        requirement_type=RequirementType.MUST_HAVE,
        category=RequirementCategory.TECHNICAL_SKILL,
        importance=Importance.HIGH,
        mandatory=True,
        hard_condition_kind=HardConditionKind.NONE,
        normalized_key="python",
        priority_factor=Decimal("0"),
        weight=Decimal("0"),
    )
    return JobProfile(
        job_id="job-ai-intern",
        title="AI 应用实习生",
        company=None,
        language=LanguageCode.ZH,
        jd_text="熟悉 Python",
        summary="AI 应用岗位",
        requirements=JobRequirementCollection(
            items=[requirement],
            source_coverage_ratio=Decimal("1"),
        ),
        keywords=["Python"],
    )


class FakeKnowledgeRepository:
    def get_version(self, version_id: str):
        return None

    def get_published_version(self, version: str | None = None):
        return None

    def get_search_capabilities(self):
        knowledge = knowledge_module()
        return knowledge.KnowledgeSearchCapabilities(
            mode="disabled",
            fts5_available=False,
        )

    def search_role_profiles(self, query, *, version_id: str, limit: int):
        return []

    def get_role_profile(self, role_profile_id: str, *, version_id: str):
        return None

    def search_requirements(self, query, *, version_id: str, limit: int):
        return []

    def search_evidence_patterns(
        self,
        requirement_ids: Sequence[str],
        *,
        version_id: str,
        limit: int,
    ):
        return []

    def search_interview_questions(
        self,
        query,
        *,
        version_id: str,
        limit: int,
    ):
        return []

    def get_sources(self, source_ids: Sequence[str], *, version_id: str):
        return []

    def get_citations(self, citation_ids: Sequence[str], *, version_id: str):
        return []

    def citation_exists(self, citation, *, version_id: str):
        return False


class FakeKnowledgeRetriever:
    def retrieve_for_job(
        self,
        job_profile: JobProfile,
        *,
        limit: int = 12,
    ):
        return knowledge_module().KnowledgeContext()


def test_repository_and_retriever_are_runtime_checkable_sync_protocols() -> None:
    protocol = protocol_module()

    assert isinstance(FakeKnowledgeRepository(), protocol.KnowledgeRepository)
    assert isinstance(FakeKnowledgeRetriever(), protocol.KnowledgeRetriever)
    assert not inspect.iscoroutinefunction(
        protocol.KnowledgeRetriever.retrieve_for_job
    )
    assert not inspect.iscoroutinefunction(
        protocol.KnowledgeRepository.search_requirements
    )


def test_protocol_annotations_use_only_domain_contracts() -> None:
    protocol = protocol_module()
    knowledge = knowledge_module()

    role_hints = get_type_hints(
        protocol.KnowledgeRepository.search_role_profiles
    )
    retrieve_hints = get_type_hints(
        protocol.KnowledgeRetriever.retrieve_for_job
    )

    assert role_hints["return"] == list[knowledge.RetrievedRoleProfile]
    assert retrieve_hints["job_profile"] is JobProfile
    assert retrieve_hints["return"] is knowledge.KnowledgeContext
    assert "sqlalchemy" not in protocol.__dict__


def test_public_knowledge_imports_resolve_to_the_domain_contracts() -> None:
    protocol = protocol_module()
    knowledge = knowledge_module()
    query = query_module()

    assert public_models.KnowledgeContext is knowledge.KnowledgeContext
    assert public_models.KnowledgeCitation is knowledge.KnowledgeCitation
    assert public_knowledge.KnowledgeRepository is protocol.KnowledgeRepository
    assert public_knowledge.KnowledgeRetriever is protocol.KnowledgeRetriever
    assert public_knowledge.RoleProfileQuery is query.RoleProfileQuery
    assert callable(public_knowledge.detect_fts5_capability)
    assert callable(public_knowledge.normalize_search_text)
    assert public_knowledge.KnowledgeSearchIndex.__name__ == "KnowledgeSearchIndex"
    assert (
        public_models.KnowledgeSearchCapabilityStatus
        is knowledge.KnowledgeSearchCapabilityStatus
    )


def test_normal_empty_repository_results_use_none_and_empty_lists() -> None:
    repository = FakeKnowledgeRepository()
    query = query_module().RoleProfileQuery(title="AI 应用实习生")

    assert repository.get_published_version() is None
    assert (
        repository.search_role_profiles(
            query,
            version_id="kbv-2026-07-1",
            limit=12,
        )
        == []
    )
    assert (
        repository.get_role_profile(
            "rp-missing",
            version_id="kbv-2026-07-1",
        )
        is None
    )


def test_query_objects_are_frozen_validated_and_reuse_job_enums() -> None:
    query = query_module()

    role_query = query.RoleProfileQuery(
        title=" AI 应用实习生 ",
        aliases=("ai intern",),
        seniority="intern",
        keywords=("python",),
        job_family_codes=("ai_application",),
    )
    search_query = query.KnowledgeSearchQuery(
        role_profile_ids=("rp-ai-application-intern",),
        terms=("python",),
        requirement_types=(RequirementType.MUST_HAVE,),
        importance_levels=(Importance.HIGH,),
        source_ids=("ks-synthetic-source",),
    )

    assert role_query.title == "AI 应用实习生"
    assert role_query.job_family_codes == ("ai_application",)
    assert search_query.requirement_types == (RequirementType.MUST_HAVE,)
    assert search_query.source_ids == ("ks-synthetic-source",)
    with pytest.raises((AttributeError, TypeError)):
        role_query.title = "changed"
    with pytest.raises(ValueError):
        query.RoleProfileQuery(title=" ")
    with pytest.raises(ValueError):
        query.KnowledgeSearchQuery(
            role_profile_ids=(),
            terms=("python",),
        )


@pytest.mark.parametrize("invalid", [True, 0, -1, 21])
def test_knowledge_limit_rejects_non_positive_boolean_or_excessive_values(
    invalid: int,
) -> None:
    with pytest.raises(ValueError):
        query_module().validate_knowledge_limit(invalid)


@pytest.mark.parametrize("valid", [1, 12, 20])
def test_knowledge_limit_accepts_bounded_positive_values(valid: int) -> None:
    assert query_module().validate_knowledge_limit(valid) == valid


def test_retriever_does_not_mutate_job_profile_or_return_scores() -> None:
    job = make_job_profile()
    before = job.model_dump()
    context = FakeKnowledgeRetriever().retrieve_for_job(job, limit=12)

    assert job.model_dump() == before
    assert context == knowledge_module().KnowledgeContext()
    assert "score_summary" not in type(context).model_fields
