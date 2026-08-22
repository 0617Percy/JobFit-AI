"""Database-independent contracts for reviewed job knowledge."""

from __future__ import annotations

import re
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Self

from pydantic import (
    AnyHttpUrl,
    AwareDatetime,
    ConfigDict,
    Field,
    StringConstraints,
    field_serializer,
    field_validator,
    model_validator,
)

from jobfit.models.common import (
    Importance,
    NonEmptyStr,
    RequirementType,
    StrictModel,
)

KnowledgeVersion = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        pattern=r"^\d{4}\.\d{2}\.\d+$",
    ),
]
KnowledgeVersionId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        pattern=r"^kbv-[a-z0-9][a-z0-9-]*$",
    ),
]
CitationId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        pattern=r"^cite-[0-9a-f]{16}$",
    ),
]
SourceId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        pattern=r"^ks-[a-z0-9][a-z0-9-]*$",
    ),
]
ChunkId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        pattern=r"^kc-[a-z0-9][a-z0-9-]*$",
    ),
]
RoleProfileId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        pattern=r"^rp-[a-z0-9][a-z0-9-]*$",
    ),
]
KnowledgeRequirementId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        pattern=r"^kr-[a-z0-9][a-z0-9-]*$",
    ),
]
EvidencePatternId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        pattern=r"^ep-[a-z0-9][a-z0-9-]*$",
    ),
]
KnowledgeQuestionId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        pattern=r"^iq-[a-z0-9][a-z0-9-]*$",
    ),
]
KnowledgeCode = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        pattern=r"^[a-z0-9][a-z0-9_-]*$",
    ),
]
Sha256Hex = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_lower=True,
        pattern=r"^[0-9a-f]{64}$",
    ),
]
RelevanceScore = Annotated[
    Decimal,
    Field(ge=Decimal("0"), le=Decimal("1"), max_digits=5, decimal_places=4),
]


class KnowledgeVersionStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    RETIRED = "retired"


class KnowledgeReviewStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class KnowledgeRetrievalStatus(StrEnum):
    DISABLED = "disabled"
    AVAILABLE = "available"
    NO_MATCH = "no_match"
    UNAVAILABLE = "unavailable"
    AMBIGUOUS = "ambiguous"


class KnowledgeSearchMode(StrEnum):
    AUTO = "auto"
    FTS5 = "fts5"
    KEYWORD = "keyword"


class KnowledgeSearchBackend(StrEnum):
    FTS5 = "fts5"
    KEYWORD_FALLBACK = "keyword_fallback"
    DISABLED = "disabled"


class KnowledgeSearchCapabilityStatus(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    PROBE_FAILED = "probe_failed"
    DISABLED = "disabled"


class KnowledgeSourceType(StrEnum):
    OFFICIAL_JOB_DESCRIPTION = "official_job_description"
    PUBLIC_RECRUITMENT_PAGE = "public_recruitment_page"
    EXPERT_DEFINITION = "expert_definition"
    INTERNAL_TEMPLATE = "internal_template"
    RESEARCH_REPORT = "research_report"


class ReliabilityLevel(StrEnum):
    PRIMARY = "primary"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class EvidencePatternStrength(StrEnum):
    STRONG = "strong"
    MEDIUM = "medium"
    WEAK = "weak"


class KnowledgeQuestionType(StrEnum):
    PROJECT_DEEP_DIVE = "project_deep_dive"
    TECHNICAL = "technical"
    BUSINESS_SCENARIO = "business_scenario"
    GAP_VALIDATION = "gap_validation"
    COLLABORATION_MOTIVATION = "collaboration_motivation"


class InterviewDifficulty(StrEnum):
    BASIC = "basic"
    MEDIUM = "medium"
    ADVANCED = "advanced"


class KnowledgeWarningCode(StrEnum):
    DISABLED = "knowledge_disabled"
    DB_UNAVAILABLE = "knowledge_db_unavailable"
    VERSION_UNAVAILABLE = "knowledge_version_unavailable"
    NO_ROLE_MATCH = "knowledge_no_role_match"
    AMBIGUOUS_ROLE = "knowledge_ambiguous_role"
    RETRIEVAL_FAILED = "knowledge_retrieval_failed"
    SEARCH_FALLBACK = "knowledge_search_fallback"
    BUDGET_TRUNCATED = "knowledge_budget_truncated"
    CITATION_INVALID = "knowledge_citation_invalid"


class _KnowledgeModel(StrictModel):
    """Immutable public contract that never exposes persistence objects."""

    model_config = ConfigDict(frozen=True)


class KnowledgeBaseVersionInfo(_KnowledgeModel):
    id: KnowledgeVersionId
    version: KnowledgeVersion
    name: NonEmptyStr
    description: str | None = Field(default=None, max_length=500)
    status: KnowledgeVersionStatus
    content_hash: Sha256Hex
    published_at: AwareDatetime | None = None
    created_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def require_publication_time(self) -> Self:
        if (
            self.status
            in {KnowledgeVersionStatus.PUBLISHED, KnowledgeVersionStatus.RETIRED}
            and self.published_at is None
        ):
            raise ValueError("published_at is required for published or retired versions")
        return self


class KnowledgeCitation(_KnowledgeModel):
    """A source reference for role knowledge, never candidate evidence."""

    citation_id: CitationId
    source_id: SourceId
    chunk_id: ChunkId | None = None
    source_title: NonEmptyStr
    source_type: KnowledgeSourceType
    publisher: NonEmptyStr | None = None
    source_url: AnyHttpUrl | None = None
    section: str | None = Field(default=None, max_length=120)
    knowledge_version_id: KnowledgeVersionId
    reliability_level: ReliabilityLevel = ReliabilityLevel.MEDIUM
    excerpt: str | None = Field(default=None, max_length=240)
    source_checksum: Sha256Hex


class RetrievedRoleProfile(_KnowledgeModel):
    role_profile_id: RoleProfileId
    job_family_code: KnowledgeCode
    code: KnowledgeCode
    name: NonEmptyStr
    seniority: NonEmptyStr
    industry: NonEmptyStr | None = None
    description: str = Field(min_length=1, max_length=1_000)
    relevance_score: RelevanceScore
    matched_terms: list[NonEmptyStr] = Field(min_length=1, max_length=30)
    matched_fields: list[NonEmptyStr] = Field(
        default_factory=list,
        max_length=20,
    )
    citation_ids: list[CitationId] = Field(min_length=1, max_length=20)

    @field_serializer("relevance_score")
    def serialize_relevance_score(self, value: Decimal) -> str:
        return format(value, "f")


class RetrievedRequirement(_KnowledgeModel):
    knowledge_requirement_id: KnowledgeRequirementId
    role_profile_id: RoleProfileId
    competency_dimension_code: KnowledgeCode
    title: NonEmptyStr
    description: str = Field(min_length=1, max_length=1_000)
    requirement_type: RequirementType
    importance: Importance
    is_common_hard_blocker: bool = False
    expected_evidence: list[NonEmptyStr] = Field(
        default_factory=list,
        max_length=20,
    )
    weak_evidence: list[NonEmptyStr] = Field(default_factory=list, max_length=20)
    negative_signals: list[NonEmptyStr] = Field(
        default_factory=list,
        max_length=20,
    )
    relevance_score: RelevanceScore
    matched_terms: list[NonEmptyStr] = Field(
        default_factory=list,
        max_length=30,
    )
    matched_fields: list[NonEmptyStr] = Field(
        default_factory=list,
        max_length=20,
    )
    citation_ids: list[CitationId] = Field(min_length=1, max_length=20)

    @field_serializer("relevance_score")
    def serialize_relevance_score(self, value: Decimal) -> str:
        return format(value, "f")


class RetrievedEvidencePattern(_KnowledgeModel):
    evidence_pattern_id: EvidencePatternId
    knowledge_requirement_id: KnowledgeRequirementId
    evidence_type: KnowledgeCode
    description: str = Field(min_length=1, max_length=1_000)
    strength: EvidencePatternStrength
    positive_example: str | None = Field(default=None, max_length=500)
    weak_example: str | None = Field(default=None, max_length=500)
    negative_example: str | None = Field(default=None, max_length=500)
    citation_ids: list[CitationId] = Field(min_length=1, max_length=20)


class RetrievedInterviewQuestion(_KnowledgeModel):
    knowledge_question_id: KnowledgeQuestionId
    role_profile_id: RoleProfileId
    competency_dimension_code: KnowledgeCode
    question: str = Field(min_length=1, max_length=500)
    question_type: KnowledgeQuestionType
    expected_points: list[NonEmptyStr] = Field(min_length=1, max_length=10)
    follow_up_questions: list[NonEmptyStr] = Field(
        default_factory=list,
        max_length=5,
    )
    difficulty: InterviewDifficulty
    relevance_score: RelevanceScore
    matched_terms: list[NonEmptyStr] = Field(
        default_factory=list,
        max_length=30,
    )
    matched_fields: list[NonEmptyStr] = Field(
        default_factory=list,
        max_length=20,
    )
    citation_ids: list[CitationId] = Field(min_length=1, max_length=20)

    @field_serializer("relevance_score")
    def serialize_relevance_score(self, value: Decimal) -> str:
        return format(value, "f")


_UNSAFE_WARNING_PATTERNS = (
    re.compile(r"(?i)\b[A-Z]:[\\/](?:Users|Documents and Settings)[\\/]"),
    re.compile(r"(?i)(?:^|[\s\"'])/(?:Users|home)/[^/\s]+/"),
    re.compile(r"(?i)\b(?:select\s+.+\s+from|insert\s+into|delete\s+from)\b"),
    re.compile(r"(?i)\bupdate\s+\S+\s+set\b"),
    re.compile(r"(?i)(?:sk-|ghp_|github_pat_|AKIA)[A-Za-z0-9_-]*"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)


class KnowledgeWarning(_KnowledgeModel):
    code: KnowledgeWarningCode
    message: str = Field(min_length=1, max_length=300)
    recoverable: bool = True
    details: dict[str, str] | None = None

    @field_validator("message")
    @classmethod
    def reject_internal_details(cls, value: str) -> str:
        if any(pattern.search(value) for pattern in _UNSAFE_WARNING_PATTERNS):
            raise ValueError("warning message contains unsafe internal details")
        return value


class KnowledgeSearchCapabilities(_KnowledgeModel):
    mode: KnowledgeSearchBackend = KnowledgeSearchBackend.DISABLED
    fts5_available: bool = False
    status: KnowledgeSearchCapabilityStatus = (
        KnowledgeSearchCapabilityStatus.DISABLED
    )
    keyword_fallback_available: bool = False
    search_index_version: str | None = Field(
        default=None,
        pattern=r"^\d+$",
    )

    @model_validator(mode="before")
    @classmethod
    def infer_legacy_capability_defaults(cls, value: object) -> object:
        if not isinstance(value, dict) or "status" in value:
            return value
        updated = dict(value)
        mode = updated.get("mode", KnowledgeSearchBackend.DISABLED)
        if mode != KnowledgeSearchBackend.DISABLED:
            updated["status"] = KnowledgeSearchCapabilityStatus.AVAILABLE
        if mode == KnowledgeSearchBackend.KEYWORD_FALLBACK:
            updated.setdefault("keyword_fallback_available", True)
        return updated

    @model_validator(mode="after")
    def ensure_capability_consistency(self) -> Self:
        if self.mode is KnowledgeSearchBackend.FTS5 and not self.fts5_available:
            raise ValueError("FTS5 mode requires fts5_available")
        if self.mode is KnowledgeSearchBackend.DISABLED and self.fts5_available:
            raise ValueError("disabled search cannot expose FTS5 availability")
        if self.status is KnowledgeSearchCapabilityStatus.DISABLED and (
            self.mode is not KnowledgeSearchBackend.DISABLED
            or self.keyword_fallback_available
        ):
            raise ValueError("disabled capability cannot expose a search backend")
        if (
            self.status is KnowledgeSearchCapabilityStatus.AVAILABLE
            and self.mode is KnowledgeSearchBackend.DISABLED
        ):
            raise ValueError("available capability requires a search backend")
        return self


def _require_unique(values: list[str], *, field_name: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{field_name} must not contain duplicates")


def _is_stably_ranked(
    items: list[RetrievedRoleProfile] | list[RetrievedRequirement],
) -> bool:
    keys = [(-item.relevance_score, item.role_profile_id) for item in items]
    if items and isinstance(items[0], RetrievedRequirement):
        keys = [
            (-item.relevance_score, item.knowledge_requirement_id)
            for item in items
        ]
    return keys == sorted(keys)


class KnowledgeContext(_KnowledgeModel):
    """Bounded, reviewed reference knowledge supplied to future workflow stages."""

    status: KnowledgeRetrievalStatus = KnowledgeRetrievalStatus.DISABLED
    version: KnowledgeBaseVersionInfo | None = None
    inferred_role_profiles: list[RetrievedRoleProfile] = Field(
        default_factory=list,
        max_length=3,
    )
    requirements: list[RetrievedRequirement] = Field(
        default_factory=list,
        max_length=20,
    )
    evidence_patterns: list[RetrievedEvidencePattern] = Field(
        default_factory=list,
        max_length=30,
    )
    interview_questions: list[RetrievedInterviewQuestion] = Field(
        default_factory=list,
        max_length=15,
    )
    citations: list[KnowledgeCitation] = Field(default_factory=list, max_length=30)
    warnings: list[KnowledgeWarning] = Field(default_factory=list, max_length=20)
    capabilities: KnowledgeSearchCapabilities = Field(
        default_factory=KnowledgeSearchCapabilities
    )
    retrieval_strategy_version: str = Field(
        default="1.0",
        pattern=r"^\d+\.\d+$",
    )

    @model_validator(mode="after")
    def enforce_context_invariants(self) -> Self:
        self._validate_status_payload()
        self._validate_identity_sets()
        self._validate_citation_references()
        self._validate_stable_order()
        return self

    def _validate_status_payload(self) -> None:
        content = (
            self.inferred_role_profiles,
            self.requirements,
            self.evidence_patterns,
            self.interview_questions,
            self.citations,
        )
        has_content = any(content)
        if self.status is KnowledgeRetrievalStatus.AVAILABLE:
            if (
                self.version is None
                or self.version.status is not KnowledgeVersionStatus.PUBLISHED
                or not self.inferred_role_profiles
            ):
                raise ValueError(
                    "available knowledge requires a published version and role"
                )
            if self.capabilities.mode is KnowledgeSearchBackend.DISABLED:
                raise ValueError("available knowledge requires an active search backend")
            return

        if self.status is KnowledgeRetrievalStatus.AMBIGUOUS:
            if (
                self.version is None
                or self.version.status is not KnowledgeVersionStatus.PUBLISHED
                or len(self.inferred_role_profiles) < 2
            ):
                raise ValueError(
                    "ambiguous knowledge requires a published version and roles"
                )
            if (
                self.requirements
                or self.evidence_patterns
                or self.interview_questions
            ):
                raise ValueError("ambiguous knowledge cannot include retrieved details")
            return

        if has_content:
            raise ValueError("non-available knowledge cannot include retrieved content")
        if self.status is KnowledgeRetrievalStatus.DISABLED:
            if self.version is not None:
                raise ValueError("disabled knowledge cannot include a version")
            if self.capabilities.mode is not KnowledgeSearchBackend.DISABLED:
                raise ValueError("disabled knowledge requires disabled capabilities")

    def _validate_identity_sets(self) -> None:
        identity_groups = (
            (
                [item.role_profile_id for item in self.inferred_role_profiles],
                "inferred_role_profiles",
            ),
            (
                [item.knowledge_requirement_id for item in self.requirements],
                "requirements",
            ),
            (
                [item.evidence_pattern_id for item in self.evidence_patterns],
                "evidence_patterns",
            ),
            (
                [item.knowledge_question_id for item in self.interview_questions],
                "interview_questions",
            ),
            ([item.citation_id for item in self.citations], "citations"),
        )
        for identities, name in identity_groups:
            _require_unique(identities, field_name=name)

    def _validate_citation_references(self) -> None:
        known = {citation.citation_id for citation in self.citations}
        referenced: set[str] = set()
        for item in (
            *self.inferred_role_profiles,
            *self.requirements,
            *self.evidence_patterns,
            *self.interview_questions,
        ):
            _require_unique(item.citation_ids, field_name="citation_ids")
            if item.citation_ids != sorted(item.citation_ids):
                raise ValueError("citation_ids must use stable citation order")
            referenced.update(item.citation_ids)
        unknown = referenced - known
        if unknown:
            raise ValueError("knowledge object references an unknown citation")

    def _validate_stable_order(self) -> None:
        if not _is_stably_ranked(self.inferred_role_profiles):
            raise ValueError("role profiles must use stable relevance order")
        if not _is_stably_ranked(self.requirements):
            raise ValueError("requirements must use stable relevance order")
        if self.citations != sorted(
            self.citations,
            key=lambda citation: citation.citation_id,
        ):
            raise ValueError("citations must use stable citation order")
        if self.evidence_patterns != sorted(
            self.evidence_patterns,
            key=lambda pattern: pattern.evidence_pattern_id,
        ):
            raise ValueError("evidence patterns must use stable ID order")
        question_keys = [
            (-question.relevance_score, question.knowledge_question_id)
            for question in self.interview_questions
        ]
        if question_keys != sorted(question_keys):
            raise ValueError("interview questions must use stable relevance order")


class KnowledgeRetrievalResult(_KnowledgeModel):
    """Retriever output plus privacy-safe deterministic query trace."""

    context: KnowledgeContext
    query_fingerprint: Sha256Hex
    normalized_job_title: NonEmptyStr
    query_terms: list[NonEmptyStr] = Field(default_factory=list, max_length=50)
    candidate_role_ids: list[RoleProfileId] = Field(
        default_factory=list,
        max_length=20,
    )

    @model_validator(mode="after")
    def require_unique_trace_values(self) -> Self:
        _require_unique(self.query_terms, field_name="query_terms")
        _require_unique(self.candidate_role_ids, field_name="candidate_role_ids")
        return self


__all__ = [
    "EvidencePatternStrength",
    "InterviewDifficulty",
    "KnowledgeBaseVersionInfo",
    "KnowledgeCitation",
    "KnowledgeContext",
    "KnowledgeQuestionType",
    "KnowledgeRetrievalResult",
    "KnowledgeRetrievalStatus",
    "KnowledgeReviewStatus",
    "KnowledgeSearchBackend",
    "KnowledgeSearchCapabilityStatus",
    "KnowledgeSearchCapabilities",
    "KnowledgeSearchMode",
    "KnowledgeSourceType",
    "KnowledgeVersionStatus",
    "KnowledgeWarning",
    "KnowledgeWarningCode",
    "ReliabilityLevel",
    "RetrievedEvidencePattern",
    "RetrievedInterviewQuestion",
    "RetrievedRequirement",
    "RetrievedRoleProfile",
]
