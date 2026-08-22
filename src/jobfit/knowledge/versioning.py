"""Explicit publish and retire transitions for reviewed knowledge versions."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy import select

from jobfit.errors import ErrorCode, KnowledgeSeedError
from jobfit.knowledge.db import KnowledgeDatabase
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
from jobfit.knowledge.seed_loader import calculate_seed_content_hash
from jobfit.knowledge.seed_models import (
    SEED_SCHEMA_VERSION,
    CompetencyDimensionSeed,
    EvidencePatternSeed,
    InterviewQuestionSeed,
    JobFamilySeed,
    KnowledgeChunkSeed,
    KnowledgeSeedBundle,
    KnowledgeSourceSeed,
    KnowledgeVersionSeed,
    RoleProfileSeed,
    RoleRequirementSeed,
    SeedPublishResult,
    SeedRetireResult,
    SourceRoleLinkSeed,
)

_SAFE_VERSION_MESSAGE = "Knowledge version transition failed."


def _error(code: ErrorCode) -> KnowledgeSeedError:
    return KnowledgeSeedError(
        code=code,
        user_message=_SAFE_VERSION_MESSAGE,
        recoverable=False,
    )


def _aware(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


def _strings(raw: str) -> list[str]:
    value = json.loads(raw)
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError("stored seed collection is invalid")
    return value


def _rows(session, record_type, version_id: str):
    return list(
        session.scalars(
            select(record_type)
            .where(record_type.knowledge_version_id == version_id)
            .order_by(record_type.id.asc())
        )
    )


def _bundle_from_session(
    session,
    version: KnowledgeBaseVersionRecord,
) -> KnowledgeSeedBundle:
    version_id = version.id
    families = _rows(session, JobFamilyRecord, version_id)
    roles = _rows(session, RoleProfileRecord, version_id)
    dimensions = _rows(session, CompetencyDimensionRecord, version_id)
    requirements = _rows(session, RoleRequirementRecord, version_id)
    patterns = _rows(session, EvidencePatternRecord, version_id)
    chunks = _rows(session, KnowledgeChunkRecord, version_id)
    questions = _rows(session, InterviewQuestionRecord, version_id)
    links = list(
        session.scalars(
            select(SourceRoleLinkRecord)
            .where(SourceRoleLinkRecord.knowledge_version_id == version_id)
            .order_by(
                SourceRoleLinkRecord.source_id.asc(),
                SourceRoleLinkRecord.role_profile_id.asc(),
            )
        )
    )
    source_ids = {
        item.source_id
        for collection in (requirements, patterns, chunks, questions, links)
        for item in collection
    }
    sources = (
        list(
            session.scalars(
                select(KnowledgeSourceRecord)
                .where(KnowledgeSourceRecord.id.in_(sorted(source_ids)))
                .order_by(KnowledgeSourceRecord.id.asc())
            )
        )
        if source_ids
        else []
    )
    return KnowledgeSeedBundle(
        schema_version=SEED_SCHEMA_VERSION,
        knowledge_base_version=KnowledgeVersionSeed(
            id=version.id,
            version=version.version,
            name=version.name,
            description=version.description,
            status="draft",
        ),
        job_families=[
            JobFamilySeed(
                id=item.id,
                code=item.code,
                name=item.name,
                description=item.description,
                aliases=_strings(item.aliases_json),
                knowledge_version_id=item.knowledge_version_id,
                is_active=item.is_active,
            )
            for item in families
        ],
        role_profiles=[
            RoleProfileSeed(
                id=item.id,
                job_family_id=item.job_family_id,
                code=item.code,
                name=item.name,
                seniority=item.seniority,
                industry=item.industry,
                description=item.description,
                aliases=_strings(item.aliases_json),
                keywords=_strings(item.keywords_json),
                knowledge_version_id=item.knowledge_version_id,
                review_status=item.review_status,
                is_active=item.is_active,
            )
            for item in roles
        ],
        competency_dimensions=[
            CompetencyDimensionSeed(
                id=item.id,
                code=item.code,
                name=item.name,
                description=item.description,
                scoring_category_hint=item.scoring_category_hint,
                display_order=item.display_order,
                knowledge_version_id=item.knowledge_version_id,
                review_status=item.review_status,
                is_active=item.is_active,
            )
            for item in dimensions
        ],
        role_requirements=[
            RoleRequirementSeed(
                id=item.id,
                role_profile_id=item.role_profile_id,
                competency_dimension_id=item.competency_dimension_id,
                title=item.title,
                description=item.description,
                requirement_type=item.requirement_type,
                importance=item.importance,
                is_common_hard_blocker=item.is_common_hard_blocker,
                expected_evidence=_strings(item.expected_evidence_json),
                weak_evidence=_strings(item.weak_evidence_json),
                negative_signals=_strings(item.negative_signals_json),
                keywords=_strings(item.keywords_json),
                source_id=item.source_id,
                knowledge_version_id=item.knowledge_version_id,
                review_status=item.review_status,
                is_active=item.is_active,
            )
            for item in requirements
        ],
        evidence_patterns=[
            EvidencePatternSeed(
                id=item.id,
                role_requirement_id=item.role_requirement_id,
                evidence_type=item.evidence_type,
                description=item.description,
                strength=item.strength,
                positive_example=item.positive_example,
                weak_example=item.weak_example,
                negative_example=item.negative_example,
                source_id=item.source_id,
                knowledge_version_id=item.knowledge_version_id,
                review_status=item.review_status,
                is_active=item.is_active,
            )
            for item in patterns
        ],
        knowledge_sources=[
            KnowledgeSourceSeed(
                id=item.id,
                title=item.title,
                source_type=item.source_type,
                publisher=item.publisher,
                source_url=item.source_url,
                published_at=_aware(item.published_at),
                collected_at=_aware(item.collected_at),
                license_note=item.license_note,
                reliability_level=item.reliability_level,
                review_status=item.review_status,
                checksum=item.checksum,
            )
            for item in sources
        ],
        knowledge_chunks=[
            KnowledgeChunkSeed(
                id=item.id,
                source_id=item.source_id,
                role_profile_id=item.role_profile_id,
                section=item.section,
                chunk_text=item.chunk_text,
                start_offset=item.start_offset,
                end_offset=item.end_offset,
                keywords=_strings(item.keywords_json),
                knowledge_version_id=item.knowledge_version_id,
                review_status=item.review_status,
                content_hash=item.content_hash,
            )
            for item in chunks
        ],
        interview_questions=[
            InterviewQuestionSeed(
                id=item.id,
                role_profile_id=item.role_profile_id,
                competency_dimension_id=item.competency_dimension_id,
                question=item.question,
                question_type=item.question_type,
                expected_points=_strings(item.expected_points_json),
                follow_up_questions=_strings(item.follow_up_questions_json),
                difficulty=item.difficulty,
                source_id=item.source_id,
                knowledge_version_id=item.knowledge_version_id,
                review_status=item.review_status,
                is_active=item.is_active,
            )
            for item in questions
        ],
        source_role_links=[
            SourceRoleLinkSeed(
                source_id=item.source_id,
                role_profile_id=item.role_profile_id,
                knowledge_version_id=item.knowledge_version_id,
                relation_type=item.relation_type,
            )
            for item in links
        ],
    )


def load_persisted_seed_bundle(
    session,
    version: KnowledgeBaseVersionRecord,
) -> KnowledgeSeedBundle:
    """Revalidate one database snapshot without exposing ORM records."""
    try:
        return _bundle_from_session(session, version)
    except (json.JSONDecodeError, TypeError, ValueError, ValidationError) as exc:
        raise _error(ErrorCode.KNOWLEDGE_SEED_HASH_MISMATCH) from exc


def calculate_persisted_version_hash(
    database: KnowledgeDatabase,
    version_id: str,
) -> str:
    database.ensure_compatible_schema()
    with database._session_scope() as session:
        version = session.get(KnowledgeBaseVersionRecord, version_id)
        if version is None:
            raise _error(ErrorCode.KNOWLEDGE_VERSION_UNAVAILABLE)
        return calculate_seed_content_hash(load_persisted_seed_bundle(session, version))


class KnowledgeVersionPublisher:
    """Apply explicit, locally verified lifecycle transitions."""

    def __init__(self, database: KnowledgeDatabase) -> None:
        self._database = database

    def publish(
        self,
        version_id: str,
        *,
        published_at: datetime | None = None,
    ) -> SeedPublishResult:
        self._database.ensure_compatible_schema()
        timestamp = published_at or datetime.now(UTC)
        if timestamp.tzinfo is None:
            raise _error(ErrorCode.KNOWLEDGE_VERSION_NOT_PUBLISHABLE)
        timestamp = timestamp.astimezone(UTC)
        with self._database._session_scope() as session:
            version = session.get(KnowledgeBaseVersionRecord, version_id)
            if version is None:
                raise _error(ErrorCode.KNOWLEDGE_VERSION_UNAVAILABLE)
            if version.status != "draft":
                raise _error(ErrorCode.KNOWLEDGE_PUBLISHED_IMMUTABLE)
            bundle = load_persisted_seed_bundle(session, version)
            self._validate_publish_gate(bundle)
            actual_hash = calculate_seed_content_hash(bundle)
            if actual_hash != version.content_hash:
                raise _error(ErrorCode.KNOWLEDGE_SEED_HASH_MISMATCH)
            version.status = "published"
            version.published_at = timestamp
            session.flush()
            return SeedPublishResult(
                version_id=version.id,
                version=version.version,
                content_hash=version.content_hash,
                status=version.status,
                published_at=timestamp,
            )

    def retire(self, version_id: str) -> SeedRetireResult:
        self._database.ensure_compatible_schema()
        with self._database._session_scope() as session:
            version = session.get(KnowledgeBaseVersionRecord, version_id)
            if version is None:
                raise _error(ErrorCode.KNOWLEDGE_VERSION_UNAVAILABLE)
            if version.status != "published":
                raise _error(ErrorCode.KNOWLEDGE_VERSION_RETIRE_INVALID)
            actual_hash = calculate_seed_content_hash(load_persisted_seed_bundle(session, version))
            if actual_hash != version.content_hash:
                raise _error(ErrorCode.KNOWLEDGE_SEED_HASH_MISMATCH)
            version.status = "retired"
            session.flush()
            return SeedRetireResult(
                version_id=version.id,
                version=version.version,
                content_hash=version.content_hash,
                status=version.status,
                published_at=_aware(version.published_at),
            )

    @staticmethod
    def _validate_publish_gate(bundle: KnowledgeSeedBundle) -> None:
        active_families = {
            item.id for item in bundle.job_families if item.is_active
        }
        active_roles = {
            item.id
            for item in bundle.role_profiles
            if item.is_active and item.job_family_id in active_families
        }
        active_dimensions = {
            item.id
            for item in bundle.competency_dimensions
            if item.is_active
        }
        active_requirements = [
            item
            for item in bundle.role_requirements
            if item.is_active
            and item.role_profile_id in active_roles
            and item.competency_dimension_id in active_dimensions
        ]
        roles_by_family = {
            family.id: {
                role.id
                for role in bundle.role_profiles
                if role.job_family_id == family.id
            }
            for family in bundle.job_families
        }
        requirements_by_role = {
            role.id: {
                requirement.id
                for requirement in bundle.role_requirements
                if requirement.role_profile_id == role.id
            }
            for role in bundle.role_profiles
        }
        if not (
            active_families
            and active_roles
            and active_requirements
            and bundle.knowledge_sources
            and bundle.source_role_links
        ):
            raise _error(ErrorCode.KNOWLEDGE_VERSION_NOT_PUBLISHABLE)
        if any(not role_ids for role_ids in roles_by_family.values()) or any(
            not requirement_ids
            for requirement_ids in requirements_by_role.values()
        ):
            raise _error(ErrorCode.KNOWLEDGE_VERSION_NOT_PUBLISHABLE)
        reviewed = (
            *bundle.role_profiles,
            *bundle.competency_dimensions,
            *bundle.role_requirements,
            *bundle.evidence_patterns,
            *bundle.knowledge_chunks,
            *bundle.interview_questions,
            *bundle.knowledge_sources,
        )
        if any(item.review_status.value != "approved" for item in reviewed):
            raise _error(ErrorCode.KNOWLEDGE_VERSION_NOT_PUBLISHABLE)
        if any(
            not source.license_note or not source.license_note.strip()
            for source in bundle.knowledge_sources
        ):
            raise _error(ErrorCode.KNOWLEDGE_VERSION_NOT_PUBLISHABLE)


__all__ = [
    "KnowledgeVersionPublisher",
    "calculate_persisted_version_hash",
]
