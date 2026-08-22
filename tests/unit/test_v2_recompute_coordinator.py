"""B6 stage orchestration, reuse, and failure-boundary behavior."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from jobfit.models.v2 import (
    AnalysisChangeEvent,
    AnalysisChangeType,
    AnalysisInputSnapshot,
    AnalysisStage,
    ArtifactGraph,
    ArtifactRecord,
    ChangeSemanticScope,
    FailureCategory,
    FailureImpactLevel,
    LifecycleStatus,
    TaskStatus,
    UserClarification,
    ValidityStatus,
    VersionManifest,
)
from jobfit.workflow.v2 import (
    IncrementalRecomputeCoordinator,
    IncrementalRecomputePlanner,
    RecomputeExecutionError,
    StageExecutionFailure,
    create_analysis_run,
    transition_run,
)


def _artifacts() -> ArtifactGraph:
    return ArtifactGraph(
        analysis_id="AN001",
        artifacts=(
            ArtifactRecord(
                artifact_id="artifact-score",
                analysis_id="AN001",
                stage=AnalysisStage.SCORING,
                validity=ValidityStatus.VALID,
                content_hash="1" * 64,
            ),
            ArtifactRecord(
                artifact_id="artifact-recommendation",
                analysis_id="AN001",
                stage=AnalysisStage.RECOMMENDATION,
                validity=ValidityStatus.VALID,
                content_hash="2" * 64,
                source_artifact_ids=("artifact-score",),
            ),
            ArtifactRecord(
                artifact_id="artifact-actions",
                analysis_id="AN001",
                stage=AnalysisStage.ACTIONS,
                validity=ValidityStatus.VALID,
                content_hash="3" * 64,
                source_artifact_ids=("artifact-recommendation",),
            ),
            ArtifactRecord(
                artifact_id="artifact-interview",
                analysis_id="AN001",
                stage=AnalysisStage.INTERVIEW,
                validity=ValidityStatus.VALID,
                content_hash="4" * 64,
                source_artifact_ids=("artifact-actions",),
            ),
            ArtifactRecord(
                artifact_id="artifact-report",
                analysis_id="AN001",
                stage=AnalysisStage.REPORT,
                validity=ValidityStatus.VALID,
                content_hash="5" * 64,
                source_artifact_ids=(
                    "artifact-recommendation",
                    "artifact-actions",
                    "artifact-interview",
                ),
            ),
        ),
    )


def _snapshot(analysis_id: str) -> AnalysisInputSnapshot:
    return AnalysisInputSnapshot.freeze(
        analysis_id=analysis_id,
        resume_version_id="resume-v2",
        jd_snapshot_id="jd-v1",
        user_clarifications=(
            UserClarification(
                clarification_id="clarification-AN002",
                analysis_id=analysis_id,
                question="Did you own deployment?",
                answer="Yes.",
            ),
        ),
        versions=VersionManifest(
            software_version="1.1.0",
            prompt_pack_version="1.0.0",
            schema_version="2.0.0",
            scoring_rule_version="1.0.0",
            knowledge_version="2026.08.1",
            analysis_engine_version="1.0.0",
        ),
    )


def _event(change_type: AnalysisChangeType) -> AnalysisChangeEvent:
    return AnalysisChangeEvent(
        change_id=f"change-{change_type.value.casefold()}",
        analysis_id="AN001",
        change_type=change_type,
        changed_object_ids=("prompt",),
        old_version_identity="1.0.0",
        new_version_identity="1.0.1",
        source="prompt_governance",
        semantic_scope=ChangeSemanticScope.PROMPT_SEMANTIC,
        created_at=datetime(2026, 8, 9, 12, 0, tzinfo=UTC),
        reason="Synthetic prompt update.",
    )


def _plan(change_type: AnalysisChangeType):
    return IncrementalRecomputePlanner().plan(
        current_artifacts=_artifacts(),
        change_events=(_event(change_type),),
        target_analysis_id="AN002",
    )


def _ready_run():
    run = create_analysis_run("AN002", status=LifecycleStatus.NEEDS_REANALYSIS)
    return transition_run(
        run,
        LifecycleStatus.ANALYSIS_READY,
        snapshot=_snapshot("AN002"),
    )


def _runner(stage: AnalysisStage, calls: list[AnalysisStage]):
    def run(context):
        calls.append(context.stage)
        return ArtifactRecord(
            artifact_id=f"AN002-{stage.value}",
            analysis_id="AN002",
            stage=stage,
            validity=ValidityStatus.VALID,
            content_hash=f"{len(calls) + 10:064x}",
            source_artifact_ids=tuple(
                item.artifact_id for item in context.available_artifacts
            ),
        )

    return run


def test_p08_recompute_runs_only_report_and_preserves_all_upstream_ids() -> None:
    calls: list[AnalysisStage] = []
    result = IncrementalRecomputeCoordinator().execute(
        run=_ready_run(),
        plan=_plan(AnalysisChangeType.PROMPT_P08_CHANGED),
        current_artifacts=_artifacts(),
        stage_runners={AnalysisStage.REPORT: _runner(AnalysisStage.REPORT, calls)},
    )

    assert calls == [AnalysisStage.REPORT]
    assert result.lifecycle.status is LifecycleStatus.COMPLETED
    assert result.lifecycle.report_status is TaskStatus.COMPLETED
    assert result.produced_artifacts[0].artifact_id == "AN002-report"
    assert set(result.preserved_artifact_ids) == {
        "artifact-score",
        "artifact-recommendation",
        "artifact-actions",
        "artifact-interview",
    }


def test_p06_recompute_runs_actions_then_interview_then_report() -> None:
    calls: list[AnalysisStage] = []
    stages = (
        AnalysisStage.ACTIONS,
        AnalysisStage.INTERVIEW,
        AnalysisStage.REPORT,
    )
    result = IncrementalRecomputeCoordinator().execute(
        run=_ready_run(),
        plan=_plan(AnalysisChangeType.PROMPT_P06_CHANGED),
        current_artifacts=_artifacts(),
        stage_runners={stage: _runner(stage, calls) for stage in stages},
    )

    assert calls == list(stages)
    assert result.lifecycle.last_successful_stage == AnalysisStage.REPORT.value
    assert result.failure is None


def test_report_failure_is_invalid_without_polluting_score_or_recommendation() -> None:
    def fail_report(_context):
        raise StageExecutionFailure(
            failure_code="REPORT_SCHEMA_INVALID",
            category=FailureCategory.MODEL,
            impact_level=FailureImpactLevel.BASE_ANALYSIS,
            retryable=True,
            user_action_required=False,
            technical_message="Synthetic report validation failure.",
            user_message="The report could not be completed safely.",
        )

    result = IncrementalRecomputeCoordinator().execute(
        run=_ready_run(),
        plan=_plan(AnalysisChangeType.PROMPT_P08_CHANGED),
        current_artifacts=_artifacts(),
        stage_runners={AnalysisStage.REPORT: fail_report},
    )

    assert result.lifecycle.status is LifecycleStatus.FAILED
    assert result.lifecycle.report_status is TaskStatus.FAILED
    assert result.failure is not None
    assert result.failure.failure_stage == AnalysisStage.REPORT.value
    assert result.failure.last_successful_stage is None
    assert "artifact-score" in result.preserved_artifact_ids
    assert "artifact-recommendation" in result.preserved_artifact_ids
    assert result.invalid_stage is AnalysisStage.REPORT
    validity = {item.artifact_id: item.validity for item in result.artifact_validity}
    assert validity["artifact-report"] is ValidityStatus.INVALID
    assert validity["artifact-score"] is ValidityStatus.VALID
    assert validity["artifact-recommendation"] is ValidityStatus.VALID


def test_unknown_programming_error_is_not_silently_converted_to_failure() -> None:
    def crash(_context):
        raise RuntimeError("programming defect")

    with pytest.raises(RuntimeError, match="programming defect"):
        IncrementalRecomputeCoordinator().execute(
            run=_ready_run(),
            plan=_plan(AnalysisChangeType.PROMPT_P08_CHANGED),
            current_artifacts=_artifacts(),
            stage_runners={AnalysisStage.REPORT: crash},
        )


def test_coordinator_fails_closed_before_execution_when_a_runner_is_missing() -> None:
    with pytest.raises(RecomputeExecutionError, match="runner"):
        IncrementalRecomputeCoordinator().execute(
            run=_ready_run(),
            plan=_plan(AnalysisChangeType.PROMPT_P06_CHANGED),
            current_artifacts=_artifacts(),
            stage_runners={},
        )


def test_coordinator_rejects_a_non_topological_handcrafted_plan() -> None:
    plan = _plan(AnalysisChangeType.PROMPT_P06_CHANGED)
    unsafe = plan.model_copy(update={"stages_to_run": tuple(reversed(plan.stages_to_run))})
    stages = set(plan.stages_to_run)

    with pytest.raises(RecomputeExecutionError, match="order|dependency"):
        IncrementalRecomputeCoordinator().execute(
            run=_ready_run(),
            plan=unsafe,
            current_artifacts=_artifacts(),
            stage_runners={stage: _runner(stage, []) for stage in stages},
        )


def test_coordinator_rejects_artifact_partitions_outside_the_source_graph() -> None:
    plan = _plan(AnalysisChangeType.PROMPT_P08_CHANGED)
    unsafe = plan.model_copy(
        update={
            "preserved_artifact_ids": (*plan.preserved_artifact_ids, "artifact-ghost")
        }
    )

    with pytest.raises(RecomputeExecutionError, match="artifact partition"):
        IncrementalRecomputeCoordinator().execute(
            run=_ready_run(),
            plan=unsafe,
            current_artifacts=_artifacts(),
            stage_runners={AnalysisStage.REPORT: _runner(AnalysisStage.REPORT, [])},
        )


def test_coordinator_rejects_cross_analysis_or_wrong_stage_artifacts() -> None:
    def wrong_stage(_context):
        return ArtifactRecord(
            artifact_id="bad-output",
            analysis_id="AN999",
            stage=AnalysisStage.ACTIONS,
            validity=ValidityStatus.VALID,
            content_hash="a" * 64,
        )

    with pytest.raises(RecomputeExecutionError, match="output"):
        IncrementalRecomputeCoordinator().execute(
            run=_ready_run(),
            plan=_plan(AnalysisChangeType.PROMPT_P08_CHANGED),
            current_artifacts=_artifacts(),
            stage_runners={AnalysisStage.REPORT: wrong_stage},
        )


def test_fallback_levels_remain_the_four_frozen_f0_to_f3_values() -> None:
    assert [item.value for item in FailureImpactLevel] == ["F0", "F1", "F2", "F3"]
