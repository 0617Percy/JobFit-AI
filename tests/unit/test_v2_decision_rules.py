"""Frozen R21-R35 deterministic guard and decision tests."""

from __future__ import annotations

from decimal import Decimal

import pytest

from jobfit.models.common import Importance
from jobfit.models.v2 import (
    AbilityStatus,
    AnalysisReadiness,
    CandidateProfile,
    ClarityLevel,
    Confidence,
    CriticalStatus,
    EligibilityStatus,
    Evidence,
    EvidenceLevel,
    EvidenceSourceOrigin,
    EvidenceStatus,
    MatchCoverage,
    MatchedEvidence,
    ParseCompleteness,
    PersonalContribution,
    ReasonCode,
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
)
from jobfit.scoring.v2 import (
    ClarificationCandidate,
    ClarificationImpact,
    DecisionNotFinalizableError,
    SeniorityFacts,
    SeniorScopeDemand,
    evaluate_confidence,
    evaluate_critical,
    evaluate_eligibility,
    evaluate_hard,
    evaluate_readiness,
    evaluate_recommendation,
    evaluate_seniority,
    select_clarifications,
    should_force_continue,
)


def make_requirement(
    requirement_id: str,
    requirement_type: RequirementType,
    *,
    importance: Importance = Importance.HIGH,
    critical_status: CriticalStatus = CriticalStatus.NOT_CRITICAL,
) -> Requirement:
    return Requirement(
        requirement_id=requirement_id,
        jd_snapshot_id="jd-v1",
        raw_requirement_ids=[f"raw-{requirement_id}"],
        raw_text=requirement_id,
        normalized_capability=requirement_id,
        requirement_type=requirement_type,
        importance=importance,
        explicitness=RequirementExplicitness.EXPLICIT,
        source=RequirementSource.JD,
        critical_status=critical_status,
    )


def make_evidence(evidence_id: str, level: EvidenceLevel) -> Evidence:
    overrides: dict[EvidenceLevel, dict[str, object]] = {
        EvidenceLevel.L4: {},
        EvidenceLevel.L3: {
            "result_clarity": ClarityLevel.UNKNOWN,
            "verification_strength": ClarityLevel.UNKNOWN,
        },
        EvidenceLevel.L2: {
            "personal_contribution": PersonalContribution.UNCLEAR,
        },
        EvidenceLevel.L1: {
            "personal_contribution": PersonalContribution.NOT_APPLICABLE,
            "task_clarity": ClarityLevel.UNKNOWN,
            "method_tool_clarity": ClarityLevel.UNKNOWN,
            "result_clarity": ClarityLevel.UNKNOWN,
            "verification_strength": ClarityLevel.UNKNOWN,
            "practical_use": ClarityLevel.UNKNOWN,
        },
    }
    payload: dict[str, object] = {
        "evidence_id": evidence_id,
        "source_origin": EvidenceSourceOrigin.PORTFOLIO,
        "source_type": "project",
        "source_text": "Structured decision evidence.",
        "personal_contribution": PersonalContribution.CLEAR,
        "task_clarity": ClarityLevel.HIGH,
        "method_tool_clarity": ClarityLevel.HIGH,
        "result_clarity": ClarityLevel.HIGH,
        "verification_strength": ClarityLevel.MEDIUM,
        "practical_use": ClarityLevel.HIGH,
        "evidence_level": level,
    }
    payload.update(overrides[level])
    return Evidence(**payload)


def make_match(
    requirement_id: str,
    evidence: Evidence | None,
    *,
    relevance: Relevance = Relevance.HIGH,
    support_type: SupportType = SupportType.DIRECT,
    coverage: MatchCoverage | None = None,
    conflict: bool = False,
    confirmed_gap: bool = False,
) -> RequirementMatch:
    if conflict:
        return RequirementMatch(
            match_id=f"match-{requirement_id}",
            requirement_id=requirement_id,
            matched_evidence=[
                MatchedEvidence(
                    evidence_id=evidence.evidence_id,
                    relevance=relevance,
                    support_type=support_type,
                )
            ],
            coverage=coverage or MatchCoverage.PARTIAL,
            evidence_status=EvidenceStatus.CONFLICT,
            ability_status=AbilityStatus.CONFLICT,
        )
    if evidence is None:
        return RequirementMatch(
            match_id=f"match-{requirement_id}",
            requirement_id=requirement_id,
            matched_evidence=[],
            coverage=MatchCoverage.NONE,
            evidence_status=EvidenceStatus.MISSING,
            ability_status=(
                AbilityStatus.CONFIRMED_GAP
                if confirmed_gap
                else AbilityStatus.UNKNOWN
            ),
            ability_confirmation_id=("clarification-1" if confirmed_gap else None),
        )
    return RequirementMatch(
        match_id=f"match-{requirement_id}",
        requirement_id=requirement_id,
        matched_evidence=[
            MatchedEvidence(
                evidence_id=evidence.evidence_id,
                relevance=relevance,
                support_type=support_type,
            )
        ],
        coverage=coverage or MatchCoverage.FULL,
        evidence_status=(
            EvidenceStatus.WEAK
            if evidence.evidence_level in {EvidenceLevel.L1, EvidenceLevel.L2}
            else EvidenceStatus.PRESENT
        ),
        ability_status=AbilityStatus.CONFIRMED,
        best_evidence_level=evidence.evidence_level,
    )


def make_resume(
    *,
    parse: ParseCompleteness = ParseCompleteness.COMPLETE,
    ambiguity_ids: list[str] | None = None,
    years: Decimal | None = Decimal("0"),
) -> ResumeProfile:
    return ResumeProfile(
        resume_version_id="resume-v1",
        candidate_profile=CandidateProfile(
            years_of_full_time_experience=years,
        ),
        evidence_ids=[],
        ambiguity_ids=ambiguity_ids or [],
        parse_completeness=parse,
    )


def test_hard_guard_separates_confirmed_blockers_from_unknown_pending() -> None:
    hard_blocked = make_requirement("hard-blocked", RequirementType.HARD)
    hard_unknown = make_requirement("hard-unknown", RequirementType.HARD)
    core = make_requirement("core", RequirementType.CORE)
    result = evaluate_hard(
        [hard_blocked, hard_unknown, core],
        [
            make_match("hard-blocked", None, confirmed_gap=True),
            make_match("hard-unknown", None),
            make_match("core", None),
        ],
    )

    assert result.blocker_ids == ("hard-blocked",)
    assert result.pending_ids == ("hard-unknown",)
    assert result.eligibility_status is EligibilityStatus.BLOCKED


def test_eligibility_precedence_is_blocked_then_pending_then_met() -> None:
    assert evaluate_eligibility(["blocked"], ["pending"]) is EligibilityStatus.BLOCKED
    assert evaluate_eligibility([], ["pending"]) is EligibilityStatus.PENDING
    assert evaluate_eligibility([], []) is EligibilityStatus.MET


def test_critical_guard_classifies_direct_and_transferable_evidence() -> None:
    requirements = [
        make_requirement(
            name,
            RequirementType.CORE,
            importance=Importance.CRITICAL,
            critical_status=CriticalStatus.CONFIRMED,
        )
        for name in ("strong", "borderline", "mitigated", "gap", "pending")
    ]
    evidence = {
        "ev-strong": make_evidence("ev-strong", EvidenceLevel.L3),
        "ev-borderline": make_evidence("ev-borderline", EvidenceLevel.L2),
        "ev-mitigated": make_evidence("ev-mitigated", EvidenceLevel.L4),
        "ev-conflict": make_evidence("ev-conflict", EvidenceLevel.L3),
    }
    matches = [
        make_match("strong", evidence["ev-strong"]),
        make_match("borderline", evidence["ev-borderline"]),
        make_match(
            "mitigated",
            evidence["ev-mitigated"],
            relevance=Relevance.MEDIUM,
            support_type=SupportType.TRANSFERABLE,
            coverage=MatchCoverage.SUBSTANTIAL,
        ),
        make_match("gap", None),
        make_match("pending", evidence["ev-conflict"], conflict=True),
    ]

    result = evaluate_critical(requirements, matches, evidence)

    assert result.strong_ids == ("strong",)
    assert result.borderline_ids == ("borderline", "mitigated")
    assert result.gap_ids == ("gap",)
    assert result.pending_ids == ("pending",)


def test_only_confirmed_explicit_critical_core_enters_critical_guard() -> None:
    candidate = make_requirement(
        "candidate",
        RequirementType.CORE,
        importance=Importance.CRITICAL,
        critical_status=CriticalStatus.CANDIDATE,
    )
    hard = make_requirement(
        "hard",
        RequirementType.HARD,
        importance=Importance.CRITICAL,
        critical_status=CriticalStatus.CONFIRMED,
    )

    result = evaluate_critical(
        [candidate, hard],
        [make_match("candidate", None), make_match("hard", None)],
        {},
    )

    assert result.gap_ids == ()


def test_seniority_uses_normalized_scope_and_conservative_unknown_handling() -> None:
    student = CandidateProfile(years_of_full_time_experience=Decimal("0"))
    assert evaluate_seniority(
        student,
        SeniorityFacts(explicit_entry_scope=True),
    ) is SeniorityAlignment.ALIGNED
    assert evaluate_seniority(
        CandidateProfile(years_of_full_time_experience=Decimal("1")),
        SeniorityFacts(required_years=Decimal("3")),
    ) is SeniorityAlignment.BORDERLINE
    assert evaluate_seniority(
        student,
        SeniorityFacts(
            required_years=Decimal("5"),
            senior_scope_demands=(
                SeniorScopeDemand.LEADERSHIP,
                SeniorScopeDemand.BUDGET,
                SeniorScopeDemand.BUSINESS_OWNER,
            ),
        ),
    ) is SeniorityAlignment.MISALIGNED

    unknown = CandidateProfile(years_of_full_time_experience=None)
    with pytest.raises(DecisionNotFinalizableError, match="seniority"):
        evaluate_seniority(
            unknown,
            SeniorityFacts(required_years=Decimal("2")),
        )
    assert evaluate_seniority(
        unknown,
        SeniorityFacts(required_years=Decimal("2")),
        forced_continue=True,
    ) is SeniorityAlignment.BORDERLINE


def test_readiness_uses_frozen_precedence_and_forced_transform() -> None:
    base = {
        "clarification_recommended": False,
        "has_evidence_or_confirmed_gap": False,
        "eligibility": EligibilityStatus.MET,
        "confidence": Confidence.HIGH,
        "forced_continue": False,
    }
    assert evaluate_readiness(
        clarification_required=True,
        **base,
    ) is AnalysisReadiness.CLARIFICATION_REQUIRED
    assert evaluate_readiness(
        clarification_required=False,
        **{**base, "clarification_recommended": True},
    ) is AnalysisReadiness.CLARIFICATION_RECOMMENDED
    assert evaluate_readiness(
        clarification_required=False,
        **{**base, "has_evidence_or_confirmed_gap": True},
    ) is AnalysisReadiness.READY_WITH_GAPS
    assert evaluate_readiness(
        clarification_required=True,
        **{**base, "forced_continue": True},
    ) is AnalysisReadiness.READY_WITH_GAPS
    assert evaluate_readiness(
        clarification_required=False,
        **base,
    ) is AnalysisReadiness.READY


def test_confidence_uses_structural_caps_not_confirmed_gap_probability() -> None:
    known_evidence = make_evidence("ev-known", EvidenceLevel.L4)
    known = make_match("known", known_evidence)
    confirmed_gap = make_match("gap", None, confirmed_gap=True)
    unknown = make_match("unknown", None)
    weak_evidence = make_evidence("ev-weak", EvidenceLevel.L1)
    weak = make_match("weak", weak_evidence)

    assert evaluate_confidence(make_resume(), [known, confirmed_gap]) is Confidence.HIGH
    assert evaluate_confidence(
        make_resume(parse=ParseCompleteness.PARTIAL),
        [known],
    ) is Confidence.MEDIUM
    assert evaluate_confidence(make_resume(), [unknown]) is Confidence.LOW
    assert evaluate_confidence(make_resume(), [known, unknown, weak]) is Confidence.MEDIUM
    assert evaluate_confidence(
        make_resume(),
        [known],
        forced_continue=True,
    ) is Confidence.LOW


def test_clarification_selector_filters_and_orders_at_most_three() -> None:
    candidates = [
        ClarificationCandidate(
            question_id="q-confidence",
            impact=ClarificationImpact.CONFIDENCE,
            question_type="confidence",
            question="Confidence detail?",
        ),
        ClarificationCandidate(
            question_id="q-hard-b",
            impact=ClarificationImpact.ELIGIBILITY,
            requirement_id="req-b",
            question_type="hard",
            question="Hard B?",
        ),
        ClarificationCandidate(
            question_id="q-ignored",
            impact=ClarificationImpact.ELIGIBILITY,
            question_type="hard",
            question="No decision impact?",
            can_change_core_decision=False,
        ),
        ClarificationCandidate(
            question_id="q-critical",
            impact=ClarificationImpact.CRITICAL_GUARD,
            requirement_id="req-c",
            question_type="critical",
            question="Critical evidence?",
        ),
        ClarificationCandidate(
            question_id="q-hard-a",
            impact=ClarificationImpact.ELIGIBILITY,
            requirement_id="req-a",
            question_type="hard",
            question="Hard A?",
        ),
    ]

    selected = select_clarifications(candidates)

    assert [item.question_id for item in selected] == [
        "q-hard-a",
        "q-hard-b",
        "q-critical",
    ]


def test_forced_continue_requires_explicit_skip_not_unknown_or_failure() -> None:
    assert should_force_continue(
        required_question_count=1,
        explicitly_skipped=True,
    ) is True
    assert should_force_continue(
        required_question_count=1,
        explicitly_skipped=False,
        answered_unknown=True,
    ) is False
    assert should_force_continue(
        required_question_count=1,
        explicitly_skipped=True,
        technical_failure=True,
    ) is False


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (Decimal("85.00"), Recommendation.PRIORITY),
        (Decimal("70.00"), Recommendation.SUGGESTED),
        (Decimal("55.00"), Recommendation.CHALLENGE),
        (Decimal("54.99"), Recommendation.NOT_RECOMMENDED),
    ],
)
def test_recommendation_uses_inclusive_persisted_score_bands(
    score: Decimal,
    expected: Recommendation,
) -> None:
    result = evaluate_recommendation(
        score,
        seniority=SeniorityAlignment.ALIGNED,
        eligibility=EligibilityStatus.MET,
        readiness=AnalysisReadiness.READY,
        critical_gap_count=0,
        confidence=Confidence.HIGH,
        forced_continue=False,
    )
    assert result.recommendation is expected


def test_recommendation_applies_strictest_guard_and_stable_reason_order() -> None:
    result = evaluate_recommendation(
        Decimal("95.00"),
        seniority=SeniorityAlignment.BORDERLINE,
        eligibility=EligibilityStatus.MET,
        readiness=AnalysisReadiness.READY_WITH_GAPS,
        critical_gap_count=1,
        confidence=Confidence.LOW,
        forced_continue=False,
    )

    assert result.recommendation is Recommendation.SUGGESTED
    assert result.reason_codes == (
        ReasonCode.SENIORITY_BORDERLINE,
        ReasonCode.HIGH_FIT_SCORE,
        ReasonCode.CRITICAL_GAP_ONE,
        ReasonCode.LOW_CONFIDENCE,
    )

    blocked = evaluate_recommendation(
        Decimal("95.00"),
        seniority=SeniorityAlignment.ALIGNED,
        eligibility=EligibilityStatus.BLOCKED,
        readiness=AnalysisReadiness.READY_WITH_GAPS,
        critical_gap_count=0,
        confidence=Confidence.HIGH,
        forced_continue=False,
    )
    assert blocked.recommendation is Recommendation.NOT_RECOMMENDED


def test_pending_after_forced_continue_caps_at_challenge() -> None:
    result = evaluate_recommendation(
        Decimal("95.00"),
        seniority=SeniorityAlignment.ALIGNED,
        eligibility=EligibilityStatus.PENDING,
        readiness=AnalysisReadiness.READY_WITH_GAPS,
        critical_gap_count=0,
        confidence=Confidence.LOW,
        forced_continue=True,
    )
    assert result.recommendation is Recommendation.CHALLENGE

    with pytest.raises(DecisionNotFinalizableError, match="clarification"):
        evaluate_recommendation(
            Decimal("95.00"),
            seniority=SeniorityAlignment.ALIGNED,
            eligibility=EligibilityStatus.PENDING,
            readiness=AnalysisReadiness.CLARIFICATION_REQUIRED,
            critical_gap_count=0,
            confidence=Confidence.LOW,
            forced_continue=False,
        )
