"""Synchronous protocols for future job-knowledge persistence and retrieval."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from jobfit.knowledge.query import (
    DEFAULT_KNOWLEDGE_LIMIT,
    KnowledgeSearchQuery,
    RoleProfileQuery,
)
from jobfit.models import JobProfile
from jobfit.models.knowledge import (
    KnowledgeBaseVersionInfo,
    KnowledgeCitation,
    KnowledgeContext,
    KnowledgeSearchCapabilities,
    RetrievedEvidencePattern,
    RetrievedInterviewQuestion,
    RetrievedRequirement,
    RetrievedRoleProfile,
)


@runtime_checkable
class KnowledgeRepository(Protocol):
    """Pure domain interface; concrete storage remains a later phase."""

    def get_version(self, version_id: str) -> KnowledgeBaseVersionInfo | None: ...

    def get_published_version(
        self,
        version: str | None = None,
    ) -> KnowledgeBaseVersionInfo | None: ...

    def get_search_capabilities(self) -> KnowledgeSearchCapabilities: ...

    def search_role_profiles(
        self,
        query: RoleProfileQuery,
        *,
        version_id: str,
        limit: int,
    ) -> list[RetrievedRoleProfile]: ...

    def get_role_profile(
        self,
        role_profile_id: str,
        *,
        version_id: str,
    ) -> RetrievedRoleProfile | None: ...

    def search_requirements(
        self,
        query: KnowledgeSearchQuery,
        *,
        version_id: str,
        limit: int,
    ) -> list[RetrievedRequirement]: ...

    def search_evidence_patterns(
        self,
        requirement_ids: Sequence[str],
        *,
        version_id: str,
        limit: int,
    ) -> list[RetrievedEvidencePattern]: ...

    def search_interview_questions(
        self,
        query: KnowledgeSearchQuery,
        *,
        version_id: str,
        limit: int,
    ) -> list[RetrievedInterviewQuestion]: ...

    def get_sources(
        self,
        source_ids: Sequence[str],
        *,
        version_id: str,
    ) -> list[KnowledgeCitation]: ...

    def get_citations(
        self,
        citation_ids: Sequence[str],
        *,
        version_id: str,
    ) -> list[KnowledgeCitation]: ...

    def citation_exists(
        self,
        citation: KnowledgeCitation,
        *,
        version_id: str,
    ) -> bool: ...


@runtime_checkable
class KnowledgeRetriever(Protocol):
    """Resolve bounded reference knowledge for an existing JobProfile."""

    def retrieve_for_job(
        self,
        job_profile: JobProfile,
        *,
        limit: int = DEFAULT_KNOWLEDGE_LIMIT,
    ) -> KnowledgeContext: ...


__all__ = ["KnowledgeRepository", "KnowledgeRetriever"]
