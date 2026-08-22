"""P08 twelve-module assembly without decision recomputation."""

from __future__ import annotations

import re
from dataclasses import dataclass

from jobfit.models.v2 import (
    AbilityStatus,
    ActionType,
    AnalysisCore,
    CitationUsage,
    EvidenceStatus,
    JobFitDomainBundle,
    JobFitReport,
    RequirementSource,
)
from jobfit.reporting.v2.validation import B5ReportValidationError, P08ReportValidator
from jobfit.semantic.v2.advisory_contracts import P08ReportInput, P08ReportOutput
from jobfit.semantic.v2.contracts import PromptAttemptRecord, PromptExecutionRecord
from jobfit.semantic.v2.executor import (
    SemanticPromptError,
    SemanticPromptExecutor,
    SemanticValidationIssueError,
)
from jobfit.semantic.v2.governance import KnowledgeTier

_UNSUPPORTED_CANDIDATE_ASSERTION = re.compile(
    (
        r"(?:\b(?:the candidate|candidate|you)\s+"
        r"(?:has|have|had|led|managed|built|implemented|achieved|improved|developed|"
        r"delivered)\b|(?:候选人|你)(?:已|曾)?(?:具备|拥有|完成|主导|负责|实现|提升))"
    ),
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class P08ReportResult:
    analysis_core: AnalysisCore
    report: JobFitReport
    warnings: tuple[str, ...]
    execution: PromptExecutionRecord


class P08ReportAssembler:
    """Use P08 for bounded narrative and code for all decision-bearing fields."""

    def __init__(
        self,
        executor: SemanticPromptExecutor,
        validator: P08ReportValidator | None = None,
    ) -> None:
        self._executor = executor
        self._validator = validator or P08ReportValidator()

    def generate(self, bundle: JobFitDomainBundle) -> P08ReportResult:
        core = bundle.analysis_core
        job = bundle.job_profile
        versions = bundle.versions
        if core is None or job is None or versions is None:
            raise SemanticPromptError("P08", "INCOMPLETE_VALIDATED_INPUT")
        explicit = [
            item for item in bundle.requirements if item.source is RequirementSource.JD
        ]
        implicit = [
            item
            for item in bundle.requirements
            if item.source is RequirementSource.KNOWLEDGE
        ]
        citations = [
            item
            for item in bundle.knowledge_citations
            if item.usage
            in {CitationUsage.JOB_EXPLANATION, CitationUsage.IMPLICIT_REQUIREMENT}
        ]
        prompt_input = P08ReportInput(
            analysis_id=core.analysis_id,
            analysis_core=core,
            explicit_requirements=explicit,
            implicit_requirements=implicit,
            candidate_evidence=bundle.evidence,
            knowledge_context=citations,
        )
        response = self._executor.execute_prompt(
            prompt_id="P08",
            input_payload=prompt_input,
            input_object_ids=(core.analysis_id,),
            response_model=P08ReportOutput,
            business_validator=_validate_presentation,
            cross_object_validator=lambda output: _validate_presentation_references(
                output, bundle
            ),
            knowledge_scope=(KnowledgeTier.JOB_EXPLANATION, KnowledgeTier.IMPLICIT),
        )
        report = _assemble_report(bundle, response.output)
        try:
            self._validator.validate_or_raise(report, bundle)
        except B5ReportValidationError as exc:
            category = _safe_report_validation_category(exc)
            attempt = PromptAttemptRecord(
                attempt=1,
                stage="local_report_assembly",
                syntax_valid=True,
                schema_valid=True,
                business_valid=False,
                cross_object_valid=False,
                error_code="REPORT_ASSEMBLY_VALIDATION_FAILED",
                validation_error_count=1,
                validation_paths=("report",),
                validation_types=("value_error",),
                validation_categories=(category,),
            )
            raise SemanticPromptError(
                "P08",
                "REPORT_ASSEMBLY_VALIDATION_FAILED",
                attempts=(attempt,),
            ) from exc
        return P08ReportResult(
            analysis_core=core,
            report=report,
            warnings=tuple(response.output.warnings),
            execution=response.record,
        )


def _validate_presentation(output: P08ReportOutput) -> None:
    texts = [
        *(item.text for item in output.job_explanations),
        *(item.text for item in output.implicit_explanations),
        *output.application_strategy_notes,
        *output.boundary_notes,
    ]
    for index, note in enumerate(texts):
        if not note.strip():
            _fail(
                "BUSINESS_VALIDATION_FAILED",
                f"presentation_text[{index}]",
                "REPORT_PRESENTATION_EMPTY",
            )
        if _UNSUPPORTED_CANDIDATE_ASSERTION.search(note):
            _fail(
                "BUSINESS_VALIDATION_FAILED",
                f"presentation_text[{index}]",
                "CANDIDATE_FACT_FABRICATION",
            )


def _validate_presentation_references(
    output: P08ReportOutput,
    bundle: JobFitDomainBundle,
) -> None:
    citation_by_id = {item.citation_id: item for item in bundle.knowledge_citations}
    requirement_by_id = {item.requirement_id: item for item in bundle.requirements}
    core = bundle.analysis_core
    job = bundle.job_profile
    versions = bundle.versions
    if core is None or job is None or versions is None:
        raise ValueError("P08 reference validation requires validated inputs.")
    for index, explanation in enumerate(output.job_explanations):
        _validate_citation_usage(
            explanation.knowledge_citation_ids,
            citation_by_id,
            CitationUsage.JOB_EXPLANATION,
            versions.knowledge_version,
            job.job_family,
            f"job_explanations[{index}].knowledge_citation_ids",
        )
    for index, explanation in enumerate(output.implicit_explanations):
        path = f"implicit_explanations[{index}]"
        requirement = requirement_by_id.get(explanation.requirement_id)
        if requirement is None or requirement.source is not RequirementSource.KNOWLEDGE:
            _fail(
                "CROSS_OBJECT_VALIDATION_FAILED",
                f"{path}.requirement_id",
                "INVALID_IMPLICIT_REQUIREMENT_REFERENCE",
            )
        _validate_citation_usage(
            explanation.knowledge_citation_ids,
            citation_by_id,
            CitationUsage.IMPLICIT_REQUIREMENT,
            versions.knowledge_version,
            job.job_family,
            f"{path}.knowledge_citation_ids",
        )


def _validate_citation_usage(
    citation_ids: list[str],
    citation_by_id: dict[str, object],
    usage: CitationUsage,
    version: str,
    role_family: object,
    path: str,
) -> None:
    for citation_id in citation_ids:
        citation = citation_by_id.get(citation_id)
        if citation is None or (
            citation.usage is not usage
            or citation.knowledge_version != version
            or citation.role_family not in {None, role_family}
        ):
            _fail(
                "CROSS_OBJECT_VALIDATION_FAILED",
                path,
                "KNOWLEDGE_SCOPE_VIOLATION",
            )


def _safe_report_validation_category(error: B5ReportValidationError) -> str:
    code = str(error).split(":", 1)[0]
    return {
        "REPORT_MODULE_INCOMPLETE": "REPORT_MODULE_MISSING",
        "REPORT_DECISION_DRIFT": "REPORT_CORE_INVARIANCE_VIOLATION",
        "REPORT_ADVISORY_DRIFT": "REPORT_ADVISORY_INVARIANCE_VIOLATION",
        "REPORT_EXPLICIT_REQUIREMENT_DRIFT": "REPORT_REFERENCE_INVALID",
        "REPORT_IMPLICIT_EXPLICIT_MIXED": "REPORT_REFERENCE_INVALID",
        "REPORT_VERSION_IDENTITY_DRIFT": "REPORT_VERSION_INVARIANCE_VIOLATION",
        "REPORT_INPUT_INCOMPLETE": "REPORT_INPUT_INCOMPLETE",
    }.get(code, "REPORT_ASSEMBLY_INVARIANCE_VIOLATION")


def _fail(code: str, path: str, category: str) -> None:
    raise SemanticValidationIssueError(
        code,
        validation_paths=(path,),
        validation_categories=(category,),
    )


def _assemble_report(
    bundle: JobFitDomainBundle,
    presentation: P08ReportOutput,
) -> JobFitReport:
    core = bundle.analysis_core
    job = bundle.job_profile
    versions = bundle.versions
    assert core is not None and job is not None and versions is not None
    explicit = sorted(
        (item for item in bundle.requirements if item.source is RequirementSource.JD),
        key=lambda item: item.requirement_id,
    )
    matches = sorted(
        bundle.requirement_matches,
        key=lambda item: (item.requirement_id, item.match_id),
    )
    evidence = sorted(
        (
            item
            for item in bundle.evidence
            if item.source_origin is not None
        ),
        key=lambda item: item.evidence_id,
    )
    actions = sorted(bundle.actions, key=lambda item: item.action_id)
    questions = sorted(bundle.interview_questions, key=lambda item: item.question_id)
    strengths = [
        item.requirement_id
        for item in matches
        if item.evidence_status is EvidenceStatus.PRESENT
        and item.ability_status is AbilityStatus.CONFIRMED
    ]
    gaps = [
        {
            "requirement_id": item.requirement_id,
            "gap_kind": (
                "confirmed_gap"
                if item.ability_status is AbilityStatus.CONFIRMED_GAP
                else "missing_evidence"
                if item.evidence_status is EvidenceStatus.MISSING
                else "unknown"
            ),
            "ability_status": item.ability_status.value,
            "safe_note": (
                "This is a confirmed gap."
                if item.ability_status is AbilityStatus.CONFIRMED_GAP
                else "Current evidence is insufficient; ability remains unknown."
            ),
        }
        for item in matches
        if item.evidence_status is not EvidenceStatus.PRESENT
        or item.ability_status is not AbilityStatus.CONFIRMED
    ]
    return JobFitReport(
        report_id=f"report-{core.analysis_id}",
        analysis_id=core.analysis_id,
        summary={
            "analysis_readiness": core.analysis_readiness.value,
            "eligibility_status": core.eligibility_status.value,
            "seniority_alignment": core.seniority_alignment.value,
            "confidence": core.confidence.value,
            "recommendation": core.recommendation.value,
            "critical_gap_requirement_ids": list(core.critical_gap_requirement_ids),
        },
        job_profile={
            "job_title": job.job_title,
            "job_family": job.job_family.value,
            "explicit_requirements": [item.model_dump(mode="json") for item in explicit],
            "job_explanations": [
                item.model_dump(mode="json") for item in presentation.job_explanations
            ],
            "implicit_context": [
                item.model_dump(mode="json")
                for item in presentation.implicit_explanations
            ],
        },
        resume_evidence_profile={
            "resume_version_id": core.resume_version_id,
            "candidate_evidence": [item.model_dump(mode="json") for item in evidence],
        },
        requirement_match=[item.model_dump(mode="json") for item in matches],
        score_explanation={
            "base_fit_score": str(core.base_fit_score),
            "preferred_bonus": str(core.preferred_bonus),
            "final_fit_score": str(core.final_fit_score),
            "confidence": core.confidence.value,
            "recommendation_reason_codes": [
                item.value for item in core.recommendation_reason_codes
            ],
        },
        strengths_and_gaps={
            "strength_requirement_ids": strengths,
            "gaps": gaps,
            "critical_gap_requirement_ids": list(core.critical_gap_requirement_ids),
        },
        hard_check={
            "hard_blocker_ids": list(core.hard_blocker_ids),
            "hard_pending_ids": list(core.hard_pending_ids),
        },
        resume_optimization={
            "rewrite": [
                item.model_dump(mode="json")
                for item in actions
                if item.action_type is ActionType.REWRITE
            ],
            "recover": [
                item.model_dump(mode="json")
                for item in actions
                if item.action_type is ActionType.RECOVER
            ],
        },
        build_recommendations=[
            item.model_dump(mode="json")
            for item in actions
            if item.action_type is ActionType.BUILD
        ],
        application_strategy={
            "recommendation": core.recommendation.value,
            "notes": presentation.application_strategy_notes,
        },
        interview_preparation=[item.model_dump(mode="json") for item in questions],
        analysis_basis_and_limits={
            "versions": versions.model_dump(mode="json"),
            "resume_version_id": core.resume_version_id,
            "jd_snapshot_id": core.jd_snapshot_id,
            "boundaries": [
                "Candidate evidence comes only from validated candidate sources.",
                "Knowledge is explanatory and never candidate evidence.",
                "Missing evidence keeps ability unknown unless explicitly confirmed.",
                *presentation.boundary_notes,
            ],
        },
    )
