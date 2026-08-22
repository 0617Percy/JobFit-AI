"""Strict prompt DTOs and non-decision intermediate semantic objects."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import Field, JsonValue, model_validator

from jobfit.models.common import Importance, NonEmptyStr, StrictModel
from jobfit.models.v2 import (
    AbilityStatus,
    CandidateStatus,
    ClarityLevel,
    CriticalStatus,
    EvidenceSourceOrigin,
    EvidenceStatus,
    JobFamily,
    MatchCoverage,
    ParseCompleteness,
    PersonalContribution,
    Relevance,
    RequirementExplicitness,
    RequirementSource,
    RequirementType,
    SupportType,
)
from jobfit.semantic.v2.advisory_contracts import (
    P06ActionInput,
    P06ActionOutput,
    P07InterviewInput,
    P07InterviewOutput,
    P08ReportInput,
    P08ReportOutput,
)


class SemanticAmbiguity(StrictModel):
    ambiguity_id: NonEmptyStr
    message: NonEmptyStr
    object_ids: list[NonEmptyStr] = Field(default_factory=list)


class SemanticSegmentInput(StrictModel):
    segment_id: NonEmptyStr
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)
    text: str = Field(min_length=1)
    page_number: int | None = Field(default=None, ge=1)
    section_hint: str | None = None


class SemanticDocumentInput(StrictModel):
    document_id: NonEmptyStr
    language: NonEmptyStr
    normalized_text: str = Field(min_length=1)
    segments: list[SemanticSegmentInput] = Field(min_length=1)


class P01ResumeInput(StrictModel):
    analysis_id: NonEmptyStr
    resume_version_id: NonEmptyStr
    document: SemanticDocumentInput


class P02JobInput(StrictModel):
    analysis_id: NonEmptyStr
    jd_snapshot_id: NonEmptyStr
    document: SemanticDocumentInput


class ResumeCollectionItemDraft(StrictModel):
    item_id: NonEmptyStr
    label: NonEmptyStr
    details: dict[str, JsonValue] = Field(default_factory=dict)
    evidence_local_ids: list[NonEmptyStr] = Field(min_length=1)


class P01EvidenceDraft(StrictModel):
    local_id: NonEmptyStr
    source_type: NonEmptyStr
    quote: str = Field(min_length=1)
    document_id: NonEmptyStr
    segment_id: NonEmptyStr
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_range(self) -> P01EvidenceDraft:
        if self.end_char <= self.start_char:
            raise ValueError("Evidence end offset must exceed start offset.")
        if self.end_char - self.start_char != len(self.quote):
            raise ValueError("Evidence offsets must match the exact quote length.")
        return self


class P01EvidenceLLMDraft(StrictModel):
    """P01 model transport without deterministic character offsets."""

    local_id: NonEmptyStr
    source_type: NonEmptyStr
    quote: str = Field(min_length=1)
    document_id: NonEmptyStr
    segment_id: NonEmptyStr


class P01ResumeLLMOutput(StrictModel):
    """Strict P01 response shape supplied to the language model."""

    candidate_profile: CandidateProfileDraft
    education: list[ResumeCollectionItemDraft]
    skills: list[ResumeCollectionItemDraft]
    projects: list[ResumeCollectionItemDraft]
    internships: list[ResumeCollectionItemDraft]
    work_experience: list[ResumeCollectionItemDraft]
    research: list[ResumeCollectionItemDraft]
    competitions: list[ResumeCollectionItemDraft]
    campus_experience: list[ResumeCollectionItemDraft]
    achievements: list[ResumeCollectionItemDraft]
    evidence_items: list[P01EvidenceLLMDraft]
    ambiguities: list[SemanticAmbiguity] = Field(default_factory=list)
    parse_completeness: ParseCompleteness


class P01ResumeOutput(StrictModel):
    candidate_profile: CandidateProfileDraft
    education: list[ResumeCollectionItemDraft]
    skills: list[ResumeCollectionItemDraft]
    projects: list[ResumeCollectionItemDraft]
    internships: list[ResumeCollectionItemDraft]
    work_experience: list[ResumeCollectionItemDraft]
    research: list[ResumeCollectionItemDraft]
    competitions: list[ResumeCollectionItemDraft]
    campus_experience: list[ResumeCollectionItemDraft]
    achievements: list[ResumeCollectionItemDraft]
    evidence_items: list[P01EvidenceDraft]
    ambiguities: list[SemanticAmbiguity] = Field(default_factory=list)
    parse_completeness: ParseCompleteness


class CandidateEvidence(StrictModel):
    evidence_id: NonEmptyStr
    resume_version_id: NonEmptyStr
    source_type: NonEmptyStr
    quote: str = Field(min_length=1)
    document_id: NonEmptyStr
    segment_id: NonEmptyStr
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)


class CandidateProfileDraft(StrictModel):
    name: str | None = None
    education_level: str | None = None
    current_status: CandidateStatus = CandidateStatus.UNKNOWN
    graduation_date: str | None = None
    years_of_full_time_experience: Decimal | None = Field(default=None, ge=0)


class JDSourceItemDraft(StrictModel):
    local_id: NonEmptyStr
    text: str = Field(min_length=1)
    document_id: NonEmptyStr
    segment_id: NonEmptyStr
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_range(self) -> JDSourceItemDraft:
        if self.end_char <= self.start_char:
            raise ValueError("JD source end offset must exceed start offset.")
        if self.end_char - self.start_char != len(self.text):
            raise ValueError("JD source offsets must match exact text length.")
        return self


class JDSourceItemLLMDraft(StrictModel):
    """P02 model transport without deterministic character offsets."""

    local_id: NonEmptyStr
    text: str = Field(min_length=1)
    document_id: NonEmptyStr
    segment_id: NonEmptyStr


class P02JobLLMOutput(StrictModel):
    """Strict P02 response shape supplied to the language model."""

    job_title: NonEmptyStr
    company: str | None = None
    location: str | None = None
    employment_type: str | None = None
    job_family: JobFamily
    responsibilities: list[JDSourceItemLLMDraft]
    raw_requirements: list[JDSourceItemLLMDraft]
    explicit_constraints: list[JDSourceItemLLMDraft] = Field(default_factory=list)
    seniority_signals: list[JDSourceItemLLMDraft] = Field(default_factory=list)
    ambiguities: list[SemanticAmbiguity] = Field(default_factory=list)
    parse_completeness: ParseCompleteness


class P02JobOutput(StrictModel):
    job_title: NonEmptyStr
    company: str | None = None
    location: str | None = None
    employment_type: str | None = None
    job_family: JobFamily
    responsibilities: list[JDSourceItemDraft]
    raw_requirements: list[JDSourceItemDraft]
    explicit_constraints: list[JDSourceItemDraft] = Field(default_factory=list)
    seniority_signals: list[JDSourceItemDraft] = Field(default_factory=list)
    ambiguities: list[SemanticAmbiguity] = Field(default_factory=list)
    parse_completeness: ParseCompleteness


class JDSourceItem(StrictModel):
    object_id: NonEmptyStr
    text: str = Field(min_length=1)
    document_id: NonEmptyStr
    segment_id: NonEmptyStr
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)


class ExplicitRequirementType(StrEnum):
    HARD = "hard"
    CORE = "core"
    SUPPORTING = "supporting"
    PREFERRED = "preferred"


class RequirementCriticalCandidate(StrEnum):
    CANDIDATE = "candidate"
    NOT_CRITICAL = "not_critical"


class P03RequirementDraft(StrictModel):
    local_id: NonEmptyStr
    raw_requirement_ids: list[NonEmptyStr] = Field(min_length=1)
    normalized_capability: NonEmptyStr
    requirement_type: ExplicitRequirementType
    importance: Importance
    critical_status: RequirementCriticalCandidate = (
        RequirementCriticalCandidate.NOT_CRITICAL
    )
    classification_reason: NonEmptyStr


class P03RequirementOutput(StrictModel):
    requirements: list[P03RequirementDraft] = Field(min_length=1)
    warnings: list[NonEmptyStr] = Field(default_factory=list)


class P03RequirementInput(StrictModel):
    analysis_id: NonEmptyStr
    jd_snapshot_id: NonEmptyStr
    job_title: NonEmptyStr
    job_family: JobFamily
    responsibilities: list[JDSourceItem]
    raw_requirements: list[JDSourceItem] = Field(min_length=1)
    explicit_constraints: list[JDSourceItem] = Field(default_factory=list)
    seniority_signals: list[JDSourceItem] = Field(default_factory=list)


class P04EvidenceFeatureDraft(StrictModel):
    evidence_id: NonEmptyStr
    normalized_capabilities: list[NonEmptyStr] = Field(default_factory=list)
    personal_contribution: PersonalContribution
    task_clarity: ClarityLevel
    method_tool_clarity: ClarityLevel
    result_clarity: ClarityLevel
    verification_strength: ClarityLevel
    practical_use: ClarityLevel
    ambiguity: bool = False

    @model_validator(mode="after")
    def validate_capabilities(self) -> P04EvidenceFeatureDraft:
        if len(self.normalized_capabilities) != len(
            set(self.normalized_capabilities)
        ):
            raise ValueError("P04 normalized capabilities must be unique.")
        return self


class P04EvidenceOutput(StrictModel):
    evidence: list[P04EvidenceFeatureDraft] = Field(min_length=1)
    warnings: list[NonEmptyStr] = Field(default_factory=list)


class P04EvidenceInput(StrictModel):
    analysis_id: NonEmptyStr
    resume_version_id: NonEmptyStr
    candidate_evidence: list[CandidateEvidence] = Field(min_length=1)


class P05MatchedEvidenceDraft(StrictModel):
    evidence_id: NonEmptyStr
    relevance: Relevance
    support_type: SupportType


class P05RequirementMatchDraft(StrictModel):
    requirement_id: NonEmptyStr
    matched_evidence: list[P05MatchedEvidenceDraft]
    coverage: MatchCoverage
    evidence_status: EvidenceStatus
    ability_status: AbilityStatus
    reason: NonEmptyStr

    @model_validator(mode="after")
    def validate_relation_ids(self) -> P05RequirementMatchDraft:
        evidence_ids = [item.evidence_id for item in self.matched_evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("P05 matched evidence IDs must be unique.")
        return self


class P05MatchOutput(StrictModel):
    matches: list[P05RequirementMatchDraft] = Field(min_length=1)
    warnings: list[NonEmptyStr] = Field(default_factory=list)


class P05RequirementInput(StrictModel):
    requirement_id: NonEmptyStr
    jd_snapshot_id: NonEmptyStr
    raw_requirement_ids: list[NonEmptyStr]
    raw_text: str | None = None
    normalized_capability: NonEmptyStr
    requirement_type: RequirementType
    importance: Importance
    explicitness: RequirementExplicitness
    source: RequirementSource
    critical_status: CriticalStatus
    classification_reason: str | None = None


class P05EvidenceInput(StrictModel):
    evidence_id: NonEmptyStr
    resume_version_id: NonEmptyStr
    source_origin: EvidenceSourceOrigin
    source_type: NonEmptyStr
    source_record_id: NonEmptyStr | None = None
    source_text: str = Field(min_length=1)
    normalized_capabilities: list[NonEmptyStr]
    personal_contribution: PersonalContribution
    task_clarity: ClarityLevel
    method_tool_clarity: ClarityLevel
    result_clarity: ClarityLevel
    verification_strength: ClarityLevel
    practical_use: ClarityLevel
    ambiguity: bool
    document_id: NonEmptyStr
    segment_id: NonEmptyStr
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)


class P05MatchInput(StrictModel):
    analysis_id: NonEmptyStr
    jd_snapshot_id: NonEmptyStr
    resume_version_id: NonEmptyStr
    requirements: list[P05RequirementInput] = Field(min_length=1)
    candidate_evidence: list[P05EvidenceInput] = Field(min_length=1)


PROMPT_INPUT_MODELS = {
    "P01": P01ResumeInput,
    "P02": P02JobInput,
    "P03": P03RequirementInput,
    "P04": P04EvidenceInput,
    "P05": P05MatchInput,
    "P06": P06ActionInput,
    "P07": P07InterviewInput,
    "P08": P08ReportInput,
}
PROMPT_OUTPUT_MODELS = {
    "P01": P01ResumeLLMOutput,
    "P02": P02JobLLMOutput,
    "P03": P03RequirementOutput,
    "P04": P04EvidenceOutput,
    "P05": P05MatchOutput,
    "P06": P06ActionOutput,
    "P07": P07InterviewOutput,
    "P08": P08ReportOutput,
}
