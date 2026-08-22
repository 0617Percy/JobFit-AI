"""Source-grounding checks shared by resume and job extractors."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from jobfit.errors import ErrorCode, SchemaValidationError
from jobfit.models import (
    DocumentContent,
    EvidenceCandidate,
    JobRequirementDraft,
    ResumeFactDraft,
    TextSegment,
)

_NEGATION_PATTERN = re.compile(
    r"(没有|无|未曾|未具备|不具备|不熟悉|不会|no\b|not\b|without\b)",
    re.IGNORECASE,
)


def grounding_error(message: str = "结构化结果与原始文本证据不一致。") -> SchemaValidationError:
    return SchemaValidationError(
        code=ErrorCode.SCHEMA_VALIDATION_FAILED,
        user_message=message,
        recoverable=True,
    )


def find_containing_segment(
    document: DocumentContent,
    *,
    start_char: int,
    end_char: int,
) -> TextSegment:
    for segment in document.segments:
        if segment.start_char <= start_char and end_char <= segment.end_char:
            return segment
    raise grounding_error("证据区间无法对应到原始文档片段。")


def validate_evidence_candidate(
    document: DocumentContent,
    candidate: EvidenceCandidate,
) -> TextSegment:
    if candidate.end_char > len(document.normalized_text):
        raise grounding_error()
    quote = document.normalized_text[candidate.start_char : candidate.end_char]
    if quote != candidate.quote:
        raise grounding_error()
    segment = find_containing_segment(
        document,
        start_char=candidate.start_char,
        end_char=candidate.end_char,
    )
    if candidate.page_number is not None and candidate.page_number != segment.page_number:
        raise grounding_error("证据页码与原始文档片段不一致。")
    return segment


def validate_resume_fact(document: DocumentContent, fact: ResumeFactDraft) -> None:
    if fact.raw_text not in document.normalized_text:
        raise grounding_error("简历事实原文无法在文档中定位。")

    evidence_text = "\n".join(candidate.quote for candidate in fact.evidence_candidates)
    if fact.raw_text not in evidence_text and evidence_text not in fact.raw_text:
        raise grounding_error("简历事实与其证据引用不一致。")

    for candidate in fact.evidence_candidates:
        validate_evidence_candidate(document, candidate)

    _validate_supported_values(
        fact.structured_fields,
        evidence_text=evidence_text,
        excluded_keys={"skill_type"},
    )
    if fact.fact_type.casefold() == "skill":
        skill_name = fact.structured_fields.get("name")
        if (
            isinstance(skill_name, str)
            and _NEGATION_PATTERN.search(fact.raw_text)
            and _compact(skill_name) in _compact(fact.raw_text)
        ):
            raise grounding_error("否定表述不能转换为正向技能事实。")


def validate_job_requirement(
    document: DocumentContent,
    requirement: JobRequirementDraft,
) -> None:
    if requirement.source_end_char > len(document.normalized_text):
        raise grounding_error()
    source_slice = document.normalized_text[
        requirement.source_start_char : requirement.source_end_char
    ]
    if source_slice != requirement.source_text:
        raise grounding_error("岗位要求的原文引用区间不一致。")
    find_containing_segment(
        document,
        start_char=requirement.source_start_char,
        end_char=requirement.source_end_char,
    )
    requirement_tokens = _semantic_tokens(requirement.requirement_text)
    source_compact = _compact(requirement.source_text)
    if any(_compact(token) not in source_compact for token in requirement_tokens):
        raise grounding_error("岗位要求文本超出了其引用原文。")


def require_source_supported(value: str | None, source_text: str, label: str) -> None:
    if value is not None and _compact(value) not in _compact(source_text):
        raise grounding_error(f"{label}无法在原始文本中确认。")


def _validate_supported_values(
    values: Mapping[str, Any],
    *,
    evidence_text: str,
    excluded_keys: set[str],
) -> None:
    for key, value in values.items():
        if key in excluded_keys:
            continue
        for item in _iter_scalar_values(value):
            if isinstance(item, bool) or item is None:
                continue
            rendered = str(item)
            if _compact(rendered) and _compact(rendered) not in _compact(evidence_text):
                raise grounding_error("结构化字段包含证据中未出现的信息。")


def _iter_scalar_values(value: Any) -> Iterable[Any]:
    if isinstance(value, Mapping):
        for nested in value.values():
            yield from _iter_scalar_values(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _iter_scalar_values(nested)
    else:
        yield value


def _compact(value: str) -> str:
    return "".join(character.casefold() for character in value if character.isalnum())


def _semantic_tokens(value: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9.+#-]+|[\u4e00-\u9fff]+", value)
