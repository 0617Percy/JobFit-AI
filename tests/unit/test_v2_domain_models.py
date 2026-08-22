"""Field and business-invariant tests for the isolated v2 domain models."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from jobfit.models.common import Importance
from jobfit.models.v2 import (
    NOT_EXPLICITLY_VERSIONED,
    AbilityStatus,
    ActionRecommendation,
    ActionType,
    AnalysisCore,
    AnalysisLifecycle,
    AnalysisReadiness,
    CandidateProfile,
    CandidateStatus,
    CitationUsage,
    Confidence,
    CriticalStatus,
    EligibilityStatus,
    Evidence,
    EvidenceLevel,
    EvidenceSourceOrigin,
    EvidenceStatus,
    Failure,
    FailureImpactLevel,
    InterviewQuestion,
    InterviewQuestionType,
    JobFamily,
    JobFitReport,
    JobProfile,
    KnowledgeCitation,
    KnowledgeCoverage,
    LifecycleStatus,
    MatchCoverage,
    MatchedEvidence,
    ParseCompleteness,
    Priority,
    Recommendation,
    RecomputeFrom,
    Requirement,
    RequirementExplicitness,
    RequirementMatch,
    RequirementSource,
    RequirementType,
    ResumeProfile,
    SeniorityAlignment,
    SupportType,
    TaskStatus,
    UserClarification,
    ValidityStatus,
    VersionManifest,
)


def make_evidence(**updates: object) -> Evidence:
    payload: dict[str, object] = {
        "evidence_id": "ev-001",
        "resume_version_id": "resume-v1",
        "source_origin": EvidenceSourceOrigin.RESUME,
        "source_type": "project",
        "source_text": "Built API",
        "document_id": "doc-resume-v1",
        "segment_id": "seg-001",
        "start_char": 10,
        "end_char": 19,
        "evidence_level": EvidenceLevel.L3,
    }
    payload.update(updates)
    return Evidence(**payload)


def make_requirement(**updates: object) -> Requirement:
    payload: dict[str, object] = {
        "requirement_id": "req-001",
        "jd_snapshot_id": "jd-v1",
        "raw_requirement_ids": ["raw-001"],
        "raw_text": "Build AI applications",
        "normalized_capability": "AI application development",
        "requirement_type": RequirementType.CORE,
        "importance": Importance.HIGH,
        "explicitness": RequirementExplicitness.EXPLICIT,
        "source": RequirementSource.JD,
        "critical_status": CriticalStatus.CANDIDATE,
    }
    payload.update(updates)
    return Requirement(**payload)


def make_match(**updates: object) -> RequirementMatch:
    payload: dict[str, object] = {
        "match_id": "match-001",
        "requirement_id": "req-001",
        "matched_evidence": [
            MatchedEvidence(
                evidence_id="ev-001",
                relevance="high",
                support_type=SupportType.DIRECT,
            )
        ],
        "coverage": MatchCoverage.FULL,
        "evidence_status": EvidenceStatus.PRESENT,
        "ability_status": AbilityStatus.CONFIRMED,
        "best_evidence_level": EvidenceLevel.L3,
    }
    payload.update(updates)
    return RequirementMatch(**payload)


def make_analysis_core(**updates: object) -> AnalysisCore:
    payload: dict[str, object] = {
        "analysis_id": "analysis-001",
        "resume_version_id": "resume-v1",
        "jd_snapshot_id": "jd-v1",
        "analysis_readiness": AnalysisReadiness.READY,
        "eligibility_status": EligibilityStatus.MET,
        "seniority_alignment": SeniorityAlignment.ALIGNED,
        "base_fit_score": Decimal("80"),
        "preferred_bonus": Decimal("3"),
        "final_fit_score": Decimal("83"),
        "confidence": Confidence.HIGH,
        "recommendation": Recommendation.SUGGESTED,
        "recommendation_reason_codes": ["CORE_COVERAGE_STRONG"],
    }
    payload.update(updates)
    return AnalysisCore(**payload)


def test_evidence_preserves_grounding_and_rejects_l0_or_bad_offsets() -> None:
    evidence = make_evidence(provider_metadata={"model": "semantic-only"})

    assert evidence.source_text == "Built API"
    assert evidence.document_id == "doc-resume-v1"
    assert evidence.segment_id == "seg-001"
    assert evidence.start_char == 10
    assert evidence.end_char == 19
    assert evidence.provider_metadata == {"model": "semantic-only"}

    with pytest.raises(ValidationError, match="evidence_level"):
        make_evidence(evidence_level="L0")
    with pytest.raises(ValidationError, match="offset"):
        make_evidence(end_char=18)


def test_user_clarification_evidence_keeps_a_distinct_source_identity() -> None:
    evidence = Evidence(
        evidence_id="ev-clarification-001",
        source_origin=EvidenceSourceOrigin.USER_CLARIFICATION,
        source_type="clarification_answer",
        source_record_id="clarification-001",
        source_text="I did not own deployment.",
        evidence_level=EvidenceLevel.L2,
    )

    assert evidence.resume_version_id is None
    assert evidence.source_record_id == "clarification-001"

    with pytest.raises(ValidationError, match="source_record_id"):
        Evidence(
            evidence_id="ev-clarification-002",
            source_origin=EvidenceSourceOrigin.USER_CLARIFICATION,
            source_type="clarification_answer",
            source_text="I did not own deployment.",
            evidence_level=EvidenceLevel.L2,
        )


def test_resume_and_job_profiles_validate_identity_lists_without_old_ids() -> None:
    resume = ResumeProfile(
        resume_version_id="resume-v1",
        candidate_profile=CandidateProfile(
            current_status=CandidateStatus.STUDENT,
            education_level="bachelor",
        ),
        evidence_ids=["ev-001"],
        parse_completeness=ParseCompleteness.COMPLETE,
    )
    JobProfile(
        jd_snapshot_id="jd-v1",
        job_title="AI Application Intern",
        job_family=JobFamily.AI_APPLICATION,
        knowledge_coverage=KnowledgeCoverage.ENHANCED,
        requirement_ids=["req-001"],
    )

    assert "resume_id" not in ResumeProfile.model_fields
    assert "job_id" not in JobProfile.model_fields

    with pytest.raises(ValidationError, match="unique"):
        ResumeProfile(
            resume_version_id=resume.resume_version_id,
            candidate_profile=resume.candidate_profile,
            evidence_ids=["ev-001", "ev-001"],
            parse_completeness=resume.parse_completeness,
        )
    with pytest.raises(ValidationError, match="unique"):
        JobProfile(
            jd_snapshot_id="jd-v1",
            job_title="AI Application Intern",
            job_family=JobFamily.AI_APPLICATION,
            knowledge_coverage=KnowledgeCoverage.ENHANCED,
            requirement_ids=["req-001", "req-001"],
        )


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        (
            {
                "requirement_type": RequirementType.IMPLICIT,
                "source": RequirementSource.JD,
                "explicitness": RequirementExplicitness.IMPLICIT,
            },
            "Implicit requirements must come from knowledge",
        ),
        (
            {
                "requirement_type": RequirementType.HARD,
                "source": RequirementSource.KNOWLEDGE,
                "explicitness": RequirementExplicitness.IMPLICIT,
            },
            "Knowledge requirements must be implicit",
        ),
        (
            {
                "source": RequirementSource.KNOWLEDGE,
                "explicitness": RequirementExplicitness.EXPLICIT,
            },
            "Knowledge cannot be an explicit requirement",
        ),
    ],
)
def test_requirement_enforces_jd_and_knowledge_ownership(
    updates: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        make_requirement(**updates)


def test_requirement_match_keeps_evidence_and_ability_status_distinct() -> None:
    missing = make_match(
        matched_evidence=[],
        coverage=MatchCoverage.NONE,
        evidence_status=EvidenceStatus.MISSING,
        ability_status=AbilityStatus.UNKNOWN,
        best_evidence_level=None,
    )
    confirmed_gap = missing.model_copy(
        update={
            "ability_status": AbilityStatus.CONFIRMED_GAP,
            "ability_confirmation_id": "clarification-001",
        }
    )

    assert missing.ability_status is AbilityStatus.UNKNOWN
    assert confirmed_gap.ability_status is AbilityStatus.CONFIRMED_GAP

    with pytest.raises(ValidationError, match="explicit clarification"):
        make_match(
            matched_evidence=[],
            coverage=MatchCoverage.NONE,
            evidence_status=EvidenceStatus.MISSING,
            ability_status=AbilityStatus.CONFIRMED_GAP,
            best_evidence_level=None,
        )
    with pytest.raises(ValidationError, match="conflict"):
        make_match(
            evidence_status=EvidenceStatus.CONFLICT,
            ability_status=AbilityStatus.CONFIRMED,
        )


def test_analysis_core_rejects_invalid_deterministic_state_combinations() -> None:
    with pytest.raises(ValidationError, match="blocked eligibility"):
        make_analysis_core(
            eligibility_status=EligibilityStatus.BLOCKED,
            recommendation=Recommendation.CHALLENGE,
        )
    with pytest.raises(ValidationError, match="priority"):
        make_analysis_core(
            confidence=Confidence.LOW,
            recommendation=Recommendation.PRIORITY,
        )
    with pytest.raises(ValidationError, match="clarification_required"):
        make_analysis_core(
            analysis_readiness=AnalysisReadiness.CLARIFICATION_REQUIRED,
            eligibility_status=EligibilityStatus.MET,
        )


def test_actions_enforce_rewrite_recover_build_evidence_boundaries() -> None:
    rewrite = ActionRecommendation(
        action_id="action-rewrite-001",
        action_type=ActionType.REWRITE,
        priority=Priority.P0,
        title="Clarify the existing project",
        related_requirement_ids=["req-001"],
        related_evidence_ids=["ev-001"],
        supported_by_evidence_ids=["ev-001"],
    )
    assert rewrite.supported_by_evidence_ids == ["ev-001"]

    with pytest.raises(ValidationError, match="candidate evidence"):
        ActionRecommendation(
            action_id="action-recover-001",
            action_type=ActionType.RECOVER,
            priority=Priority.P1,
            title="Recover omitted experience",
        )
    with pytest.raises(ValidationError, match="cannot claim existing evidence"):
        ActionRecommendation(
            action_id="action-build-001",
            action_type=ActionType.BUILD,
            priority=Priority.P1,
            title="Build a new deployment project",
            supported_by_evidence_ids=["ev-001"],
        )


def test_clarification_failure_versions_and_lifecycle_are_pure_contracts() -> None:
    clarification = UserClarification(
        clarification_id="clarification-001",
        analysis_id="analysis-001",
        question="Did you own deployment?",
        answer="No.",
        affected_requirement_ids=["req-001"],
        creates_evidence=False,
        affects_recommendation=True,
    )
    failure = Failure(
        failure_id="failure-001",
        failure_stage="matching",
        failure_code="MATCH_SCHEMA_INVALID",
        impact_level=FailureImpactLevel.DECISION_UNSAFE,
        retryable=False,
        user_action_required=True,
        last_successful_stage="evidence",
        technical_message="Cross-object validation failed.",
        user_message="The analysis could not be completed safely.",
    )
    versions = VersionManifest(
        software_version="1.1.0",
        prompt_pack_version="1.0.0",
        schema_version=NOT_EXPLICITLY_VERSIONED,
        scoring_rule_version=NOT_EXPLICITLY_VERSIONED,
        knowledge_version="2026.08.1",
        analysis_engine_version=NOT_EXPLICITLY_VERSIONED,
        business_test_set_version=NOT_EXPLICITLY_VERSIONED,
        golden_set_version=NOT_EXPLICITLY_VERSIONED,
    )
    lifecycle = AnalysisLifecycle(
        analysis_id="analysis-001",
        status=LifecycleStatus.ANALYZING,
        validity=ValidityStatus.VALID,
        recompute_from=RecomputeFrom.NONE,
        resume_parse_status=TaskStatus.COMPLETED,
        jd_parse_status=TaskStatus.COMPLETED,
        match_status=TaskStatus.RUNNING,
    )

    assert clarification.source_origin is EvidenceSourceOrigin.USER_CLARIFICATION
    assert failure.impact_level is FailureImpactLevel.DECISION_UNSAFE
    assert versions.schema_version == NOT_EXPLICITLY_VERSIONED
    assert lifecycle.match_status is TaskStatus.RUNNING


def test_interview_citation_and_report_match_the_structured_schema_shape() -> None:
    question = InterviewQuestion(
        question_id="question-001",
        question_type=InterviewQuestionType.ROLE_CAPABILITY,
        priority=Priority.P1,
        question="How would you validate structured model output?",
        related_requirement_ids=["req-001"],
        related_evidence_ids=["ev-001"],
        preparation_points=["Explain validation and failure handling."],
        knowledge_citation_ids=["citation-001"],
    )
    citation = KnowledgeCitation(
        citation_id="citation-001",
        knowledge_version="2026.08.1",
        source_id="source-001",
        role_family=JobFamily.AI_APPLICATION,
        usage=CitationUsage.INTERVIEW_PREPARATION,
    )
    report = JobFitReport(
        report_id="report-001",
        analysis_id="analysis-001",
        summary={"recommendation": "suggested"},
        application_strategy={"next_step": "apply"},
        interview_preparation=[question.model_dump(mode="json")],
    )

    assert citation.citation_id == "citation-001"
    assert report.analysis_id == "analysis-001"
    assert report.interview_preparation[0]["question_id"] == "question-001"


def test_decimal_and_json_serialization_are_deterministic() -> None:
    core = make_analysis_core()

    first = core.model_dump_json()
    second = core.model_dump_json()

    assert first == second
    assert '"base_fit_score":"80"' in first
