"""Structured, read-only SQLAlchemy repository for published knowledge."""

from __future__ import annotations

import json
from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy import func, or_, select

from jobfit.errors import ErrorCode, KnowledgeDatabaseError
from jobfit.knowledge.db import KnowledgeDatabase
from jobfit.knowledge.fts import MAX_FTS_CANDIDATES, KnowledgeSearchIndex
from jobfit.knowledge.mappers import (
    citation_id_for,
    map_evidence_pattern,
    map_interview_question,
    map_requirement,
    map_role_profile,
    map_source_citation,
    map_version,
)
from jobfit.knowledge.normalization import normalize_query_terms
from jobfit.knowledge.orm import (
    CompetencyDimensionRecord,
    EvidencePatternRecord,
    InterviewQuestionRecord,
    JobFamilyRecord,
    KnowledgeBaseVersionRecord,
    KnowledgeChunkRecord,
    KnowledgeSourceRecord,
    RoleProfileRecord,
    RoleRequirementRecord,
    SourceRoleLinkRecord,
)
from jobfit.knowledge.query import (
    KnowledgeSearchQuery,
    RoleProfileQuery,
    validate_knowledge_limit,
)
from jobfit.knowledge.ranking import (
    REQUIREMENT_RELEVANCE_THRESHOLD,
    ROLE_RELEVANCE_THRESHOLD,
    RankedKnowledgeCandidate,
    RequirementRankCandidate,
    RoleRankCandidate,
    rank_knowledge_candidates,
    score_requirement_candidate,
    score_role_candidate,
    score_text_candidate,
)
from jobfit.models import Importance
from jobfit.models.knowledge import (
    KnowledgeBaseVersionInfo,
    KnowledgeCitation,
    KnowledgeSearchBackend,
    KnowledgeSearchCapabilities,
    KnowledgeSearchMode,
    RetrievedEvidencePattern,
    RetrievedInterviewQuestion,
    RetrievedRequirement,
    RetrievedRoleProfile,
)

_FULL_RELEVANCE = Decimal("1.0000")
_SAFE_SEARCH_MESSAGE = "Knowledge search is temporarily unavailable."


def _search_error(
    code: ErrorCode = ErrorCode.KNOWLEDGE_SEARCH_UNAVAILABLE,
    *,
    cause: Exception | None = None,
) -> KnowledgeDatabaseError:
    return KnowledgeDatabaseError(
        code=code,
        user_message=_SAFE_SEARCH_MESSAGE,
        recoverable=True,
        cause=cause,
    )


def _string_tuple(raw: str) -> tuple[str, ...]:
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise _search_error(
            ErrorCode.KNOWLEDGE_SEARCH_FAILED,
            cause=exc,
        ) from exc
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise _search_error(ErrorCode.KNOWLEDGE_SEARCH_FAILED)
    return tuple(value)


def _escape_like(token: str) -> str:
    return token.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class SqliteKnowledgeRepository:
    """Implement the Phase 11.1 protocol using bounded structured queries."""

    def __init__(
        self,
        database: KnowledgeDatabase,
        *,
        search_mode: KnowledgeSearchMode = KnowledgeSearchMode.AUTO,
        search_index: KnowledgeSearchIndex | None = None,
        search_enabled: bool = True,
    ) -> None:
        self._database = database
        self._search_mode = KnowledgeSearchMode(search_mode)
        self._search_index = search_index or KnowledgeSearchIndex(database)
        self._search_enabled = search_enabled

    def _check_schema(self) -> None:
        self._database.ensure_compatible_schema()

    def get_version(self, version_id: str) -> KnowledgeBaseVersionInfo | None:
        self._check_schema()
        with self._database._session_scope() as session:
            record = session.get(KnowledgeBaseVersionRecord, version_id)
            return map_version(record) if record is not None else None

    def get_published_version(
        self,
        version: str | None = None,
    ) -> KnowledgeBaseVersionInfo | None:
        self._check_schema()
        statement = select(KnowledgeBaseVersionRecord).where(
            KnowledgeBaseVersionRecord.status == "published"
        )
        if version is not None:
            statement = statement.where(
                KnowledgeBaseVersionRecord.version == version
            )
        statement = statement.order_by(
            KnowledgeBaseVersionRecord.published_at.desc(),
            KnowledgeBaseVersionRecord.id.asc(),
        ).limit(1)
        with self._database._session_scope() as session:
            record = session.execute(statement).scalar_one_or_none()
            return map_version(record) if record is not None else None

    def get_search_capabilities(self) -> KnowledgeSearchCapabilities:
        return self._search_index.capabilities(
            self._search_mode,
            enabled=self._search_enabled,
        )

    def _candidate_ids(
        self,
        *,
        version_id: str,
        entity_types: tuple[str, ...],
        tokens: tuple[str, ...],
        role_profile_ids: tuple[str, ...] = (),
        job_family_codes: tuple[str, ...] = (),
        source_ids: tuple[str, ...] = (),
        limit: int,
    ) -> set[str] | None:
        capabilities = self.get_search_capabilities()
        if capabilities.mode is KnowledgeSearchBackend.DISABLED:
            if not self._search_enabled:
                return set()
            raise _search_error()
        if not tokens:
            return None
        if capabilities.mode is KnowledgeSearchBackend.KEYWORD_FALLBACK:
            return None
        if not self._search_index.has_index_objects():
            if self._search_mode is KnowledgeSearchMode.AUTO:
                return None
            raise _search_error()
        try:
            candidates = self._search_index.search_candidates(
                version_id=version_id,
                entity_types=entity_types,
                tokens=tokens,
                role_profile_ids=role_profile_ids,
                job_family_codes=job_family_codes,
                source_ids=source_ids,
                limit=min(limit * 4, MAX_FTS_CANDIDATES),
            )
        except KnowledgeDatabaseError:
            if self._search_mode is KnowledgeSearchMode.AUTO:
                return None
            raise
        return {candidate.entity_id for candidate in candidates}

    @staticmethod
    def _keyword_clause(tokens: tuple[str, ...], *columns):
        if not tokens:
            return None
        clauses = []
        for token in tokens:
            pattern = f"%{_escape_like(token)}%"
            clauses.extend(
                func.lower(column).like(pattern, escape="\\")
                for column in columns
            )
        return or_(*clauses)

    def _published_version_exists(self, session, version_id: str) -> bool:
        statement = select(KnowledgeBaseVersionRecord.id).where(
            KnowledgeBaseVersionRecord.id == version_id,
            KnowledgeBaseVersionRecord.status == "published",
        )
        return session.execute(statement).scalar_one_or_none() is not None

    def _source_citation_ids_for_role(
        self,
        session,
        *,
        role_profile_id: str,
        version_id: str,
    ) -> list[str]:
        statement = (
            select(KnowledgeSourceRecord)
            .join(
                SourceRoleLinkRecord,
                SourceRoleLinkRecord.source_id == KnowledgeSourceRecord.id,
            )
            .where(
                SourceRoleLinkRecord.role_profile_id == role_profile_id,
                SourceRoleLinkRecord.knowledge_version_id == version_id,
                KnowledgeSourceRecord.review_status == "approved",
            )
            .order_by(KnowledgeSourceRecord.id.asc())
        )
        sources = session.execute(statement).scalars().all()
        return [
            map_source_citation(source, version_id=version_id).citation_id
            for source in sources
        ]

    def search_role_profiles(
        self,
        query: RoleProfileQuery,
        *,
        version_id: str,
        limit: int,
    ) -> list[RetrievedRoleProfile]:
        safe_limit = validate_knowledge_limit(limit)
        self._check_schema()
        tokens = normalize_query_terms(
            (query.title, *query.aliases, *query.keywords)
        )
        candidate_ids = self._candidate_ids(
            version_id=version_id,
            entity_types=("role_profile",),
            tokens=tokens,
            job_family_codes=query.job_family_codes,
            limit=safe_limit,
        )
        if candidate_ids == set():
            return []
        statement = (
            select(RoleProfileRecord, JobFamilyRecord.code)
            .join(
                JobFamilyRecord,
                JobFamilyRecord.id == RoleProfileRecord.job_family_id,
            )
            .join(
                KnowledgeBaseVersionRecord,
                KnowledgeBaseVersionRecord.id
                == RoleProfileRecord.knowledge_version_id,
            )
            .where(
                RoleProfileRecord.knowledge_version_id == version_id,
                KnowledgeBaseVersionRecord.status == "published",
                RoleProfileRecord.review_status == "approved",
                RoleProfileRecord.is_active.is_(True),
                JobFamilyRecord.is_active.is_(True),
            )
        )
        if candidate_ids is not None:
            if not candidate_ids:
                return []
            statement = statement.where(
                RoleProfileRecord.id.in_(sorted(candidate_ids))
            )
        else:
            keyword_clause = self._keyword_clause(
                tokens,
                RoleProfileRecord.code,
                RoleProfileRecord.name,
                RoleProfileRecord.aliases_json,
                RoleProfileRecord.keywords_json,
                RoleProfileRecord.description,
            )
            if keyword_clause is not None:
                statement = statement.where(keyword_clause)
        if query.seniority is not None:
            statement = statement.where(
                func.lower(RoleProfileRecord.seniority)
                == query.seniority.casefold()
            )
        if query.industry is not None:
            statement = statement.where(
                func.lower(RoleProfileRecord.industry) == query.industry.casefold()
            )
        if query.job_family_codes:
            statement = statement.where(
                JobFamilyRecord.code.in_(query.job_family_codes)
            )
        statement = statement.order_by(RoleProfileRecord.id.asc()).limit(
            min(safe_limit * 4, MAX_FTS_CANDIDATES)
        )

        with self._database._session_scope() as session:
            rows = session.execute(statement).all()
            scored: list[
                tuple[
                    RankedKnowledgeCandidate,
                    RoleProfileRecord,
                    str,
                    list[str],
                ]
            ] = []
            for role, family_code in rows:
                citations = self._source_citation_ids_for_role(
                    session,
                    role_profile_id=role.id,
                    version_id=version_id,
                )
                score = score_role_candidate(
                    query,
                    RoleRankCandidate(
                        entity_id=role.id,
                        code=role.code,
                        name=role.name,
                        aliases=_string_tuple(role.aliases_json),
                        keywords=_string_tuple(role.keywords_json),
                        description=role.description,
                        seniority=role.seniority,
                        industry=role.industry,
                    ),
                )
                if score.relevance < ROLE_RELEVANCE_THRESHOLD:
                    continue
                ranked = RankedKnowledgeCandidate(
                    entity_type="role_profile",
                    entity_id=role.id,
                    relevance=score.relevance,
                    importance=None,
                    matched_fields=score.matched_fields,
                    matched_terms=score.matched_terms,
                )
                scored.append((ranked, role, family_code, citations))
            order = rank_knowledge_candidates(
                [item[0] for item in scored],
                limit=safe_limit,
            )
            by_id = {item[0].entity_id: item for item in scored}
            return [
                map_role_profile(
                    by_id[item.entity_id][1],
                    job_family_code=by_id[item.entity_id][2],
                    citation_ids=by_id[item.entity_id][3],
                    matched_terms=list(item.matched_terms) or [query.title],
                    relevance_score=item.relevance,
                    matched_fields=item.matched_fields,
                )
                for item in order
            ]

    def get_role_profile(
        self,
        role_profile_id: str,
        *,
        version_id: str,
    ) -> RetrievedRoleProfile | None:
        self._check_schema()
        statement = (
            select(RoleProfileRecord, JobFamilyRecord.code)
            .join(
                JobFamilyRecord,
                JobFamilyRecord.id == RoleProfileRecord.job_family_id,
            )
            .join(
                KnowledgeBaseVersionRecord,
                KnowledgeBaseVersionRecord.id
                == RoleProfileRecord.knowledge_version_id,
            )
            .where(
                RoleProfileRecord.id == role_profile_id,
                RoleProfileRecord.knowledge_version_id == version_id,
                KnowledgeBaseVersionRecord.status == "published",
                RoleProfileRecord.review_status == "approved",
                RoleProfileRecord.is_active.is_(True),
                JobFamilyRecord.is_active.is_(True),
            )
        )
        with self._database._session_scope() as session:
            row = session.execute(statement).one_or_none()
            if row is None:
                return None
            role, family_code = row
            return map_role_profile(
                role,
                job_family_code=family_code,
                citation_ids=self._source_citation_ids_for_role(
                    session,
                    role_profile_id=role.id,
                    version_id=version_id,
                ),
                matched_terms=[role.name],
                relevance_score=_FULL_RELEVANCE,
            )

    def search_requirements(
        self,
        query: KnowledgeSearchQuery,
        *,
        version_id: str,
        limit: int,
    ) -> list[RetrievedRequirement]:
        safe_limit = validate_knowledge_limit(limit)
        self._check_schema()
        tokens = normalize_query_terms(query.terms)
        candidate_ids = self._candidate_ids(
            version_id=version_id,
            entity_types=("role_requirement",),
            tokens=tokens,
            role_profile_ids=query.role_profile_ids,
            source_ids=query.source_ids,
            limit=safe_limit,
        )
        if candidate_ids == set():
            return []
        statement = (
            select(
                RoleRequirementRecord,
                CompetencyDimensionRecord.code,
                KnowledgeSourceRecord,
            )
            .join(
                CompetencyDimensionRecord,
                CompetencyDimensionRecord.id
                == RoleRequirementRecord.competency_dimension_id,
            )
            .join(
                KnowledgeSourceRecord,
                KnowledgeSourceRecord.id == RoleRequirementRecord.source_id,
            )
            .join(
                KnowledgeBaseVersionRecord,
                KnowledgeBaseVersionRecord.id
                == RoleRequirementRecord.knowledge_version_id,
            )
            .where(
                RoleRequirementRecord.knowledge_version_id == version_id,
                RoleRequirementRecord.role_profile_id.in_(
                    query.role_profile_ids
                ),
                KnowledgeBaseVersionRecord.status == "published",
                RoleRequirementRecord.review_status == "approved",
                RoleRequirementRecord.is_active.is_(True),
                CompetencyDimensionRecord.review_status == "approved",
                CompetencyDimensionRecord.is_active.is_(True),
                KnowledgeSourceRecord.review_status == "approved",
            )
        )
        if query.requirement_types:
            statement = statement.where(
                RoleRequirementRecord.requirement_type.in_(
                    tuple(item.value for item in query.requirement_types)
                )
            )
        if query.importance_levels:
            statement = statement.where(
                RoleRequirementRecord.importance.in_(
                    tuple(item.value for item in query.importance_levels)
                )
            )
        if query.source_ids:
            statement = statement.where(
                RoleRequirementRecord.source_id.in_(query.source_ids)
            )
        if candidate_ids is not None:
            if not candidate_ids:
                return []
            statement = statement.where(
                RoleRequirementRecord.id.in_(sorted(candidate_ids))
            )
        else:
            keyword_clause = self._keyword_clause(
                tokens,
                RoleRequirementRecord.title,
                RoleRequirementRecord.description,
                RoleRequirementRecord.keywords_json,
                RoleRequirementRecord.expected_evidence_json,
                RoleRequirementRecord.weak_evidence_json,
                RoleRequirementRecord.negative_signals_json,
            )
            if keyword_clause is not None:
                statement = statement.where(keyword_clause)
        statement = statement.order_by(RoleRequirementRecord.id.asc()).limit(
            min(safe_limit * 4, MAX_FTS_CANDIDATES)
        )
        with self._database._session_scope() as session:
            scored: list[
                tuple[
                    RankedKnowledgeCandidate,
                    RoleRequirementRecord,
                    str,
                    KnowledgeSourceRecord,
                ]
            ] = []
            for requirement, dimension_code, source in session.execute(
                statement
            ).all():
                score = score_requirement_candidate(
                    query,
                    RequirementRankCandidate(
                        entity_id=requirement.id,
                        role_profile_id=requirement.role_profile_id,
                        title=requirement.title,
                        keywords=_string_tuple(requirement.keywords_json),
                        description=requirement.description,
                        expected_evidence=_string_tuple(
                            requirement.expected_evidence_json
                        ),
                        importance=Importance(requirement.importance),
                    ),
                    role_relevance=_FULL_RELEVANCE,
                )
                if score.relevance < REQUIREMENT_RELEVANCE_THRESHOLD:
                    continue
                scored.append(
                    (
                        RankedKnowledgeCandidate(
                            entity_type="role_requirement",
                            entity_id=requirement.id,
                            relevance=score.relevance,
                            importance=Importance(requirement.importance),
                            matched_fields=score.matched_fields,
                            matched_terms=score.matched_terms,
                        ),
                        requirement,
                        dimension_code,
                        source,
                    )
                )
            order = rank_knowledge_candidates(
                [item[0] for item in scored],
                limit=safe_limit,
            )
            by_id = {item[0].entity_id: item for item in scored}
            return [
                map_requirement(
                    by_id[item.entity_id][1],
                    competency_dimension_code=by_id[item.entity_id][2],
                    citation_ids=[
                        map_source_citation(
                            by_id[item.entity_id][3],
                            version_id=version_id,
                        ).citation_id
                    ],
                    relevance_score=item.relevance,
                    matched_terms=item.matched_terms,
                    matched_fields=item.matched_fields,
                )
                for item in order
            ]

    def search_evidence_patterns(
        self,
        requirement_ids: Sequence[str],
        *,
        version_id: str,
        limit: int,
    ) -> list[RetrievedEvidencePattern]:
        safe_limit = validate_knowledge_limit(limit)
        if not requirement_ids:
            return []
        self._check_schema()
        statement = (
            select(EvidencePatternRecord, KnowledgeSourceRecord)
            .join(
                KnowledgeSourceRecord,
                KnowledgeSourceRecord.id == EvidencePatternRecord.source_id,
            )
            .join(
                KnowledgeBaseVersionRecord,
                KnowledgeBaseVersionRecord.id
                == EvidencePatternRecord.knowledge_version_id,
            )
            .where(
                EvidencePatternRecord.role_requirement_id.in_(
                    tuple(requirement_ids)
                ),
                EvidencePatternRecord.knowledge_version_id == version_id,
                KnowledgeBaseVersionRecord.status == "published",
                EvidencePatternRecord.review_status == "approved",
                EvidencePatternRecord.is_active.is_(True),
                KnowledgeSourceRecord.review_status == "approved",
            )
            .order_by(EvidencePatternRecord.id.asc())
            .limit(safe_limit)
        )
        with self._database._session_scope() as session:
            return [
                map_evidence_pattern(
                    pattern,
                    citation_ids=[
                        map_source_citation(
                            source,
                            version_id=version_id,
                        ).citation_id
                    ],
                )
                for pattern, source in session.execute(statement).all()
            ]

    def search_interview_questions(
        self,
        query: KnowledgeSearchQuery,
        *,
        version_id: str,
        limit: int,
    ) -> list[RetrievedInterviewQuestion]:
        safe_limit = validate_knowledge_limit(limit)
        self._check_schema()
        tokens = normalize_query_terms(query.terms)
        candidate_ids = self._candidate_ids(
            version_id=version_id,
            entity_types=("interview_question",),
            tokens=tokens,
            role_profile_ids=query.role_profile_ids,
            source_ids=query.source_ids,
            limit=safe_limit,
        )
        if candidate_ids == set():
            return []
        statement = (
            select(
                InterviewQuestionRecord,
                CompetencyDimensionRecord.code,
                KnowledgeSourceRecord,
            )
            .join(
                CompetencyDimensionRecord,
                CompetencyDimensionRecord.id
                == InterviewQuestionRecord.competency_dimension_id,
            )
            .join(
                KnowledgeSourceRecord,
                KnowledgeSourceRecord.id == InterviewQuestionRecord.source_id,
            )
            .join(
                KnowledgeBaseVersionRecord,
                KnowledgeBaseVersionRecord.id
                == InterviewQuestionRecord.knowledge_version_id,
            )
            .where(
                InterviewQuestionRecord.role_profile_id.in_(
                    query.role_profile_ids
                ),
                InterviewQuestionRecord.knowledge_version_id == version_id,
                KnowledgeBaseVersionRecord.status == "published",
                InterviewQuestionRecord.review_status == "approved",
                InterviewQuestionRecord.is_active.is_(True),
                CompetencyDimensionRecord.review_status == "approved",
                CompetencyDimensionRecord.is_active.is_(True),
                KnowledgeSourceRecord.review_status == "approved",
            )
        )
        if query.source_ids:
            statement = statement.where(
                InterviewQuestionRecord.source_id.in_(query.source_ids)
            )
        if candidate_ids is not None:
            if not candidate_ids:
                return []
            statement = statement.where(
                InterviewQuestionRecord.id.in_(sorted(candidate_ids))
            )
        else:
            keyword_clause = self._keyword_clause(
                tokens,
                InterviewQuestionRecord.question,
                InterviewQuestionRecord.expected_points_json,
                InterviewQuestionRecord.follow_up_questions_json,
            )
            if keyword_clause is not None:
                statement = statement.where(keyword_clause)
        statement = statement.order_by(
            InterviewQuestionRecord.id.asc()
        ).limit(min(safe_limit * 4, MAX_FTS_CANDIDATES))
        with self._database._session_scope() as session:
            scored: list[
                tuple[
                    RankedKnowledgeCandidate,
                    InterviewQuestionRecord,
                    str,
                    KnowledgeSourceRecord,
                ]
            ] = []
            for question, dimension_code, source in session.execute(
                statement
            ).all():
                score = (
                    score_text_candidate(
                        query.terms,
                        primary=question.question,
                        keywords=_string_tuple(
                            question.expected_points_json
                        ),
                        description=" ".join(
                            _string_tuple(
                                question.follow_up_questions_json
                            )
                        ),
                    )
                    if tokens
                    else None
                )
                relevance = (
                    score.relevance if score is not None else _FULL_RELEVANCE
                )
                if tokens and relevance == Decimal("0"):
                    continue
                scored.append(
                    (
                        RankedKnowledgeCandidate(
                            entity_type="interview_question",
                            entity_id=question.id,
                            relevance=relevance,
                            importance=None,
                            matched_fields=(
                                score.matched_fields if score is not None else ()
                            ),
                            matched_terms=(
                                score.matched_terms if score is not None else ()
                            ),
                        ),
                        question,
                        dimension_code,
                        source,
                    )
                )
            order = rank_knowledge_candidates(
                [item[0] for item in scored],
                limit=safe_limit,
            )
            by_id = {item[0].entity_id: item for item in scored}
            return [
                map_interview_question(
                    by_id[item.entity_id][1],
                    competency_dimension_code=by_id[item.entity_id][2],
                    citation_ids=[
                        map_source_citation(
                            by_id[item.entity_id][3],
                            version_id=version_id,
                        ).citation_id
                    ],
                    relevance_score=item.relevance,
                    matched_terms=item.matched_terms,
                    matched_fields=item.matched_fields,
                )
                for item in order
            ]

    def get_sources(
        self,
        source_ids: Sequence[str],
        *,
        version_id: str,
    ) -> list[KnowledgeCitation]:
        if not source_ids:
            return []
        self._check_schema()
        statement = (
            select(KnowledgeSourceRecord)
            .join(
                SourceRoleLinkRecord,
                SourceRoleLinkRecord.source_id == KnowledgeSourceRecord.id,
            )
            .join(
                KnowledgeBaseVersionRecord,
                KnowledgeBaseVersionRecord.id
                == SourceRoleLinkRecord.knowledge_version_id,
            )
            .where(
                KnowledgeSourceRecord.id.in_(tuple(source_ids)),
                KnowledgeSourceRecord.review_status == "approved",
                SourceRoleLinkRecord.knowledge_version_id == version_id,
                KnowledgeBaseVersionRecord.status == "published",
            )
            .distinct()
            .order_by(KnowledgeSourceRecord.id.asc())
        )
        with self._database._session_scope() as session:
            return [
                map_source_citation(source, version_id=version_id)
                for source in session.execute(statement).scalars().all()
            ]

    def get_citations(
        self,
        citation_ids: Sequence[str],
        *,
        version_id: str,
    ) -> list[KnowledgeCitation]:
        requested = set(citation_ids)
        if not requested:
            return []
        self._check_schema()
        with self._database._session_scope() as session:
            if not self._published_version_exists(session, version_id):
                return []

            source_statement = (
                select(KnowledgeSourceRecord)
                .join(
                    SourceRoleLinkRecord,
                    SourceRoleLinkRecord.source_id == KnowledgeSourceRecord.id,
                )
                .where(
                    SourceRoleLinkRecord.knowledge_version_id == version_id,
                    KnowledgeSourceRecord.review_status == "approved",
                )
                .distinct()
                .order_by(KnowledgeSourceRecord.id.asc())
            )
            citations = [
                map_source_citation(source, version_id=version_id)
                for source in session.execute(source_statement).scalars().all()
            ]

            chunk_statement = (
                select(KnowledgeChunkRecord, KnowledgeSourceRecord)
                .join(
                    KnowledgeSourceRecord,
                    KnowledgeSourceRecord.id == KnowledgeChunkRecord.source_id,
                )
                .where(
                    KnowledgeChunkRecord.knowledge_version_id == version_id,
                    KnowledgeChunkRecord.review_status == "approved",
                    KnowledgeSourceRecord.review_status == "approved",
                )
                .order_by(KnowledgeChunkRecord.id.asc())
            )
            citations.extend(
                map_source_citation(source, version_id=version_id, chunk=chunk)
                for chunk, source in session.execute(chunk_statement).all()
            )
            return sorted(
                (
                    citation
                    for citation in citations
                    if citation.citation_id in requested
                ),
                key=lambda citation: citation.citation_id,
            )

    def citation_exists(
        self,
        citation: KnowledgeCitation,
        *,
        version_id: str,
    ) -> bool:
        if citation.knowledge_version_id != version_id:
            return False
        expected_id = citation_id_for(
            version_id=version_id,
            source_id=citation.source_id,
            chunk_id=citation.chunk_id,
        )
        if citation.citation_id != expected_id:
            return False
        self._check_schema()
        with self._database._session_scope() as session:
            if not self._published_version_exists(session, version_id):
                return False
            source = session.get(KnowledgeSourceRecord, citation.source_id)
            if source is None or source.review_status != "approved":
                return False
            if citation.chunk_id is not None:
                chunk = session.get(KnowledgeChunkRecord, citation.chunk_id)
                return bool(
                    chunk is not None
                    and chunk.source_id == citation.source_id
                    and chunk.knowledge_version_id == version_id
                    and chunk.review_status == "approved"
                )
            statement = select(SourceRoleLinkRecord.source_id).where(
                SourceRoleLinkRecord.source_id == citation.source_id,
                SourceRoleLinkRecord.knowledge_version_id == version_id,
            )
            return session.execute(statement).first() is not None


__all__ = ["SqliteKnowledgeRepository"]
