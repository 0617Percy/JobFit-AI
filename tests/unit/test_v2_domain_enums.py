"""Frozen enum contracts for the product-architecture domain boundary."""

from __future__ import annotations

from jobfit.models.common import RequirementType as LegacyRequirementType
from jobfit.models.v2 import (
    AbilityStatus,
    ActionTiming,
    ActionType,
    AnalysisReadiness,
    CandidateStatus,
    CitationUsage,
    CriticalStatus,
    EligibilityStatus,
    EvidenceLevel,
    EvidenceSourceOrigin,
    EvidenceStatus,
    FailureImpactLevel,
    JobFamily,
    KnowledgeCoverage,
    LifecycleStatus,
    MatchCoverage,
    ParseCompleteness,
    Priority,
    ReasonCode,
    Recommendation,
    RecomputeFrom,
    Relevance,
    RequirementExplicitness,
    RequirementSource,
    RequirementType,
    SeniorityAlignment,
    SupportType,
    TaskStatus,
    ValidityStatus,
)


def _values(enum_type: type) -> set[str]:
    return {item.value for item in enum_type}


def test_frozen_semantic_enums_use_the_planning_pack_values() -> None:
    assert _values(EvidenceSourceOrigin) == {
        "resume",
        "user_clarification",
        "portfolio",
        "external_verification",
    }
    assert _values(EvidenceLevel) == {"L1", "L2", "L3", "L4"}
    assert _values(CandidateStatus) == {
        "student",
        "fresh_graduate",
        "early_career",
        "unknown",
    }
    assert _values(ParseCompleteness) == {"complete", "partial", "insufficient"}
    assert _values(RequirementType) == {
        "hard",
        "core",
        "supporting",
        "preferred",
        "implicit",
    }
    assert _values(RequirementExplicitness) == {"explicit", "implicit"}
    assert _values(RequirementSource) == {"jd", "knowledge"}
    assert _values(CriticalStatus) == {
        "confirmed",
        "candidate",
        "not_critical",
    }
    assert _values(JobFamily) == {
        "ai_application",
        "data_analytics",
        "technology_strategy",
        "other",
        "unknown",
    }
    assert _values(KnowledgeCoverage) == {
        "enhanced",
        "base_only",
        "partial",
        "unavailable",
    }
    assert _values(Relevance) == {"high", "medium", "low"}
    assert _values(SupportType) == {"direct", "transferable", "contextual"}
    assert _values(MatchCoverage) == {
        "full",
        "substantial",
        "partial",
        "weak",
        "none",
    }
    assert _values(EvidenceStatus) == {"present", "weak", "missing", "conflict"}
    assert _values(AbilityStatus) == {
        "confirmed",
        "confirmed_gap",
        "unknown",
        "conflict",
    }


def test_frozen_decision_and_lifecycle_enums_use_the_planning_pack_values() -> None:
    assert _values(AnalysisReadiness) == {
        "ready",
        "ready_with_gaps",
        "clarification_recommended",
        "clarification_required",
        "review_required",
    }
    assert _values(EligibilityStatus) == {"met", "pending", "blocked"}
    assert _values(SeniorityAlignment) == {
        "aligned",
        "borderline",
        "misaligned",
    }
    assert _values(Recommendation) == {
        "priority",
        "suggested",
        "challenge",
        "not_recommended",
    }
    assert _values(ActionType) == {"rewrite", "recover", "build"}
    assert _values(Priority) == {"p0", "p1", "p2"}
    assert _values(ActionTiming) == {
        "before_apply",
        "parallel_with_applications",
        "long_term",
    }
    assert _values(CitationUsage) == {
        "job_explanation",
        "implicit_requirement",
        "build_recommendation",
        "interview_preparation",
    }
    assert _values(LifecycleStatus) == {
        "draft",
        "input_ready",
        "parsing",
        "review_required",
        "analysis_ready",
        "analyzing",
        "report_generating",
        "completed",
        "needs_reanalysis",
        "failed",
    }
    assert _values(TaskStatus) == {"not_started", "running", "completed", "failed"}
    assert _values(ValidityStatus) == {"valid", "stale", "invalid"}
    assert _values(RecomputeFrom) == {
        "none",
        "resume_parse",
        "jd_parse",
        "evidence",
        "readiness",
        "matching",
        "eligibility",
        "scoring",
        "recommendation",
        "actions",
        "interview",
        "report",
    }
    assert _values(FailureImpactLevel) == {"F0", "F1", "F2", "F3"}
    assert _values(ReasonCode) == {
        "HIGH_FIT_SCORE",
        "MEDIUM_FIT_SCORE",
        "LOW_FIT_SCORE",
        "HARD_BLOCKER",
        "HARD_PENDING",
        "CRITICAL_GAP_ONE",
        "CRITICAL_GAP_MULTIPLE",
        "CORE_COVERAGE_STRONG",
        "CORE_COVERAGE_WEAK",
        "STRONG_TRANSFERABLE_EVIDENCE",
        "LOW_CONFIDENCE",
        "SENIORITY_MISMATCH",
        "SENIORITY_BORDERLINE",
        "FORCED_CONTINUE",
        "CLARIFICATION_RECOMMENDED",
    }


def test_legacy_requirement_type_is_not_silently_relabelled_as_target_hard() -> None:
    assert LegacyRequirementType.MUST_HAVE.value == "must_have"
    assert LegacyRequirementType.MUST_HAVE.value not in _values(RequirementType)
    assert RequirementType.HARD.value not in _values(LegacyRequirementType)
