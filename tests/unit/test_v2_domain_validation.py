"""Cross-object validation for the target JobFit domain snapshot."""

from __future__ import annotations

from decimal import Decimal

import pytest

from jobfit.errors import ErrorCode, SchemaValidationError
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
    CitationUsage,
    Confidence,
    CriticalStatus,
    EligibilityStatus,
    Evidence,
    EvidenceLevel,
    EvidenceSourceOrigin,
    EvidenceStatus,
    InterviewQuestion,
    InterviewQuestionType,
    JobFamily,
    JobFitDomainBundle,
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
    Relevance,
    Requirement,
    RequirementExplicitness,
    RequirementMatch,
    RequirementSource,
    RequirementType,
    ResumeProfile,
    SeniorityAlignment,
    SupportType,
    UserClarification,
    ValidityStatus,
    VersionManifest,
)
from jobfit.validators.v2 import DomainValidator


def make_valid_bundle() -> JobFitDomainBundle:
    evidence = Evidence(
        evidence_id="ev-001",
        resume_version_id="resume-v1",
        source_origin=EvidenceSourceOrigin.RESUME,
        source_type="project",
        source_text="Built API",
        document_id="doc-resume-v1",
        segment_id="seg-001",
        start_char=10,
        end_char=19,
        evidence_level=EvidenceLevel.L3,
    )
    resume = ResumeProfile(
        resume_version_id="resume-v1",
        candidate_profile=CandidateProfile(),
        evidence_ids=[evidence.evidence_id],
        parse_completeness=ParseCompleteness.COMPLETE,
    )
    requirement = Requirement(
        requirement_id="req-001",
        jd_snapshot_id="jd-v1",
        raw_requirement_ids=["raw-001"],
        raw_text="Build AI applications",
        normalized_capability="AI application development",
        requirement_type=RequirementType.CORE,
        importance=Importance.HIGH,
        explicitness=RequirementExplicitness.EXPLICIT,
        source=RequirementSource.JD,
        critical_status=CriticalStatus.CANDIDATE,
    )
    job = JobProfile(
        jd_snapshot_id="jd-v1",
        job_title="AI Application Intern",
        job_family=JobFamily.AI_APPLICATION,
        knowledge_coverage=KnowledgeCoverage.ENHANCED,
        requirement_ids=[requirement.requirement_id],
    )
    match = RequirementMatch(
        match_id="match-001",
        requirement_id=requirement.requirement_id,
        matched_evidence=[
            MatchedEvidence(
                evidence_id=evidence.evidence_id,
                relevance=Relevance.HIGH,
                support_type=SupportType.DIRECT,
            )
        ],
        coverage=MatchCoverage.FULL,
        evidence_status=EvidenceStatus.PRESENT,
        ability_status=AbilityStatus.CONFIRMED,
        best_evidence_level=EvidenceLevel.L3,
        match_score_component=Decimal("0.85"),
    )
    core = AnalysisCore(
        analysis_id="analysis-001",
        resume_version_id=resume.resume_version_id,
        jd_snapshot_id=job.jd_snapshot_id,
        analysis_readiness=AnalysisReadiness.READY,
        eligibility_status=EligibilityStatus.MET,
        seniority_alignment=SeniorityAlignment.ALIGNED,
        base_fit_score=Decimal("80"),
        preferred_bonus=Decimal("3"),
        final_fit_score=Decimal("83"),
        confidence=Confidence.HIGH,
        recommendation=Recommendation.SUGGESTED,
        recommendation_reason_codes=["CORE_COVERAGE_STRONG"],
    )
    action = ActionRecommendation(
        action_id="action-001",
        action_type=ActionType.REWRITE,
        priority=Priority.P0,
        title="Clarify the existing project",
        related_requirement_ids=[requirement.requirement_id],
        related_evidence_ids=[evidence.evidence_id],
        supported_by_evidence_ids=[evidence.evidence_id],
    )
    citation = KnowledgeCitation(
        citation_id="citation-001",
        knowledge_version="2026.08.1",
        source_id="source-001",
        role_family=JobFamily.AI_APPLICATION,
        usage=CitationUsage.INTERVIEW_PREPARATION,
    )
    question = InterviewQuestion(
        question_id="question-001",
        question_type=InterviewQuestionType.ROLE_CAPABILITY,
        priority=Priority.P1,
        question="How would you validate structured output?",
        related_requirement_ids=[requirement.requirement_id],
        related_evidence_ids=[evidence.evidence_id],
        knowledge_citation_ids=[citation.citation_id],
    )
    versions = VersionManifest(
        software_version="1.1.0",
        prompt_pack_version="1.0.0",
        schema_version=NOT_EXPLICITLY_VERSIONED,
        scoring_rule_version=NOT_EXPLICITLY_VERSIONED,
        knowledge_version="2026.08.1",
        analysis_engine_version=NOT_EXPLICITLY_VERSIONED,
    )
    report = JobFitReport(
        report_id="report-001",
        analysis_id=core.analysis_id,
        summary={"recommendation": "suggested"},
        application_strategy={"next_step": "apply"},
    )
    lifecycle = AnalysisLifecycle(
        analysis_id=core.analysis_id,
        status=LifecycleStatus.COMPLETED,
        validity=ValidityStatus.VALID,
    )
    return JobFitDomainBundle(
        resume_profile=resume,
        evidence=[evidence],
        job_profile=job,
        requirements=[requirement],
        requirement_matches=[match],
        analysis_core=core,
        actions=[action],
        interview_questions=[question],
        knowledge_citations=[citation],
        user_clarifications=[],
        report=report,
        versions=versions,
        analysis_lifecycle=lifecycle,
    )


def _codes(bundle: JobFitDomainBundle) -> set[str]:
    return {issue.code for issue in DomainValidator().validate(bundle).issues}


def test_valid_domain_bundle_has_deterministic_cross_object_validation() -> None:
    bundle = make_valid_bundle()

    first = DomainValidator().validate(bundle)
    second = DomainValidator().validate(bundle)

    assert first.valid is True
    assert first.issues == []
    assert first == second


def test_duplicate_and_dangling_ids_fail_closed() -> None:
    bundle = make_valid_bundle()
    invalid = bundle.model_copy(
        update={
            "evidence": [bundle.evidence[0], bundle.evidence[0]],
            "job_profile": bundle.job_profile.model_copy(
                update={"requirement_ids": ["req-missing"]}
            ),
            "requirement_matches": [
                bundle.requirement_matches[0].model_copy(
                    update={
                        "matched_evidence": [
                            MatchedEvidence(
                                evidence_id="ev-missing",
                                relevance=Relevance.HIGH,
                                support_type=SupportType.DIRECT,
                            )
                        ]
                    }
                )
            ],
        }
    )

    assert _codes(invalid) >= {
        "DUPLICATE_EVIDENCE_ID",
        "DANGLING_JOB_REQUIREMENT_REFERENCE",
        "DANGLING_MATCH_EVIDENCE_REFERENCE",
    }


def test_knowledge_citation_cannot_share_candidate_evidence_identity() -> None:
    bundle = make_valid_bundle()
    citation = bundle.knowledge_citations[0].model_copy(
        update={"citation_id": bundle.evidence[0].evidence_id}
    )
    invalid = bundle.model_copy(update={"knowledge_citations": [citation]})

    assert "KNOWLEDGE_CANDIDATE_EVIDENCE_COLLISION" in _codes(invalid)


def test_confirmed_gap_requires_a_matching_user_clarification_reference() -> None:
    bundle = make_valid_bundle()
    confirmed_gap = RequirementMatch(
        match_id="match-001",
        requirement_id="req-001",
        matched_evidence=[],
        coverage=MatchCoverage.NONE,
        evidence_status=EvidenceStatus.MISSING,
        ability_status=AbilityStatus.CONFIRMED_GAP,
        ability_confirmation_id="clarification-001",
    )
    missing_clarification = bundle.model_copy(
        update={"requirement_matches": [confirmed_gap]}
    )
    assert "DANGLING_ABILITY_CONFIRMATION_REFERENCE" in _codes(
        missing_clarification
    )

    unrelated = UserClarification(
        clarification_id="clarification-001",
        analysis_id="analysis-001",
        question="Can you deploy the service?",
        answer="No.",
        affected_requirement_ids=["req-other"],
        affects_recommendation=True,
    )
    wrong_target = missing_clarification.model_copy(
        update={"user_clarifications": [unrelated]}
    )
    assert "ABILITY_CONFIRMATION_TARGET_MISMATCH" in _codes(wrong_target)


def test_version_and_report_identity_mismatches_are_rejected() -> None:
    bundle = make_valid_bundle()
    invalid = bundle.model_copy(
        update={
            "evidence": [
                bundle.evidence[0].model_copy(
                    update={"resume_version_id": "resume-v2"}
                )
            ],
            "knowledge_citations": [
                bundle.knowledge_citations[0].model_copy(
                    update={"knowledge_version": "2026.09.1"}
                )
            ],
            "report": bundle.report.model_copy(update={"analysis_id": "analysis-2"}),
            "analysis_lifecycle": bundle.analysis_lifecycle.model_copy(
                update={"analysis_id": "analysis-2"}
            ),
        }
    )

    assert _codes(invalid) >= {
        "EVIDENCE_RESUME_VERSION_MISMATCH",
        "KNOWLEDGE_VERSION_MISMATCH",
        "REPORT_ANALYSIS_ID_MISMATCH",
        "LIFECYCLE_ANALYSIS_ID_MISMATCH",
    }


def test_implicit_knowledge_requirement_never_enters_core_scoring_or_guards() -> None:
    bundle = make_valid_bundle()
    implicit = Requirement(
        requirement_id="req-implicit",
        normalized_capability="Role context",
        requirement_type=RequirementType.IMPLICIT,
        importance=Importance.MEDIUM,
        explicitness=RequirementExplicitness.IMPLICIT,
        source=RequirementSource.KNOWLEDGE,
        knowledge_citation_ids=["citation-001"],
    )
    implicit_match = RequirementMatch(
        match_id="match-implicit",
        requirement_id=implicit.requirement_id,
        matched_evidence=[
            MatchedEvidence(
                evidence_id="ev-001",
                relevance=Relevance.LOW,
                support_type=SupportType.CONTEXTUAL,
            )
        ],
        coverage=MatchCoverage.WEAK,
        evidence_status=EvidenceStatus.WEAK,
        ability_status=AbilityStatus.UNKNOWN,
        best_evidence_level=EvidenceLevel.L1,
        match_score_component=Decimal("0.2"),
    )
    invalid = bundle.model_copy(
        update={
            "requirements": [*bundle.requirements, implicit],
            "requirement_matches": [*bundle.requirement_matches, implicit_match],
            "analysis_core": bundle.analysis_core.model_copy(
                update={"critical_gap_requirement_ids": [implicit.requirement_id]}
            ),
        }
    )

    assert _codes(invalid) >= {
        "IMPLICIT_REQUIREMENT_SCORE_COMPONENT",
        "IMPLICIT_REQUIREMENT_DECISION_GUARD",
    }


def test_hard_and_critical_guards_only_reference_their_frozen_requirement_types(
) -> None:
    bundle = make_valid_bundle()
    invalid = bundle.model_copy(
        update={
            "analysis_core": bundle.analysis_core.model_copy(
                update={
                    "hard_pending_ids": ["req-001"],
                    "critical_gap_requirement_ids": ["req-001"],
                }
            )
        }
    )

    assert _codes(invalid) >= {
        "HARD_GUARD_REQUIREMENT_TYPE_INVALID",
        "CRITICAL_GAP_REQUIREMENT_INVALID",
    }


def test_clarification_created_evidence_must_keep_user_source_identity() -> None:
    bundle = make_valid_bundle()
    clarification = UserClarification(
        clarification_id="clarification-001",
        analysis_id="analysis-001",
        question="What did you personally own?",
        answer="I implemented validation.",
        creates_evidence=True,
        created_evidence_ids=["ev-001"],
    )
    invalid = bundle.model_copy(update={"user_clarifications": [clarification]})

    assert "CLARIFICATION_EVIDENCE_SOURCE_MISMATCH" in _codes(invalid)


def test_validate_or_raise_uses_the_existing_safe_schema_error_boundary() -> None:
    bundle = make_valid_bundle().model_copy(
        update={"report": make_valid_bundle().report.model_copy(
            update={"analysis_id": "missing-analysis"}
        )}
    )

    with pytest.raises(SchemaValidationError) as exc_info:
        DomainValidator().validate_or_raise(bundle)

    assert exc_info.value.code is ErrorCode.SCHEMA_VALIDATION_FAILED
    assert "report" not in exc_info.value.user_message.casefold()
    assert exc_info.value.cause is None
