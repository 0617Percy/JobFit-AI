"""Revalidate private ORM records into immutable public knowledge contracts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, TypeVar

from pydantic import ValidationError

from jobfit.errors import ErrorCode, KnowledgeDatabaseError
from jobfit.models.knowledge import (
    KnowledgeBaseVersionInfo,
    KnowledgeCitation,
    RetrievedEvidencePattern,
    RetrievedInterviewQuestion,
    RetrievedRequirement,
    RetrievedRoleProfile,
)

_T = TypeVar("_T")
_INVALID_DATA_MESSAGE = "岗位知识库包含无效数据，已停止使用该知识结果。"


def _mapping_error(cause: Exception) -> KnowledgeDatabaseError:
    return KnowledgeDatabaseError(
        code=ErrorCode.KNOWLEDGE_DB_UNAVAILABLE,
        user_message=_INVALID_DATA_MESSAGE,
        recoverable=True,
        cause=cause,
    )


def _validated(factory: Callable[[], _T]) -> _T:
    try:
        return factory()
    except KnowledgeDatabaseError:
        raise
    except (TypeError, ValueError, ValidationError, json.JSONDecodeError) as exc:
        raise _mapping_error(exc) from exc


def _aware(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


def _string_list(raw: str) -> list[str]:
    value: Any = json.loads(raw)
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError("stored JSON value must be a string list")
    return list(dict.fromkeys(value))


def citation_id_for(
    *,
    version_id: str,
    source_id: str,
    chunk_id: str | None = None,
) -> str:
    identity = f"{version_id}|{source_id}|{chunk_id or ''}".encode()
    return f"cite-{hashlib.sha256(identity).hexdigest()[:16]}"


def map_version(record) -> KnowledgeBaseVersionInfo:
    return _validated(
        lambda: KnowledgeBaseVersionInfo(
            id=record.id,
            version=record.version,
            name=record.name,
            description=record.description or None,
            status=record.status,
            content_hash=record.content_hash,
            published_at=_aware(record.published_at),
            created_at=_aware(record.created_at),
        )
    )


def map_source_citation(
    source,
    *,
    version_id: str,
    chunk=None,
) -> KnowledgeCitation:
    def create() -> KnowledgeCitation:
        chunk_id = chunk.id if chunk is not None else None
        return KnowledgeCitation(
            citation_id=citation_id_for(
                version_id=version_id,
                source_id=source.id,
                chunk_id=chunk_id,
            ),
            source_id=source.id,
            chunk_id=chunk_id,
            source_title=source.title,
            source_type=source.source_type,
            publisher=source.publisher,
            source_url=source.source_url,
            section=chunk.section if chunk is not None else None,
            knowledge_version_id=version_id,
            reliability_level=source.reliability_level,
            excerpt=chunk.chunk_text[:240] if chunk is not None else None,
            source_checksum=source.checksum,
        )

    return _validated(create)


def _stable_ids(values: Sequence[str]) -> list[str]:
    return sorted(dict.fromkeys(values))


def map_role_profile(
    record,
    *,
    job_family_code: str,
    citation_ids: Sequence[str],
    matched_terms: Sequence[str],
    relevance_score: Decimal,
    matched_fields: Sequence[str] = (),
) -> RetrievedRoleProfile:
    return _validated(
        lambda: RetrievedRoleProfile(
            role_profile_id=record.id,
            job_family_code=job_family_code,
            code=record.code,
            name=record.name,
            seniority=record.seniority,
            industry=record.industry,
            description=record.description,
            relevance_score=relevance_score,
            matched_terms=sorted(dict.fromkeys(matched_terms)),
            matched_fields=list(dict.fromkeys(matched_fields)),
            citation_ids=_stable_ids(citation_ids),
        )
    )


def map_requirement(
    record,
    *,
    competency_dimension_code: str,
    citation_ids: Sequence[str],
    relevance_score: Decimal,
    matched_terms: Sequence[str] = (),
    matched_fields: Sequence[str] = (),
) -> RetrievedRequirement:
    def create() -> RetrievedRequirement:
        return RetrievedRequirement(
            knowledge_requirement_id=record.id,
            role_profile_id=record.role_profile_id,
            competency_dimension_code=competency_dimension_code,
            title=record.title,
            description=record.description,
            requirement_type=record.requirement_type,
            importance=record.importance,
            is_common_hard_blocker=record.is_common_hard_blocker,
            expected_evidence=_string_list(record.expected_evidence_json),
            weak_evidence=_string_list(record.weak_evidence_json),
            negative_signals=_string_list(record.negative_signals_json),
            relevance_score=relevance_score,
            matched_terms=sorted(dict.fromkeys(matched_terms)),
            matched_fields=list(dict.fromkeys(matched_fields)),
            citation_ids=_stable_ids(citation_ids),
        )

    return _validated(create)


def map_evidence_pattern(
    record,
    *,
    citation_ids: Sequence[str],
) -> RetrievedEvidencePattern:
    return _validated(
        lambda: RetrievedEvidencePattern(
            evidence_pattern_id=record.id,
            knowledge_requirement_id=record.role_requirement_id,
            evidence_type=record.evidence_type,
            description=record.description,
            strength=record.strength,
            positive_example=record.positive_example,
            weak_example=record.weak_example,
            negative_example=record.negative_example,
            citation_ids=_stable_ids(citation_ids),
        )
    )


def map_interview_question(
    record,
    *,
    competency_dimension_code: str,
    citation_ids: Sequence[str],
    relevance_score: Decimal,
    matched_terms: Sequence[str] = (),
    matched_fields: Sequence[str] = (),
) -> RetrievedInterviewQuestion:
    def create() -> RetrievedInterviewQuestion:
        return RetrievedInterviewQuestion(
            knowledge_question_id=record.id,
            role_profile_id=record.role_profile_id,
            competency_dimension_code=competency_dimension_code,
            question=record.question,
            question_type=record.question_type,
            expected_points=_string_list(record.expected_points_json),
            follow_up_questions=_string_list(record.follow_up_questions_json),
            difficulty=record.difficulty,
            relevance_score=relevance_score,
            matched_terms=sorted(dict.fromkeys(matched_terms)),
            matched_fields=list(dict.fromkeys(matched_fields)),
            citation_ids=_stable_ids(citation_ids),
        )

    return _validated(create)


__all__ = [
    "citation_id_for",
    "map_evidence_pattern",
    "map_interview_question",
    "map_requirement",
    "map_role_profile",
    "map_source_citation",
    "map_version",
]
