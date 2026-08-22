"""Global test safeguards."""

from __future__ import annotations

import socket
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from jobfit.config import Settings
from jobfit.generators import GeneratedAdvice
from jobfit.generators.diagnosis import finalize_diagnosis
from jobfit.generators.interview import finalize_questions
from jobfit.generators.rewrite import partition_rewrites
from jobfit.models import (
    AdviceBundleDraft,
    AnalysisReport,
    DocumentContent,
    EvidenceItem,
    EvidenceKind,
    EvidencePatternStrength,
    EvidenceRegistry,
    EvidenceSourceType,
    HardConditionKind,
    Importance,
    InterviewDifficulty,
    JobProfile,
    JobRequirement,
    JobRequirementCollection,
    KnowledgeBaseVersionInfo,
    KnowledgeCitation,
    KnowledgeContext,
    KnowledgeQuestionType,
    KnowledgeRetrievalStatus,
    KnowledgeSearchBackend,
    KnowledgeSearchCapabilities,
    KnowledgeSearchCapabilityStatus,
    KnowledgeSourceType,
    KnowledgeVersionStatus,
    LanguageCode,
    MatchScoreSummary,
    MatchStatus,
    ReliabilityLevel,
    RequirementCategory,
    RequirementMatch,
    RequirementMatchDraft,
    RequirementType,
    ResumeFact,
    ResumeProfile,
    RetrievedEvidencePattern,
    RetrievedInterviewQuestion,
    RetrievedRequirement,
    RetrievedRoleProfile,
)
from jobfit.parsers.text import TextDocumentParser
from jobfit.scoring import ScoringEngine
from jobfit.validators.report import build_analysis_report


@pytest.fixture
def available_knowledge_context() -> KnowledgeContext:
    """Small, reviewed, synthetic context shared by knowledge-advice tests."""

    version_id = "kbv-2026-07-1"
    citation_id = "cite-1111111111111111"
    role_id = "rp-synthetic-ai"
    requirement_id = "kr-synthetic-python"
    version = KnowledgeBaseVersionInfo(
        id=version_id,
        version="2026.07.1",
        name="Synthetic reviewed knowledge",
        status=KnowledgeVersionStatus.PUBLISHED,
        content_hash="a" * 64,
        published_at=datetime(2026, 7, 25, 8, 0, tzinfo=UTC),
    )
    citation = KnowledgeCitation(
        citation_id=citation_id,
        source_id="ks-synthetic-ai",
        source_title="Synthetic reviewed role source",
        source_type=KnowledgeSourceType.INTERNAL_TEMPLATE,
        source_url="https://example.test/knowledge/source",
        knowledge_version_id=version_id,
        reliability_level=ReliabilityLevel.HIGH,
        source_checksum="b" * 64,
    )
    role = RetrievedRoleProfile(
        role_profile_id=role_id,
        job_family_code="synthetic_ai",
        code="synthetic_ai_intern",
        name="Synthetic AI application intern",
        seniority="intern",
        description="Build bounded applications using reviewed practices.",
        relevance_score=Decimal("0.9000"),
        matched_terms=["synthetic", "ai"],
        matched_fields=["name"],
        citation_ids=[citation_id],
    )
    requirement = RetrievedRequirement(
        knowledge_requirement_id=requirement_id,
        role_profile_id=role_id,
        competency_dimension_code="application_engineering",
        title="Python application development",
        description="Use Python to implement bounded application logic.",
        requirement_type=RequirementType.MUST_HAVE,
        importance=Importance.HIGH,
        expected_evidence=["A concrete implementation action."],
        relevance_score=Decimal("0.8500"),
        matched_terms=["python"],
        matched_fields=["title"],
        citation_ids=[citation_id],
    )
    pattern = RetrievedEvidencePattern(
        evidence_pattern_id="ep-synthetic-python",
        knowledge_requirement_id=requirement_id,
        evidence_type="project",
        description="Look for a concrete implementation action.",
        strength=EvidencePatternStrength.STRONG,
        citation_ids=[citation_id],
    )
    question = RetrievedInterviewQuestion(
        knowledge_question_id="iq-synthetic-ai",
        role_profile_id=role_id,
        competency_dimension_code="application_engineering",
        question="Describe an application implementation.",
        question_type=KnowledgeQuestionType.PROJECT_DEEP_DIVE,
        expected_points=["context", "action", "validation"],
        difficulty=InterviewDifficulty.MEDIUM,
        relevance_score=Decimal("0.8000"),
        matched_terms=["application"],
        matched_fields=["question"],
        citation_ids=[citation_id],
    )
    return KnowledgeContext(
        status=KnowledgeRetrievalStatus.AVAILABLE,
        version=version,
        inferred_role_profiles=[role],
        requirements=[requirement],
        evidence_patterns=[pattern],
        interview_questions=[question],
        citations=[citation],
        capabilities=KnowledgeSearchCapabilities(
            mode=KnowledgeSearchBackend.KEYWORD_FALLBACK,
            status=KnowledgeSearchCapabilityStatus.AVAILABLE,
            keyword_fallback_available=True,
        ),
        retrieval_strategy_version="1.0",
    )


@pytest.fixture(autouse=True)
def block_network_for_offline_tests(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail any accidental network connection in the ordinary test suite."""

    if request.node.get_closest_marker("live_api") is not None:
        return

    def deny_network(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("Network access is disabled in offline tests")

    monkeypatch.setattr(socket.socket, "connect", deny_network)


@pytest.fixture(autouse=True)
def disable_local_dotenv_for_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the suite independent from an ignored developer dotenv file."""

    monkeypatch.setitem(Settings.model_config, "env_file", None)


@dataclass(frozen=True)
class MatchingCase:
    document: DocumentContent
    resume: ResumeProfile
    job: JobProfile
    registry: EvidenceRegistry

    def draft(
        self,
        requirement_id: str,
        status: MatchStatus,
        evidence_ids: tuple[str, ...] = (),
        *,
        reasoning: str = "依据已引用的简历原文作出克制判断。",
        confidence: str = "0.90",
        missing_note: str | None = None,
    ) -> RequirementMatchDraft:
        return RequirementMatchDraft(
            requirement_id=requirement_id,
            match_status=status,
            evidence_items=self.registry.require_many(evidence_ids),
            reasoning=reasoning,
            confidence=Decimal(confidence),
            missing_evidence_note=missing_note,
            improvement_suggestion="补充与该要求直接相关的真实项目证据。",
        )

    def match(
        self,
        requirement_id: str,
        status: MatchStatus,
        evidence_ids: tuple[str, ...] = (),
        *,
        reasoning: str = "依据已引用的简历原文作出克制判断。",
        confidence: str = "0.90",
        missing_note: str | None = None,
    ) -> RequirementMatch:
        status_values = {
            MatchStatus.MATCHED: Decimal("1.0"),
            MatchStatus.PARTIAL_MATCH: Decimal("0.6"),
            MatchStatus.NOT_MATCHED: Decimal("0.0"),
            MatchStatus.UNKNOWN: Decimal("0.0"),
        }
        return RequirementMatch(
            **self.draft(
                requirement_id,
                status,
                evidence_ids,
                reasoning=reasoning,
                confidence=confidence,
                missing_note=missing_note,
            ).model_dump(),
            match_score=status_values[status],
        )


@pytest.fixture
def matching_case() -> MatchingCase:
    resume_text = "\n".join(
        [
            "Python项目：使用Python完成数据处理。",
            "课程项目：学习机器学习模型。",
            "没有Python经验。",
            "没有Java经验。",
        ]
    )
    document = TextDocumentParser().parse_text(resume_text)

    def evidence(
        evidence_id: str,
        quote: str,
        kind: EvidenceKind,
    ) -> EvidenceItem:
        start = document.normalized_text.index(quote)
        segment = next(
            item
            for item in document.segments
            if item.start_char <= start < item.end_char
        )
        return EvidenceItem(
            evidence_id=evidence_id,
            document_id=document.document_id,
            segment_id=segment.segment_id,
            source_type=EvidenceSourceType.RESUME,
            source_reference=segment.segment_id,
            quote=quote,
            start_char=start,
            end_char=start + len(quote),
            page_number=segment.page_number,
            evidence_kind=kind,
            confidence=Decimal("0.95"),
        )

    evidence_items = [
        evidence("ev-python", "使用Python完成数据处理", EvidenceKind.DIRECT),
        evidence("ev-course", "课程项目：学习机器学习模型", EvidenceKind.DIRECT),
        evidence("ev-context", "课程项目：学习机器学习模型", EvidenceKind.CONTEXTUAL),
        evidence("ev-no-python", "没有Python经验", EvidenceKind.DIRECT),
        evidence("ev-no-java", "没有Java经验", EvidenceKind.DIRECT),
    ]
    registry = EvidenceRegistry(evidence_items)
    resume = ResumeProfile(
        resume_id="resume-test",
        document_id=document.document_id,
        language=LanguageCode.ZH,
        additional_information=[
            ResumeFact(
                fact_id=f"fact-{index}",
                fact_type="test_fact",
                text=item.quote,
                evidence_ids=[item.evidence_id],
            )
            for index, item in enumerate(evidence_items, start=1)
        ],
    )

    jd_text = "\n".join(
        [
            "要求：熟悉Python。",
            "要求：具有生产级机器学习部署经验。",
            "要求：熟悉Java。",
            "要求：熟悉SQL。",
        ]
    )

    def requirement(
        requirement_id: str,
        source_text: str,
        category: RequirementCategory,
    ) -> JobRequirement:
        start = jd_text.index(source_text)
        return JobRequirement(
            requirement_id=requirement_id,
            requirement_text=source_text,
            source_text=source_text,
            source_start_char=start,
            source_end_char=start + len(source_text),
            requirement_type=RequirementType.MUST_HAVE,
            category=category,
            importance=Importance.HIGH,
            mandatory=True,
            hard_condition_kind=HardConditionKind.NONE,
            normalized_key=requirement_id,
            priority_factor=Decimal("0"),
            weight=Decimal("0"),
        )

    requirements = [
        requirement(
            "req-python",
            "熟悉Python",
            RequirementCategory.TECHNICAL_SKILL,
        ),
        requirement(
            "req-production",
            "具有生产级机器学习部署经验",
            RequirementCategory.EXPERIENCE_PROJECT,
        ),
        requirement(
            "req-java",
            "熟悉Java",
            RequirementCategory.TECHNICAL_SKILL,
        ),
        requirement(
            "req-sql",
            "熟悉SQL",
            RequirementCategory.TECHNICAL_SKILL,
        ),
    ]
    job = JobProfile(
        job_id="job-test",
        title="AI应用开发实习生",
        language=LanguageCode.ZH,
        jd_text=jd_text,
        summary="匿名测试岗位。",
        requirements=JobRequirementCollection(
            items=requirements,
            source_coverage_ratio=Decimal("1"),
        ),
    )
    return MatchingCase(
        document=document,
        resume=resume,
        job=job,
        registry=registry,
    )


@dataclass(frozen=True)
class AdviceCase:
    document: DocumentContent
    resume: ResumeProfile
    job: JobProfile
    registry: EvidenceRegistry
    matches: list[RequirementMatch]
    score: MatchScoreSummary


@pytest.fixture
def advice_case(matching_case: MatchingCase) -> AdviceCase:
    matches = [
        matching_case.match(
            "req-python",
            MatchStatus.MATCHED,
            ("ev-python",),
            reasoning="简历明确写明使用Python完成数据处理。",
        ),
        matching_case.match(
            "req-production",
            MatchStatus.PARTIAL_MATCH,
            ("ev-course",),
            reasoning="课程项目相关，但没有生产部署证据。",
        ),
        matching_case.match(
            "req-java",
            MatchStatus.NOT_MATCHED,
            ("ev-no-java",),
            reasoning="简历明确写明没有Java经验。",
            missing_note="存在明确否定表述。",
        ),
        matching_case.match(
            "req-sql",
            MatchStatus.UNKNOWN,
            reasoning="当前简历没有足够证据确认SQL能力。",
            missing_note="当前简历未提供足够证据确认该能力。",
        ),
    ]
    score = ScoringEngine().score(
        matching_case.job.requirements.items,
        matches,
    )
    return AdviceCase(
        document=matching_case.document,
        resume=matching_case.resume,
        job=matching_case.job,
        registry=matching_case.registry,
        matches=matches,
        score=score,
    )


@dataclass(frozen=True)
class ReportCase:
    document: DocumentContent
    resume: ResumeProfile
    job: JobProfile
    registry: EvidenceRegistry
    matches: list[RequirementMatch]
    score: MatchScoreSummary
    advice: GeneratedAdvice
    limitations: list[str]


@pytest.fixture
def report_case(advice_case: AdviceCase) -> ReportCase:
    fixture_path = (
        Path(__file__).parent
        / "fixtures"
        / "llm_responses"
        / "generate_advice_bundle.json"
    )
    draft = AdviceBundleDraft.model_validate_json(
        fixture_path.read_text(encoding="utf-8")
    )
    strengths, gaps, recommendation = finalize_diagnosis(
        draft,
        advice_case.job,
        advice_case.matches,
        advice_case.score,
        advice_case.registry,
    )
    direct, confirmation = partition_rewrites(
        draft.rewrite_suggestions,
        advice_case.job.requirements.items,
        advice_case.registry,
    )
    questions = finalize_questions(
        draft.interview_questions,
        advice_case.job.requirements.items,
        advice_case.registry,
        gaps,
    )
    advice = GeneratedAdvice(
        strengths=strengths,
        gaps=gaps,
        recommendation=recommendation,
        direct_rewrites=direct,
        confirmation_required_rewrites=confirmation,
        interview_questions=questions,
    )
    return ReportCase(
        document=advice_case.document,
        resume=advice_case.resume,
        job=advice_case.job,
        registry=advice_case.registry,
        matches=advice_case.matches,
        score=advice_case.score,
        advice=advice,
        limitations=[
            "匹配分数不是录用概率。",
            "unknown表示当前简历证据不足。",
        ],
    )


@pytest.fixture
def analysis_report(report_case: ReportCase) -> AnalysisReport:
    return build_analysis_report(
        document=report_case.document,
        resume=report_case.resume,
        job=report_case.job,
        matches=report_case.matches,
        score=report_case.score,
        advice=report_case.advice,
        registry=report_case.registry,
        limitations=report_case.limitations,
        report_id="report-export-test",
        generated_at=datetime(2026, 7, 23, 10, 0, tzinfo=UTC),
    )
