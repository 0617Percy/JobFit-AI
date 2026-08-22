"""P06 generation with structural Rewrite/Recover versus Build isolation."""

from __future__ import annotations

import re
from dataclasses import dataclass

from jobfit.advisory.v2.selectors import select_top_actions
from jobfit.generators.rewrite import _detect_new_claims
from jobfit.models.v2 import (
    ActionRecommendation,
    ActionType,
    AnalysisCore,
    CitationUsage,
    ClarificationAnswerStatus,
    Evidence,
    EvidenceSourceOrigin,
    JobFitDomainBundle,
    KnowledgeCitation,
)
from jobfit.semantic.v2.advisory_contracts import (
    P06ActionDraft,
    P06ActionInput,
    P06ActionMode,
    P06ActionOutput,
    P06BuildActionDraft,
    P06BuildInput,
    P06BuildOutput,
    P06CandidateActionDraft,
    P06CandidateOutput,
    P06ClarificationReference,
    P06EvidenceReference,
    P06RequirementReference,
)
from jobfit.semantic.v2.contracts import PromptExecutionRecord
from jobfit.semantic.v2.executor import (
    SemanticPromptError,
    SemanticPromptExecutor,
    SemanticValidationIssueError,
)
from jobfit.semantic.v2.governance import KnowledgeTier
from jobfit.semantic.v2.severity import SemanticValidationIssue, validation_issue

_ENGLISH_OWNERSHIP_ESCALATION = re.compile(
    r"\b(?:led|owned|managed|directed|independently led)\b",
    re.IGNORECASE,
)
_LOW_INFORMATION_ACTION_COPY = {
    "build a validation artifact",
    "clarify your project",
    "finish it",
    "make this more specific",
    "the evidence is relevant",
}
_VERIFIABLE_ARTIFACT_TERMS = {
    "analysis",
    "artifact",
    "dashboard",
    "document",
    "notebook",
    "notes",
    "readme",
    "report",
    "repository",
    "script",
    "table",
    "test",
    "分析",
    "报告",
    "文档",
    "测试",
    "看板",
    "脚本",
    "表",
    "记录",
}


@dataclass(frozen=True, slots=True)
class P06ActionResult:
    analysis_core: AnalysisCore
    actions: tuple[ActionRecommendation, ...]
    warnings: tuple[str, ...]
    executions: tuple[PromptExecutionRecord, PromptExecutionRecord]


class P06ActionGenerator:
    """Run candidate-grounded and future-build contexts separately."""

    def __init__(self, executor: SemanticPromptExecutor) -> None:
        self._executor = executor

    def generate(self, bundle: JobFitDomainBundle) -> P06ActionResult:
        core = bundle.analysis_core
        if core is None or bundle.job_profile is None or bundle.versions is None:
            raise SemanticPromptError("P06", "INCOMPLETE_VALIDATED_INPUT")
        base_payload = {
            "analysis_id": core.analysis_id,
            "analysis_core": core,
            "requirements": bundle.requirements,
            "requirement_matches": bundle.requirement_matches,
            "candidate_evidence": bundle.evidence,
            "user_clarifications": bundle.user_clarifications,
            "requirement_reference_catalog": [
                P06RequirementReference(
                    requirement_id=item.requirement_id,
                    descriptor=item.normalized_capability,
                )
                for item in bundle.requirements
            ],
            "evidence_reference_catalog": _evidence_reference_catalog(bundle),
            "clarification_reference_catalog": [
                P06ClarificationReference(
                    clarification_id=item.clarification_id,
                    descriptor=f"{item.answer_status.value} clarification",
                    created_evidence_ids=item.created_evidence_ids,
                )
                for item in bundle.user_clarifications
            ],
        }
        candidate_input = P06ActionInput(
            **base_payload,
            mode=P06ActionMode.CANDIDATE_GROUNDED,
        )
        candidate = self._executor.execute_prompt(
            prompt_id="P06",
            input_payload=candidate_input,
            input_object_ids=(core.analysis_id,),
            response_model=P06CandidateOutput,
            business_validator=lambda output: _validate_mode(
                _map_candidate_output(output), P06ActionMode.CANDIDATE_GROUNDED
            ),
            quality_validator=lambda output: _action_quality_issues(
                _map_candidate_output(output)
            ),
            cross_object_validator=lambda output: _validate_references(
                _map_candidate_output(output),
                bundle,
                P06ActionMode.CANDIDATE_GROUNDED,
            ),
            output_id_getter=lambda output: [
                _deterministic_action_id(P06ActionMode.CANDIDATE_GROUNDED, index)
                for index in range(len(output.actions))
            ],
        )
        build_citations = [
            citation
            for citation in bundle.knowledge_citations
            if citation.usage is CitationUsage.BUILD_RECOMMENDATION
        ]
        build_input = P06BuildInput(
            **base_payload,
            mode=P06ActionMode.FUTURE_BUILD,
            knowledge_context=build_citations,
        )
        build = self._executor.execute_prompt(
            prompt_id="P06",
            input_payload=build_input,
            input_object_ids=(core.analysis_id,),
            response_model=P06BuildOutput,
            business_validator=lambda output: _validate_mode(
                _map_build_output(output), P06ActionMode.FUTURE_BUILD
            ),
            quality_validator=lambda output: _action_quality_issues(
                _map_build_output(output)
            ),
            cross_object_validator=lambda output: _validate_references(
                _map_build_output(output),
                bundle,
                P06ActionMode.FUTURE_BUILD,
            ),
            output_id_getter=lambda output: [
                _deterministic_action_id(P06ActionMode.FUTURE_BUILD, index)
                for index in range(len(output.actions))
            ],
            knowledge_scope=(KnowledgeTier.BUILD,),
        )
        candidate_canonical = _map_candidate_output(candidate.output)
        build_canonical = _map_build_output(build.output)
        actions = tuple(
            _assemble_action(item)
            for item in (*candidate_canonical.actions, *build_canonical.actions)
        )
        if len({item.action_id for item in actions}) != len(actions):
            raise SemanticPromptError("P06", "DUPLICATE_ACTION_ID")
        return P06ActionResult(
            analysis_core=core,
            actions=select_top_actions(
                actions,
                analysis_core=core,
                requirements=bundle.requirements,
                requirement_matches=bundle.requirement_matches,
            ),
            warnings=tuple(
                dict.fromkeys(
                    [
                        *candidate.output.warnings,
                        *build.output.warnings,
                        *candidate.record.warnings,
                        *build.record.warnings,
                    ]
                )
            ),
            executions=(candidate.record, build.record),
        )


def _evidence_reference_catalog(
    bundle: JobFitDomainBundle,
) -> list[P06EvidenceReference]:
    core = bundle.analysis_core
    if core is None:
        raise ValueError("P06 requires a validated analysis core.")
    clarification_by_id = {
        item.clarification_id: item for item in bundle.user_clarifications
    }
    catalog: list[P06EvidenceReference] = []
    for item in bundle.evidence:
        clarification = clarification_by_id.get(item.source_record_id or "")
        recover_eligible = (
            item.source_origin is EvidenceSourceOrigin.USER_CLARIFICATION
            and clarification is not None
            and clarification.analysis_id == core.analysis_id
            and clarification.answer_status is ClarificationAnswerStatus.ANSWERED
            and item.evidence_id in clarification.created_evidence_ids
        ) or (
            item.source_origin
            not in {
                EvidenceSourceOrigin.RESUME,
                EvidenceSourceOrigin.USER_CLARIFICATION,
            }
            and item.source_record_id is not None
        )
        catalog.append(
            P06EvidenceReference(
                evidence_id=item.evidence_id,
                descriptor=(
                    "; ".join(item.normalized_capabilities) or item.source_type
                ),
                source_origin=item.source_origin,
                source_record_id=item.source_record_id,
                eligible_for_rewrite=(
                    item.source_origin is EvidenceSourceOrigin.RESUME
                    and item.resume_version_id == core.resume_version_id
                ),
                eligible_for_recover=recover_eligible,
            )
        )
    return catalog


def _deterministic_action_id(mode: P06ActionMode, index: int) -> str:
    """System-owned, stable action identity: mode prefix + local sequence.

    Identical provider semantic output in the same mode and ordering always
    yields identical IDs; no UUID, timestamp, text hash, or model input.
    """
    prefix = (
        "p06-candidate"
        if mode is P06ActionMode.CANDIDATE_GROUNDED
        else "p06-build"
    )
    return f"{prefix}-{index + 1:03d}"


def _map_candidate_output(output: P06CandidateOutput) -> P06ActionOutput:
    return P06ActionOutput(
        actions=[
            _map_candidate_item(item, index)
            for index, item in enumerate(output.actions)
        ],
        warnings=output.warnings,
    )


def _map_candidate_item(
    item: P06CandidateActionDraft,
    index: int,
) -> P06ActionDraft:
    return P06ActionDraft(
        action_id=_deterministic_action_id(P06ActionMode.CANDIDATE_GROUNDED, index),
        action_type=item.action_type,
        priority=item.priority,
        related_requirement_ids=item.related_requirement_ids,
        related_evidence_ids=item.related_evidence_ids,
        supported_by_evidence_ids=item.supported_by_evidence_ids,
        source_clarification_ids=item.source_clarification_ids,
        knowledge_citation_ids=item.knowledge_citation_ids,
        title=item.title,
        why_it_matters=item.why_it_matters,
        recommended_action=item.recommended_action,
        completion_criteria=item.completion_criteria,
        effort=item.effort,
        time_to_complete=item.time_to_complete,
        timing=item.timing,
        introduced_claims=item.introduced_claims,
    )


def _map_build_output(output: P06BuildOutput) -> P06ActionOutput:
    return P06ActionOutput(
        actions=[
            _map_build_item(item, index) for index, item in enumerate(output.actions)
        ],
        warnings=output.warnings,
    )


def _map_build_item(item: P06BuildActionDraft, index: int) -> P06ActionDraft:
    """Future-build transport → canonical draft with system-fixed fields."""
    return P06ActionDraft(
        action_id=_deterministic_action_id(P06ActionMode.FUTURE_BUILD, index),
        action_type=ActionType.BUILD,
        priority=item.priority,
        related_requirement_ids=item.related_requirement_ids,
        related_evidence_ids=[],
        supported_by_evidence_ids=[],
        source_clarification_ids=[],
        knowledge_citation_ids=item.knowledge_citation_ids,
        title=item.title,
        why_it_matters=item.why_it_matters,
        recommended_action=item.recommended_action,
        completion_criteria=item.completion_criteria,
        effort=item.effort,
        time_to_complete=item.time_to_complete,
        timing=item.timing,
        introduced_claims=[],
    )


def _validate_mode(output: P06ActionOutput, mode: P06ActionMode) -> None:
    allowed = (
        {ActionType.REWRITE, ActionType.RECOVER}
        if mode is P06ActionMode.CANDIDATE_GROUNDED
        else {ActionType.BUILD}
    )
    for index, item in enumerate(output.actions):
        if item.action_type not in allowed:
            _fail(
                "BUSINESS_VALIDATION_FAILED",
                f"actions[{index}].action_type",
                "INVALID_ACTION_TYPE",
            )


def _validate_references(
    output: P06ActionOutput,
    bundle: JobFitDomainBundle,
    mode: P06ActionMode,
) -> None:
    requirement_ids = {item.requirement_id for item in bundle.requirements}
    evidence_by_id = {item.evidence_id: item for item in bundle.evidence}
    clarification_by_id = {
        item.clarification_id: item for item in bundle.user_clarifications
    }
    citation_by_id = {
        item.citation_id: item for item in bundle.knowledge_citations
    }
    versions = bundle.versions
    job = bundle.job_profile
    core = bundle.analysis_core
    if versions is None or job is None or core is None:
        raise ValueError("P06 requires validated version, job, and core objects.")

    strength_paths: list[str] = []
    for index, item in enumerate(output.actions):
        path = f"actions[{index}]"
        if not set(item.related_requirement_ids) <= requirement_ids:
            _fail(
                "CROSS_OBJECT_VALIDATION_FAILED",
                f"{path}.related_requirement_ids",
                "UNKNOWN_REQUIREMENT_REFERENCE",
            )
        evidence_ids = {
            *item.related_evidence_ids,
            *item.supported_by_evidence_ids,
        }
        if not evidence_ids <= evidence_by_id.keys():
            _fail(
                "CROSS_OBJECT_VALIDATION_FAILED",
                f"{path}.related_evidence_ids",
                "UNKNOWN_EVIDENCE_REFERENCE",
            )
        if not set(item.source_clarification_ids) <= clarification_by_id.keys():
            _fail(
                "CROSS_OBJECT_VALIDATION_FAILED",
                f"{path}.source_clarification_ids",
                "UNKNOWN_CLARIFICATION_REFERENCE",
            )
        if not set(item.knowledge_citation_ids) <= citation_by_id.keys():
            _fail(
                "CROSS_OBJECT_VALIDATION_FAILED",
                f"{path}.knowledge_citation_ids",
                "UNKNOWN_KNOWLEDGE_REFERENCE",
            )

        if item.action_type is ActionType.REWRITE:
            strength_path = _validate_rewrite(
                item, evidence_by_id, core.resume_version_id, path
            )
            if strength_path is not None:
                strength_paths.append(strength_path)
        elif item.action_type is ActionType.RECOVER:
            _validate_recover(
                item,
                evidence_by_id,
                clarification_by_id,
                core.analysis_id,
                path,
            )
        else:
            _validate_build(
                item,
                citation_by_id,
                versions.knowledge_version,
                job.job_family,
                path,
            )
        if mode is P06ActionMode.CANDIDATE_GROUNDED and item.knowledge_citation_ids:
            _fail(
                "CROSS_OBJECT_VALIDATION_FAILED",
                f"{path}.knowledge_citation_ids",
                "FORBIDDEN_KNOWLEDGE_REFERENCE",
            )

    if strength_paths:
        raise SemanticValidationIssueError(
            "BUSINESS_VALIDATION_FAILED",
            validation_paths=tuple(strength_paths),
            validation_categories=tuple(
                "SEMANTIC_STRENGTH_INCREASE" for _ in strength_paths
            ),
        )


def _validate_rewrite(
    item: P06ActionDraft,
    evidence_by_id: dict[str, Evidence],
    resume_version_id: str,
    path: str,
) -> str | None:
    """Validate one Rewrite; return its strength path when the semantic
    strength detector fires (for P06-wide aggregation), else None."""
    if not item.supported_by_evidence_ids:
        _fail(
            "CROSS_OBJECT_VALIDATION_FAILED",
            f"{path}.supported_by_evidence_ids",
            "REWRITE_TRACEABILITY_MISSING",
        )
    if item.source_clarification_ids or item.knowledge_citation_ids:
        _fail(
            "CROSS_OBJECT_VALIDATION_FAILED",
            path,
            "REWRITE_SOURCE_INVALID",
        )
    evidence = [evidence_by_id[value] for value in item.supported_by_evidence_ids]
    if any(value.source_origin is not EvidenceSourceOrigin.RESUME for value in evidence):
        _fail("CROSS_OBJECT_VALIDATION_FAILED", path, "REWRITE_SOURCE_INVALID")
    if any(value.resume_version_id != resume_version_id for value in evidence):
        _fail(
            "CROSS_OBJECT_VALIDATION_FAILED",
            f"{path}.supported_by_evidence_ids",
            "EVIDENCE_VERSION_MISMATCH",
        )
    if item.introduced_claims:
        _fail(
            "BUSINESS_VALIDATION_FAILED",
            f"{path}.introduced_claims",
            "FORBIDDEN_INTRODUCED_CLAIM",
        )
    source = " ".join(value.source_text for value in evidence)
    allowed_terms = [
        capability
        for value in evidence
        for capability in value.normalized_capabilities
    ]
    proxy = type(
        "RewriteProxy",
        (),
        {"original_text": source, "rewritten_text": item.recommended_action},
    )()
    if _detect_new_claims(proxy, evidence_text=source, allowed_terms=allowed_terms):
        return f"{path}.recommended_action"
    if _ENGLISH_OWNERSHIP_ESCALATION.search(item.recommended_action) and not (
        _ENGLISH_OWNERSHIP_ESCALATION.search(source)
    ):
        _fail(
            "BUSINESS_VALIDATION_FAILED",
            f"{path}.recommended_action",
            "OWNERSHIP_ESCALATION",
        )
    return None


def _validate_recover(
    item: P06ActionDraft,
    evidence_by_id: dict[str, Evidence],
    clarification_by_id: dict[str, object],
    analysis_id: str,
    path: str,
) -> None:
    if not item.supported_by_evidence_ids:
        _fail(
            "CROSS_OBJECT_VALIDATION_FAILED",
            f"{path}.supported_by_evidence_ids",
            "RECOVER_TRACEABILITY_MISSING",
        )
    if item.knowledge_citation_ids:
        _fail(
            "CROSS_OBJECT_VALIDATION_FAILED",
            f"{path}.knowledge_citation_ids",
            "FORBIDDEN_KNOWLEDGE_REFERENCE",
        )
    for evidence_id in item.supported_by_evidence_ids:
        evidence = evidence_by_id[evidence_id]
        if evidence.source_origin is EvidenceSourceOrigin.RESUME:
            _fail(
                "CROSS_OBJECT_VALIDATION_FAILED",
                f"{path}.supported_by_evidence_ids",
                "RECOVER_SOURCE_INVALID",
            )
        if evidence.source_origin is EvidenceSourceOrigin.USER_CLARIFICATION:
            clarification_id = evidence.source_record_id
            if clarification_id not in item.source_clarification_ids:
                _fail(
                    "CROSS_OBJECT_VALIDATION_FAILED",
                    f"{path}.source_clarification_ids",
                    "RECOVER_SOURCE_IDENTITY_MISSING",
                )
            clarification = clarification_by_id[clarification_id]
            if (
                clarification.analysis_id != analysis_id
                or clarification.answer_status is not ClarificationAnswerStatus.ANSWERED
                or evidence_id not in clarification.created_evidence_ids
            ):
                _fail(
                    "CROSS_OBJECT_VALIDATION_FAILED",
                    f"{path}.source_clarification_ids",
                    "UNCONFIRMED_CLARIFICATION_REFERENCE",
                )
        elif evidence.source_record_id is None:
            _fail(
                "CROSS_OBJECT_VALIDATION_FAILED",
                f"{path}.supported_by_evidence_ids",
                "EXTERNAL_SOURCE_IDENTITY_MISSING",
            )


def _validate_build(
    item: P06ActionDraft,
    citation_by_id: dict[str, KnowledgeCitation],
    knowledge_version: str,
    role_family: object,
    path: str,
) -> None:
    if (
        item.related_evidence_ids
        or item.supported_by_evidence_ids
        or item.source_clarification_ids
    ):
        _fail(
            "BUSINESS_VALIDATION_FAILED",
            path,
            "INVALID_ACTION_TIMING",
        )
    build_text = " ".join(
        [item.recommended_action, item.completion_criteria]
    ).casefold()
    if not any(term in build_text for term in _VERIFIABLE_ARTIFACT_TERMS):
        _fail(
            "BUSINESS_VALIDATION_FAILED",
            f"{path}.completion_criteria",
            "BUILD_TRACEABILITY_MISSING",
        )
    for citation_id in item.knowledge_citation_ids:
        citation = citation_by_id[citation_id]
        if (
            citation.usage is not CitationUsage.BUILD_RECOMMENDATION
            or citation.knowledge_version != knowledge_version
            or citation.role_family not in {None, role_family}
        ):
            _fail(
                "CROSS_OBJECT_VALIDATION_FAILED",
                f"{path}.knowledge_citation_ids",
                "KNOWLEDGE_SCOPE_VIOLATION",
            )


def _action_quality_issues(
    output: P06ActionOutput,
) -> tuple[SemanticValidationIssue, ...]:
    issues: list[SemanticValidationIssue] = []
    for index, item in enumerate(output.actions):
        fields = (
            item.title,
            item.why_it_matters,
            item.recommended_action,
            item.completion_criteria,
        )
        normalized = {
            value.casefold().strip().rstrip(".!?。！？")
            for value in fields
        }
        if normalized & _LOW_INFORMATION_ACTION_COPY:
            issues.append(
                validation_issue(
                    stage="P06",
                    category="ACTION_QUALITY_TOO_GENERIC",
                    safe_path=f"actions[{index}]",
                )
            )
    return tuple(issues)


def _fail(code: str, path: str, category: str) -> None:
    raise SemanticValidationIssueError(
        code,
        validation_paths=(path,),
        validation_categories=(category,),
    )


def _assemble_action(item: P06ActionDraft) -> ActionRecommendation:
    payload = item.model_dump(
        exclude={
            "source_clarification_ids",
            "knowledge_citation_ids",
            "introduced_claims",
        }
    )
    return ActionRecommendation.model_validate(
        {
            **payload,
            "source_clarification_ids": item.source_clarification_ids,
            "knowledge_citation_ids": item.knowledge_citation_ids,
            "future_only": item.action_type is ActionType.BUILD,
        }
    )
