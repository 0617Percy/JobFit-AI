"""Target knowledge-citation and twelve-section report contracts."""

from __future__ import annotations

from pydantic import Field, JsonValue, model_validator

from jobfit.models.common import NonEmptyStr
from jobfit.models.v2._base import ExtensibleDomainModel, require_unique
from jobfit.models.v2.enums import CitationUsage, JobFamily, Reliability


class KnowledgeCitation(ExtensibleDomainModel):
    citation_id: NonEmptyStr
    knowledge_version: NonEmptyStr
    source_id: NonEmptyStr
    role_family: JobFamily | None = None
    title: str | None = None
    source_type: str | None = None
    reliability: Reliability | None = None
    usage: CitationUsage
    supported_claim: str | None = None


class JobFitReport(ExtensibleDomainModel):
    report_id: NonEmptyStr
    analysis_id: NonEmptyStr
    summary: dict[str, JsonValue]
    job_profile: dict[str, JsonValue] | None = None
    resume_evidence_profile: dict[str, JsonValue] | None = None
    requirement_match: list[JsonValue] = Field(default_factory=list)
    score_explanation: dict[str, JsonValue] | None = None
    strengths_and_gaps: dict[str, JsonValue] | None = None
    hard_check: dict[str, JsonValue] | None = None
    resume_optimization: dict[str, JsonValue] | None = None
    build_recommendations: list[JsonValue] = Field(default_factory=list)
    application_strategy: dict[str, JsonValue]
    interview_preparation: list[JsonValue] = Field(default_factory=list)
    analysis_basis_and_limits: dict[str, JsonValue] | None = None

    @model_validator(mode="after")
    def validate_embedded_ids(self) -> JobFitReport:
        action_ids = [
            item.get("action_id")
            for item in self.build_recommendations
            if isinstance(item, dict) and isinstance(item.get("action_id"), str)
        ]
        question_ids = [
            item.get("question_id")
            for item in self.interview_preparation
            if isinstance(item, dict) and isinstance(item.get("question_id"), str)
        ]
        require_unique(action_ids, "build recommendation action_id")
        require_unique(question_ids, "interview question_id")
        return self
