"""Four-layer validation for candidate semantic pipeline artifacts."""

from __future__ import annotations

from collections.abc import Sequence

from jobfit.models.common import NonEmptyStr, StrictModel
from jobfit.models.v2 import (
    Evidence,
    JobFitDomainBundle,
    JobProfile,
    Requirement,
    RequirementMatch,
    ResumeProfile,
)
from jobfit.semantic.v2.contracts import PromptExecutionRecord
from jobfit.validators.v2 import DomainValidator

_EXPECTED_PROMPTS = ("P01", "P02", "P03", "P04", "P05")


class SemanticValidationResult(StrictModel):
    valid: bool
    syntax_valid: bool
    schema_valid: bool
    business_valid: bool
    cross_object_valid: bool
    issue_codes: tuple[NonEmptyStr, ...] = ()


class SemanticPipelineValidator:
    """Require syntax, schema, business, and cross-object validation to pass."""

    def __init__(self, domain_validator: DomainValidator | None = None) -> None:
        self._domain_validator = domain_validator or DomainValidator()

    def validate(
        self,
        *,
        analysis_id: str,
        resume_profile: ResumeProfile,
        evidence: Sequence[Evidence],
        job_profile: JobProfile,
        requirements: Sequence[Requirement],
        matches: Sequence[RequirementMatch],
        execution_records: Sequence[PromptExecutionRecord],
    ) -> SemanticValidationResult:
        issue_codes: list[str] = []
        syntax_valid = all(
            record.validation.syntax_valid for record in execution_records
        )
        schema_valid = all(
            record.validation.schema_valid for record in execution_records
        )
        business_valid = all(
            record.validation.business_valid for record in execution_records
        )
        if tuple(record.prompt_id for record in execution_records) != _EXPECTED_PROMPTS:
            issue_codes.append("PROMPT_TRACE_INCOMPLETE")
            business_valid = False
        if any(
            analysis_id not in record.input_object_ids
            for record in execution_records
        ):
            issue_codes.append("PROMPT_TRACE_ANALYSIS_MISMATCH")
            business_valid = False

        domain_result = self._domain_validator.validate(
            JobFitDomainBundle(
                resume_profile=resume_profile,
                evidence=list(evidence),
                job_profile=job_profile,
                requirements=list(requirements),
                requirement_matches=list(matches),
            )
        )
        cross_object_valid = (
            all(
                record.validation.cross_object_valid
                for record in execution_records
            )
            and domain_result.valid
        )
        issue_codes.extend(issue.code for issue in domain_result.issues)
        if not syntax_valid:
            issue_codes.append("PROMPT_SYNTAX_VALIDATION_FAILED")
        if not schema_valid:
            issue_codes.append("PROMPT_SCHEMA_VALIDATION_FAILED")
        if not business_valid and "PROMPT_TRACE_INCOMPLETE" not in issue_codes:
            issue_codes.append("PROMPT_BUSINESS_VALIDATION_FAILED")
        if not cross_object_valid and domain_result.valid:
            issue_codes.append("PROMPT_CROSS_OBJECT_VALIDATION_FAILED")
        unique_codes = tuple(dict.fromkeys(issue_codes))
        valid = (
            syntax_valid
            and schema_valid
            and business_valid
            and cross_object_valid
            and not unique_codes
        )
        return SemanticValidationResult(
            valid=valid,
            syntax_valid=syntax_valid,
            schema_valid=schema_valid,
            business_valid=business_valid,
            cross_object_valid=cross_object_valid,
            issue_codes=unique_codes,
        )
