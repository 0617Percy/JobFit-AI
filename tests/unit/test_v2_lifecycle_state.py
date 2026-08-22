"""B6 lifecycle, sub-status, and immutable input snapshot contracts."""

from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from jobfit.models.v2 import (
    AnalysisInputSnapshot,
    AnalysisLifecycle,
    AnalysisRun,
    AnalysisStage,
    LifecycleStatus,
    TaskStatus,
    UserClarification,
    ValidityStatus,
    VersionManifest,
)
from jobfit.workflow.v2 import (
    LifecycleTransitionError,
    complete_stage,
    create_analysis_run,
    fail_stage,
    fork_analysis_run,
    start_stage,
    transition_run,
)


def _versions() -> VersionManifest:
    return VersionManifest(
        software_version="1.1.0",
        prompt_pack_version="1.0.0",
        schema_version="2.0.0",
        scoring_rule_version="1.0.0",
        knowledge_version="2026.08.1",
        analysis_engine_version="1.0.0",
    )


def _snapshot(analysis_id: str = "AN001") -> AnalysisInputSnapshot:
    clarification = UserClarification(
        clarification_id="clarification-001",
        analysis_id=analysis_id,
        question="Did you own deployment?",
        answer="Yes, for the synthetic project.",
        target_object_ids=["req-001"],
    )
    return AnalysisInputSnapshot.freeze(
        analysis_id=analysis_id,
        resume_version_id="resume-v1",
        jd_snapshot_id="jd-v1",
        user_clarifications=[clarification],
        versions=_versions(),
    )


def _completed_run():
    run = create_analysis_run("AN001")
    run = transition_run(run, LifecycleStatus.INPUT_READY)
    run = transition_run(run, LifecycleStatus.PARSING)
    run = transition_run(run, LifecycleStatus.ANALYSIS_READY, snapshot=_snapshot())
    run = transition_run(run, LifecycleStatus.ANALYZING)
    run = transition_run(run, LifecycleStatus.REPORT_GENERATING)
    return transition_run(run, LifecycleStatus.COMPLETED)


def _run_with_status(status: LifecycleStatus) -> AnalysisRun:
    return AnalysisRun(
        analysis_id="AN001",
        lifecycle=AnalysisLifecycle(
            analysis_id="AN001",
            status=status,
            validity=ValidityStatus.VALID,
        ),
    )


def test_lifecycle_contract_has_exactly_the_ten_authorized_states() -> None:
    assert [item.value for item in LifecycleStatus] == [
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
    ]


def test_lifecycle_accepts_both_review_and_direct_analysis_ready_paths() -> None:
    direct = create_analysis_run("AN001")
    direct = transition_run(direct, LifecycleStatus.INPUT_READY)
    direct = transition_run(direct, LifecycleStatus.PARSING)
    direct = transition_run(
        direct,
        LifecycleStatus.ANALYSIS_READY,
        snapshot=_snapshot("AN001"),
    )

    reviewed = create_analysis_run("AN002")
    reviewed = transition_run(reviewed, LifecycleStatus.INPUT_READY)
    reviewed = transition_run(reviewed, LifecycleStatus.PARSING)
    reviewed = transition_run(reviewed, LifecycleStatus.REVIEW_REQUIRED)
    reviewed = transition_run(
        reviewed,
        LifecycleStatus.ANALYSIS_READY,
        snapshot=_snapshot("AN002"),
    )

    assert direct.lifecycle.status is LifecycleStatus.ANALYSIS_READY
    assert reviewed.lifecycle.status is LifecycleStatus.ANALYSIS_READY


@pytest.mark.parametrize(
    ("start", "target"),
    [
        (LifecycleStatus.DRAFT, LifecycleStatus.COMPLETED),
        (LifecycleStatus.COMPLETED, LifecycleStatus.ANALYZING),
        (LifecycleStatus.FAILED, LifecycleStatus.COMPLETED),
    ],
)
def test_lifecycle_rejects_unauthorized_jumps(
    start: LifecycleStatus,
    target: LifecycleStatus,
) -> None:
    run = _run_with_status(start)

    with pytest.raises(LifecycleTransitionError, match="transition"):
        transition_run(run, target)


def test_run_factory_rejects_non_initial_lifecycle_states() -> None:
    with pytest.raises(LifecycleTransitionError, match="initial"):
        create_analysis_run("AN001", status=LifecycleStatus.COMPLETED)


def test_analysis_ready_requires_the_frozen_input_snapshot() -> None:
    run = create_analysis_run("AN001")
    run = transition_run(run, LifecycleStatus.INPUT_READY)
    run = transition_run(run, LifecycleStatus.PARSING)

    with pytest.raises(LifecycleTransitionError, match="snapshot"):
        transition_run(run, LifecycleStatus.ANALYSIS_READY)


def test_snapshot_is_deeply_stable_after_original_clarification_changes() -> None:
    clarification = UserClarification(
        clarification_id="clarification-001",
        analysis_id="AN001",
        question="Did you own deployment?",
        answer="Yes.",
    )
    snapshot = AnalysisInputSnapshot.freeze(
        analysis_id="AN001",
        resume_version_id="resume-v1",
        jd_snapshot_id="jd-v1",
        user_clarifications=[clarification],
        versions=_versions(),
    )
    before = snapshot.model_dump_json()

    clarification.answer = "No."

    assert snapshot.model_dump_json() == before
    assert '"answer":"Yes."' in snapshot.user_clarifications[0].canonical_payload
    with pytest.raises(ValidationError, match="frozen"):
        snapshot.resume_version_id = "resume-v2"
    with pytest.raises(ValidationError, match="frozen"):
        snapshot.versions.knowledge_version = "2026.09.1"


def test_snapshot_freezes_every_authorized_input_and_version_identity() -> None:
    snapshot = _snapshot()

    assert snapshot.resume_version_id == "resume-v1"
    assert snapshot.jd_snapshot_id == "jd-v1"
    assert snapshot.versions.prompt_pack_version == "1.0.0"
    assert snapshot.versions.schema_version == "2.0.0"
    assert snapshot.versions.scoring_rule_version == "1.0.0"
    assert snapshot.versions.knowledge_version == "2026.08.1"
    assert snapshot.versions.analysis_engine_version == "1.0.0"
    assert [item.clarification_id for item in snapshot.user_clarifications] == [
        "clarification-001"
    ]


def test_completed_run_cannot_be_mutated_and_reanalysis_forks_a_child() -> None:
    completed = _completed_run()
    before = deepcopy(completed.model_dump(mode="json"))

    with pytest.raises(LifecycleTransitionError, match="historical"):
        transition_run(completed, LifecycleStatus.NEEDS_REANALYSIS)

    child = fork_analysis_run(
        completed,
        target_analysis_id="AN002",
        reason="Resume V2 supplied.",
    )

    assert child.analysis_id == "AN002"
    assert child.parent_analysis_id == "AN001"
    assert child.lifecycle.status is LifecycleStatus.NEEDS_REANALYSIS
    assert completed.model_dump(mode="json") == before


def test_sub_status_follows_not_started_running_completed_and_never_restarts() -> None:
    lifecycle = _run_with_status(LifecycleStatus.ANALYZING).lifecycle

    lifecycle = start_stage(lifecycle, AnalysisStage.SCORING)
    assert lifecycle.score_status is TaskStatus.RUNNING
    lifecycle = complete_stage(lifecycle, AnalysisStage.SCORING)
    assert lifecycle.score_status is TaskStatus.COMPLETED
    assert lifecycle.last_successful_stage == AnalysisStage.SCORING.value

    with pytest.raises(LifecycleTransitionError, match="cannot restart"):
        start_stage(lifecycle, AnalysisStage.SCORING)


def test_sub_status_rejects_logically_concurrent_stages() -> None:
    lifecycle = _run_with_status(LifecycleStatus.ANALYZING).lifecycle
    lifecycle = start_stage(lifecycle, AnalysisStage.SCORING)

    with pytest.raises(LifecycleTransitionError, match="already running"):
        start_stage(lifecycle, AnalysisStage.REPORT)


def test_failed_stage_keeps_the_previous_last_successful_stage() -> None:
    lifecycle = _run_with_status(LifecycleStatus.ANALYZING).lifecycle
    lifecycle = start_stage(lifecycle, AnalysisStage.SCORING)
    lifecycle = complete_stage(lifecycle, AnalysisStage.SCORING)
    lifecycle = start_stage(lifecycle, AnalysisStage.RECOMMENDATION)
    lifecycle = fail_stage(lifecycle, AnalysisStage.RECOMMENDATION)

    assert lifecycle.recommendation_status is TaskStatus.FAILED
    assert lifecycle.last_successful_stage == AnalysisStage.SCORING.value
    assert lifecycle.status is LifecycleStatus.FAILED


def test_failed_run_recovery_creates_a_new_run_and_preserves_failure_history() -> None:
    failed = _run_with_status(LifecycleStatus.ANALYZING)
    lifecycle = start_stage(failed.lifecycle, AnalysisStage.SCORING)
    lifecycle = complete_stage(lifecycle, AnalysisStage.SCORING)
    lifecycle = start_stage(lifecycle, AnalysisStage.RECOMMENDATION)
    lifecycle = fail_stage(lifecycle, AnalysisStage.RECOMMENDATION)
    failed = failed.model_copy(update={"lifecycle": lifecycle})
    before = failed.model_dump_json()

    retry = fork_analysis_run(
        failed,
        target_analysis_id="AN002",
        reason="Retry from the last successful stage.",
    )

    assert retry.analysis_id == "AN002"
    assert retry.parent_analysis_id == "AN001"
    assert retry.lifecycle.status is LifecycleStatus.NEEDS_REANALYSIS
    assert failed.model_dump_json() == before
