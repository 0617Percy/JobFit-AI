"""P07 interview preparation with K4-only role-side knowledge."""

from __future__ import annotations

import re
from dataclasses import dataclass

from jobfit.models.v2 import (
    AnalysisCore,
    CitationUsage,
    InterviewQuestion,
    InterviewQuestionType,
    JobFitDomainBundle,
    KnowledgeCitation,
    Priority,
)
from jobfit.semantic.v2.advisory_contracts import (
    P07InterviewDraft,
    P07InterviewInput,
    P07InterviewOutput,
)
from jobfit.semantic.v2.contracts import PromptExecutionRecord
from jobfit.semantic.v2.executor import (
    SemanticPromptError,
    SemanticPromptExecutor,
    SemanticValidationIssueError,
)
from jobfit.semantic.v2.governance import KnowledgeTier
from jobfit.semantic.v2.severity import SemanticValidationIssue, validation_issue

_ASSUMED_PERSONAL_FACT = re.compile(
    (
        r"(?:你曾经|你曾|你主导|你负责|你独立完成|when you led|when you managed)"
    ),
    re.IGNORECASE,
)
_SCRIPTED_PERSONAL_FACT = re.compile(
    r"(?:say that you|claim that you)",
    re.IGNORECASE,
)
_LOW_INFORMATION_PREPARATION = {
    "answer with star",
    "prepare an answer",
    "use star",
}
_PRIORITY_RANK = {Priority.P0: 0, Priority.P1: 1, Priority.P2: 2}
_TYPE_RANK = {
    InterviewQuestionType.RESUME_DEEP_DIVE: 0,
    InterviewQuestionType.ROLE_CAPABILITY: 1,
    InterviewQuestionType.GAP_RISK: 2,
    InterviewQuestionType.BEHAVIORAL: 3,
}


@dataclass(frozen=True, slots=True)
class P07InterviewResult:
    analysis_core: AnalysisCore
    questions: tuple[InterviewQuestion, ...]
    warnings: tuple[str, ...]
    execution: PromptExecutionRecord


def _eligible_interview_citations(
    bundle: JobFitDomainBundle,
) -> list[KnowledgeCitation]:
    """Deterministic P07-eligible knowledge citation universe.

    Mirrors the P07 cross-object validator exactly: usage must be
    INTERVIEW_PREPARATION, version must match the current knowledge
    version, and role_family must match the role family or be
    role-agnostic (None).
    """
    versions = bundle.versions
    job = bundle.job_profile
    if versions is None or job is None:
        return []
    return [
        item
        for item in bundle.knowledge_citations
        if item.usage is CitationUsage.INTERVIEW_PREPARATION
        and item.knowledge_version == versions.knowledge_version
        and item.role_family in {None, job.job_family}
    ]


def _project_citation_ids(item: object, eligible_ids: set[str]) -> object:
    """Non-mutating model-facing copy whose citation IDs are eligible only."""
    current = list(getattr(item, "knowledge_citation_ids", None) or [])
    filtered = [value for value in current if value in eligible_ids]
    if filtered == current:
        return item
    payload = item.model_dump(mode="json")
    payload["knowledge_citation_ids"] = filtered
    return type(item).model_validate(payload)


class P07InterviewGenerator:
    """Generate deterministic, traceable interview preparation."""

    def __init__(self, executor: SemanticPromptExecutor) -> None:
        self._executor = executor

    def generate(self, bundle: JobFitDomainBundle) -> P07InterviewResult:
        core = bundle.analysis_core
        job = bundle.job_profile
        versions = bundle.versions
        if core is None or job is None or versions is None:
            raise SemanticPromptError("P07", "INCOMPLETE_VALIDATED_INPUT")
        citations = _eligible_interview_citations(bundle)
        eligible_ids = {item.citation_id for item in citations}
        prompt_input = P07InterviewInput(
            analysis_id=core.analysis_id,
            analysis_core=core,
            requirements=[
                _project_citation_ids(item, eligible_ids)
                for item in bundle.requirements
            ],
            requirement_matches=bundle.requirement_matches,
            candidate_evidence=bundle.evidence,
            actions=[
                _project_citation_ids(item, eligible_ids) for item in bundle.actions
            ],
            knowledge_context=citations,
        )
        response = self._executor.execute_prompt(
            prompt_id="P07",
            input_payload=prompt_input,
            input_object_ids=(core.analysis_id,),
            response_model=P07InterviewOutput,
            business_validator=_validate_business,
            quality_validator=_quality_issues,
            cross_object_validator=lambda output: _validate_references(output, bundle),
            output_id_getter=lambda output: [
                item.question_id for item in output.questions
            ],
            knowledge_scope=(KnowledgeTier.INTERVIEW,),
        )
        questions = sorted(
            (_assemble_question(item) for item in response.output.questions),
            key=lambda item: (
                _PRIORITY_RANK[item.priority],
                _TYPE_RANK[item.question_type],
                item.question_id,
            ),
        )
        return P07InterviewResult(
            analysis_core=core,
            questions=tuple(questions),
            warnings=tuple(
                dict.fromkeys([*response.output.warnings, *response.record.warnings])
            ),
            execution=response.record,
        )


def _validate_business(output: P07InterviewOutput) -> None:
    for index, item in enumerate(output.questions):
        path = f"questions[{index}]"
        candidate_text = " ".join([item.question, *item.preparation_points])
        scripted_fact = _SCRIPTED_PERSONAL_FACT.search(candidate_text)
        if scripted_fact or _ASSUMED_PERSONAL_FACT.search(candidate_text):
            _fail(
                "BUSINESS_VALIDATION_FAILED",
                path,
                "CANDIDATE_FACT_FABRICATION",
            )


def _quality_issues(
    output: P07InterviewOutput,
) -> tuple[SemanticValidationIssue, ...]:
    issues: list[SemanticValidationIssue] = []
    normalized_questions = [
        " ".join(item.question.casefold().split()) for item in output.questions
    ]
    if len(normalized_questions) != len(set(normalized_questions)):
        issues.append(
            validation_issue(
                stage="P07",
                category="DUPLICATE_INTERVIEW_QUESTION",
                safe_path="questions",
            )
        )
    for index, item in enumerate(output.questions):
        normalized_points = {
            value.casefold().strip().rstrip(".!?。！？")
            for value in item.preparation_points
        }
        if normalized_points & _LOW_INFORMATION_PREPARATION:
            issues.append(
                validation_issue(
                    stage="P07",
                    category="INTERVIEW_GUIDANCE_TOO_GENERIC",
                    safe_path=f"questions[{index}].preparation_points",
                )
            )
    return tuple(issues)


def _validate_references(
    output: P07InterviewOutput,
    bundle: JobFitDomainBundle,
) -> None:
    requirement_ids = {item.requirement_id for item in bundle.requirements}
    evidence_ids = {item.evidence_id for item in bundle.evidence}
    action_ids = {item.action_id for item in bundle.actions}
    citation_by_id = {item.citation_id: item for item in bundle.knowledge_citations}
    core = bundle.analysis_core
    versions = bundle.versions
    job = bundle.job_profile
    if core is None or versions is None or job is None:
        raise ValueError("P07 requires validated core, version, and job objects.")
    hard_ids = {*core.hard_blocker_ids, *core.hard_pending_ids}
    critical_ids = set(core.critical_gap_requirement_ids)
    for index, item in enumerate(output.questions):
        path = f"questions[{index}]"
        trace_ids = {
            *item.related_requirement_ids,
            *item.related_evidence_ids,
            *item.critical_gap_requirement_ids,
            *item.hard_concern_requirement_ids,
            *item.related_action_ids,
        }
        if not trace_ids:
            _fail(
                "CROSS_OBJECT_VALIDATION_FAILED",
                path,
                "INTERVIEW_TRACEABILITY_MISSING",
            )
        if not set(item.related_requirement_ids) <= requirement_ids:
            _fail(
                "CROSS_OBJECT_VALIDATION_FAILED",
                f"{path}.related_requirement_ids",
                "UNKNOWN_REQUIREMENT_REFERENCE",
            )
        if not set(item.related_evidence_ids) <= evidence_ids:
            _fail(
                "CROSS_OBJECT_VALIDATION_FAILED",
                f"{path}.related_evidence_ids",
                "UNKNOWN_EVIDENCE_REFERENCE",
            )
        if not set(item.related_action_ids) <= action_ids:
            _fail(
                "CROSS_OBJECT_VALIDATION_FAILED",
                f"{path}.related_action_ids",
                "UNKNOWN_ACTION_REFERENCE",
            )
        if not set(item.critical_gap_requirement_ids) <= critical_ids:
            _fail(
                "CROSS_OBJECT_VALIDATION_FAILED",
                f"{path}.critical_gap_requirement_ids",
                "INVENTED_CRITICAL_GAP_REFERENCE",
            )
        if not set(item.hard_concern_requirement_ids) <= hard_ids:
            _fail(
                "CROSS_OBJECT_VALIDATION_FAILED",
                f"{path}.hard_concern_requirement_ids",
                "INVENTED_HARD_CONCERN_REFERENCE",
            )
        for citation_id in item.knowledge_citation_ids:
            citation = citation_by_id.get(citation_id)
            if citation is None or (
                citation.usage is not CitationUsage.INTERVIEW_PREPARATION
                or citation.knowledge_version != versions.knowledge_version
                or citation.role_family not in {None, job.job_family}
            ):
                _fail(
                    "CROSS_OBJECT_VALIDATION_FAILED",
                    f"{path}.knowledge_citation_ids",
                    "KNOWLEDGE_SCOPE_VIOLATION",
                )


def _fail(code: str, path: str, category: str) -> None:
    raise SemanticValidationIssueError(
        code,
        validation_paths=(path,),
        validation_categories=(category,),
    )


def _assemble_question(item: P07InterviewDraft) -> InterviewQuestion:
    payload = item.model_dump(
        exclude={
            "critical_gap_requirement_ids",
            "hard_concern_requirement_ids",
            "related_action_ids",
        }
    )
    return InterviewQuestion.model_validate(
        {
            **payload,
            "critical_gap_requirement_ids": item.critical_gap_requirement_ids,
            "hard_concern_requirement_ids": item.hard_concern_requirement_ids,
            "related_action_ids": item.related_action_ids,
        }
    )
