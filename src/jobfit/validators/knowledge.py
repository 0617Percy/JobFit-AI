"""Deterministic validation of model-proposed knowledge citation usage."""

from __future__ import annotations

from collections.abc import Sequence

from jobfit.errors import ErrorCode, SchemaValidationError
from jobfit.generators.advice_bundle import GeneratedAdvice
from jobfit.models import KnowledgeContext, KnowledgeRetrievalStatus
from jobfit.models.knowledge_advice import (
    KnowledgeAdviceTargetType,
    KnowledgeCitationPurpose,
    KnowledgeCitationUse,
    KnowledgeCitationUseDraft,
)

KNOWLEDGE_CITATION_VALIDATOR_VERSION = "1.0"


class KnowledgeCitationValidator:
    """Validate against the exact bounded context supplied to the model."""

    def validate_or_raise(
        self,
        *,
        context: KnowledgeContext | None,
        citation_uses: Sequence[KnowledgeCitationUseDraft],
        provided_citation_ids: Sequence[str],
        advice: GeneratedAdvice,
    ) -> tuple[KnowledgeCitationUse, ...]:
        if not citation_uses:
            return ()
        if (
            context is None
            or context.status is not KnowledgeRetrievalStatus.AVAILABLE
            or context.version is None
            or len(context.inferred_role_profiles) != 1
        ):
            raise _citation_error()

        proposed_ids = [item.citation_id for item in citation_uses]
        if len(proposed_ids) != len(set(proposed_ids)):
            raise _citation_error()
        provided = set(provided_citation_ids)
        known = {item.citation_id: item for item in context.citations}
        scoped = {
            citation_id
            for item in (
                *context.inferred_role_profiles,
                *context.requirements,
                *context.evidence_patterns,
                *context.interview_questions,
            )
            for citation_id in item.citation_ids
        }
        if not provided.issubset(known) or not provided.issubset(scoped):
            raise _citation_error()

        resume_evidence_ids = {
            evidence_id
            for item in advice.strengths
            for evidence_id in item.evidence_ids
        }
        resume_evidence_ids.update(
            evidence_id
            for item in advice.rewrite_suggestions
            for evidence_id in item.evidence_ids
        )
        resume_evidence_ids.update(
            evidence_id
            for item in advice.interview_questions
            for evidence_id in item.resume_evidence_ids
        )
        if set(known).intersection(resume_evidence_ids):
            raise _citation_error()

        validated: list[KnowledgeCitationUse] = []
        for proposed in citation_uses:
            citation = known.get(proposed.citation_id)
            if (
                citation is None
                or proposed.citation_id not in provided
                or proposed.citation_id not in scoped
                or citation.knowledge_version_id != context.version.id
            ):
                raise _citation_error()
            self._validate_target(proposed, advice)
            validated.append(
                KnowledgeCitationUse(
                    **proposed.model_dump(),
                    output_reference=(
                        f"{proposed.target_type.value}:{proposed.target_index}"
                    ),
                )
            )
        return tuple(validated)

    @staticmethod
    def _validate_target(
        proposed: KnowledgeCitationUseDraft,
        advice: GeneratedAdvice,
    ) -> None:
        limits = {
            KnowledgeAdviceTargetType.GAP: len(advice.gaps),
            KnowledgeAdviceTargetType.RECOMMENDATION: 1,
            KnowledgeAdviceTargetType.REWRITE: len(advice.rewrite_suggestions),
            KnowledgeAdviceTargetType.INTERVIEW_QUESTION: len(
                advice.interview_questions
            ),
        }
        if proposed.target_index >= limits[proposed.target_type]:
            raise _citation_error()
        if (
            proposed.purpose is KnowledgeCitationPurpose.INTERVIEW_DIMENSION
            and proposed.target_type
            is not KnowledgeAdviceTargetType.INTERVIEW_QUESTION
        ):
            raise _citation_error()


def _citation_error() -> SchemaValidationError:
    return SchemaValidationError(
        code=ErrorCode.KNOWLEDGE_CITATION_INVALID,
        user_message="知识引用未通过本地校验，已停止使用该增强结果。",
        recoverable=True,
    )


__all__ = [
    "KNOWLEDGE_CITATION_VALIDATOR_VERSION",
    "KnowledgeCitationValidator",
]
