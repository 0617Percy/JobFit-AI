"""Shared deterministic boundaries for advice generation."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping, Sequence

from jobfit.errors import ErrorCode, SchemaValidationError
from jobfit.models import (
    EvidenceItem,
    EvidenceRegistry,
    EvidenceSourceType,
    JobRequirement,
)

_SPACE_AND_PUNCTUATION = re.compile(r"[\W_]+", re.UNICODE)


def advice_error(message: str, *, cause: Exception | None = None) -> SchemaValidationError:
    return SchemaValidationError(
        code=ErrorCode.ADVICE_VALIDATION_FAILED,
        user_message=message,
        recoverable=True,
        cause=cause,
    )


def requirement_index(
    requirements: Sequence[JobRequirement],
) -> dict[str, JobRequirement]:
    index = {item.requirement_id: item for item in requirements}
    if len(index) != len(requirements):
        raise advice_error("岗位要求ID存在重复，无法生成诊断建议。")
    return index


def require_requirement_ids(
    requirement_ids: Iterable[str],
    requirements: Mapping[str, JobRequirement],
) -> list[JobRequirement]:
    ids = list(requirement_ids)
    if not ids or len(ids) != len(set(ids)):
        raise advice_error("建议必须引用至少一个且不得重复的岗位要求ID。")
    try:
        return [requirements[requirement_id] for requirement_id in ids]
    except KeyError as exc:
        raise advice_error("建议引用了不存在的岗位要求。", cause=exc) from exc


def require_resume_evidence(
    evidence_ids: Iterable[str],
    registry: EvidenceRegistry,
    *,
    allow_empty: bool = False,
) -> list[EvidenceItem]:
    ids = list(evidence_ids)
    if not allow_empty and not ids:
        raise advice_error("建议缺少可追溯的简历证据。")
    if len(ids) != len(set(ids)):
        raise advice_error("建议包含重复的Evidence ID。")
    try:
        evidence = registry.require_many(ids)
    except KeyError as exc:
        raise advice_error("建议引用了不存在的Evidence ID。", cause=exc) from exc
    if any(item.source_type is not EvidenceSourceType.RESUME for item in evidence):
        raise advice_error("建议只能引用简历证据，不能引用岗位描述。")
    return evidence


def normalized_phrase(value: str) -> str:
    return _SPACE_AND_PUNCTUATION.sub("", value).casefold()


def stable_generated_id(prefix: str, *parts: object) -> str:
    payload = "\x1f".join(str(part) for part in parts)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"
