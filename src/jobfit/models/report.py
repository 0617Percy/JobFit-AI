"""Final analysis report and validation result contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, ConfigDict, Field, model_validator

from jobfit.models.advice import (
    ApplicationRecommendation,
    GapItem,
    InterviewQuestion,
    RewriteSuggestion,
    StrengthItem,
)
from jobfit.models.common import (
    NonEmptyStr,
    StrictModel,
    ValidationSeverity,
)
from jobfit.models.job import JobProfile
from jobfit.models.matching import MatchScoreSummary, RequirementMatch
from jobfit.models.report_knowledge import ReportKnowledgeSection
from jobfit.models.resume import ResumeProfile


class ValidationIssue(StrictModel):
    code: NonEmptyStr
    severity: ValidationSeverity
    message: str = Field(min_length=1)
    object_ref: str | None = None


class ValidationResult(StrictModel):
    valid: bool
    issues: list[ValidationIssue]
    checked_rules: list[NonEmptyStr] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_flag(self) -> ValidationResult:
        has_error = any(
            issue.severity is ValidationSeverity.ERROR for issue in self.issues
        )
        if self.valid == has_error:
            raise ValueError(
                "valid must be false exactly when an error issue is present"
            )
        return self


class AnalysisReport(StrictModel):
    model_config = ConfigDict(frozen=True)

    schema_version: Literal["1.0", "1.1"] = "1.1"
    report_id: NonEmptyStr
    generated_at: AwareDatetime
    job_profile: JobProfile
    resume_profile: ResumeProfile
    matches: list[RequirementMatch] = Field(min_length=1)
    score_summary: MatchScoreSummary
    strengths: list[StrengthItem] = Field(max_length=3)
    gaps: list[GapItem] = Field(max_length=3)
    recommendation: ApplicationRecommendation
    rewrite_suggestions: list[RewriteSuggestion] = Field(default_factory=list)
    interview_questions: list[InterviewQuestion] = Field(
        min_length=5,
        max_length=5,
    )
    limitations: list[str]
    validation: ValidationResult
    knowledge: ReportKnowledgeSection | None = None

    @model_validator(mode="after")
    def validate_schema_knowledge_contract(self) -> AnalysisReport:
        if self.schema_version == "1.0" and self.knowledge is not None:
            raise ValueError("AnalysisReport 1.0 cannot contain knowledge metadata")
        if self.schema_version == "1.1" and self.knowledge is None:
            raise ValueError("AnalysisReport 1.1 requires a knowledge section")
        return self
