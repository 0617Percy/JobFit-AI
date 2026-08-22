"""Target resume-version and candidate-evidence contracts."""

from __future__ import annotations

from decimal import Decimal

from pydantic import Field, JsonValue, model_validator

from jobfit.models.common import NonEmptyStr
from jobfit.models.v2._base import ExtensibleDomainModel, require_unique
from jobfit.models.v2.enums import (
    CandidateStatus,
    ClarityLevel,
    EvidenceLevel,
    EvidenceSourceOrigin,
    ParseCompleteness,
    PersonalContribution,
)


class CandidateProfile(ExtensibleDomainModel):
    name: str | None = None
    education_level: str | None = None
    current_status: CandidateStatus = CandidateStatus.UNKNOWN
    graduation_date: str | None = None
    years_of_full_time_experience: Decimal | None = Field(default=None, ge=0)


class Evidence(ExtensibleDomainModel):
    evidence_id: NonEmptyStr
    resume_version_id: NonEmptyStr | None = None
    source_origin: EvidenceSourceOrigin
    source_type: NonEmptyStr
    source_record_id: NonEmptyStr | None = None
    source_text: str = Field(min_length=1)
    normalized_capabilities: list[NonEmptyStr] = Field(default_factory=list)
    personal_contribution: PersonalContribution = PersonalContribution.NOT_APPLICABLE
    task_clarity: ClarityLevel = ClarityLevel.UNKNOWN
    method_tool_clarity: ClarityLevel = ClarityLevel.UNKNOWN
    result_clarity: ClarityLevel = ClarityLevel.UNKNOWN
    verification_strength: ClarityLevel = ClarityLevel.UNKNOWN
    practical_use: ClarityLevel = ClarityLevel.UNKNOWN
    evidence_level: EvidenceLevel
    ambiguity: bool = False
    document_id: NonEmptyStr | None = None
    segment_id: NonEmptyStr | None = None
    start_char: int | None = Field(default=None, ge=0)
    end_char: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_source_grounding(self) -> Evidence:
        if self.source_origin is EvidenceSourceOrigin.RESUME:
            required = {
                "resume_version_id": self.resume_version_id,
                "document_id": self.document_id,
                "segment_id": self.segment_id,
                "start_char": self.start_char,
                "end_char": self.end_char,
            }
            missing = [name for name, value in required.items() if value is None]
            if missing:
                raise ValueError(
                    "Resume evidence requires grounding fields: " + ", ".join(missing)
                )
        if (
            self.source_origin is EvidenceSourceOrigin.USER_CLARIFICATION
            and self.source_record_id is None
        ):
            raise ValueError("User clarification evidence requires source_record_id")
        if (self.start_char is None) != (self.end_char is None):
            raise ValueError("Evidence offsets must be provided together")
        if self.start_char is not None and self.end_char is not None:
            if self.end_char <= self.start_char:
                raise ValueError("Evidence end offset must exceed start offset")
            if self.end_char - self.start_char != len(self.source_text):
                raise ValueError("Evidence offsets must match source_text length")
        require_unique(self.normalized_capabilities, "normalized_capabilities")
        return self


class ResumeProfile(ExtensibleDomainModel):
    resume_version_id: NonEmptyStr
    candidate_profile: CandidateProfile
    education: list[JsonValue] = Field(default_factory=list)
    skills: list[JsonValue] = Field(default_factory=list)
    projects: list[JsonValue] = Field(default_factory=list)
    internships: list[JsonValue] = Field(default_factory=list)
    work_experience: list[JsonValue] = Field(default_factory=list)
    research: list[JsonValue] = Field(default_factory=list)
    competitions: list[JsonValue] = Field(default_factory=list)
    campus_experience: list[JsonValue] = Field(default_factory=list)
    achievements: list[JsonValue] = Field(default_factory=list)
    evidence_ids: list[NonEmptyStr]
    ambiguity_ids: list[NonEmptyStr] = Field(default_factory=list)
    parse_completeness: ParseCompleteness

    @model_validator(mode="after")
    def validate_identity_lists(self) -> ResumeProfile:
        require_unique(self.evidence_ids, "evidence_ids")
        require_unique(self.ambiguity_ids, "ambiguity_ids")
        return self
