"""Strict, database-independent contracts for versioned knowledge seeds."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Self

from pydantic import (
    AnyHttpUrl,
    AwareDatetime,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from jobfit.models.common import Importance, NonEmptyStr, RequirementType, StrictModel
from jobfit.models.knowledge import (
    EvidencePatternId,
    EvidencePatternStrength,
    InterviewDifficulty,
    KnowledgeCode,
    KnowledgeQuestionId,
    KnowledgeQuestionType,
    KnowledgeRequirementId,
    KnowledgeReviewStatus,
    KnowledgeSourceType,
    KnowledgeVersion,
    KnowledgeVersionId,
    KnowledgeVersionStatus,
    ReliabilityLevel,
    RoleProfileId,
    Sha256Hex,
    SourceId,
)

SEED_SCHEMA_VERSION = "1.0"
SEED_IMPORT_STRATEGY_VERSION = "1.0"

JobFamilyId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        pattern=r"^jf-[a-z0-9][a-z0-9-]*$",
    ),
]
CompetencyDimensionId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        pattern=r"^cd-[a-z0-9][a-z0-9-]*$",
    ),
]
ChunkSeedId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        pattern=r"^kc-[a-z0-9][a-z0-9-]*$",
    ),
]


class SeedImportMode(StrEnum):
    CREATE = "create"
    REPLACE_DRAFT = "replace_draft"


class SourceRoleRelationType(StrEnum):
    SUPPORTS = "supports"
    CONTRASTS = "contrasts"
    BACKGROUND = "background"


class _SeedModel(StrictModel):
    model_config = ConfigDict(frozen=True)


def _stable_strings(values: list[str]) -> list[str]:
    return sorted(dict.fromkeys(value.strip() for value in values))


class KnowledgeVersionSeed(_SeedModel):
    id: KnowledgeVersionId
    version: KnowledgeVersion
    name: NonEmptyStr
    description: str | None = Field(default=None, max_length=500)
    status: KnowledgeVersionStatus = KnowledgeVersionStatus.DRAFT

    @model_validator(mode="after")
    def require_draft(self) -> Self:
        if self.status is not KnowledgeVersionStatus.DRAFT:
            raise ValueError("seed knowledge version must be draft")
        return self


class JobFamilySeed(_SeedModel):
    id: JobFamilyId
    code: KnowledgeCode
    name: NonEmptyStr
    description: str = Field(min_length=1, max_length=1_000)
    aliases: list[NonEmptyStr] = Field(default_factory=list, max_length=30)
    knowledge_version_id: KnowledgeVersionId
    is_active: bool = True

    @field_validator("aliases")
    @classmethod
    def normalize_aliases(cls, value: list[str]) -> list[str]:
        return _stable_strings(value)


class RoleProfileSeed(_SeedModel):
    id: RoleProfileId
    job_family_id: JobFamilyId
    code: KnowledgeCode
    name: NonEmptyStr
    seniority: NonEmptyStr
    industry: NonEmptyStr | None = None
    description: str = Field(min_length=1, max_length=1_000)
    aliases: list[NonEmptyStr] = Field(default_factory=list, max_length=30)
    keywords: list[NonEmptyStr] = Field(default_factory=list, max_length=50)
    knowledge_version_id: KnowledgeVersionId
    review_status: KnowledgeReviewStatus
    is_active: bool = True

    @field_validator("aliases", "keywords")
    @classmethod
    def normalize_set_lists(cls, value: list[str]) -> list[str]:
        return _stable_strings(value)


class CompetencyDimensionSeed(_SeedModel):
    id: CompetencyDimensionId
    code: KnowledgeCode
    name: NonEmptyStr
    description: str = Field(min_length=1, max_length=1_000)
    scoring_category_hint: str | None = Field(default=None, max_length=80)
    display_order: int = Field(ge=0)
    knowledge_version_id: KnowledgeVersionId
    review_status: KnowledgeReviewStatus
    is_active: bool = True


class KnowledgeSourceSeed(_SeedModel):
    id: SourceId
    title: NonEmptyStr
    source_type: KnowledgeSourceType
    publisher: NonEmptyStr | None = None
    source_url: AnyHttpUrl | None = None
    published_at: AwareDatetime | None = None
    collected_at: AwareDatetime
    license_note: str | None = Field(default=None, max_length=1_000)
    reliability_level: ReliabilityLevel
    review_status: KnowledgeReviewStatus
    checksum: Sha256Hex

    @field_validator("published_at", "collected_at")
    @classmethod
    def normalize_datetime(cls, value: datetime | None) -> datetime | None:
        return value.astimezone(UTC) if value is not None else None


class RoleRequirementSeed(_SeedModel):
    id: KnowledgeRequirementId
    role_profile_id: RoleProfileId
    competency_dimension_id: CompetencyDimensionId
    title: NonEmptyStr
    description: str = Field(min_length=1, max_length=1_000)
    requirement_type: RequirementType
    importance: Importance
    is_common_hard_blocker: bool = False
    expected_evidence: list[NonEmptyStr] = Field(default_factory=list, max_length=20)
    weak_evidence: list[NonEmptyStr] = Field(default_factory=list, max_length=20)
    negative_signals: list[NonEmptyStr] = Field(default_factory=list, max_length=20)
    keywords: list[NonEmptyStr] = Field(default_factory=list, max_length=50)
    source_id: SourceId
    knowledge_version_id: KnowledgeVersionId
    review_status: KnowledgeReviewStatus
    is_active: bool = True

    @field_validator(
        "expected_evidence",
        "weak_evidence",
        "negative_signals",
        "keywords",
    )
    @classmethod
    def normalize_set_lists(cls, value: list[str]) -> list[str]:
        return _stable_strings(value)


class EvidencePatternSeed(_SeedModel):
    id: EvidencePatternId
    role_requirement_id: KnowledgeRequirementId
    evidence_type: KnowledgeCode
    description: str = Field(min_length=1, max_length=1_000)
    strength: EvidencePatternStrength
    positive_example: str | None = Field(default=None, max_length=500)
    weak_example: str | None = Field(default=None, max_length=500)
    negative_example: str | None = Field(default=None, max_length=500)
    source_id: SourceId
    knowledge_version_id: KnowledgeVersionId
    review_status: KnowledgeReviewStatus
    is_active: bool = True


class KnowledgeChunkSeed(_SeedModel):
    id: ChunkSeedId
    source_id: SourceId
    role_profile_id: RoleProfileId | None = None
    section: str | None = Field(default=None, max_length=120)
    chunk_text: str = Field(min_length=1, max_length=2_000)
    start_offset: int | None = Field(default=None, ge=0)
    end_offset: int | None = Field(default=None, ge=0)
    keywords: list[NonEmptyStr] = Field(default_factory=list, max_length=50)
    knowledge_version_id: KnowledgeVersionId
    review_status: KnowledgeReviewStatus
    content_hash: Sha256Hex

    @field_validator("keywords")
    @classmethod
    def normalize_keywords(cls, value: list[str]) -> list[str]:
        return _stable_strings(value)

    @model_validator(mode="after")
    def validate_offsets(self) -> Self:
        if (self.start_offset is None) != (self.end_offset is None):
            raise ValueError("chunk offsets must both be present or absent")
        if (
            self.start_offset is not None
            and self.end_offset is not None
            and self.end_offset < self.start_offset
        ):
            raise ValueError("chunk end_offset must not precede start_offset")
        return self


class InterviewQuestionSeed(_SeedModel):
    id: KnowledgeQuestionId
    role_profile_id: RoleProfileId
    competency_dimension_id: CompetencyDimensionId
    question: str = Field(min_length=1, max_length=500)
    question_type: KnowledgeQuestionType
    expected_points: list[NonEmptyStr] = Field(min_length=1, max_length=10)
    follow_up_questions: list[NonEmptyStr] = Field(
        default_factory=list,
        max_length=5,
    )
    difficulty: InterviewDifficulty
    source_id: SourceId
    knowledge_version_id: KnowledgeVersionId
    review_status: KnowledgeReviewStatus
    is_active: bool = True


class SourceRoleLinkSeed(_SeedModel):
    source_id: SourceId
    role_profile_id: RoleProfileId
    knowledge_version_id: KnowledgeVersionId
    relation_type: SourceRoleRelationType


_COLLECTIONS = (
    "job_families",
    "role_profiles",
    "competency_dimensions",
    "role_requirements",
    "evidence_patterns",
    "knowledge_sources",
    "knowledge_chunks",
    "interview_questions",
)


class KnowledgeSeedBundle(_SeedModel):
    schema_version: str = Field(pattern=r"^1\.0$")
    knowledge_base_version: KnowledgeVersionSeed
    job_families: list[JobFamilySeed]
    role_profiles: list[RoleProfileSeed]
    competency_dimensions: list[CompetencyDimensionSeed]
    role_requirements: list[RoleRequirementSeed]
    evidence_patterns: list[EvidencePatternSeed]
    knowledge_sources: list[KnowledgeSourceSeed]
    knowledge_chunks: list[KnowledgeChunkSeed]
    interview_questions: list[InterviewQuestionSeed]
    source_role_links: list[SourceRoleLinkSeed]

    @model_validator(mode="after")
    def normalize_and_reject_duplicates(self) -> Self:
        for field_name in _COLLECTIONS:
            values = getattr(self, field_name)
            ids = [item.id for item in values]
            if len(ids) != len(set(ids)):
                raise ValueError(f"{field_name} contains a duplicate id")
            object.__setattr__(
                self,
                field_name,
                sorted(values, key=lambda item: item.id),
            )
        link_keys = [
            (item.source_id, item.role_profile_id, item.knowledge_version_id)
            for item in self.source_role_links
        ]
        if len(link_keys) != len(set(link_keys)):
            raise ValueError("source_role_links contains a duplicate relationship")
        object.__setattr__(
            self,
            "source_role_links",
            sorted(
                self.source_role_links,
                key=lambda item: (
                    item.source_id,
                    item.role_profile_id,
                    item.knowledge_version_id,
                ),
            ),
        )
        return self


class SeedEntityCounts(_SeedModel):
    job_families: int = Field(ge=0)
    role_profiles: int = Field(ge=0)
    competency_dimensions: int = Field(ge=0)
    role_requirements: int = Field(ge=0)
    evidence_patterns: int = Field(ge=0)
    knowledge_sources: int = Field(ge=0)
    knowledge_chunks: int = Field(ge=0)
    interview_questions: int = Field(ge=0)
    source_role_links: int = Field(ge=0)
    knowledge_versions: int = Field(default=1, ge=0)

    @property
    def total(self) -> int:
        return (
            sum(value for name, value in self.model_dump().items() if name != "knowledge_versions")
            + self.knowledge_versions
        )

    @classmethod
    def from_bundle(cls, bundle: KnowledgeSeedBundle) -> SeedEntityCounts:
        return cls(
            job_families=len(bundle.job_families),
            role_profiles=len(bundle.role_profiles),
            competency_dimensions=len(bundle.competency_dimensions),
            role_requirements=len(bundle.role_requirements),
            evidence_patterns=len(bundle.evidence_patterns),
            knowledge_sources=len(bundle.knowledge_sources),
            knowledge_chunks=len(bundle.knowledge_chunks),
            interview_questions=len(bundle.interview_questions),
            source_role_links=len(bundle.source_role_links),
        )


class SeedImportResult(_SeedModel):
    version_id: KnowledgeVersionId
    version: KnowledgeVersion
    content_hash: Sha256Hex
    status: KnowledgeVersionStatus
    created_at: AwareDatetime
    created: bool
    idempotent: bool
    replaced_draft: bool
    counts: SeedEntityCounts
    import_strategy_version: str = SEED_IMPORT_STRATEGY_VERSION
    warnings: list[str] = Field(default_factory=list, max_length=20)


class SeedVersionTransitionResult(_SeedModel):
    version_id: KnowledgeVersionId
    version: KnowledgeVersion
    content_hash: Sha256Hex
    status: KnowledgeVersionStatus
    published_at: AwareDatetime | None


class SeedPublishResult(SeedVersionTransitionResult):
    pass


class SeedRetireResult(SeedVersionTransitionResult):
    pass


__all__ = [
    "CompetencyDimensionSeed",
    "EvidencePatternSeed",
    "InterviewQuestionSeed",
    "JobFamilySeed",
    "KnowledgeChunkSeed",
    "KnowledgeSeedBundle",
    "KnowledgeSourceSeed",
    "KnowledgeVersionSeed",
    "RoleProfileSeed",
    "RoleRequirementSeed",
    "SEED_IMPORT_STRATEGY_VERSION",
    "SEED_SCHEMA_VERSION",
    "SeedEntityCounts",
    "SeedImportMode",
    "SeedImportResult",
    "SeedPublishResult",
    "SeedRetireResult",
    "SourceRoleLinkSeed",
    "SourceRoleRelationType",
]
