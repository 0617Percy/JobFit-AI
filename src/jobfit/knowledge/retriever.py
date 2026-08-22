"""Deterministic, bounded retrieval of reviewed reference knowledge."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from decimal import Decimal

from jobfit.errors import ErrorCode, KnowledgeDatabaseError
from jobfit.knowledge.normalization import normalize_query_terms, normalize_search_text
from jobfit.knowledge.protocol import KnowledgeRepository
from jobfit.knowledge.query import (
    KnowledgeSearchQuery,
    RoleProfileQuery,
    validate_knowledge_limit,
)
from jobfit.knowledge.ranking import ROLE_RELEVANCE_THRESHOLD
from jobfit.models import JobProfile
from jobfit.models.knowledge import (
    KnowledgeBaseVersionInfo,
    KnowledgeCitation,
    KnowledgeContext,
    KnowledgeRetrievalStatus,
    KnowledgeSearchBackend,
    KnowledgeSearchCapabilities,
    KnowledgeSearchMode,
    KnowledgeVersionStatus,
    KnowledgeWarning,
    KnowledgeWarningCode,
    RetrievedEvidencePattern,
    RetrievedInterviewQuestion,
    RetrievedRequirement,
    RetrievedRoleProfile,
)

ROLE_CANDIDATE_LIMIT = 3
ROLE_AMBIGUITY_MARGIN = Decimal("0.0500")
EVIDENCE_PATTERN_LIMIT = 12
EVIDENCE_PATTERNS_PER_REQUIREMENT = 2
INTERVIEW_QUESTION_LIMIT = 10
CITATION_LIMIT = 20


def build_role_resolution_query(job_profile: JobProfile) -> RoleProfileQuery:
    """Build a stable query from structured job facts, never the full JD."""
    title = normalize_search_text(job_profile.title or job_profile.summary)
    requirement_signals = tuple(
        signal
        for requirement in job_profile.requirements.items
        for signal in (
            requirement.normalized_key.replace("_", " "),
            requirement.requirement_text,
        )
    )
    keywords = normalize_query_terms(
        (
            job_profile.summary,
            *job_profile.keywords,
            *requirement_signals,
        )
    )
    return RoleProfileQuery(title=title, keywords=keywords)


def build_knowledge_cache_identity(
    context: KnowledgeContext,
    *,
    requirement_limit: int,
    prompt_char_limit: int,
) -> str:
    """Hash only stable knowledge identity and bounded retrieval configuration."""
    safe_limit = validate_knowledge_limit(requirement_limit)
    if isinstance(prompt_char_limit, bool) or prompt_char_limit <= 0:
        raise ValueError("prompt_char_limit must be a positive integer")
    selected_role_id = (
        context.inferred_role_profiles[0].role_profile_id
        if context.status is KnowledgeRetrievalStatus.AVAILABLE
        else None
    )
    payload = {
        "enabled": context.status is not KnowledgeRetrievalStatus.DISABLED,
        "status": context.status.value,
        "knowledge_version": context.version.version if context.version else None,
        "content_hash": context.version.content_hash if context.version else None,
        "retrieval_mode": context.capabilities.mode.value,
        "strategy_version": context.retrieval_strategy_version,
        "selected_role_profile_id": selected_role_id,
        "requirement_limit": safe_limit,
        "prompt_char_limit": prompt_char_limit,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _warning(code: KnowledgeWarningCode, message: str) -> KnowledgeWarning:
    return KnowledgeWarning(code=code, message=message, recoverable=True)


def _serialized_size(value: object) -> int:
    if hasattr(value, "model_dump_json"):
        return len(value.model_dump_json(exclude_none=True))  # type: ignore[attr-defined]
    raise TypeError("knowledge budget values must be domain models")


def _stable_roles(
    roles: Iterable[RetrievedRoleProfile],
) -> list[RetrievedRoleProfile]:
    return sorted(
        roles,
        key=lambda item: (-item.relevance_score, item.role_profile_id),
    )


def _stable_requirements(
    requirements: Iterable[RetrievedRequirement],
) -> list[RetrievedRequirement]:
    return sorted(
        requirements,
        key=lambda item: (-item.relevance_score, item.knowledge_requirement_id),
    )


def _stable_questions(
    questions: Iterable[RetrievedInterviewQuestion],
) -> list[RetrievedInterviewQuestion]:
    return sorted(
        questions,
        key=lambda item: (-item.relevance_score, item.knowledge_question_id),
    )


class NoOpKnowledgeRetriever:
    """Return a valid disabled context without touching a repository."""

    def __init__(self, *, retrieval_strategy_version: str = "1.0") -> None:
        self._strategy_version = retrieval_strategy_version

    def retrieve_for_job(
        self,
        job_profile: JobProfile,
        *,
        limit: int = 12,
    ) -> KnowledgeContext:
        del job_profile
        validate_knowledge_limit(limit)
        return KnowledgeContext(
            status=KnowledgeRetrievalStatus.DISABLED,
            warnings=[
                _warning(
                    KnowledgeWarningCode.DISABLED,
                    "Job knowledge enhancement is disabled.",
                )
            ],
            retrieval_strategy_version=self._strategy_version,
        )


class DefaultKnowledgeRetriever:
    """Resolve one published role profile and its bounded, reviewed knowledge."""

    def __init__(
        self,
        repository: KnowledgeRepository,
        *,
        enabled: bool = True,
        requested_version: str | None = None,
        search_mode: KnowledgeSearchMode = KnowledgeSearchMode.AUTO,
        requirement_limit: int = 12,
        prompt_char_limit: int = 8_000,
        retrieval_strategy_version: str = "1.0",
    ) -> None:
        self._repository = repository
        self._enabled = enabled
        self._requested_version = requested_version
        self._search_mode = KnowledgeSearchMode(search_mode)
        self._requirement_limit = validate_knowledge_limit(requirement_limit)
        if isinstance(prompt_char_limit, bool) or not isinstance(
            prompt_char_limit, int
        ):
            raise ValueError("prompt_char_limit must be a positive integer")
        if prompt_char_limit <= 0:
            raise ValueError("prompt_char_limit must be a positive integer")
        self._prompt_char_limit = prompt_char_limit
        self._strategy_version = retrieval_strategy_version

    def retrieve_for_job(
        self,
        job_profile: JobProfile,
        *,
        limit: int = 12,
    ) -> KnowledgeContext:
        effective_limit = min(
            validate_knowledge_limit(limit),
            self._requirement_limit,
        )
        if not self._enabled:
            return NoOpKnowledgeRetriever(
                retrieval_strategy_version=self._strategy_version
            ).retrieve_for_job(job_profile, limit=effective_limit)

        try:
            version = self._repository.get_published_version(
                self._requested_version
            )
        except KnowledgeDatabaseError as exc:
            return self._database_unavailable(exc)
        if version is None:
            return self._unavailable(
                KnowledgeWarningCode.VERSION_UNAVAILABLE,
                "The requested published knowledge version is unavailable.",
            )
        if version.status is not KnowledgeVersionStatus.PUBLISHED:
            return self._unavailable(
                KnowledgeWarningCode.VERSION_UNAVAILABLE,
                "The requested published knowledge version is unavailable.",
            )

        query = build_role_resolution_query(job_profile)
        warnings: list[KnowledgeWarning] = []
        try:
            capabilities = self._repository.get_search_capabilities()
            if capabilities.mode is KnowledgeSearchBackend.DISABLED:
                return self._unavailable(
                    KnowledgeWarningCode.RETRIEVAL_FAILED,
                    "Reviewed knowledge search is unavailable.",
                    version=version,
                    capabilities=capabilities,
                )
            roles = _stable_roles(
                self._repository.search_role_profiles(
                    query,
                    version_id=version.id,
                    limit=ROLE_CANDIDATE_LIMIT,
                )
            )
        except KnowledgeDatabaseError as exc:
            return self._database_unavailable(exc, version=version)

        if (
            self._search_mode is KnowledgeSearchMode.AUTO
            and capabilities.mode is KnowledgeSearchBackend.KEYWORD_FALLBACK
        ):
            warnings.append(
                _warning(
                    KnowledgeWarningCode.SEARCH_FALLBACK,
                    "Full-text search is unavailable; deterministic keyword search was used.",
                )
            )

        if not roles or roles[0].relevance_score < ROLE_RELEVANCE_THRESHOLD:
            return KnowledgeContext(
                status=KnowledgeRetrievalStatus.NO_MATCH,
                version=version,
                capabilities=capabilities,
                warnings=[
                    *warnings,
                    _warning(
                        KnowledgeWarningCode.NO_ROLE_MATCH,
                        "No reviewed role profile met the deterministic threshold.",
                    ),
                ],
                retrieval_strategy_version=self._strategy_version,
            )

        if self._is_ambiguous(roles):
            return self._ambiguous_context(
                roles[:2],
                version=version,
                capabilities=capabilities,
                warnings=warnings,
            )

        selected = roles[0]
        try:
            search_query = KnowledgeSearchQuery(
                role_profile_ids=(selected.role_profile_id,),
                terms=query.keywords,
            )
            requirements = _stable_requirements(
                item
                for item in self._repository.search_requirements(
                    search_query,
                    version_id=version.id,
                    limit=effective_limit,
                )
                if item.role_profile_id == selected.role_profile_id
            )
            requirement_ids = {
                item.knowledge_requirement_id for item in requirements
            }
            patterns = sorted(
                (
                    item
                    for item in self._repository.search_evidence_patterns(
                        sorted(requirement_ids),
                        version_id=version.id,
                        limit=EVIDENCE_PATTERN_LIMIT,
                    )
                    if item.knowledge_requirement_id in requirement_ids
                ),
                key=lambda item: item.evidence_pattern_id,
            )
            questions = _stable_questions(
                item
                for item in self._repository.search_interview_questions(
                    search_query,
                    version_id=version.id,
                    limit=INTERVIEW_QUESTION_LIMIT,
                )
                if item.role_profile_id == selected.role_profile_id
            )
            (
                requirements,
                patterns,
                questions,
                count_truncated,
            ) = self._apply_reference_count_budget(
                selected=selected,
                requirements=requirements,
                patterns=patterns,
                questions=questions,
            )
            citations = self._resolve_citations(
                (selected, *requirements, *patterns, *questions),
                version_id=version.id,
            )
        except KnowledgeDatabaseError as exc:
            return self._database_unavailable(exc, version=version)

        if citations is None:
            return self._unavailable(
                KnowledgeWarningCode.CITATION_INVALID,
                "Reviewed knowledge citations could not be validated.",
                version=version,
                capabilities=capabilities,
            )

        return self._apply_budget(
            selected=selected,
            requirements=requirements,
            patterns=patterns,
            questions=questions,
            citations=citations,
            version=version,
            capabilities=capabilities,
            warnings=warnings,
            truncated=count_truncated,
        )

    @staticmethod
    def _is_ambiguous(roles: Sequence[RetrievedRoleProfile]) -> bool:
        if len(roles) < 2:
            return False
        first, second = roles[:2]
        if second.relevance_score < ROLE_RELEVANCE_THRESHOLD:
            return False
        difference = first.relevance_score - second.relevance_score
        if first.job_family_code != second.job_family_code:
            return difference <= ROLE_AMBIGUITY_MARGIN
        return difference == Decimal("0.0000")

    def _ambiguous_context(
        self,
        roles: list[RetrievedRoleProfile],
        *,
        version: KnowledgeBaseVersionInfo,
        capabilities: KnowledgeSearchCapabilities,
        warnings: list[KnowledgeWarning],
    ) -> KnowledgeContext:
        try:
            citations = self._resolve_citations(roles, version_id=version.id)
        except KnowledgeDatabaseError as exc:
            return self._database_unavailable(exc, version=version)
        if citations is None:
            return self._unavailable(
                KnowledgeWarningCode.CITATION_INVALID,
                "Reviewed knowledge citations could not be validated.",
                version=version,
                capabilities=capabilities,
            )
        if sum(map(_serialized_size, (*roles, *citations))) > self._prompt_char_limit:
            return self._unavailable(
                KnowledgeWarningCode.BUDGET_TRUNCATED,
                "The role knowledge summary exceeds the configured character budget.",
                version=version,
                capabilities=capabilities,
            )
        return KnowledgeContext(
            status=KnowledgeRetrievalStatus.AMBIGUOUS,
            version=version,
            inferred_role_profiles=roles,
            citations=citations,
            capabilities=capabilities,
            warnings=[
                *warnings,
                _warning(
                    KnowledgeWarningCode.AMBIGUOUS_ROLE,
                    "Multiple reviewed role profiles are too close to select safely.",
                ),
            ],
            retrieval_strategy_version=self._strategy_version,
        )

    def _resolve_citations(
        self,
        values: Sequence[
            RetrievedRoleProfile
            | RetrievedRequirement
            | RetrievedEvidencePattern
            | RetrievedInterviewQuestion
        ],
        *,
        version_id: str,
    ) -> list[KnowledgeCitation] | None:
        expected_ids = sorted(
            {
                citation_id
                for value in values
                for citation_id in value.citation_ids
            }
        )
        if len(expected_ids) > CITATION_LIMIT:
            return None
        citations = self._repository.get_citations(
            expected_ids,
            version_id=version_id,
        )
        actual_ids = [citation.citation_id for citation in citations]
        if (
            len(actual_ids) != len(set(actual_ids))
            or set(actual_ids) != set(expected_ids)
            or any(
                citation.knowledge_version_id != version_id
                or not self._repository.citation_exists(
                    citation,
                    version_id=version_id,
                )
                for citation in citations
            )
        ):
            return None
        return sorted(citations, key=lambda citation: citation.citation_id)

    @staticmethod
    def _apply_reference_count_budget(
        *,
        selected: RetrievedRoleProfile,
        requirements: list[RetrievedRequirement],
        patterns: list[RetrievedEvidencePattern],
        questions: list[RetrievedInterviewQuestion],
    ) -> tuple[
        list[RetrievedRequirement],
        list[RetrievedEvidencePattern],
        list[RetrievedInterviewQuestion],
        bool,
    ]:
        known_citations = set(selected.citation_ids)
        truncated = False

        def fits(citation_ids: Sequence[str]) -> bool:
            return len(known_citations.union(citation_ids)) <= CITATION_LIMIT

        kept_requirements: list[RetrievedRequirement] = []
        for requirement in requirements:
            if fits(requirement.citation_ids):
                kept_requirements.append(requirement)
                known_citations.update(requirement.citation_ids)
            else:
                truncated = True

        kept_requirement_ids = {
            item.knowledge_requirement_id for item in kept_requirements
        }
        kept_patterns: list[RetrievedEvidencePattern] = []
        per_requirement: dict[str, int] = {}
        for pattern in patterns:
            requirement_id = pattern.knowledge_requirement_id
            if (
                requirement_id not in kept_requirement_ids
                or per_requirement.get(requirement_id, 0)
                >= EVIDENCE_PATTERNS_PER_REQUIREMENT
                or not fits(pattern.citation_ids)
            ):
                truncated = True
                continue
            kept_patterns.append(pattern)
            known_citations.update(pattern.citation_ids)
            per_requirement[requirement_id] = (
                per_requirement.get(requirement_id, 0) + 1
            )

        kept_questions: list[RetrievedInterviewQuestion] = []
        for question in questions:
            if fits(question.citation_ids):
                kept_questions.append(question)
                known_citations.update(question.citation_ids)
            else:
                truncated = True

        return (
            kept_requirements,
            kept_patterns,
            kept_questions,
            truncated,
        )

    def _apply_budget(
        self,
        *,
        selected: RetrievedRoleProfile,
        requirements: list[RetrievedRequirement],
        patterns: list[RetrievedEvidencePattern],
        questions: list[RetrievedInterviewQuestion],
        citations: list[KnowledgeCitation],
        version: KnowledgeBaseVersionInfo,
        capabilities: KnowledgeSearchCapabilities,
        warnings: list[KnowledgeWarning],
        truncated: bool = False,
    ) -> KnowledgeContext:
        citation_by_id = {
            citation.citation_id: citation for citation in citations
        }
        kept_citations: dict[str, KnowledgeCitation] = {}
        used = _serialized_size(selected)
        for citation_id in selected.citation_ids:
            citation = citation_by_id[citation_id]
            kept_citations[citation_id] = citation
            used += _serialized_size(citation)
        if used > self._prompt_char_limit:
            return self._unavailable(
                KnowledgeWarningCode.BUDGET_TRUNCATED,
                "The role knowledge summary exceeds the configured character budget.",
                version=version,
                capabilities=capabilities,
            )

        kept_requirements: list[RetrievedRequirement] = []
        kept_patterns: list[RetrievedEvidencePattern] = []
        kept_questions: list[RetrievedInterviewQuestion] = []

        def try_add(value: object, citation_ids: Sequence[str]) -> bool:
            nonlocal used
            new_citations = [
                citation_by_id[citation_id]
                for citation_id in citation_ids
                if citation_id not in kept_citations
            ]
            if len(kept_citations) + len(new_citations) > CITATION_LIMIT:
                return False
            added_size = _serialized_size(value) + sum(
                map(_serialized_size, new_citations)
            )
            if used + added_size > self._prompt_char_limit:
                return False
            used += added_size
            kept_citations.update(
                (citation.citation_id, citation) for citation in new_citations
            )
            return True

        for requirement in requirements:
            if try_add(requirement, requirement.citation_ids):
                kept_requirements.append(requirement)
            else:
                truncated = True

        kept_requirement_ids = {
            item.knowledge_requirement_id for item in kept_requirements
        }
        per_requirement: dict[str, int] = {}
        for pattern in patterns:
            requirement_id = pattern.knowledge_requirement_id
            if requirement_id not in kept_requirement_ids:
                truncated = True
                continue
            if per_requirement.get(requirement_id, 0) >= (
                EVIDENCE_PATTERNS_PER_REQUIREMENT
            ):
                truncated = True
                continue
            if try_add(pattern, pattern.citation_ids):
                kept_patterns.append(pattern)
                per_requirement[requirement_id] = (
                    per_requirement.get(requirement_id, 0) + 1
                )
            else:
                truncated = True

        for question in questions:
            if try_add(question, question.citation_ids):
                kept_questions.append(question)
            else:
                truncated = True

        if truncated:
            warnings = [
                *warnings,
                _warning(
                    KnowledgeWarningCode.BUDGET_TRUNCATED,
                    "Lower-priority knowledge entries were omitted to respect configured budgets.",
                ),
            ]
        return KnowledgeContext(
            status=KnowledgeRetrievalStatus.AVAILABLE,
            version=version,
            inferred_role_profiles=[selected],
            requirements=kept_requirements,
            evidence_patterns=kept_patterns,
            interview_questions=kept_questions,
            citations=sorted(
                kept_citations.values(),
                key=lambda citation: citation.citation_id,
            ),
            warnings=warnings,
            capabilities=capabilities,
            retrieval_strategy_version=self._strategy_version,
        )

    def _database_unavailable(
        self,
        error: KnowledgeDatabaseError,
        *,
        version: KnowledgeBaseVersionInfo | None = None,
    ) -> KnowledgeContext:
        code = (
            KnowledgeWarningCode.DB_UNAVAILABLE
            if error.code
            in {
                ErrorCode.KNOWLEDGE_DB_UNAVAILABLE,
                ErrorCode.KNOWLEDGE_SEARCH_UNAVAILABLE,
            }
            else KnowledgeWarningCode.RETRIEVAL_FAILED
        )
        message = (
            "The reviewed knowledge database is temporarily unavailable."
            if code is KnowledgeWarningCode.DB_UNAVAILABLE
            else "Reviewed knowledge retrieval could not be completed."
        )
        return self._unavailable(code, message, version=version)

    def _unavailable(
        self,
        code: KnowledgeWarningCode,
        message: str,
        *,
        version: KnowledgeBaseVersionInfo | None = None,
        capabilities: KnowledgeSearchCapabilities | None = None,
    ) -> KnowledgeContext:
        return KnowledgeContext(
            status=KnowledgeRetrievalStatus.UNAVAILABLE,
            version=version,
            warnings=[_warning(code, message)],
            capabilities=capabilities or KnowledgeSearchCapabilities(),
            retrieval_strategy_version=self._strategy_version,
        )


__all__ = [
    "DefaultKnowledgeRetriever",
    "NoOpKnowledgeRetriever",
    "build_knowledge_cache_identity",
    "build_role_resolution_query",
]
