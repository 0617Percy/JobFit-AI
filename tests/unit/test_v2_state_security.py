"""Fail-closed B6 identity, graph, and orchestration boundaries."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from jobfit.models.v2 import (
    AnalysisChangeEvent,
    AnalysisChangeType,
    AnalysisInputSnapshot,
    AnalysisLifecycle,
    AnalysisRun,
    AnalysisStage,
    ArtifactGraph,
    ArtifactRecord,
    ArtifactValidity,
    ChangeSemanticScope,
    FrozenVersionManifest,
    LifecycleStatus,
    RecomputeFrom,
    RecomputePlan,
    TaskStatus,
    UserClarification,
    ValidityStatus,
)
from jobfit.workflow.v2 import (
    DEFAULT_DEPENDENCY_GRAPH,
    DependencyGraphError,
    IncrementalRecomputeCoordinator,
    IncrementalRecomputePlanner,
    LifecycleTransitionError,
    RecomputeExecutionError,
    complete_stage,
    create_analysis_run,
    start_stage,
    transition_run,
)


def _versions() -> FrozenVersionManifest:
    return FrozenVersionManifest(
        software_version="1.1.0",
        prompt_pack_version="1.0.0",
        schema_version="2.0.0",
        scoring_rule_version="1.0.0",
        knowledge_version="2026.08.1",
        analysis_engine_version="1.0.0",
    )


def _snapshot(analysis_id: str = "AN001") -> AnalysisInputSnapshot:
    return AnalysisInputSnapshot.freeze(
        analysis_id=analysis_id,
        resume_version_id="resume-v1",
        jd_snapshot_id="jd-v1",
        user_clarifications=(),
        versions=_versions(),
    )


def _artifact_graph(analysis_id: str = "AN001") -> ArtifactGraph:
    return ArtifactGraph(
        analysis_id=analysis_id,
        artifacts=(
            ArtifactRecord(
                artifact_id="artifact-report",
                analysis_id=analysis_id,
                stage=AnalysisStage.REPORT,
                validity=ValidityStatus.VALID,
                content_hash="a" * 64,
            ),
        ),
    )


def _event() -> AnalysisChangeEvent:
    return AnalysisChangeEvent(
        change_id="change-report",
        analysis_id="AN001",
        change_type=AnalysisChangeType.PROMPT_P08_CHANGED,
        changed_object_ids=("P08",),
        old_version_identity="1.0.0",
        new_version_identity="1.0.1",
        source="prompt_governance",
        semantic_scope=ChangeSemanticScope.PROMPT_SEMANTIC,
        created_at=datetime(2026, 8, 9, 12, 0, tzinfo=UTC),
        reason="Synthetic report prompt change.",
    )


def _plan() -> RecomputePlan:
    return IncrementalRecomputePlanner().plan(
        current_artifacts=_artifact_graph(),
        change_events=(_event(),),
        target_analysis_id="AN002",
    )


def _ready_run() -> AnalysisRun:
    run = create_analysis_run("AN002", status=LifecycleStatus.NEEDS_REANALYSIS)
    return transition_run(
        run,
        LifecycleStatus.ANALYSIS_READY,
        snapshot=_snapshot("AN002"),
    )


def test_snapshot_rejects_duplicate_or_cross_analysis_clarifications() -> None:
    clarification = UserClarification(
        clarification_id="clarification-001",
        analysis_id="AN999",
        question="Did you own deployment?",
        answer="Yes.",
    )
    with pytest.raises(ValueError, match="another analysis"):
        AnalysisInputSnapshot.freeze(
            analysis_id="AN001",
            resume_version_id="resume-v1",
            jd_snapshot_id="jd-v1",
            user_clarifications=(clarification,),
            versions=_versions(),
        )

    item = {
        "clarification_id": "clarification-001",
        "canonical_payload": "{}",
        "content_hash": "a" * 64,
    }
    with pytest.raises(ValidationError, match="unique"):
        AnalysisInputSnapshot(
            analysis_id="AN001",
            resume_version_id="resume-v1",
            jd_snapshot_id="jd-v1",
            user_clarifications=(item, item),
            versions=_versions(),
        )


def test_snapshot_rejects_a_noncanonical_clarification_hash() -> None:
    with pytest.raises(ValidationError, match="content_hash"):
        AnalysisInputSnapshot(
            analysis_id="AN001",
            resume_version_id="resume-v1",
            jd_snapshot_id="jd-v1",
            user_clarifications=(
                {
                    "clarification_id": "clarification-001",
                    "canonical_payload": "{}",
                    "content_hash": "not-a-sha256",
                },
            ),
            versions=_versions(),
        )


@pytest.mark.parametrize(
    "source_ids",
    [("parent", "parent"), ("artifact-self",)],
)
def test_artifact_rejects_duplicate_or_self_dependencies(
    source_ids: tuple[str, ...],
) -> None:
    with pytest.raises(ValidationError, match="dependencies|itself"):
        ArtifactRecord(
            artifact_id="artifact-self",
            analysis_id="AN001",
            stage=AnalysisStage.REPORT,
            validity=ValidityStatus.VALID,
            content_hash="a" * 64,
            source_artifact_ids=source_ids,
        )


def test_artifact_graph_rejects_duplicate_artifact_ids() -> None:
    artifact = _artifact_graph().artifacts[0]
    with pytest.raises(ValidationError, match="unique"):
        ArtifactGraph(analysis_id="AN001", artifacts=(artifact, artifact))


def test_change_event_rejects_duplicate_references_and_wrong_ui_scope() -> None:
    payload = _event().model_dump(mode="python")
    payload["changed_object_ids"] = ("P08", "P08")
    with pytest.raises(ValidationError, match="Changed object IDs"):
        AnalysisChangeEvent.model_validate(payload)

    payload = _event().model_dump(mode="python")
    payload["affected_stages"] = (AnalysisStage.REPORT, AnalysisStage.REPORT)
    with pytest.raises(ValidationError, match="Affected stages"):
        AnalysisChangeEvent.model_validate(payload)

    payload = _event().model_dump(mode="python")
    payload.update(
        {
            "change_type": AnalysisChangeType.UI_OR_NOTE_ONLY,
            "semantic_scope": ChangeSemanticScope.INPUT_SEMANTIC,
        }
    )
    with pytest.raises(ValidationError, match="UI-only"):
        AnalysisChangeEvent.model_validate(payload)


def test_recompute_plan_rejects_overlapping_artifacts_and_duplicate_events() -> None:
    plan = _plan()
    payload = plan.model_dump(mode="python")
    payload["preserved_artifact_ids"] = ("artifact-report",)
    with pytest.raises(ValidationError, match="disjoint"):
        RecomputePlan.model_validate(payload)

    payload = plan.model_dump(mode="python")
    payload["change_event_ids"] = ("change-report", "change-report")
    with pytest.raises(ValidationError, match="unique"):
        RecomputePlan.model_validate(payload)


def test_analysis_run_rejects_cross_object_identity_drift() -> None:
    lifecycle = AnalysisLifecycle(
        analysis_id="AN999",
        status=LifecycleStatus.DRAFT,
        validity=ValidityStatus.VALID,
    )
    with pytest.raises(ValidationError, match="Lifecycle"):
        AnalysisRun(analysis_id="AN001", lifecycle=lifecycle)

    lifecycle = lifecycle.model_copy(update={"analysis_id": "AN001"})
    with pytest.raises(ValidationError, match="snapshot"):
        AnalysisRun(
            analysis_id="AN001",
            lifecycle=lifecycle,
            input_snapshot=_snapshot("AN999"),
        )
    with pytest.raises(ValidationError, match="own parent"):
        AnalysisRun(
            analysis_id="AN001",
            parent_analysis_id="AN001",
            lifecycle=lifecycle,
        )
    with pytest.raises(ValidationError, match="Artifact graph"):
        AnalysisRun(
            analysis_id="AN001",
            lifecycle=lifecycle,
            artifact_graph=_artifact_graph("AN999"),
        )


def test_transition_rejects_snapshot_replacement_and_wrong_timing() -> None:
    run = create_analysis_run("AN001")
    with pytest.raises(LifecycleTransitionError, match="only be frozen"):
        transition_run(run, LifecycleStatus.INPUT_READY, snapshot=_snapshot())

    run = transition_run(run, LifecycleStatus.INPUT_READY)
    run = transition_run(run, LifecycleStatus.PARSING)
    run = transition_run(run, LifecycleStatus.ANALYSIS_READY, snapshot=_snapshot())
    replacement = AnalysisInputSnapshot.freeze(
        analysis_id="AN001",
        resume_version_id="resume-v2",
        jd_snapshot_id="jd-v1",
        user_clarifications=(),
        versions=_versions(),
    )
    with pytest.raises(LifecycleTransitionError, match="cannot be replaced"):
        transition_run(
            run.model_copy(
                update={
                    "lifecycle": run.lifecycle.model_copy(
                        update={"status": LifecycleStatus.REVIEW_REQUIRED}
                    )
                }
            ),
            LifecycleStatus.ANALYSIS_READY,
            snapshot=replacement,
        )


def test_stage_completion_requires_the_matching_running_stage() -> None:
    lifecycle = AnalysisLifecycle(
        analysis_id="AN001",
        status=LifecycleStatus.ANALYZING,
        validity=ValidityStatus.VALID,
    )
    with pytest.raises(LifecycleTransitionError, match="not the current"):
        complete_stage(lifecycle, AnalysisStage.SCORING)

    lifecycle = start_stage(lifecycle, AnalysisStage.ELIGIBILITY)
    with pytest.raises(LifecycleTransitionError, match="not the current"):
        complete_stage(lifecycle, AnalysisStage.SCORING)


def test_dependency_graph_unknown_stage_queries_fail_closed() -> None:
    partial = {AnalysisStage.REPORT: ()}
    from jobfit.workflow.v2 import DependencyGraph

    graph = DependencyGraph(partial)
    with pytest.raises(DependencyGraphError, match="missing"):
        graph.dependencies_of(AnalysisStage.SCORING)
    with pytest.raises(DependencyGraphError, match="missing"):
        graph.downstream_of(AnalysisStage.SCORING)
    assert DEFAULT_DEPENDENCY_GRAPH.stages[0] is AnalysisStage.RESUME_PARSE


@pytest.mark.parametrize("failure", ["run", "source", "target", "noop"])
def test_coordinator_preflight_rejects_invalid_execution_context(failure: str) -> None:
    run = _ready_run()
    plan = _plan()
    graph = _artifact_graph()
    runners = {AnalysisStage.REPORT: lambda context: graph.artifacts[0]}
    if failure == "run":
        run = create_analysis_run("AN002")
    elif failure == "source":
        graph = _artifact_graph("AN999")
    elif failure == "target":
        plan = plan.model_copy(update={"target_analysis_id": "AN999"})
    else:
        plan = RecomputePlan(
            source_analysis_id="AN001",
            target_analysis_id="AN002",
            change_event_ids=("change-ui",),
            recompute_from=RecomputeFrom.NONE,
            root_stages=(),
            artifact_validity=(
                ArtifactValidity(
                    artifact_id="artifact-report",
                    validity=ValidityStatus.VALID,
                ),
            ),
            preserved_artifact_ids=("artifact-report",),
            stale_artifact_ids=(),
            invalid_artifact_ids=(),
            stages_to_run=(),
            stages_to_skip=(AnalysisStage.REPORT,),
            reason_codes=("CHANGE_UI_OR_NOTE_ONLY",),
            version_delta=(),
        )
    with pytest.raises(RecomputeExecutionError):
        IncrementalRecomputeCoordinator().execute(
            run=run,
            plan=plan,
            current_artifacts=graph,
            stage_runners=runners,
        )


def test_non_substatus_stage_still_updates_atomic_current_and_last_success() -> None:
    lifecycle = AnalysisLifecycle(
        analysis_id="AN001",
        status=LifecycleStatus.ANALYZING,
        validity=ValidityStatus.VALID,
    )
    lifecycle = start_stage(lifecycle, AnalysisStage.ELIGIBILITY)
    assert lifecycle.current_stage == AnalysisStage.ELIGIBILITY.value
    assert lifecycle.score_status is TaskStatus.NOT_STARTED

    lifecycle = complete_stage(lifecycle, AnalysisStage.ELIGIBILITY)
    assert lifecycle.current_stage is None
    assert lifecycle.last_successful_stage == AnalysisStage.ELIGIBILITY.value
