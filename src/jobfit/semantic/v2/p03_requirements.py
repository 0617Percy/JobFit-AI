"""P03 candidate-blind classification of explicit JD requirements."""

from __future__ import annotations

from dataclasses import dataclass

from jobfit.extractors.common import stable_id
from jobfit.models.v2 import (
    CriticalStatus,
    JobProfile,
    KnowledgeCoverage,
    Requirement,
    RequirementExplicitness,
    RequirementSource,
    RequirementType,
)
from jobfit.semantic.v2.contracts import PromptExecutionRecord
from jobfit.semantic.v2.executor import (
    SemanticPromptExecutor,
    SemanticValidationIssueError,
)
from jobfit.semantic.v2.p02_job import P02JobResult
from jobfit.semantic.v2.stage_contracts import (
    JDSourceItem,
    P03RequirementDraft,
    P03RequirementInput,
    P03RequirementOutput,
)


@dataclass(frozen=True, slots=True)
class P03RequirementResult:
    analysis_id: str
    job_profile: JobProfile
    requirements: tuple[Requirement, ...]
    warnings: tuple[str, ...]
    execution: PromptExecutionRecord


class P03RequirementClassifier:
    """Classify only P02 JD facts; final guards remain frozen B2 code."""

    def __init__(self, executor: SemanticPromptExecutor) -> None:
        self._executor = executor

    def classify(self, parsed_job: P02JobResult) -> P03RequirementResult:
        input_payload = P03RequirementInput(
            analysis_id=parsed_job.analysis_id,
            jd_snapshot_id=parsed_job.jd_snapshot_id,
            job_title=parsed_job.job_title,
            job_family=parsed_job.job_family,
            responsibilities=list(parsed_job.responsibilities),
            raw_requirements=list(parsed_job.raw_requirements),
            explicit_constraints=list(parsed_job.explicit_constraints),
            seniority_signals=list(parsed_job.seniority_signals),
        )
        result = self._executor.execute_prompt(
            prompt_id="P03",
            input_payload=input_payload,
            input_object_ids=(
                parsed_job.analysis_id,
                parsed_job.jd_snapshot_id,
                *(item.object_id for item in parsed_job.raw_requirements),
            ),
            response_model=P03RequirementOutput,
            business_validator=_validate_business,
            cross_object_validator=lambda output: _validate_references(
                output, parsed_job
            ),
        )
        raw_by_id = {
            item.object_id: item for item in parsed_job.raw_requirements
        }
        requirements = tuple(
            _assemble_requirement(
                item,
                jd_snapshot_id=parsed_job.jd_snapshot_id,
                raw_by_id=raw_by_id,
            )
            for item in result.output.requirements
        )
        profile = JobProfile(
            jd_snapshot_id=parsed_job.jd_snapshot_id,
            company=parsed_job.company,
            job_title=parsed_job.job_title,
            location=parsed_job.location,
            employment_type=parsed_job.employment_type,
            job_family=parsed_job.job_family,
            knowledge_coverage=KnowledgeCoverage.BASE_ONLY,
            seniority_signals=[
                item.model_dump(mode="json") for item in parsed_job.seniority_signals
            ],
            responsibility_ids=[
                item.object_id for item in parsed_job.responsibilities
            ],
            raw_requirement_ids=[
                item.object_id for item in parsed_job.raw_requirements
            ],
            requirement_ids=[item.requirement_id for item in requirements],
        )
        execution = result.record.model_copy(
            update={
                "output_object_ids": tuple(
                    item.requirement_id for item in requirements
                )
            }
        )
        return P03RequirementResult(
            analysis_id=parsed_job.analysis_id,
            job_profile=profile,
            requirements=requirements,
            warnings=tuple(result.output.warnings),
            execution=execution,
        )


def _validate_business(output: P03RequirementOutput) -> None:
    local_ids = [item.local_id for item in output.requirements]
    if len(local_ids) != len(set(local_ids)):
        _fail(
            "BUSINESS_VALIDATION_FAILED",
            "requirements",
            "P03_REQUIREMENT_ID_DUPLICATE",
        )
    capabilities = [
        item.normalized_capability.casefold() for item in output.requirements
    ]
    if len(capabilities) != len(set(capabilities)):
        _fail(
            "BUSINESS_VALIDATION_FAILED",
            "requirements.normalized_capability",
            "P03_REQUIREMENT_NORMALIZATION_DUPLICATE",
        )


def _validate_references(
    output: P03RequirementOutput,
    parsed_job: P02JobResult,
) -> None:
    expected = [item.object_id for item in parsed_job.raw_requirements]
    actual = [
        raw_id
        for requirement in output.requirements
        for raw_id in requirement.raw_requirement_ids
    ]
    if sorted(actual) != sorted(expected) or len(actual) != len(set(actual)):
        _fail(
            "CROSS_OBJECT_VALIDATION_FAILED",
            "requirements.raw_requirement_ids",
            "P03_CLASSIFICATION_INCOMPLETE",
        )


def _fail(code: str, path: str, category: str) -> None:
    raise SemanticValidationIssueError(
        code,
        validation_paths=(path,),
        validation_categories=(category,),
    )


def _assemble_requirement(
    item: P03RequirementDraft,
    *,
    jd_snapshot_id: str,
    raw_by_id: dict[str, JDSourceItem],
) -> Requirement:
    raw_text = "\n".join(
        raw_by_id[raw_id].text for raw_id in item.raw_requirement_ids
    )
    requirement_id = stable_id(
        "requirement",
        jd_snapshot_id,
        *item.raw_requirement_ids,
        item.normalized_capability,
    )
    return Requirement(
        requirement_id=requirement_id,
        jd_snapshot_id=jd_snapshot_id,
        raw_requirement_ids=item.raw_requirement_ids,
        raw_text=raw_text,
        normalized_capability=item.normalized_capability,
        requirement_type=RequirementType(item.requirement_type.value),
        importance=item.importance,
        explicitness=RequirementExplicitness.EXPLICIT,
        source=RequirementSource.JD,
        critical_status=CriticalStatus(item.critical_status.value),
        classification_reason=item.classification_reason,
    )
