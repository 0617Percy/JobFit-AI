"""Transactional imports for validated draft knowledge seed bundles."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import delete, select

from jobfit.errors import (
    ErrorCode,
    KnowledgeDatabaseError,
    KnowledgeSeedError,
)
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
from jobfit.knowledge.seed_loader import (
    calculate_seed_content_hash,
    validate_knowledge_seed,
)
from jobfit.knowledge.seed_models import (
    KnowledgeSeedBundle,
    SeedEntityCounts,
    SeedImportMode,
    SeedImportResult,
)

_SAFE_IMPORT_MESSAGE = "Knowledge seed import failed."


def _error(
    code: ErrorCode,
    *,
    cause: Exception | None = None,
) -> KnowledgeSeedError:
    return KnowledgeSeedError(
        code=code,
        user_message=_SAFE_IMPORT_MESSAGE,
        recoverable=False,
        cause=cause,
    )


def _json_strings(values: list[str]) -> str:
    return json.dumps(values, ensure_ascii=False, separators=(",", ":"))


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class KnowledgeSeedImporter:
    """Write one validated draft package in one SQLite transaction."""

    def __init__(self, database: KnowledgeDatabase) -> None:
        self._database = database

    def import_seed(
        self,
        bundle: KnowledgeSeedBundle,
        *,
        mode: SeedImportMode = SeedImportMode.CREATE,
    ) -> SeedImportResult:
        if not isinstance(bundle, KnowledgeSeedBundle):
            raise _error(ErrorCode.KNOWLEDGE_SEED_SCHEMA_INVALID)
        try:
            import_mode = SeedImportMode(mode)
        except ValueError as exc:
            raise _error(
                ErrorCode.KNOWLEDGE_SEED_SCHEMA_INVALID,
                cause=exc,
            ) from exc
        validated = validate_knowledge_seed(bundle)
        content_hash = calculate_seed_content_hash(validated)
        counts = SeedEntityCounts.from_bundle(validated)
        self._database.ensure_compatible_schema()
        now = datetime.now(UTC)
        try:
            with self._database._session_scope() as session:
                existing = session.execute(
                    select(KnowledgeBaseVersionRecord).where(
                        (
                            KnowledgeBaseVersionRecord.version
                            == validated.knowledge_base_version.version
                        )
                        | (KnowledgeBaseVersionRecord.id == validated.knowledge_base_version.id)
                    )
                ).scalar_one_or_none()
                if existing is not None:
                    result = self._handle_existing(
                        session,
                        existing=existing,
                        content_hash=content_hash,
                        counts=counts,
                        mode=import_mode,
                    )
                    if result is not None:
                        return result

                self._insert_bundle(
                    session,
                    validated,
                    content_hash=content_hash,
                    created_at=now,
                )
            return SeedImportResult(
                version_id=validated.knowledge_base_version.id,
                version=validated.knowledge_base_version.version,
                content_hash=content_hash,
                status="draft",
                created_at=now,
                created=True,
                idempotent=False,
                replaced_draft=import_mode is SeedImportMode.REPLACE_DRAFT,
                counts=counts,
            )
        except KnowledgeSeedError:
            raise
        except KnowledgeDatabaseError as exc:
            raise _error(ErrorCode.KNOWLEDGE_SEED_INVALID, cause=exc) from exc

    def _handle_existing(
        self,
        session,
        *,
        existing: KnowledgeBaseVersionRecord,
        content_hash: str,
        counts: SeedEntityCounts,
        mode: SeedImportMode,
    ) -> SeedImportResult | None:
        if existing.status != "draft":
            raise _error(ErrorCode.KNOWLEDGE_PUBLISHED_IMMUTABLE)
        if existing.content_hash == content_hash:
            from jobfit.knowledge.versioning import load_persisted_seed_bundle

            persisted_hash = calculate_seed_content_hash(
                load_persisted_seed_bundle(session, existing)
            )
            if persisted_hash != existing.content_hash:
                raise _error(ErrorCode.KNOWLEDGE_SEED_HASH_MISMATCH)
            return SeedImportResult(
                version_id=existing.id,
                version=existing.version,
                content_hash=existing.content_hash,
                status=existing.status,
                created_at=_aware(existing.created_at),
                created=False,
                idempotent=True,
                replaced_draft=False,
                counts=counts,
            )
        if mode is not SeedImportMode.REPLACE_DRAFT:
            raise _error(ErrorCode.KNOWLEDGE_DRAFT_CONFLICT)
        self._delete_draft(session, existing.id)
        session.flush()
        return None

    def _delete_draft(self, session, version_id: str) -> None:
        source_ids = set(
            session.scalars(
                select(RoleRequirementRecord.source_id).where(
                    RoleRequirementRecord.knowledge_version_id == version_id
                )
            )
        )
        source_ids.update(
            session.scalars(
                select(EvidencePatternRecord.source_id).where(
                    EvidencePatternRecord.knowledge_version_id == version_id
                )
            )
        )
        source_ids.update(
            session.scalars(
                select(KnowledgeChunkRecord.source_id).where(
                    KnowledgeChunkRecord.knowledge_version_id == version_id
                )
            )
        )
        source_ids.update(
            session.scalars(
                select(InterviewQuestionRecord.source_id).where(
                    InterviewQuestionRecord.knowledge_version_id == version_id
                )
            )
        )
        source_ids.update(
            session.scalars(
                select(SourceRoleLinkRecord.source_id).where(
                    SourceRoleLinkRecord.knowledge_version_id == version_id
                )
            )
        )

        for record_type in (
            EvidencePatternRecord,
            InterviewQuestionRecord,
            KnowledgeChunkRecord,
            RoleRequirementRecord,
            SourceRoleLinkRecord,
            RoleProfileRecord,
            CompetencyDimensionRecord,
            JobFamilyRecord,
        ):
            session.execute(
                delete(record_type).where(record_type.knowledge_version_id == version_id)
            )
        session.execute(
            delete(KnowledgeBaseVersionRecord).where(KnowledgeBaseVersionRecord.id == version_id)
        )
        session.flush()
        for source_id in sorted(source_ids):
            if not self._source_is_referenced(session, source_id):
                session.execute(
                    delete(KnowledgeSourceRecord).where(KnowledgeSourceRecord.id == source_id)
                )

    @staticmethod
    def _source_is_referenced(session, source_id: str) -> bool:
        record_types = (
            RoleRequirementRecord,
            EvidencePatternRecord,
            KnowledgeChunkRecord,
            InterviewQuestionRecord,
            SourceRoleLinkRecord,
        )
        return any(
            session.execute(
                select(record_type.source_id).where(record_type.source_id == source_id).limit(1)
            ).first()
            is not None
            for record_type in record_types
        )

    def _insert_bundle(
        self,
        session,
        bundle: KnowledgeSeedBundle,
        *,
        content_hash: str,
        created_at: datetime,
    ) -> None:
        version = bundle.knowledge_base_version
        session.add(
            KnowledgeBaseVersionRecord(
                id=version.id,
                version=version.version,
                name=version.name,
                description=version.description,
                status="draft",
                published_at=None,
                created_at=created_at,
                content_hash=content_hash,
            )
        )
        self._insert_sources(session, bundle)
        session.flush()

        session.add_all(
            JobFamilyRecord(
                id=item.id,
                code=item.code,
                name=item.name,
                description=item.description,
                aliases_json=_json_strings(item.aliases),
                knowledge_version_id=item.knowledge_version_id,
                is_active=item.is_active,
                created_at=created_at,
                updated_at=created_at,
            )
            for item in bundle.job_families
        )
        session.add_all(
            CompetencyDimensionRecord(
                id=item.id,
                code=item.code,
                name=item.name,
                description=item.description,
                scoring_category_hint=item.scoring_category_hint,
                display_order=item.display_order,
                knowledge_version_id=item.knowledge_version_id,
                review_status=item.review_status.value,
                is_active=item.is_active,
            )
            for item in bundle.competency_dimensions
        )
        session.flush()

        session.add_all(
            RoleProfileRecord(
                id=item.id,
                job_family_id=item.job_family_id,
                code=item.code,
                name=item.name,
                seniority=item.seniority,
                industry=item.industry,
                description=item.description,
                aliases_json=_json_strings(item.aliases),
                keywords_json=_json_strings(item.keywords),
                knowledge_version_id=item.knowledge_version_id,
                review_status=item.review_status.value,
                is_active=item.is_active,
                created_at=created_at,
                updated_at=created_at,
            )
            for item in bundle.role_profiles
        )
        session.flush()

        session.add_all(
            RoleRequirementRecord(
                id=item.id,
                role_profile_id=item.role_profile_id,
                competency_dimension_id=item.competency_dimension_id,
                title=item.title,
                description=item.description,
                requirement_type=item.requirement_type.value,
                importance=item.importance.value,
                is_common_hard_blocker=item.is_common_hard_blocker,
                expected_evidence_json=_json_strings(item.expected_evidence),
                weak_evidence_json=_json_strings(item.weak_evidence),
                negative_signals_json=_json_strings(item.negative_signals),
                keywords_json=_json_strings(item.keywords),
                source_id=item.source_id,
                knowledge_version_id=item.knowledge_version_id,
                review_status=item.review_status.value,
                is_active=item.is_active,
            )
            for item in bundle.role_requirements
        )
        session.add_all(
            KnowledgeChunkRecord(
                id=item.id,
                source_id=item.source_id,
                role_profile_id=item.role_profile_id,
                section=item.section,
                chunk_text=item.chunk_text,
                start_offset=item.start_offset,
                end_offset=item.end_offset,
                keywords_json=_json_strings(item.keywords),
                knowledge_version_id=item.knowledge_version_id,
                review_status=item.review_status.value,
                content_hash=item.content_hash,
            )
            for item in bundle.knowledge_chunks
        )
        session.flush()

        session.add_all(
            EvidencePatternRecord(
                id=item.id,
                role_requirement_id=item.role_requirement_id,
                evidence_type=item.evidence_type,
                description=item.description,
                strength=item.strength.value,
                positive_example=item.positive_example,
                weak_example=item.weak_example,
                negative_example=item.negative_example,
                source_id=item.source_id,
                knowledge_version_id=item.knowledge_version_id,
                review_status=item.review_status.value,
                is_active=item.is_active,
            )
            for item in bundle.evidence_patterns
        )
        session.add_all(
            InterviewQuestionRecord(
                id=item.id,
                role_profile_id=item.role_profile_id,
                competency_dimension_id=item.competency_dimension_id,
                question=item.question,
                question_type=item.question_type.value,
                expected_points_json=_json_strings(item.expected_points),
                follow_up_questions_json=_json_strings(item.follow_up_questions),
                difficulty=item.difficulty.value,
                source_id=item.source_id,
                knowledge_version_id=item.knowledge_version_id,
                review_status=item.review_status.value,
                is_active=item.is_active,
            )
            for item in bundle.interview_questions
        )
        session.flush()
        session.add_all(
            SourceRoleLinkRecord(
                source_id=item.source_id,
                role_profile_id=item.role_profile_id,
                knowledge_version_id=item.knowledge_version_id,
                relation_type=item.relation_type.value,
                created_at=created_at,
            )
            for item in bundle.source_role_links
        )
        session.flush()

    @staticmethod
    def _insert_sources(session, bundle: KnowledgeSeedBundle) -> None:
        for item in bundle.knowledge_sources:
            existing = session.get(KnowledgeSourceRecord, item.id)
            if existing is not None:
                expected = (
                    item.title,
                    item.source_type.value,
                    item.publisher,
                    str(item.source_url) if item.source_url else None,
                    item.published_at,
                    item.collected_at,
                    item.license_note,
                    item.reliability_level.value,
                    item.review_status.value,
                    item.checksum,
                )
                actual = (
                    existing.title,
                    existing.source_type,
                    existing.publisher,
                    existing.source_url,
                    _aware(existing.published_at) if existing.published_at is not None else None,
                    _aware(existing.collected_at),
                    existing.license_note,
                    existing.reliability_level,
                    existing.review_status,
                    existing.checksum,
                )
                if actual != expected:
                    raise _error(ErrorCode.KNOWLEDGE_DRAFT_CONFLICT)
                continue
            session.add(
                KnowledgeSourceRecord(
                    id=item.id,
                    title=item.title,
                    source_type=item.source_type.value,
                    publisher=item.publisher,
                    source_url=str(item.source_url) if item.source_url else None,
                    published_at=item.published_at,
                    collected_at=item.collected_at,
                    license_note=item.license_note,
                    reliability_level=item.reliability_level.value,
                    review_status=item.review_status.value,
                    checksum=item.checksum,
                )
            )


__all__ = ["KnowledgeSeedImporter"]
