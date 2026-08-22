"""Resume extraction and normalized resume profile contracts."""

from __future__ import annotations

from decimal import Decimal

from pydantic import Field, JsonValue, model_validator

from jobfit.models.common import (
    EvidenceKind,
    LanguageCode,
    NonEmptyStr,
    SkillType,
    StrictModel,
)


class BasicInfo(StrictModel):
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    target_title: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)


class ResumeBullet(StrictModel):
    bullet_id: NonEmptyStr
    text: str = Field(min_length=1)
    action_terms: list[str] = Field(default_factory=list)
    outcome_terms: list[str] = Field(default_factory=list)
    quantified_metrics: list[str] = Field(default_factory=list)
    evidence_ids: list[NonEmptyStr] = Field(min_length=1)


class EducationItem(StrictModel):
    education_id: NonEmptyStr
    institution: str | None = None
    degree: str | None = None
    major: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    coursework: list[str] = Field(default_factory=list)
    gpa_text: str | None = None
    raw_text: str = Field(min_length=1)
    evidence_ids: list[NonEmptyStr] = Field(min_length=1)


class ExperienceItem(StrictModel):
    experience_id: NonEmptyStr
    organization: str | None = None
    role: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    bullets: list[ResumeBullet] = Field(default_factory=list)
    raw_text: str = Field(min_length=1)
    evidence_ids: list[NonEmptyStr] = Field(min_length=1)


class ProjectItem(StrictModel):
    project_id: NonEmptyStr
    name: str | None = None
    role: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    technologies: list[str] = Field(default_factory=list)
    bullets: list[ResumeBullet] = Field(default_factory=list)
    raw_text: str = Field(min_length=1)
    evidence_ids: list[NonEmptyStr] = Field(min_length=1)


class SkillItem(StrictModel):
    skill_id: NonEmptyStr
    name: NonEmptyStr
    skill_type: SkillType
    proficiency_text: str | None = None
    evidence_ids: list[NonEmptyStr] = Field(min_length=1)


class AchievementItem(StrictModel):
    achievement_id: NonEmptyStr
    name: NonEmptyStr
    issuer: str | None = None
    date: str | None = None
    result_text: str | None = None
    evidence_ids: list[NonEmptyStr] = Field(min_length=1)


class CertificateItem(StrictModel):
    certificate_id: NonEmptyStr
    name: NonEmptyStr
    issuer: str | None = None
    date: str | None = None
    evidence_ids: list[NonEmptyStr] = Field(min_length=1)


class LanguageItem(StrictModel):
    language_id: NonEmptyStr
    language: NonEmptyStr
    proficiency_text: str | None = None
    evidence_ids: list[NonEmptyStr] = Field(min_length=1)


class ResumeFact(StrictModel):
    fact_id: NonEmptyStr
    fact_type: NonEmptyStr
    text: str = Field(min_length=1)
    evidence_ids: list[NonEmptyStr] = Field(min_length=1)


class ResumeProfile(StrictModel):
    resume_id: NonEmptyStr
    document_id: NonEmptyStr
    language: LanguageCode
    basic_info: BasicInfo = Field(default_factory=BasicInfo)
    education: list[EducationItem] = Field(default_factory=list)
    experiences: list[ExperienceItem] = Field(default_factory=list)
    projects: list[ProjectItem] = Field(default_factory=list)
    skills: list[SkillItem] = Field(default_factory=list)
    achievements: list[AchievementItem] = Field(default_factory=list)
    certificates: list[CertificateItem] = Field(default_factory=list)
    languages: list[LanguageItem] = Field(default_factory=list)
    additional_information: list[ResumeFact] = Field(default_factory=list)
    extraction_warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_item_ids(self) -> ResumeProfile:
        item_ids = [
            *(item.education_id for item in self.education),
            *(item.experience_id for item in self.experiences),
            *(item.project_id for item in self.projects),
            *(item.skill_id for item in self.skills),
            *(item.achievement_id for item in self.achievements),
            *(item.certificate_id for item in self.certificates),
            *(item.language_id for item in self.languages),
            *(item.fact_id for item in self.additional_information),
        ]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("Resume item IDs must be unique")
        return self


class EvidenceCandidate(StrictModel):
    """LLM-facing evidence candidate before deterministic IDs are assigned."""

    quote: str = Field(min_length=1)
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)
    page_number: int | None = Field(default=None, ge=1)
    evidence_kind: EvidenceKind
    confidence: Decimal = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_quote_range(self) -> EvidenceCandidate:
        if self.end_char <= self.start_char:
            raise ValueError("end_char must be greater than start_char")
        if self.end_char - self.start_char != len(self.quote):
            raise ValueError("Candidate offsets must match the quote length")
        return self


class ResumeFactDraft(StrictModel):
    """Provider-neutral fact candidate mapped to a final resume item by code."""

    fact_type: NonEmptyStr
    raw_text: str = Field(min_length=1)
    structured_fields: dict[str, JsonValue] = Field(default_factory=dict)
    evidence_candidates: list[EvidenceCandidate] = Field(min_length=1)


class ResumeExtractionDraft(StrictModel):
    language: LanguageCode = LanguageCode.UNKNOWN
    basic_info: dict[str, JsonValue] = Field(default_factory=dict)
    facts: list[ResumeFactDraft] = Field(default_factory=list)
    extraction_warnings: list[str] = Field(default_factory=list)
