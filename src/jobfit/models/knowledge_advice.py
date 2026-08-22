"""Internal contracts for grounded knowledge use during advice generation."""

from __future__ import annotations

from enum import StrEnum

from pydantic import ConfigDict, Field

from jobfit.models.common import NonEmptyStr, StrictModel
from jobfit.models.knowledge import (
    KnowledgeVersion,
    KnowledgeWarning,
    RoleProfileId,
    Sha256Hex,
)


class KnowledgeAdviceTargetType(StrEnum):
    GAP = "gap"
    RECOMMENDATION = "recommendation"
    REWRITE = "rewrite"
    INTERVIEW_QUESTION = "interview_question"


class KnowledgeCitationPurpose(StrEnum):
    ROLE_REQUIREMENT_CONTEXT = "role_requirement_context"
    EVIDENCE_GUIDANCE = "evidence_guidance"
    INTERVIEW_DIMENSION = "interview_dimension"
    JD_REFERENCE_DIFFERENCE = "jd_reference_difference"


class KnowledgeCitationUseDraft(StrictModel):
    """Untrusted model proposal; local code validates every identifier."""

    citation_id: NonEmptyStr
    target_type: KnowledgeAdviceTargetType
    target_index: int = Field(ge=0, le=100)
    purpose: KnowledgeCitationPurpose


class KnowledgeCitationUse(KnowledgeCitationUseDraft):
    output_reference: NonEmptyStr


class KnowledgeAdviceTrace(StrictModel):
    """Session-only sidecar; never serialized into AnalysisReport v1.0."""

    model_config = ConfigDict(frozen=True)

    knowledge_version: KnowledgeVersion
    content_hash: Sha256Hex
    selected_role_profile_id: RoleProfileId
    citation_uses: list[KnowledgeCitationUse] = Field(
        default_factory=list,
        max_length=30,
    )
    validated: bool
    fallback_used: bool
    warnings: list[KnowledgeWarning] = Field(default_factory=list, max_length=10)
    prompt_version: NonEmptyStr
    validator_version: NonEmptyStr
    generation_strategy_version: NonEmptyStr


__all__ = [
    "KnowledgeAdviceTargetType",
    "KnowledgeAdviceTrace",
    "KnowledgeCitationPurpose",
    "KnowledgeCitationUse",
    "KnowledgeCitationUseDraft",
]
