"""Contracts for the database-independent job knowledge domain."""

from __future__ import annotations

import importlib
import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from jobfit.models import (
    EvidenceItem,
    EvidenceRegistry,
    Importance,
    RequirementType,
)


def knowledge_module():
    """Import inside tests so the first TDD run fails as a test, not collection."""
    return importlib.import_module("jobfit.models.knowledge")


def make_version(*, status: str = "published", published: bool = True):
    knowledge = knowledge_module()
    return knowledge.KnowledgeBaseVersionInfo(
        id="kbv-2026-07-1",
        version="2026.07.1",
        name="JobFit reviewed knowledge",
        status=status,
        published_at=(
            datetime(2026, 7, 25, 8, 0, tzinfo=UTC) if published else None
        ),
        content_hash="a" * 64,
    )


def make_citation(*, citation_id: str = "cite-0123456789abcdef"):
    knowledge = knowledge_module()
    return knowledge.KnowledgeCitation(
        citation_id=citation_id,
        source_id="ks-official-ai-role",
        chunk_id="kc-ai-role-python",
        source_title="公开岗位能力说明",
        source_type="official_job_description",
        publisher="示例公开发布者",
        source_url="https://example.com/jobs/ai-intern",
        knowledge_version_id="kbv-2026-07-1",
        excerpt="岗位说明强调使用 Python 完成应用开发。",
        source_checksum="b" * 64,
    )


def make_role(
    *,
    role_profile_id: str = "rp-ai-application-intern",
    score: str = "0.9500",
    citation_id: str = "cite-0123456789abcdef",
):
    knowledge = knowledge_module()
    return knowledge.RetrievedRoleProfile(
        role_profile_id=role_profile_id,
        job_family_code="ai_application",
        code="ai_application_intern",
        name="AI 应用实习生",
        seniority="intern",
        industry=None,
        description="面向大模型应用和业务落地的初级岗位。",
        relevance_score=Decimal(score),
        matched_terms=["AI", "应用"],
        citation_ids=[citation_id],
    )


def make_requirement():
    knowledge = knowledge_module()
    return knowledge.RetrievedRequirement(
        knowledge_requirement_id="kr-python-application",
        role_profile_id="rp-ai-application-intern",
        competency_dimension_code="application_engineering",
        title="Python 应用开发",
        description="能够使用 Python 实现和验证 AI 应用功能。",
        requirement_type=RequirementType.MUST_HAVE,
        importance=Importance.HIGH,
        is_common_hard_blocker=True,
        expected_evidence=["项目中存在明确的 Python 实现活动"],
        weak_evidence=["仅列出 Python 技能名称"],
        negative_signals=["明确说明没有 Python 经验"],
        relevance_score=Decimal("0.9000"),
        citation_ids=["cite-0123456789abcdef"],
    )


def make_pattern():
    knowledge = knowledge_module()
    return knowledge.RetrievedEvidencePattern(
        evidence_pattern_id="ep-python-project",
        knowledge_requirement_id="kr-python-application",
        evidence_type="project",
        description="项目描述中出现使用 Python 完成的具体动作。",
        strength="strong",
        positive_example="使用 Python 完成数据处理和模型调用。",
        weak_example="熟悉 Python。",
        negative_example="没有 Python 项目经验。",
        citation_ids=["cite-0123456789abcdef"],
    )


def make_question():
    knowledge = knowledge_module()
    return knowledge.RetrievedInterviewQuestion(
        knowledge_question_id="iq-ai-project",
        role_profile_id="rp-ai-application-intern",
        competency_dimension_code="application_engineering",
        question="请介绍一个你实现过的 AI 应用项目。",
        question_type="project_deep_dive",
        expected_points=["问题背景", "个人行动", "验证方式"],
        follow_up_questions=["你如何验证输出质量？"],
        difficulty="medium",
        relevance_score=Decimal("0.8500"),
        citation_ids=["cite-0123456789abcdef"],
    )


def make_available_context():
    knowledge = knowledge_module()
    return knowledge.KnowledgeContext(
        status="available",
        version=make_version(),
        inferred_role_profiles=[make_role()],
        requirements=[make_requirement()],
        evidence_patterns=[make_pattern()],
        interview_questions=[make_question()],
        citations=[make_citation()],
        capabilities=knowledge.KnowledgeSearchCapabilities(
            mode="fts5",
            fts5_available=True,
        ),
        retrieval_strategy_version="1.0",
    )


def test_knowledge_enums_use_reviewed_design_values() -> None:
    knowledge = knowledge_module()

    assert {item.value for item in knowledge.KnowledgeVersionStatus} == {
        "draft",
        "published",
        "retired",
    }
    assert {item.value for item in knowledge.KnowledgeReviewStatus} == {
        "pending",
        "approved",
        "rejected",
    }
    assert {item.value for item in knowledge.KnowledgeRetrievalStatus} == {
        "disabled",
        "available",
        "no_match",
        "unavailable",
        "ambiguous",
    }
    assert {item.value for item in knowledge.KnowledgeSearchMode} == {
        "auto",
        "fts5",
        "keyword",
    }
    assert {item.value for item in knowledge.KnowledgeSearchBackend} == {
        "fts5",
        "keyword_fallback",
        "disabled",
    }
    assert {item.value for item in knowledge.KnowledgeSourceType} == {
        "official_job_description",
        "public_recruitment_page",
        "expert_definition",
        "internal_template",
        "research_report",
    }
    assert {item.value for item in knowledge.ReliabilityLevel} == {
        "primary",
        "high",
        "medium",
        "low",
    }


def test_version_supports_lifecycle_and_requires_publish_timestamp() -> None:
    knowledge = knowledge_module()

    draft = make_version(status="draft", published=False)
    retired = make_version(status="retired", published=True)

    assert draft.published_at is None
    assert retired.status is knowledge.KnowledgeVersionStatus.RETIRED
    with pytest.raises(ValidationError, match="published_at"):
        make_version(status="published", published=False)
    with pytest.raises(ValidationError, match="published_at"):
        make_version(status="retired", published=False)


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("id", ""),
        ("version", ""),
        ("version", "2026-7-1"),
        ("content_hash", "not-a-sha256"),
    ],
)
def test_version_rejects_empty_or_malformed_identity(
    field_name: str,
    value: str,
) -> None:
    payload = make_version().model_dump()
    payload[field_name] = value

    with pytest.raises(ValidationError):
        knowledge_module().KnowledgeBaseVersionInfo.model_validate(payload)


def test_knowledge_models_forbid_unknown_fields_and_are_frozen() -> None:
    knowledge = knowledge_module()
    payload = make_version().model_dump()
    payload["unexpected"] = "value"

    with pytest.raises(ValidationError):
        knowledge.KnowledgeBaseVersionInfo.model_validate(payload)
    with pytest.raises(ValidationError):
        make_version().name = "changed"


def test_citation_is_short_http_only_and_not_resume_evidence() -> None:
    knowledge = knowledge_module()
    citation = make_citation()

    assert not isinstance(citation, EvidenceItem)
    assert {
        "document_id",
        "segment_id",
        "start_char",
        "end_char",
        "quote",
        "evidence_kind",
    }.isdisjoint(type(citation).model_fields)
    assert "evidence_id" not in type(citation).model_fields

    with pytest.raises(ValidationError):
        knowledge.KnowledgeCitation.model_validate(
            {**citation.model_dump(), "excerpt": "x" * 241}
        )
    with pytest.raises(ValidationError):
        knowledge.KnowledgeCitation(
            **{
                **citation.model_dump(exclude={"source_url"}),
                "source_url": r"C:\Users\example\source.txt",
            }
        )


def test_citation_rejects_empty_source_and_invalid_ids() -> None:
    knowledge = knowledge_module()
    payload = make_citation().model_dump()

    with pytest.raises(ValidationError):
        knowledge.KnowledgeCitation.model_validate({**payload, "source_id": ""})
    with pytest.raises(ValidationError):
        knowledge.KnowledgeCitation.model_validate(
            {**payload, "citation_id": "citation-created-by-model"}
        )
    with pytest.raises(ValidationError):
        knowledge.KnowledgeCitation.model_validate(
            {**payload, "source_checksum": "short"}
        )


def test_retrieved_role_profile_uses_bounded_knowledge_relevance() -> None:
    knowledge = knowledge_module()

    assert make_role().relevance_score == Decimal("0.9500")
    with pytest.raises(ValidationError):
        knowledge.RetrievedRoleProfile.model_validate(
            {**make_role().model_dump(), "relevance_score": Decimal("1.0001")}
        )
    with pytest.raises(ValidationError):
        knowledge.RetrievedRoleProfile.model_validate(
            {**make_role().model_dump(), "citation_ids": []}
        )


def test_retrieved_requirement_reuses_existing_job_enums_without_score_fields() -> None:
    requirement = make_requirement()

    assert requirement.requirement_type is RequirementType.MUST_HAVE
    assert requirement.importance is Importance.HIGH
    assert requirement.is_common_hard_blocker is True
    assert {
        "weight",
        "priority_factor",
        "score_cap",
        "final_score",
        "recommendation_level",
        "mandatory",
        "hard_condition_kind",
    }.isdisjoint(type(requirement).model_fields)


def test_evidence_pattern_is_reference_knowledge_not_resume_evidence() -> None:
    pattern = make_pattern()

    assert not isinstance(pattern, EvidenceItem)
    assert {
        "evidence_id",
        "document_id",
        "segment_id",
        "start_char",
        "end_char",
        "quote",
    }.isdisjoint(type(pattern).model_fields)
    with pytest.raises((AttributeError, TypeError)):
        EvidenceRegistry([pattern])


def test_interview_question_limits_followups_and_requires_source_citation() -> None:
    knowledge = knowledge_module()
    payload = make_question().model_dump()

    with pytest.raises(ValidationError):
        knowledge.RetrievedInterviewQuestion.model_validate(
            {**payload, "follow_up_questions": [f"追问 {i}" for i in range(6)]}
        )
    with pytest.raises(ValidationError):
        knowledge.RetrievedInterviewQuestion.model_validate(
            {**payload, "citation_ids": []}
        )


def test_warning_rejects_internal_paths_sql_and_secret_like_text() -> None:
    knowledge = knowledge_module()

    warning = knowledge.KnowledgeWarning(
        code="knowledge_db_unavailable",
        message="岗位知识暂不可用，已保留基础分析能力。",
    )
    assert warning.code is knowledge.KnowledgeWarningCode.DB_UNAVAILABLE

    for unsafe in (
        r"数据库位于 C:\Users\example\knowledge.db",
        "SELECT * FROM knowledge_sources",
        "服务密钥为 sk-example-not-a-real-secret",
    ):
        with pytest.raises(ValidationError):
            knowledge.KnowledgeWarning(
                code="knowledge_retrieval_failed",
                message=unsafe,
            )


def test_empty_knowledge_context_round_trips_without_user_or_score_fields() -> None:
    knowledge = knowledge_module()
    context = knowledge.KnowledgeContext()
    encoded = context.model_dump_json()
    decoded = knowledge.KnowledgeContext.model_validate_json(encoded)

    assert decoded == context
    assert context.status is knowledge.KnowledgeRetrievalStatus.DISABLED
    assert context.capabilities.mode is knowledge.KnowledgeSearchBackend.DISABLED
    assert context.version is None
    assert context.citations == []
    assert {
        "resume_profile",
        "resume_text",
        "job_description",
        "jd_text",
        "final_score",
        "recommendation_level",
    }.isdisjoint(type(context).model_fields)


def test_available_context_requires_published_version_and_role() -> None:
    knowledge = knowledge_module()
    valid = make_available_context()

    assert valid.version is not None
    assert valid.version.status is knowledge.KnowledgeVersionStatus.PUBLISHED
    with pytest.raises(ValidationError):
        knowledge.KnowledgeContext(
            status="available",
            version=None,
            inferred_role_profiles=[make_role()],
            capabilities=knowledge.KnowledgeSearchCapabilities(
                mode="keyword_fallback",
                fts5_available=False,
            ),
        )
    with pytest.raises(ValidationError):
        knowledge.KnowledgeContext(
            status="available",
            version=make_version(status="draft", published=False),
            capabilities=knowledge.KnowledgeSearchCapabilities(
                mode="keyword_fallback",
                fts5_available=False,
            ),
        )


def test_non_available_context_cannot_carry_knowledge_content() -> None:
    knowledge = knowledge_module()

    with pytest.raises(ValidationError):
        knowledge.KnowledgeContext(
            status="unavailable",
            citations=[make_citation()],
            capabilities=knowledge.KnowledgeSearchCapabilities(
                mode="keyword_fallback",
                fts5_available=False,
            ),
        )
    with pytest.raises(ValidationError):
        knowledge.KnowledgeContext(
            status="ambiguous",
            version=make_version(),
            inferred_role_profiles=[make_role()],
            requirements=[make_requirement()],
            capabilities=knowledge.KnowledgeSearchCapabilities(
                mode="keyword_fallback",
                fts5_available=False,
            ),
        )


def test_ambiguous_context_keeps_only_ranked_role_candidates_and_citations() -> None:
    knowledge = knowledge_module()
    second_citation = make_citation(
        citation_id="cite-fedcba9876543210",
    )
    context = knowledge.KnowledgeContext(
        status="ambiguous",
        version=make_version(),
        inferred_role_profiles=[
            make_role(),
            make_role(
                role_profile_id="rp-data-analysis-intern",
                score="0.9200",
                citation_id=second_citation.citation_id,
            ),
        ],
        citations=[make_citation(), second_citation],
        warnings=[
            knowledge.KnowledgeWarning(
                code="knowledge_ambiguous_role",
                message="岗位画像存在歧义，基础分析将继续运行。",
            )
        ],
        capabilities=knowledge.KnowledgeSearchCapabilities(
            mode="keyword_fallback",
            fts5_available=False,
        ),
    )

    assert context.status is knowledge.KnowledgeRetrievalStatus.AMBIGUOUS
    assert context.requirements == []
    assert context.evidence_patterns == []
    assert context.interview_questions == []


def test_context_requires_stable_citation_id_order() -> None:
    knowledge = knowledge_module()
    second_citation = make_citation(
        citation_id="cite-fedcba9876543210",
    )

    with pytest.raises(ValidationError, match="stable citation order"):
        knowledge.KnowledgeContext(
            status="available",
            version=make_version(),
            inferred_role_profiles=[
                make_role(),
                make_role(
                    role_profile_id="rp-ai-application-junior",
                    score="0.9000",
                    citation_id=second_citation.citation_id,
                ),
            ],
            citations=[second_citation, make_citation()],
            capabilities=knowledge.KnowledgeSearchCapabilities(
                mode="keyword_fallback",
                fts5_available=False,
            ),
        )


def test_context_rejects_duplicate_or_unknown_citation_references() -> None:
    knowledge = knowledge_module()
    payload = make_available_context().model_dump()

    duplicate = [make_citation(), make_citation()]
    with pytest.raises(ValidationError):
        knowledge.KnowledgeContext.model_validate(
            {**payload, "citations": duplicate}
        )

    role = make_role().model_copy(
        update={"citation_ids": ["cite-ffffffffffffffff"]}
    )
    with pytest.raises(ValidationError):
        knowledge.KnowledgeContext.model_validate(
            {**payload, "inferred_role_profiles": [role]}
        )


def test_context_requires_stable_rank_order() -> None:
    knowledge = knowledge_module()
    lower = make_role(
        role_profile_id="rp-ai-application-junior",
        score="0.7000",
    )
    higher = make_role(score="0.9500")

    with pytest.raises(ValidationError, match="stable relevance order"):
        knowledge.KnowledgeContext(
            status="available",
            version=make_version(),
            inferred_role_profiles=[lower, higher],
            citations=[make_citation()],
            capabilities=knowledge.KnowledgeSearchCapabilities(
                mode="keyword_fallback",
                fts5_available=False,
            ),
        )


def test_context_json_is_deterministic_for_the_same_domain_input() -> None:
    first = make_available_context()
    second = make_available_context()

    assert first.model_dump_json() == second.model_dump_json()
    assert json.loads(first.model_dump_json())["requirements"][0][
        "relevance_score"
    ] == "0.9000"


def test_retrieval_result_keeps_only_hashed_trace_and_domain_context() -> None:
    knowledge = knowledge_module()
    result = knowledge.KnowledgeRetrievalResult(
        context=make_available_context(),
        query_fingerprint="c" * 64,
        normalized_job_title="ai 应用实习生",
        query_terms=["ai", "应用"],
        candidate_role_ids=["rp-ai-application-intern"],
    )

    assert result.context.status is knowledge.KnowledgeRetrievalStatus.AVAILABLE
    assert {
        "database_row",
        "session",
        "connection",
        "sql",
        "resume_text",
        "jd_text",
    }.isdisjoint(type(result).model_fields)
    with pytest.raises(ValidationError):
        knowledge.KnowledgeRetrievalResult.model_validate(
            {**result.model_dump(), "query_fingerprint": "raw-job-description"}
        )
