"""B6 side-by-side integration over frozen B2-B5 identities."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from jobfit.models.v2 import (
    AnalysisChangeEvent,
    AnalysisChangeType,
    AnalysisCore,
    AnalysisReadiness,
    AnalysisStage,
    ArtifactGraph,
    ArtifactRecord,
    ChangeSemanticScope,
    Confidence,
    EligibilityStatus,
    Recommendation,
    SeniorityAlignment,
    ValidityStatus,
)
from jobfit.workflow.v2 import IncrementalRecomputePlanner


def _core() -> AnalysisCore:
    return AnalysisCore(
        analysis_id="AN001",
        resume_version_id="resume-v1",
        jd_snapshot_id="jd-v1",
        analysis_readiness=AnalysisReadiness.READY_WITH_GAPS,
        eligibility_status=EligibilityStatus.MET,
        seniority_alignment=SeniorityAlignment.ALIGNED,
        base_fit_score=Decimal("73.00"),
        preferred_bonus=Decimal("2.00"),
        final_fit_score=Decimal("75.00"),
        confidence=Confidence.MEDIUM,
        recommendation=Recommendation.SUGGESTED,
    )


def _graph() -> ArtifactGraph:
    stages = (
        AnalysisStage.RESUME_PARSE,
        AnalysisStage.JD_PARSE,
        AnalysisStage.REQUIREMENT_CLASSIFICATION,
        AnalysisStage.EVIDENCE,
        AnalysisStage.MATCHING,
        AnalysisStage.ELIGIBILITY,
        AnalysisStage.SCORING,
        AnalysisStage.RECOMMENDATION,
        AnalysisStage.ACTIONS,
        AnalysisStage.INTERVIEW,
        AnalysisStage.REPORT,
    )
    return ArtifactGraph(
        analysis_id="AN001",
        artifacts=tuple(
            ArtifactRecord(
                artifact_id=f"artifact-{stage.value}",
                analysis_id="AN001",
                stage=stage,
                validity=ValidityStatus.VALID,
                content_hash=f"{index + 1:064x}",
            )
            for index, stage in enumerate(stages)
        ),
    )


def _event(
    change_type: AnalysisChangeType,
    scope: ChangeSemanticScope,
) -> AnalysisChangeEvent:
    return AnalysisChangeEvent(
        change_id=f"change-{change_type.value.casefold()}",
        analysis_id="AN001",
        change_type=change_type,
        changed_object_ids=("version",),
        old_version_identity="1.0.0",
        new_version_identity="1.0.1",
        source="governance",
        semantic_scope=scope,
        created_at=datetime(2026, 8, 9, 12, 0, tzinfo=UTC),
        reason="Synthetic integration change.",
    )


def test_knowledge_version_change_preserves_b2_core_decision_exactly() -> None:
    core = _core()
    before = core.model_dump_json()
    plan = IncrementalRecomputePlanner().plan(
        current_artifacts=_graph(),
        change_events=(
            _event(
                AnalysisChangeType.KNOWLEDGE_VERSION_CHANGED,
                ChangeSemanticScope.KNOWLEDGE_ADVISORY,
            ),
        ),
        target_analysis_id="AN002",
    )

    assert core.model_dump_json() == before
    assert core.base_fit_score == Decimal("73.00")
    assert core.recommendation is Recommendation.SUGGESTED
    assert "artifact-scoring" in plan.preserved_artifact_ids
    assert "artifact-recommendation" in plan.preserved_artifact_ids
    assert plan.stages_to_run == (
        AnalysisStage.ACTIONS,
        AnalysisStage.INTERVIEW,
        AnalysisStage.REPORT,
    )


def test_hard_clarification_keeps_match_and_score_while_refreshing_advisory() -> None:
    core = _core()
    plan = IncrementalRecomputePlanner().plan(
        current_artifacts=_graph(),
        change_events=(
            _event(
                AnalysisChangeType.HARD_CLARIFICATION_CHANGED,
                ChangeSemanticScope.ELIGIBILITY_ONLY,
            ),
        ),
        target_analysis_id="AN002",
    )

    assert core.base_fit_score == Decimal("73.00")
    assert "artifact-matching" in plan.preserved_artifact_ids
    assert "artifact-scoring" in plan.preserved_artifact_ids
    assert "artifact-recommendation" in plan.stale_artifact_ids
    assert AnalysisStage.ACTIONS in plan.stages_to_run
    assert AnalysisStage.INTERVIEW in plan.stages_to_run
    assert AnalysisStage.REPORT in plan.stages_to_run


def test_p08_change_preserves_all_b2_b3_b4_and_b5_advisory_artifacts() -> None:
    plan = IncrementalRecomputePlanner().plan(
        current_artifacts=_graph(),
        change_events=(
            _event(
                AnalysisChangeType.PROMPT_P08_CHANGED,
                ChangeSemanticScope.PROMPT_SEMANTIC,
            ),
        ),
        target_analysis_id="AN002",
    )

    assert plan.stages_to_run == (AnalysisStage.REPORT,)
    assert "artifact-resume_parse" in plan.preserved_artifact_ids
    assert "artifact-jd_parse" in plan.preserved_artifact_ids
    assert "artifact-matching" in plan.preserved_artifact_ids
    assert "artifact-scoring" in plan.preserved_artifact_ids
    assert "artifact-actions" in plan.preserved_artifact_ids
    assert "artifact-interview" in plan.preserved_artifact_ids
