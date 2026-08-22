"""Repository-to-context retrieval remains offline and source grounded."""

from __future__ import annotations

from decimal import Decimal

from jobfit.knowledge.protocol import KnowledgeRetriever
from jobfit.knowledge.repository import SqliteKnowledgeRepository
from jobfit.models import (
    HardConditionKind,
    Importance,
    JobProfile,
    JobRequirement,
    JobRequirementCollection,
    LanguageCode,
    RequirementCategory,
    RequirementType,
)
from jobfit.models.knowledge import (
    KnowledgeRetrievalStatus,
    KnowledgeSearchMode,
)


def make_job() -> JobProfile:
    text = "Use Python to implement an AI application."
    return JobProfile(
        job_id="job-integration-synthetic",
        title="AI application intern",
        company=None,
        language=LanguageCode.EN,
        jd_text="Anonymous synthetic JD body.",
        summary="Build and validate bounded AI applications.",
        requirements=JobRequirementCollection(
            items=[
                JobRequirement(
                    requirement_text=text,
                    source_text=text,
                    source_start_char=0,
                    source_end_char=len(text),
                    requirement_type=RequirementType.MUST_HAVE,
                    category=RequirementCategory.TECHNICAL_SKILL,
                    importance=Importance.HIGH,
                    mandatory=True,
                    hard_condition_kind=HardConditionKind.NONE,
                    normalized_key="python_application",
                    requirement_id="req-python-application",
                    priority_factor=Decimal("1"),
                    weight=Decimal("100"),
                )
            ],
            source_coverage_ratio=Decimal("1"),
        ),
        keywords=["python", "llm"],
    )


def test_sqlite_repository_builds_grounded_knowledge_context(
    seeded_database,
) -> None:
    from jobfit.knowledge.retriever import DefaultKnowledgeRetriever

    repository = SqliteKnowledgeRepository(
        seeded_database,
        search_mode=KnowledgeSearchMode.KEYWORD,
    )
    retriever = DefaultKnowledgeRetriever(
        repository,
        enabled=True,
        requested_version="2026.07.1",
        search_mode=KnowledgeSearchMode.KEYWORD,
        requirement_limit=12,
        prompt_char_limit=8_000,
        retrieval_strategy_version="1.0",
    )

    context = retriever.retrieve_for_job(make_job())

    assert isinstance(retriever, KnowledgeRetriever)
    assert context.status is KnowledgeRetrievalStatus.AVAILABLE
    assert context.version is not None
    assert context.version.version == "2026.07.1"
    assert [item.role_profile_id for item in context.inferred_role_profiles] == [
        "rp-ai-application-intern"
    ]
    assert {item.role_profile_id for item in context.requirements} == {
        "rp-ai-application-intern"
    }
    assert {
        item.knowledge_requirement_id for item in context.evidence_patterns
    } == {"kr-python-application"}
    assert {item.role_profile_id for item in context.interview_questions} == {
        "rp-ai-application-intern"
    }
    assert context.citations
    assert all(
        repository.citation_exists(
            citation,
            version_id=context.version.id,
        )
        for citation in context.citations
    )
    assert not hasattr(context, "final_score")
    assert not hasattr(context, "recommendation_level")
