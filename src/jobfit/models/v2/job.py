"""Target JD, requirement, and requirement-match contracts."""

from __future__ import annotations

from decimal import Decimal

from pydantic import Field, JsonValue, model_validator

from jobfit.models.common import Importance, NonEmptyStr
from jobfit.models.v2._base import ExtensibleDomainModel, require_unique
from jobfit.models.v2.enums import (
    AbilityStatus,
    CriticalStatus,
    EvidenceLevel,
    EvidenceStatus,
    JobFamily,
    KnowledgeCoverage,
    MatchCoverage,
    Relevance,
    RequirementExplicitness,
    RequirementSource,
    RequirementType,
    SupportType,
)


class Requirement(ExtensibleDomainModel):
    requirement_id: NonEmptyStr
    jd_snapshot_id: NonEmptyStr | None = None
    raw_requirement_ids: list[NonEmptyStr] = Field(default_factory=list)
    raw_text: str | None = None
    normalized_capability: NonEmptyStr
    requirement_type: RequirementType
    importance: Importance
    explicitness: RequirementExplicitness | None = None
    source: RequirementSource
    critical_status: CriticalStatus = CriticalStatus.NOT_CRITICAL
    classification_reason: str | None = None
    knowledge_citation_ids: list[NonEmptyStr] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_ownership(self) -> Requirement:
        require_unique(self.raw_requirement_ids, "raw_requirement_ids")
        require_unique(self.knowledge_citation_ids, "knowledge_citation_ids")
        if (
            self.source is RequirementSource.KNOWLEDGE
            and self.explicitness is not RequirementExplicitness.IMPLICIT
        ):
            raise ValueError("Knowledge cannot be an explicit requirement")
        if (
            self.requirement_type is RequirementType.IMPLICIT
            and self.source is not RequirementSource.KNOWLEDGE
        ):
            raise ValueError("Implicit requirements must come from knowledge")
        if (
            self.source is RequirementSource.KNOWLEDGE
            and self.requirement_type is not RequirementType.IMPLICIT
        ):
            raise ValueError("Knowledge requirements must be implicit")
        if (
            self.source is RequirementSource.JD
            and self.explicitness is not RequirementExplicitness.EXPLICIT
        ):
            raise ValueError("JD requirements must be explicit")
        if self.source is RequirementSource.JD and self.knowledge_citation_ids:
            raise ValueError("JD requirements cannot be sourced from knowledge citations")
        if (
            self.requirement_type is RequirementType.IMPLICIT
            and self.critical_status is not CriticalStatus.NOT_CRITICAL
        ):
            raise ValueError("Implicit requirements cannot be critical")
        return self


class JobProfile(ExtensibleDomainModel):
    jd_snapshot_id: NonEmptyStr
    company: str | None = None
    job_title: NonEmptyStr
    location: str | None = None
    employment_type: str | None = None
    job_family: JobFamily
    knowledge_coverage: KnowledgeCoverage
    seniority_signals: list[JsonValue] = Field(default_factory=list)
    responsibility_ids: list[NonEmptyStr] = Field(default_factory=list)
    raw_requirement_ids: list[NonEmptyStr] = Field(default_factory=list)
    requirement_ids: list[NonEmptyStr]

    @model_validator(mode="after")
    def validate_identity_lists(self) -> JobProfile:
        require_unique(self.responsibility_ids, "responsibility_ids")
        require_unique(self.raw_requirement_ids, "raw_requirement_ids")
        require_unique(self.requirement_ids, "requirement_ids")
        return self


class MatchedEvidence(ExtensibleDomainModel):
    evidence_id: NonEmptyStr
    relevance: Relevance
    support_type: SupportType


class RequirementMatch(ExtensibleDomainModel):
    match_id: NonEmptyStr
    requirement_id: NonEmptyStr
    matched_evidence: list[MatchedEvidence]
    coverage: MatchCoverage
    evidence_status: EvidenceStatus
    ability_status: AbilityStatus
    best_evidence_level: EvidenceLevel | None = None
    match_score_component: Decimal | None = None
    reason: str | None = None
    ability_confirmation_id: NonEmptyStr | None = None

    @model_validator(mode="after")
    def validate_evidence_ability_boundary(self) -> RequirementMatch:
        evidence_ids = [item.evidence_id for item in self.matched_evidence]
        require_unique(evidence_ids, "matched_evidence evidence_id")
        if self.evidence_status is EvidenceStatus.MISSING:
            if self.matched_evidence:
                raise ValueError("Missing evidence status cannot carry evidence")
            if self.coverage is not MatchCoverage.NONE:
                raise ValueError("Missing evidence status requires none coverage")
            if self.best_evidence_level is not None:
                raise ValueError("Missing evidence status cannot have an evidence level")
            if self.ability_status is AbilityStatus.CONFIRMED_GAP:
                if self.ability_confirmation_id is None:
                    raise ValueError(
                        "A confirmed ability gap requires explicit clarification"
                    )
            elif self.ability_status is not AbilityStatus.UNKNOWN:
                raise ValueError("Missing evidence must keep ability status unknown")
        elif not self.matched_evidence:
            raise ValueError("Non-missing evidence status requires matched evidence")
        if (self.evidence_status is EvidenceStatus.CONFLICT) != (
            self.ability_status is AbilityStatus.CONFLICT
        ):
            raise ValueError("Evidence and ability conflict statuses must agree")
        if (
            self.ability_status is AbilityStatus.CONFIRMED_GAP
            and self.evidence_status is not EvidenceStatus.MISSING
        ):
            raise ValueError("A confirmed ability gap requires missing evidence")
        return self
