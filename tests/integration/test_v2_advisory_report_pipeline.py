"""Offline P06-P08 pipeline over frozen v2 decision objects."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from jobfit.advisory.v2.pipeline import AdvisoryReportPipeline
from jobfit.llm import LLMSettings, MockLLMProvider
from jobfit.models import Importance
from jobfit.models.v2 import (
    AbilityStatus,
    AnalysisCore,
    AnalysisReadiness,
    CitationUsage,
    Confidence,
    CriticalStatus,
    EligibilityStatus,
    Evidence,
    EvidenceLevel,
    EvidenceSourceOrigin,
    EvidenceStatus,
    JobFamily,
    JobFitDomainBundle,
    JobProfile,
    KnowledgeCitation,
    KnowledgeCoverage,
    MatchCoverage,
    MatchedEvidence,
    Recommendation,
    Relevance,
    Requirement,
    RequirementExplicitness,
    RequirementMatch,
    RequirementSource,
    RequirementType,
    SeniorityAlignment,
    SupportType,
    VersionManifest,
)
from jobfit.semantic.v2.executor import SemanticLLMTask, SemanticPromptExecutor
from jobfit.validators.v2 import DomainValidator

PROMPT_ROOT = Path(__file__).parents[2] / "src" / "jobfit" / "prompts" / "v2"


def _bundle(*, knowledge: bool, hard_blocked: bool = False) -> JobFitDomainBundle:
    text = "Built and tested a Python API."
    evidence = Evidence(
        evidence_id="ev-supported",
        resume_version_id="resume-v1",
        source_origin=EvidenceSourceOrigin.RESUME,
        source_type="project",
        source_text=text,
        evidence_level=EvidenceLevel.L3,
        document_id="doc-1",
        segment_id="seg-1",
        start_char=0,
        end_char=len(text),
    )
    supported = Requirement(
        requirement_id="req-supported",
        jd_snapshot_id="jd-v1",
        raw_requirement_ids=["raw-supported"],
        raw_text="Build Python applications.",
        normalized_capability="Python application delivery",
        requirement_type=RequirementType.CORE,
        importance=Importance.HIGH,
        explicitness=RequirementExplicitness.EXPLICIT,
        source=RequirementSource.JD,
    )
    gap = Requirement(
        requirement_id="req-gap",
        jd_snapshot_id="jd-v1",
        raw_requirement_ids=["raw-gap"],
        raw_text="Meet the synthetic gap condition.",
        normalized_capability="synthetic gap capability",
        requirement_type=(RequirementType.HARD if hard_blocked else RequirementType.CORE),
        importance=(Importance.HIGH if hard_blocked else Importance.CRITICAL),
        explicitness=RequirementExplicitness.EXPLICIT,
        source=RequirementSource.JD,
        critical_status=(
            CriticalStatus.NOT_CRITICAL
            if hard_blocked
            else CriticalStatus.CONFIRMED
        ),
    )
    requirements = [supported, gap]
    citations = []
    if knowledge:
        citations = [
            KnowledgeCitation(
                citation_id="cite-job",
                knowledge_version="2026.08.1",
                source_id="source-job",
                role_family=JobFamily.AI_APPLICATION,
                title="Synthetic role context",
                usage=CitationUsage.JOB_EXPLANATION,
            ),
            KnowledgeCitation(
                citation_id="cite-implicit",
                knowledge_version="2026.08.1",
                source_id="source-implicit",
                role_family=JobFamily.AI_APPLICATION,
                title="Synthetic implicit context",
                usage=CitationUsage.IMPLICIT_REQUIREMENT,
            ),
            KnowledgeCitation(
                citation_id="cite-build",
                knowledge_version="2026.08.1",
                source_id="source-build",
                role_family=JobFamily.AI_APPLICATION,
                title="Synthetic build context",
                usage=CitationUsage.BUILD_RECOMMENDATION,
            ),
            KnowledgeCitation(
                citation_id="cite-interview",
                knowledge_version="2026.08.1",
                source_id="source-interview",
                role_family=JobFamily.AI_APPLICATION,
                title="Synthetic interview context",
                usage=CitationUsage.INTERVIEW_PREPARATION,
            ),
        ]
        requirements.append(
            Requirement(
                requirement_id="req-implicit",
                normalized_capability="documenting system limitations",
                requirement_type=RequirementType.IMPLICIT,
                importance=Importance.MEDIUM,
                explicitness=RequirementExplicitness.IMPLICIT,
                source=RequirementSource.KNOWLEDGE,
                knowledge_citation_ids=["cite-implicit"],
            )
        )
    matches = [
        RequirementMatch(
            match_id="match-supported",
            requirement_id=supported.requirement_id,
            matched_evidence=[
                MatchedEvidence(
                    evidence_id=evidence.evidence_id,
                    relevance=Relevance.HIGH,
                    support_type=SupportType.DIRECT,
                )
            ],
            coverage=MatchCoverage.SUBSTANTIAL,
            evidence_status=EvidenceStatus.PRESENT,
            ability_status=AbilityStatus.CONFIRMED,
            best_evidence_level=EvidenceLevel.L3,
            match_score_component=Decimal("0.75"),
        ),
        RequirementMatch(
            match_id="match-gap",
            requirement_id=gap.requirement_id,
            matched_evidence=[],
            coverage=MatchCoverage.NONE,
            evidence_status=EvidenceStatus.MISSING,
            ability_status=AbilityStatus.UNKNOWN,
        ),
    ]
    core = AnalysisCore(
        analysis_id="analysis-1",
        resume_version_id="resume-v1",
        jd_snapshot_id="jd-v1",
        analysis_readiness=AnalysisReadiness.READY_WITH_GAPS,
        eligibility_status=(
            EligibilityStatus.BLOCKED if hard_blocked else EligibilityStatus.MET
        ),
        seniority_alignment=SeniorityAlignment.ALIGNED,
        base_fit_score=Decimal("42.00" if hard_blocked else "60.00"),
        preferred_bonus=Decimal("0.00" if hard_blocked else "2.00"),
        final_fit_score=Decimal("42.00" if hard_blocked else "62.00"),
        critical_gap_requirement_ids=[] if hard_blocked else [gap.requirement_id],
        confidence=Confidence.MEDIUM,
        recommendation=(
            Recommendation.NOT_RECOMMENDED
            if hard_blocked
            else Recommendation.CHALLENGE
        ),
        recommendation_reason_codes=[
            "HARD_BLOCKER" if hard_blocked else "CRITICAL_GAP_ONE"
        ],
        hard_blocker_ids=[gap.requirement_id] if hard_blocked else [],
    )
    return JobFitDomainBundle(
        evidence=[evidence],
        job_profile=JobProfile(
            jd_snapshot_id="jd-v1",
            job_title="Synthetic AI Application Intern",
            job_family=JobFamily.AI_APPLICATION,
            knowledge_coverage=(
                KnowledgeCoverage.ENHANCED
                if knowledge
                else KnowledgeCoverage.BASE_ONLY
            ),
            raw_requirement_ids=["raw-supported", "raw-gap"],
            requirement_ids=[supported.requirement_id, gap.requirement_id],
        ),
        requirements=requirements,
        requirement_matches=matches,
        analysis_core=core,
        knowledge_citations=citations,
        versions=VersionManifest(
            software_version="1.1.0",
            prompt_pack_version="1.0.0",
            schema_version="2.0.0",
            scoring_rule_version="1.0.0",
            knowledge_version="2026.08.1",
            analysis_engine_version="1.0.0",
        ),
    )


def _scripts(*, knowledge: bool) -> dict[SemanticLLMTask, list[str]]:
    rewrite = {
        "action_type": "rewrite",
        "priority": "p0",
        "related_requirement_ids": ["req-supported"],
        "related_evidence_ids": ["ev-supported"],
        "supported_by_evidence_ids": ["ev-supported"],
        "source_clarification_ids": [],
        "knowledge_citation_ids": [],
        "title": "Clarify the existing Python project",
        "why_it_matters": "The existing evidence can be more explicit.",
        "recommended_action": "Built and tested a Python API.",
        "completion_criteria": "The wording remains traceable to ev-supported.",
        "effort": "low",
        "time_to_complete": "30-45 minutes",
        "timing": "before_apply",
        "introduced_claims": [],
    }
    build = {
        "priority": "p0",
        "related_requirement_ids": ["req-gap"],
        "knowledge_citation_ids": ["cite-build"] if knowledge else [],
        "title": "Create future evidence for the gap",
        "why_it_matters": "The current evidence does not cover this requirement.",
        "recommended_action": "Complete a future synthetic practice artifact.",
        "completion_criteria": "A reproducible artifact and notes exist.",
        "effort": "medium",
        "time_to_complete": "4-6 focused hours",
        "timing": "parallel_with_applications",
    }
    question = {
        "question_id": "question-gap",
        "question_type": "gap_risk",
        "priority": "p0",
        "question": "How would you approach the currently unsupported capability?",
        "why_likely": "The explicit role requirement has no current evidence.",
        "related_requirement_ids": ["req-gap"],
        "related_evidence_ids": [],
        "critical_gap_requirement_ids": [],
        "hard_concern_requirement_ids": [],
        "related_action_ids": ["p06-build-001"],
        "preparation_points": [
            "Validation target: explain the missing capability and its role value.",
            "Evidence to recall: use only the validated project material.",
            "Answer structure: current evidence, gap, learning plan, and validation.",
        ],
        "knowledge_citation_ids": ["cite-interview"] if knowledge else [],
    }
    report = {
        "job_explanations": (
            [{"text": "Synthetic role context.", "knowledge_citation_ids": ["cite-job"]}]
            if knowledge
            else []
        ),
        "implicit_explanations": (
            [{
                "requirement_id": "req-implicit",
                "text": "Implicit context: document limitations.",
                "knowledge_citation_ids": ["cite-implicit"],
            }]
            if knowledge
            else []
        ),
        "application_strategy_notes": ["Follow the frozen recommendation."],
        "boundary_notes": ["Missing evidence does not prove missing ability."],
        "warnings": [],
    }
    return {
        SemanticLLMTask.P06_ACTIONS: [
            json.dumps({"actions": [rewrite], "warnings": []}),
            json.dumps({"actions": [build], "warnings": []}),
        ],
        SemanticLLMTask.P07_INTERVIEW: [
            json.dumps({"questions": [question], "warnings": []})
        ],
        SemanticLLMTask.P08_REPORT: [json.dumps(report)],
    }


def _pipeline(*, knowledge: bool) -> tuple[AdvisoryReportPipeline, MockLLMProvider]:
    provider = MockLLMProvider(_scripts(knowledge=knowledge))
    executor = SemanticPromptExecutor(
        provider=provider,
        prompt_root=PROMPT_ROOT,
        settings=LLMSettings(model="semantic-mock", max_retries=0),
    )
    return AdvisoryReportPipeline(executor), provider


def test_pipeline_runs_p06_twice_then_p07_and_p08_without_core_drift() -> None:
    bundle = _bundle(knowledge=True)
    pipeline, provider = _pipeline(knowledge=True)

    result = pipeline.run(bundle)

    assert result.analysis_core is bundle.analysis_core
    assert result.report.summary["recommendation"] == "challenge"
    assert result.report.score_explanation["final_fit_score"] == "62.00"
    assert [call.task for call in provider.calls] == [
        SemanticLLMTask.P06_ACTIONS,
        SemanticLLMTask.P06_ACTIONS,
        SemanticLLMTask.P07_INTERVIEW,
        SemanticLLMTask.P08_REPORT,
    ]
    assert [record.prompt_id for record in result.executions] == [
        "P06",
        "P06",
        "P07",
        "P08",
    ]
    assert DomainValidator().validate(result.bundle).valid is True


def test_pipeline_knowledge_on_off_preserves_every_core_decision_input() -> None:
    enhanced = _pipeline(knowledge=True)[0].run(_bundle(knowledge=True))
    base = _pipeline(knowledge=False)[0].run(_bundle(knowledge=False))

    assert enhanced.analysis_core == base.analysis_core
    assert enhanced.bundle.evidence == base.bundle.evidence
    assert enhanced.bundle.requirement_matches == base.bundle.requirement_matches
    assert enhanced.report.summary == base.report.summary
    assert enhanced.report.score_explanation == base.report.score_explanation
    assert enhanced.report.hard_check == base.report.hard_check
    assert enhanced.report.job_profile != base.report.job_profile
    assert enhanced.report.build_recommendations != base.report.build_recommendations
    assert enhanced.report.interview_preparation != base.report.interview_preparation


def test_pipeline_hard_blocked_case_remains_not_recommended() -> None:
    bundle = _bundle(knowledge=True, hard_blocked=True)

    result = _pipeline(knowledge=True)[0].run(bundle)

    assert result.analysis_core is bundle.analysis_core
    assert result.report.summary["recommendation"] == "not_recommended"
    assert result.report.hard_check["hard_blocker_ids"] == ["req-gap"]
    assert result.report.application_strategy["recommendation"] == "not_recommended"
