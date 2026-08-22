"""Shared Pydantic configuration, enums, and workflow boundary models."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

NonEmptyStr = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]


class StrictModel(BaseModel):
    """Base class for all persisted and exchanged domain contracts."""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        validate_default=True,
        ser_json_bytes="base64",
        val_json_bytes="base64",
    )


class LanguageCode(StrEnum):
    ZH = "zh"
    EN = "en"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class DocumentSourceKind(StrEnum):
    PDF = "pdf"
    DOCX = "docx"
    TXT = "txt"
    PASTED_TEXT = "pasted_text"


class EvidenceSourceType(StrEnum):
    RESUME = "resume"
    JOB_DESCRIPTION = "job_description"


class EvidenceKind(StrEnum):
    DIRECT = "direct"
    CONTEXTUAL = "contextual"


class RequirementType(StrEnum):
    RESPONSIBILITY = "responsibility"
    MUST_HAVE = "must_have"
    PREFERRED = "preferred"
    IMPLICIT = "implicit"


class RequirementCategory(StrEnum):
    ELIGIBILITY = "eligibility"
    TECHNICAL_SKILL = "technical_skill"
    EXPERIENCE_PROJECT = "experience_project"
    DOMAIN_BUSINESS = "domain_business"
    EDUCATION_LANGUAGE = "education_language"
    COMMUNICATION_KEYWORD = "communication_keyword"


class Importance(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class HardConditionKind(StrEnum):
    NONE = "none"
    WORK_AUTHORIZATION = "work_authorization"
    DEGREE_LEVEL = "degree_level"
    GRADUATION_WINDOW = "graduation_window"
    LANGUAGE_MINIMUM = "language_minimum"
    EXPERIENCE_MINIMUM = "experience_minimum"
    REQUIRED_CERTIFICATE = "required_certificate"
    LOCATION_AVAILABILITY = "location_availability"


class MatchStatus(StrEnum):
    MATCHED = "matched"
    PARTIAL_MATCH = "partial"
    NOT_MATCHED = "not_matched"
    UNKNOWN = "unknown"


class ConfidenceLevel(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class GapRemediability(StrEnum):
    WORDING = "wording"
    EVIDENCE_NEEDED = "evidence_needed"
    LEARNING_PRACTICE = "learning_practice"
    HARD_TO_FIX_SHORT_TERM = "hard_to_fix_short_term"


class RecommendationLevel(StrEnum):
    PRIORITY_APPLY = "priority_apply"
    OPTIMIZE_THEN_APPLY = "optimize_then_apply"
    TRY_APPLY = "try_apply"
    NOT_PRIORITY = "not_priority"


class ValidationSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class WorkflowStage(StrEnum):
    IDLE = "IDLE"
    VALIDATING_INPUT = "VALIDATING_INPUT"
    PARSING_RESUME = "PARSING_RESUME"
    EXTRACTING_RESUME = "EXTRACTING_RESUME"
    EXTRACTING_JOB = "EXTRACTING_JOB"
    RETRIEVING_KNOWLEDGE = "RETRIEVING_KNOWLEDGE"
    MATCHING_EVIDENCE = "MATCHING_EVIDENCE"
    VALIDATING_MATCHES = "VALIDATING_MATCHES"
    SCORING = "SCORING"
    GENERATING_ADVICE = "GENERATING_ADVICE"
    VALIDATING_REPORT = "VALIDATING_REPORT"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class SkillType(StrEnum):
    LANGUAGE = "language"
    FRAMEWORK = "framework"
    TOOL = "tool"
    METHOD = "method"
    DOMAIN = "domain"
    SOFT_SKILL = "soft_skill"
    OTHER = "other"


class UploadedDocumentInput(StrictModel):
    """Ephemeral upload boundary; intentionally excluded from reports."""

    filename: NonEmptyStr
    media_type: NonEmptyStr
    content: bytes
    size_bytes: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_size(self) -> UploadedDocumentInput:
        if len(self.content) != self.size_bytes:
            raise ValueError("size_bytes must equal the uploaded content length")
        return self


class AnalysisRequest(StrictModel):
    request_id: NonEmptyStr
    resume_file: UploadedDocumentInput | None = None
    pasted_resume_text: str | None = None
    job_description_text: str = Field(min_length=1)
    job_title: str | None = None
    company_name: str | None = None
    llm_mode: Literal["provider", "mock"]

    @model_validator(mode="after")
    def require_resume_input(self) -> AnalysisRequest:
        has_file = self.resume_file is not None
        has_text = bool(self.pasted_resume_text and self.pasted_resume_text.strip())
        if not has_file and not has_text:
            raise ValueError("A resume file or pasted resume text is required")
        return self


class ProgressEvent(StrictModel):
    request_id: NonEmptyStr
    stage: WorkflowStage
    progress_percent: int = Field(ge=0, le=100)
    message_key: NonEmptyStr
    recoverable: bool
