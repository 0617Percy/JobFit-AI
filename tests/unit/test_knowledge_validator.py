"""Local validation of model-proposed job-knowledge citations."""

from __future__ import annotations

from dataclasses import replace

import pytest

from jobfit.errors import ErrorCode, JobFitError
from jobfit.models import (
    KnowledgeAdviceTargetType,
    KnowledgeCitationPurpose,
    KnowledgeCitationUseDraft,
    StrengthItem,
)
from jobfit.validators import KnowledgeCitationValidator


def _use(
    citation_id: str = "cite-1111111111111111",
) -> KnowledgeCitationUseDraft:
    return KnowledgeCitationUseDraft(
        citation_id=citation_id,
        target_type=KnowledgeAdviceTargetType.RECOMMENDATION,
        target_index=0,
        purpose=KnowledgeCitationPurpose.ROLE_REQUIREMENT_CONTEXT,
    )


def test_valid_citation_is_converted_to_a_verified_usage(
    available_knowledge_context,
    report_case,
) -> None:
    uses = KnowledgeCitationValidator().validate_or_raise(
        context=available_knowledge_context,
        citation_uses=[_use()],
        provided_citation_ids=("cite-1111111111111111",),
        advice=report_case.advice,
    )

    assert len(uses) == 1
    assert uses[0].citation_id == "cite-1111111111111111"
    assert uses[0].output_reference == "recommendation:0"


@pytest.mark.parametrize(
    "citation_id",
    [
        "cite-ffffffffffffffff",
        "citation-created-by-model",
    ],
)
def test_unknown_or_fabricated_citation_is_rejected(
    available_knowledge_context,
    report_case,
    citation_id: str,
) -> None:
    with pytest.raises(JobFitError) as exc_info:
        KnowledgeCitationValidator().validate_or_raise(
            context=available_knowledge_context,
            citation_uses=[_use(citation_id)],
            provided_citation_ids=("cite-1111111111111111",),
            advice=report_case.advice,
        )

    assert exc_info.value.code is ErrorCode.KNOWLEDGE_CITATION_INVALID


def test_cross_version_citation_is_rejected(
    available_knowledge_context,
    report_case,
) -> None:
    wrong_version = available_knowledge_context.citations[0].model_copy(
        update={"knowledge_version_id": "kbv-2026-07-2"}
    )
    context = available_knowledge_context.model_copy(
        update={"citations": [wrong_version]}
    )

    with pytest.raises(JobFitError):
        KnowledgeCitationValidator().validate_or_raise(
            context=context,
            citation_uses=[_use()],
            provided_citation_ids=("cite-1111111111111111",),
            advice=report_case.advice,
        )


def test_citation_outside_selected_role_scope_is_rejected(
    available_knowledge_context,
    report_case,
) -> None:
    unrelated = available_knowledge_context.citations[0].model_copy(
        update={
            "citation_id": "cite-ffffffffffffffff",
            "source_id": "ks-unrelated-role",
        }
    )
    context = available_knowledge_context.model_copy(
        update={
            "citations": [
                available_knowledge_context.citations[0],
                unrelated,
            ]
        }
    )

    with pytest.raises(JobFitError):
        KnowledgeCitationValidator().validate_or_raise(
            context=context,
            citation_uses=[_use("cite-ffffffffffffffff")],
            provided_citation_ids=("cite-ffffffffffffffff",),
            advice=report_case.advice,
        )


def test_duplicate_citation_usage_is_rejected(
    available_knowledge_context,
    report_case,
) -> None:
    with pytest.raises(JobFitError):
        KnowledgeCitationValidator().validate_or_raise(
            context=available_knowledge_context,
            citation_uses=[_use(), _use()],
            provided_citation_ids=("cite-1111111111111111",),
            advice=report_case.advice,
        )


def test_citation_without_context_or_without_prompt_item_is_rejected(
    available_knowledge_context,
    report_case,
) -> None:
    validator = KnowledgeCitationValidator()
    with pytest.raises(JobFitError):
        validator.validate_or_raise(
            context=None,
            citation_uses=[_use()],
            provided_citation_ids=(),
            advice=report_case.advice,
        )
    with pytest.raises(JobFitError):
        validator.validate_or_raise(
            context=available_knowledge_context,
            citation_uses=[_use()],
            provided_citation_ids=(),
            advice=report_case.advice,
        )


def test_citation_cannot_masquerade_as_resume_evidence(
    available_knowledge_context,
    report_case,
) -> None:
    unsafe_strength = StrengthItem(
        title="Unsupported candidate claim",
        summary="The reference knowledge allegedly proves candidate ability.",
        requirement_ids=["req-python"],
        evidence_ids=["cite-1111111111111111"],
        why_it_matters="Reference knowledge is not resume evidence.",
    )
    advice = replace(report_case.advice, strengths=[unsafe_strength])

    with pytest.raises(JobFitError):
        KnowledgeCitationValidator().validate_or_raise(
            context=available_knowledge_context,
            citation_uses=[_use()],
            provided_citation_ids=("cite-1111111111111111",),
            advice=advice,
        )


def test_advice_without_knowledge_citations_remains_valid(report_case) -> None:
    uses = KnowledgeCitationValidator().validate_or_raise(
        context=None,
        citation_uses=[],
        provided_citation_ids=(),
        advice=report_case.advice,
    )

    assert uses == ()
