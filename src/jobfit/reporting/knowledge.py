"""Pure mapping from validated runtime knowledge into report-safe metadata."""

from __future__ import annotations

from collections import defaultdict

from jobfit.errors import ErrorCode, ReportGenerationError
from jobfit.generators import GeneratedAdvice
from jobfit.models import (
    KnowledgeAdviceTrace,
    KnowledgeContext,
    KnowledgeRetrievalStatus,
    ReportCitationStatus,
    ReportKnowledgeAdviceTrace,
    ReportKnowledgeCitation,
    ReportKnowledgeEvidencePattern,
    ReportKnowledgeInterviewReference,
    ReportKnowledgeRequirement,
    ReportKnowledgeSection,
    ReportKnowledgeWarning,
    ReportRoleProfileReference,
)


def build_report_knowledge_section(
    context: KnowledgeContext | None,
    trace: KnowledgeAdviceTrace | None,
    advice: GeneratedAdvice,
) -> ReportKnowledgeSection:
    """Build a compact report view without database access or re-retrieval."""

    context = context or KnowledgeContext()
    status = context.status
    if status is KnowledgeRetrievalStatus.DISABLED:
        return _empty_section(context, enabled=False)
    if status is KnowledgeRetrievalStatus.UNAVAILABLE:
        return _empty_section(context, enabled=True, fallback=True)
    if status is KnowledgeRetrievalStatus.NO_MATCH:
        return _empty_section(context, enabled=True, fallback=True, retain_version=True)
    if status is KnowledgeRetrievalStatus.AMBIGUOUS:
        return ReportKnowledgeSection(
            enabled=True,
            status=status,
            knowledge_version_id=context.version.id if context.version else None,
            knowledge_version=context.version.version if context.version else None,
            knowledge_content_hash=(
                context.version.content_hash if context.version else None
            ),
            retrieval_mode=context.capabilities.mode,
            retrieval_strategy_version=context.retrieval_strategy_version,
            role_candidates=[
                _role(item) for item in context.inferred_role_profiles[:3]
            ],
            warnings=_warnings(context, trace),
            fallback_used=True,
        )

    if context.version is None or len(context.inferred_role_profiles) != 1:
        raise _invalid_mapping()
    selected = context.inferred_role_profiles[0]
    used_by = _validated_usage(context, trace, advice)
    scoped_citation_ids = _scoped_citation_ids(context)
    included_citation_ids = _select_report_citation_ids(context, used_by)
    citations = []
    for citation in (
        item
        for item in context.citations
        if item.citation_id in scoped_citation_ids
        and item.citation_id in included_citation_ids
    ):
        if len(citations) == 20:
            break
        if citation.knowledge_version_id != context.version.id:
            raise _invalid_mapping()
        targets = sorted(used_by.get(citation.citation_id, set()))
        citations.append(
            ReportKnowledgeCitation(
                citation_id=citation.citation_id,
                source_id=citation.source_id,
                source_title=citation.source_title,
                source_type=citation.source_type,
                source_url=citation.source_url,
                knowledge_version_id=citation.knowledge_version_id,
                role_profile_id=selected.role_profile_id,
                section=citation.section,
                reliability_level=citation.reliability_level,
                short_summary=citation.excerpt or citation.source_title,
                used_by=targets,
                validation_status=(
                    ReportCitationStatus.VALIDATED_ADVICE
                    if targets
                    else ReportCitationStatus.REFERENCE
                ),
            )
        )
    report_trace = None
    if trace is not None:
        report_trace = ReportKnowledgeAdviceTrace(
            validated=trace.validated,
            fallback_used=trace.fallback_used,
            prompt_version=trace.prompt_version,
            validator_version=trace.validator_version,
            generation_strategy_version=trace.generation_strategy_version,
            used_citation_ids=sorted(used_by),
        )
    return ReportKnowledgeSection(
        enabled=True,
        status=status,
        knowledge_version_id=context.version.id,
        knowledge_version=context.version.version,
        knowledge_content_hash=context.version.content_hash,
        retrieval_mode=context.capabilities.mode,
        retrieval_strategy_version=context.retrieval_strategy_version,
        selected_role_profile=_role(selected),
        role_candidates=[_role(selected)],
        requirements=[
            ReportKnowledgeRequirement(
                knowledge_requirement_id=item.knowledge_requirement_id,
                title=item.title,
                description=item.description[:500],
                requirement_type=item.requirement_type,
                importance=item.importance,
                is_common_hard_blocker=item.is_common_hard_blocker,
                expected_evidence=item.expected_evidence[:5],
                citation_ids=item.citation_ids[:10],
            )
            for item in context.requirements[:12]
            if set(item.citation_ids).issubset(included_citation_ids)
        ],
        evidence_patterns=[
            ReportKnowledgeEvidencePattern(
                evidence_pattern_id=item.evidence_pattern_id,
                knowledge_requirement_id=item.knowledge_requirement_id,
                description=item.description[:300],
                strength=item.strength,
                citation_ids=item.citation_ids[:10],
            )
            for item in context.evidence_patterns[:12]
            if set(item.citation_ids).issubset(included_citation_ids)
        ],
        interview_references=[
            ReportKnowledgeInterviewReference(
                knowledge_question_id=item.knowledge_question_id,
                competency_dimension_code=item.competency_dimension_code,
                question=item.question[:300],
                question_type=item.question_type,
                citation_ids=item.citation_ids[:10],
            )
            for item in context.interview_questions[:10]
            if set(item.citation_ids).issubset(included_citation_ids)
        ],
        citations=citations,
        warnings=_warnings(context, trace),
        advice_trace=report_trace,
        fallback_used=bool(trace and trace.fallback_used),
    )


def _empty_section(
    context: KnowledgeContext,
    *,
    enabled: bool,
    fallback: bool = False,
    retain_version: bool = False,
) -> ReportKnowledgeSection:
    return ReportKnowledgeSection(
        enabled=enabled,
        status=context.status,
        knowledge_version_id=(
            context.version.id if retain_version and context.version else None
        ),
        knowledge_version=(
            context.version.version if retain_version and context.version else None
        ),
        knowledge_content_hash=(
            context.version.content_hash if retain_version and context.version else None
        ),
        retrieval_mode=context.capabilities.mode,
        retrieval_strategy_version=context.retrieval_strategy_version,
        warnings=_warnings(context, None),
        fallback_used=fallback,
    )


def _role(item) -> ReportRoleProfileReference:
    return ReportRoleProfileReference(
        role_profile_id=item.role_profile_id,
        job_family_code=item.job_family_code,
        name=item.name,
        seniority=item.seniority,
        industry=item.industry,
        relevance_score=item.relevance_score,
    )


def _warnings(
    context: KnowledgeContext,
    trace: KnowledgeAdviceTrace | None,
) -> list[ReportKnowledgeWarning]:
    result: list[ReportKnowledgeWarning] = []
    seen: set[tuple[str, str]] = set()
    for warning in [*context.warnings, *(trace.warnings if trace else [])]:
        key = (warning.code.value, warning.message)
        if key in seen:
            continue
        seen.add(key)
        result.append(
            ReportKnowledgeWarning(
                code=warning.code,
                message=warning.message,
                recoverable=warning.recoverable,
            )
        )
        if len(result) == 10:
            break
    return result


def _validated_usage(
    context: KnowledgeContext,
    trace: KnowledgeAdviceTrace | None,
    advice: GeneratedAdvice,
) -> dict[str, set[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    if trace is None:
        return result
    if trace.fallback_used:
        if trace.citation_uses:
            raise _invalid_mapping()
        return result
    selected = context.inferred_role_profiles[0]
    if (
        not trace.validated
        or context.version is None
        or trace.knowledge_version != context.version.version
        or trace.content_hash != context.version.content_hash
        or trace.selected_role_profile_id != selected.role_profile_id
    ):
        raise _invalid_mapping()
    known = {item.citation_id for item in context.citations}
    scoped = _scoped_citation_ids(context)
    for usage in trace.citation_uses:
        if usage.citation_id not in known or usage.citation_id not in scoped:
            raise _invalid_mapping()
        reference = f"{usage.target_type.value}:{usage.target_index}"
        if usage.output_reference != reference or not _target_exists(reference, advice):
            raise _invalid_mapping()
        result[usage.citation_id].add(reference)
    return result


def _scoped_citation_ids(context: KnowledgeContext) -> set[str]:
    return {
        citation_id
        for item in (
            *context.inferred_role_profiles,
            *context.requirements,
            *context.evidence_patterns,
            *context.interview_questions,
        )
        for citation_id in item.citation_ids
    }


def _select_report_citation_ids(
    context: KnowledgeContext,
    used_by: dict[str, set[str]],
) -> set[str]:
    if len(used_by) > 20:
        raise _invalid_mapping()
    priority: list[str] = sorted(used_by)
    for item in (
        *context.inferred_role_profiles,
        *context.requirements,
        *context.evidence_patterns,
        *context.interview_questions,
    ):
        priority.extend(item.citation_ids)
    selected: list[str] = []
    for citation_id in priority:
        if citation_id in selected:
            continue
        selected.append(citation_id)
        if len(selected) == 20:
            break
    return set(selected)


def _target_exists(reference: str, advice: GeneratedAdvice) -> bool:
    kind, _, raw_index = reference.partition(":")
    if not raw_index.isdigit():
        return False
    index = int(raw_index)
    limits = {
        "gap": len(advice.gaps),
        "recommendation": 1,
        "rewrite": len(advice.rewrite_suggestions),
        "interview_question": len(advice.interview_questions),
    }
    return kind in limits and index < limits[kind]


def _invalid_mapping() -> ReportGenerationError:
    return ReportGenerationError(
        code=ErrorCode.REPORT_VALIDATION_FAILED,
        user_message="岗位知识引用未通过最终报告校验，已禁止生成和下载。",
        recoverable=True,
    )


__all__ = ["build_report_knowledge_section"]
