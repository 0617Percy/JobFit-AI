"""Deterministic retrieval, role resolution, budgets, and safe fallbacks."""

from __future__ import annotations

import importlib
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from jobfit.errors import ErrorCode, KnowledgeDatabaseError
from jobfit.knowledge.protocol import KnowledgeRepository, KnowledgeRetriever
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
    EvidencePatternStrength,
    InterviewDifficulty,
    KnowledgeBaseVersionInfo,
    KnowledgeCitation,
    KnowledgeQuestionType,
    KnowledgeRetrievalStatus,
    KnowledgeSearchBackend,
    KnowledgeSearchCapabilities,
    KnowledgeSearchCapabilityStatus,
    KnowledgeSearchMode,
    KnowledgeSourceType,
    KnowledgeVersionStatus,
    KnowledgeWarningCode,
    ReliabilityLevel,
    RetrievedEvidencePattern,
    RetrievedInterviewQuestion,
    RetrievedRequirement,
    RetrievedRoleProfile,
)


def retriever_module():
    return importlib.import_module("jobfit.knowledge.retriever")


def make_job(
    *,
    title: str | None = "Synthetic AI application intern",
    summary: str = "Build bounded AI applications with Python.",
    keywords: tuple[str, ...] = ("Python", "AI application"),
    jd_text: str = "Synthetic role requires Python application work.",
    company: str | None = "Private marker company",
) -> JobProfile:
    requirement_text = "Use Python for application development"
    requirement = JobRequirement(
        requirement_text=requirement_text,
        source_text=requirement_text,
        source_start_char=0,
        source_end_char=len(requirement_text),
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
    return JobProfile(
        job_id="job-synthetic",
        title=title,
        company=company,
        language=LanguageCode.EN,
        jd_text=jd_text,
        summary=summary,
        requirements=JobRequirementCollection(
            items=[requirement],
            source_coverage_ratio=Decimal("1"),
        ),
        keywords=list(keywords),
    )


def make_version() -> KnowledgeBaseVersionInfo:
    return KnowledgeBaseVersionInfo(
        id="kbv-2026-07-1",
        version="2026.07.1",
        name="Synthetic published knowledge",
        status=KnowledgeVersionStatus.PUBLISHED,
        content_hash="a" * 64,
        published_at=datetime(2026, 7, 25, 8, 0, tzinfo=UTC),
    )


def make_citation(
    *,
    citation_id: str = "cite-1111111111111111",
    source_id: str = "ks-synthetic-ai",
) -> KnowledgeCitation:
    return KnowledgeCitation(
        citation_id=citation_id,
        source_id=source_id,
        source_title="Synthetic reviewed role source",
        source_type=KnowledgeSourceType.INTERNAL_TEMPLATE,
        publisher="JobFit synthetic fixtures",
        source_url="https://example.test/knowledge/source",
        knowledge_version_id="kbv-2026-07-1",
        reliability_level=ReliabilityLevel.HIGH,
        source_checksum="b" * 64,
    )


def make_role(
    *,
    role_id: str = "rp-synthetic-ai",
    family: str = "synthetic_ai",
    score: str = "0.9000",
    citation_id: str = "cite-1111111111111111",
    name: str = "Synthetic AI application intern",
) -> RetrievedRoleProfile:
    return RetrievedRoleProfile(
        role_profile_id=role_id,
        job_family_code=family,
        code=role_id.removeprefix("rp-").replace("-", "_"),
        name=name,
        seniority="intern",
        description="Synthetic reviewed role profile.",
        relevance_score=Decimal(score),
        matched_terms=["synthetic", "ai"],
        matched_fields=["name"],
        citation_ids=[citation_id],
    )


def make_requirement(
    *,
    requirement_id: str = "kr-synthetic-python",
    role_id: str = "rp-synthetic-ai",
    citation_id: str = "cite-1111111111111111",
    score: str = "0.9000",
    description: str = "Use Python to implement a bounded application.",
) -> RetrievedRequirement:
    return RetrievedRequirement(
        knowledge_requirement_id=requirement_id,
        role_profile_id=role_id,
        competency_dimension_code="application_engineering",
        title="Synthetic Python application development",
        description=description,
        requirement_type=RequirementType.MUST_HAVE,
        importance=Importance.HIGH,
        is_common_hard_blocker=True,
        expected_evidence=["A concrete implementation action."],
        relevance_score=Decimal(score),
        matched_terms=["python"],
        matched_fields=["title"],
        citation_ids=[citation_id],
    )


def make_pattern(
    *,
    pattern_id: str = "ep-synthetic-python",
    requirement_id: str = "kr-synthetic-python",
    citation_id: str = "cite-1111111111111111",
) -> RetrievedEvidencePattern:
    return RetrievedEvidencePattern(
        evidence_pattern_id=pattern_id,
        knowledge_requirement_id=requirement_id,
        evidence_type="project",
        description="Look for a concrete implementation action.",
        strength=EvidencePatternStrength.STRONG,
        citation_ids=[citation_id],
    )


def make_question(
    *,
    question_id: str = "iq-synthetic-ai",
    role_id: str = "rp-synthetic-ai",
    citation_id: str = "cite-1111111111111111",
) -> RetrievedInterviewQuestion:
    return RetrievedInterviewQuestion(
        knowledge_question_id=question_id,
        role_profile_id=role_id,
        competency_dimension_code="application_engineering",
        question="Describe a synthetic application implementation.",
        question_type=KnowledgeQuestionType.PROJECT_DEEP_DIVE,
        expected_points=["context", "action", "validation"],
        difficulty=InterviewDifficulty.MEDIUM,
        relevance_score=Decimal("0.8000"),
        matched_terms=["application"],
        matched_fields=["primary"],
        citation_ids=[citation_id],
    )


class FakeRepository:
    def __init__(
        self,
        *,
        version: KnowledgeBaseVersionInfo | None = None,
        roles: list[RetrievedRoleProfile] | None = None,
        requirements: list[RetrievedRequirement] | None = None,
        patterns: list[RetrievedEvidencePattern] | None = None,
        questions: list[RetrievedInterviewQuestion] | None = None,
        citations: list[KnowledgeCitation] | None = None,
        capabilities: KnowledgeSearchCapabilities | None = None,
        failure: KnowledgeDatabaseError | None = None,
    ) -> None:
        self.version = version
        self.roles = roles or []
        self.requirements = requirements or []
        self.patterns = patterns or []
        self.questions = questions or []
        self.citations = citations or []
        self.capabilities = capabilities or KnowledgeSearchCapabilities(
            mode=KnowledgeSearchBackend.KEYWORD_FALLBACK,
            status=KnowledgeSearchCapabilityStatus.AVAILABLE,
            keyword_fallback_available=True,
        )
        self.failure = failure
        self.calls: list[tuple[str, object]] = []

    def get_version(self, version_id: str):
        self.calls.append(("get_version", version_id))
        return self.version if self.version and self.version.id == version_id else None

    def get_published_version(self, version: str | None = None):
        self.calls.append(("get_published_version", version))
        if self.failure:
            raise self.failure
        if self.version is None:
            return None
        if version is not None and self.version.version != version:
            return None
        return self.version

    def get_search_capabilities(self):
        self.calls.append(("get_search_capabilities", None))
        return self.capabilities

    def search_role_profiles(self, query, *, version_id: str, limit: int):
        self.calls.append(("search_role_profiles", (query, version_id, limit)))
        if self.failure:
            raise self.failure
        return self.roles[:limit]

    def get_role_profile(self, role_profile_id: str, *, version_id: str):
        return next(
            (
                role
                for role in self.roles
                if role.role_profile_id == role_profile_id
            ),
            None,
        )

    def search_requirements(self, query, *, version_id: str, limit: int):
        self.calls.append(("search_requirements", (query, version_id, limit)))
        return self.requirements[:limit]

    def search_evidence_patterns(
        self,
        requirement_ids,
        *,
        version_id: str,
        limit: int,
    ):
        self.calls.append(
            ("search_evidence_patterns", (tuple(requirement_ids), version_id, limit))
        )
        return self.patterns[:limit]

    def search_interview_questions(
        self,
        query,
        *,
        version_id: str,
        limit: int,
    ):
        self.calls.append(
            ("search_interview_questions", (query, version_id, limit))
        )
        return self.questions[:limit]

    def get_sources(self, source_ids, *, version_id: str):
        return [
            citation
            for citation in self.citations
            if citation.source_id in source_ids
            and citation.knowledge_version_id == version_id
        ]

    def get_citations(self, citation_ids, *, version_id: str):
        self.calls.append(("get_citations", (tuple(citation_ids), version_id)))
        return [
            citation
            for citation in self.citations
            if citation.citation_id in citation_ids
            and citation.knowledge_version_id == version_id
        ]

    def citation_exists(self, citation, *, version_id: str):
        return (
            citation.knowledge_version_id == version_id
            and citation in self.citations
        )


def make_retriever(repository, **overrides):
    defaults = {
        "enabled": True,
        "requested_version": "2026.07.1",
        "search_mode": KnowledgeSearchMode.KEYWORD,
        "requirement_limit": 12,
        "prompt_char_limit": 8_000,
        "retrieval_strategy_version": "1.0",
    }
    defaults.update(overrides)
    return retriever_module().DefaultKnowledgeRetriever(repository, **defaults)


def full_repository(**overrides) -> FakeRepository:
    citation = make_citation()
    values = {
        "version": make_version(),
        "roles": [make_role()],
        "requirements": [make_requirement()],
        "patterns": [make_pattern()],
        "questions": [make_question()],
        "citations": [citation],
    }
    values.update(overrides)
    return FakeRepository(**values)


def test_disabled_retriever_returns_serializable_context_without_repository_calls():
    repository = full_repository()
    retriever = make_retriever(repository, enabled=False)

    context = retriever.retrieve_for_job(make_job())

    assert context.status is KnowledgeRetrievalStatus.DISABLED
    assert context.version is None
    assert context.inferred_role_profiles == []
    assert context.warnings[0].code is KnowledgeWarningCode.DISABLED
    assert repository.calls == []
    assert context == type(context).model_validate_json(context.model_dump_json())


def test_database_failure_becomes_safe_unavailable_context() -> None:
    failure = KnowledgeDatabaseError(
        code=ErrorCode.KNOWLEDGE_DB_UNAVAILABLE,
        user_message="Safe database message.",
        recoverable=True,
        cause=RuntimeError(r"C:\Users\private\knowledge.sqlite3"),
    )
    context = make_retriever(
        full_repository(failure=failure)
    ).retrieve_for_job(make_job(jd_text="PRIVATE_JD_MARKER"))

    assert context.status is KnowledgeRetrievalStatus.UNAVAILABLE
    assert context.warnings[0].code is KnowledgeWarningCode.DB_UNAVAILABLE
    assert "PRIVATE_JD_MARKER" not in context.warnings[0].message
    assert "Users" not in context.warnings[0].message


def test_missing_requested_published_version_does_not_mix_versions() -> None:
    repository = full_repository(version=None)

    context = make_retriever(repository).retrieve_for_job(make_job())

    assert context.status is KnowledgeRetrievalStatus.UNAVAILABLE
    assert context.version is None
    assert context.warnings[0].code is KnowledgeWarningCode.VERSION_UNAVAILABLE
    assert ("get_published_version", "2026.07.1") in repository.calls
    assert all(call[0] != "search_role_profiles" for call in repository.calls)


def test_retired_version_is_not_accepted_as_published_knowledge() -> None:
    retired = make_version().model_copy(
        update={"status": KnowledgeVersionStatus.RETIRED}
    )

    context = make_retriever(
        full_repository(version=retired)
    ).retrieve_for_job(make_job())

    assert context.status is KnowledgeRetrievalStatus.UNAVAILABLE
    assert context.warnings[0].code is KnowledgeWarningCode.VERSION_UNAVAILABLE


def test_role_query_uses_structured_fields_not_company_or_full_jd() -> None:
    first = make_job(
        company="PRIVATE_COMPANY_ALPHA",
        jd_text="PRIVATE_FULL_JD_ALPHA",
    )
    second = make_job(
        company="PRIVATE_COMPANY_BETA",
        jd_text="PRIVATE_FULL_JD_BETA",
    )

    first_query = retriever_module().build_role_resolution_query(first)
    second_query = retriever_module().build_role_resolution_query(second)

    assert first_query == second_query
    serialized = repr(first_query)
    assert "PRIVATE_COMPANY" not in serialized
    assert "PRIVATE_FULL_JD" not in serialized


def test_role_query_is_stable_for_mixed_chinese_and_english_job_facts() -> None:
    job = make_job(
        title="AI 应用实习生",
        summary="使用 Python 构建可验证的 AI 应用。",
        keywords=("Python", "模型评估"),
    )

    first = retriever_module().build_role_resolution_query(job)
    second = retriever_module().build_role_resolution_query(job)

    assert first == second
    assert "python" in first.keywords
    assert any("模型" in term for term in first.keywords)


def test_single_high_relevance_role_builds_available_context() -> None:
    repository = full_repository()

    context = make_retriever(repository).retrieve_for_job(make_job())

    assert isinstance(make_retriever(repository), KnowledgeRetriever)
    assert isinstance(repository, KnowledgeRepository)
    assert context.status is KnowledgeRetrievalStatus.AVAILABLE
    assert context.version == make_version()
    assert [item.role_profile_id for item in context.inferred_role_profiles] == [
        "rp-synthetic-ai"
    ]
    assert [item.knowledge_requirement_id for item in context.requirements] == [
        "kr-synthetic-python"
    ]
    assert len(context.evidence_patterns) == 1
    assert len(context.interview_questions) == 1
    assert context.citations == [make_citation()]


def test_disabled_search_backend_fails_softly_without_building_details() -> None:
    repository = full_repository(
        capabilities=KnowledgeSearchCapabilities(),
    )

    context = make_retriever(repository).retrieve_for_job(make_job())

    assert context.status is KnowledgeRetrievalStatus.UNAVAILABLE
    assert context.requirements == []
    assert context.warnings[0].code is KnowledgeWarningCode.RETRIEVAL_FAILED


def test_low_relevance_role_returns_no_match_without_profile_knowledge() -> None:
    repository = full_repository(roles=[make_role(score="0.4499")])

    context = make_retriever(repository).retrieve_for_job(make_job())

    assert context.status is KnowledgeRetrievalStatus.NO_MATCH
    assert context.requirements == []
    assert context.citations == []
    assert context.warnings[0].code is KnowledgeWarningCode.NO_ROLE_MATCH
    assert all(call[0] != "search_requirements" for call in repository.calls)


@pytest.mark.parametrize(
    "second_role",
    [
        make_role(
            role_id="rp-synthetic-data",
            family="synthetic_data",
            score="0.8500",
            citation_id="cite-2222222222222222",
            name="Synthetic data analyst",
        ),
        make_role(
            role_id="rp-synthetic-ai-second",
            family="synthetic_ai",
            score="0.9000",
            citation_id="cite-2222222222222222",
            name="Synthetic AI assistant intern",
        ),
    ],
)
def test_close_or_tied_top_roles_are_ambiguous_without_detail_injection(
    second_role,
) -> None:
    citations = [
        make_citation(),
        make_citation(
            citation_id="cite-2222222222222222",
            source_id="ks-synthetic-second",
        ),
    ]
    repository = full_repository(
        roles=[make_role(), second_role],
        citations=citations,
    )

    context = make_retriever(repository).retrieve_for_job(make_job())

    assert context.status is KnowledgeRetrievalStatus.AMBIGUOUS
    assert len(context.inferred_role_profiles) == 2
    assert context.requirements == []
    assert context.evidence_patterns == []
    assert context.interview_questions == []
    assert context.warnings[0].code is KnowledgeWarningCode.AMBIGUOUS_ROLE
    assert all(call[0] != "search_requirements" for call in repository.calls)


def test_matched_role_filters_cross_family_and_same_family_details() -> None:
    foreign_requirement = make_requirement(
        requirement_id="kr-foreign-data",
        role_id="rp-synthetic-data",
        citation_id="cite-2222222222222222",
    )
    same_family_requirement = make_requirement(
        requirement_id="kr-foreign-ai",
        role_id="rp-synthetic-ai-second",
        citation_id="cite-3333333333333333",
    )
    foreign_question = make_question(
        question_id="iq-foreign-data",
        role_id="rp-synthetic-data",
        citation_id="cite-2222222222222222",
    )
    repository = full_repository(
        roles=[
            make_role(),
            make_role(
                role_id="rp-synthetic-data",
                family="synthetic_data",
                score="0.7000",
                citation_id="cite-2222222222222222",
            ),
        ],
        requirements=[
            make_requirement(),
            foreign_requirement,
            same_family_requirement,
        ],
        patterns=[
            make_pattern(),
            make_pattern(
                pattern_id="ep-foreign-data",
                requirement_id="kr-foreign-data",
                citation_id="cite-2222222222222222",
            ),
        ],
        questions=[make_question(), foreign_question],
        citations=[
            make_citation(),
            make_citation(
                citation_id="cite-2222222222222222",
                source_id="ks-synthetic-data",
            ),
            make_citation(
                citation_id="cite-3333333333333333",
                source_id="ks-synthetic-ai-second",
            ),
        ],
    )

    context = make_retriever(repository).retrieve_for_job(make_job())

    assert context.status is KnowledgeRetrievalStatus.AVAILABLE
    assert {item.role_profile_id for item in context.requirements} == {
        "rp-synthetic-ai"
    }
    assert {item.role_profile_id for item in context.interview_questions} == {
        "rp-synthetic-ai"
    }
    assert {
        item.knowledge_requirement_id for item in context.evidence_patterns
    } == {"kr-synthetic-python"}
    assert {citation.source_id for citation in context.citations} == {
        "ks-synthetic-ai"
    }


def test_invalid_or_cross_version_citation_fails_closed() -> None:
    invalid = make_citation().model_copy(
        update={"knowledge_version_id": "kbv-2026-08-1"}
    )
    repository = full_repository(citations=[invalid])

    context = make_retriever(repository).retrieve_for_job(make_job())

    assert context.status is KnowledgeRetrievalStatus.UNAVAILABLE
    assert context.requirements == []
    assert context.citations == []
    assert context.warnings[0].code is KnowledgeWarningCode.CITATION_INVALID


def test_result_limits_and_character_budget_drop_complete_low_priority_items() -> None:
    requirements = [
        make_requirement(
            requirement_id=f"kr-synthetic-{index}",
            score=f"0.{9 - index}000",
            description=f"Synthetic requirement {index}. " + "x" * 300,
        )
        for index in range(5)
    ]
    repository = full_repository(
        requirements=requirements,
        patterns=[
            make_pattern(
                pattern_id=f"ep-synthetic-{index}",
                requirement_id=requirement.knowledge_requirement_id,
            )
            for index, requirement in enumerate(requirements)
        ],
    )

    context = make_retriever(
        repository,
        requirement_limit=3,
        prompt_char_limit=1_500,
    ).retrieve_for_job(make_job(), limit=3)

    assert len(context.requirements) <= 3
    assert all(
        pattern.knowledge_requirement_id
        in {item.knowledge_requirement_id for item in context.requirements}
        for pattern in context.evidence_patterns
    )
    assert any(
        warning.code is KnowledgeWarningCode.BUDGET_TRUNCATED
        for warning in context.warnings
    )
    original_descriptions = {item.description for item in requirements}
    assert {
        item.description for item in context.requirements
    } <= original_descriptions


def test_per_requirement_evidence_pattern_limit_is_deterministic() -> None:
    patterns = [
        make_pattern(pattern_id=f"ep-synthetic-{index}")
        for index in range(4)
    ]
    repository = full_repository(patterns=patterns)

    first = make_retriever(repository).retrieve_for_job(make_job())
    second = make_retriever(repository).retrieve_for_job(make_job())

    assert first == second
    assert [item.evidence_pattern_id for item in first.evidence_patterns] == [
        "ep-synthetic-0",
        "ep-synthetic-1",
    ]
    assert any(
        warning.code is KnowledgeWarningCode.BUDGET_TRUNCATED
        for warning in first.warnings
    )


def test_citation_budget_drops_complete_low_priority_items_not_whole_context() -> None:
    requirement_citations = [
        f"cite-{index:016x}" for index in range(2, 14)
    ]
    question_citations = [
        f"cite-{index:016x}" for index in range(14, 24)
    ]
    requirements = [
        make_requirement(
            requirement_id=f"kr-synthetic-budget-{index}",
            citation_id=citation_id,
        )
        for index, citation_id in enumerate(requirement_citations)
    ]
    questions = [
        make_question(
            question_id=f"iq-synthetic-budget-{index}",
            citation_id=citation_id,
        )
        for index, citation_id in enumerate(question_citations)
    ]
    citations = [
        make_citation(),
        *[
            make_citation(
                citation_id=citation_id,
                source_id=f"ks-synthetic-budget-{index}",
            )
            for index, citation_id in enumerate(
                (*requirement_citations, *question_citations)
            )
        ],
    ]
    repository = full_repository(
        requirements=requirements,
        patterns=[],
        questions=questions,
        citations=citations,
    )

    context = make_retriever(
        repository,
        prompt_char_limit=20_000,
    ).retrieve_for_job(make_job())

    assert context.status is KnowledgeRetrievalStatus.AVAILABLE
    assert len(context.citations) <= 20
    assert any(
        warning.code is KnowledgeWarningCode.BUDGET_TRUNCATED
        for warning in context.warnings
    )
    known = {citation.citation_id for citation in context.citations}
    assert all(
        set(item.citation_ids) <= known
        for item in (
            *context.inferred_role_profiles,
            *context.requirements,
            *context.interview_questions,
        )
    )


def test_tiny_character_budget_returns_safe_unavailable_context() -> None:
    context = make_retriever(
        full_repository(),
        prompt_char_limit=10,
    ).retrieve_for_job(make_job())

    assert context.status is KnowledgeRetrievalStatus.UNAVAILABLE
    assert context.inferred_role_profiles == []
    assert context.citations == []
    assert context.warnings[0].code is KnowledgeWarningCode.BUDGET_TRUNCATED


def test_auto_keyword_fallback_is_recorded_without_blocking_context() -> None:
    repository = full_repository(
        capabilities=KnowledgeSearchCapabilities(
            mode=KnowledgeSearchBackend.KEYWORD_FALLBACK,
            status=KnowledgeSearchCapabilityStatus.UNAVAILABLE,
            keyword_fallback_available=True,
        )
    )

    context = make_retriever(
        repository,
        search_mode=KnowledgeSearchMode.AUTO,
    ).retrieve_for_job(make_job())

    assert context.status is KnowledgeRetrievalStatus.AVAILABLE
    assert context.capabilities.mode is KnowledgeSearchBackend.KEYWORD_FALLBACK
    assert any(
        warning.code is KnowledgeWarningCode.SEARCH_FALLBACK
        for warning in context.warnings
    )


def test_cache_identity_is_stable_and_excludes_database_or_knowledge_text() -> None:
    context = make_retriever(full_repository()).retrieve_for_job(make_job())

    first = retriever_module().build_knowledge_cache_identity(
        context,
        requirement_limit=12,
        prompt_char_limit=8_000,
    )
    second = retriever_module().build_knowledge_cache_identity(
        context,
        requirement_limit=12,
        prompt_char_limit=8_000,
    )
    changed = retriever_module().build_knowledge_cache_identity(
        context,
        requirement_limit=10,
        prompt_char_limit=8_000,
    )

    assert first == second
    assert first != changed
    assert len(first) == 64
    assert "Synthetic" not in first
    assert "Users" not in first
