"""Explicit B6 lifecycle and stage sub-status transition policy."""

from __future__ import annotations

from types import MappingProxyType

from jobfit.models.v2 import (
    AnalysisInputSnapshot,
    AnalysisLifecycle,
    AnalysisRun,
    AnalysisStage,
    LifecycleStatus,
    TaskStatus,
    ValidityStatus,
)


class LifecycleTransitionError(ValueError):
    """A requested lifecycle or stage transition is not authorized."""


LIFECYCLE_TRANSITIONS = MappingProxyType(
    {
        LifecycleStatus.DRAFT: frozenset(
            {LifecycleStatus.INPUT_READY, LifecycleStatus.FAILED}
        ),
        LifecycleStatus.INPUT_READY: frozenset(
            {LifecycleStatus.PARSING, LifecycleStatus.FAILED}
        ),
        LifecycleStatus.PARSING: frozenset(
            {
                LifecycleStatus.REVIEW_REQUIRED,
                LifecycleStatus.ANALYSIS_READY,
                LifecycleStatus.FAILED,
            }
        ),
        LifecycleStatus.REVIEW_REQUIRED: frozenset(
            {LifecycleStatus.ANALYSIS_READY, LifecycleStatus.FAILED}
        ),
        LifecycleStatus.ANALYSIS_READY: frozenset(
            {LifecycleStatus.ANALYZING, LifecycleStatus.FAILED}
        ),
        LifecycleStatus.ANALYZING: frozenset(
            {LifecycleStatus.REPORT_GENERATING, LifecycleStatus.FAILED}
        ),
        LifecycleStatus.REPORT_GENERATING: frozenset(
            {LifecycleStatus.COMPLETED, LifecycleStatus.FAILED}
        ),
        LifecycleStatus.COMPLETED: frozenset({LifecycleStatus.NEEDS_REANALYSIS}),
        LifecycleStatus.NEEDS_REANALYSIS: frozenset(
            {
                LifecycleStatus.PARSING,
                LifecycleStatus.ANALYSIS_READY,
                LifecycleStatus.FAILED,
            }
        ),
        LifecycleStatus.FAILED: frozenset(),
    }
)

_STATUS_FIELDS = MappingProxyType(
    {
        AnalysisStage.RESUME_PARSE: "resume_parse_status",
        AnalysisStage.JD_PARSE: "jd_parse_status",
        AnalysisStage.MATCHING: "match_status",
        AnalysisStage.SCORING: "score_status",
        AnalysisStage.RECOMMENDATION: "recommendation_status",
        AnalysisStage.ACTIONS: "actions_status",
        AnalysisStage.INTERVIEW: "interview_status",
        AnalysisStage.REPORT: "report_status",
    }
)


def create_analysis_run(
    analysis_id: str,
    *,
    status: LifecycleStatus = LifecycleStatus.DRAFT,
) -> AnalysisRun:
    if status not in {LifecycleStatus.DRAFT, LifecycleStatus.NEEDS_REANALYSIS}:
        raise LifecycleTransitionError(
            "Analysis run factory only accepts an authorized initial lifecycle state."
        )
    return AnalysisRun(
        analysis_id=analysis_id,
        lifecycle=AnalysisLifecycle(
            analysis_id=analysis_id,
            status=status,
            validity=ValidityStatus.VALID,
        ),
    )


def transition_run(
    run: AnalysisRun,
    target: LifecycleStatus,
    *,
    snapshot: AnalysisInputSnapshot | None = None,
) -> AnalysisRun:
    current = run.lifecycle.status
    if (
        current is LifecycleStatus.COMPLETED
        and target is LifecycleStatus.NEEDS_REANALYSIS
    ):
        raise LifecycleTransitionError(
            "Completed historical analysis is immutable; fork a new run."
        )
    if target not in LIFECYCLE_TRANSITIONS[current]:
        raise LifecycleTransitionError(
            f"Lifecycle transition {current.value!r} -> {target.value!r} is invalid."
        )
    next_snapshot = run.input_snapshot
    if target is LifecycleStatus.ANALYSIS_READY:
        if snapshot is None and next_snapshot is None:
            raise LifecycleTransitionError(
                "analysis_ready transition requires a frozen input snapshot."
            )
        if snapshot is not None:
            if snapshot.analysis_id != run.analysis_id:
                raise LifecycleTransitionError("Snapshot belongs to another analysis.")
            if next_snapshot is not None and snapshot != next_snapshot:
                raise LifecycleTransitionError("Frozen input snapshot cannot be replaced.")
            next_snapshot = snapshot
    elif snapshot is not None:
        raise LifecycleTransitionError(
            "Input snapshot can only be frozen at analysis_ready."
        )
    lifecycle = run.lifecycle.model_copy(update={"status": target})
    return run.model_copy(
        update={"lifecycle": lifecycle, "input_snapshot": next_snapshot}
    )


def fork_analysis_run(
    parent: AnalysisRun,
    *,
    target_analysis_id: str,
    reason: str,
) -> AnalysisRun:
    if parent.lifecycle.status not in {
        LifecycleStatus.COMPLETED,
        LifecycleStatus.FAILED,
    }:
        raise LifecycleTransitionError(
            "Only a completed or failed analysis can be reanalyzed."
        )
    if target_analysis_id == parent.analysis_id:
        raise LifecycleTransitionError("Reanalysis requires a new analysis identity.")
    return AnalysisRun(
        analysis_id=target_analysis_id,
        parent_analysis_id=parent.analysis_id,
        reanalysis_reason=reason,
        lifecycle=AnalysisLifecycle(
            analysis_id=target_analysis_id,
            status=LifecycleStatus.NEEDS_REANALYSIS,
            validity=ValidityStatus.VALID,
        ),
    )


def start_stage(
    lifecycle: AnalysisLifecycle,
    stage: AnalysisStage,
) -> AnalysisLifecycle:
    if lifecycle.current_stage is not None:
        raise LifecycleTransitionError(
            f"Stage {lifecycle.current_stage!r} is already running."
        )
    update: dict[str, object] = {"current_stage": stage.value}
    status_field = _STATUS_FIELDS.get(stage)
    if status_field is not None:
        status = getattr(lifecycle, status_field)
        if status is TaskStatus.COMPLETED:
            raise LifecycleTransitionError(
                f"Completed stage {stage.value!r} cannot restart."
            )
        if status is not TaskStatus.NOT_STARTED:
            raise LifecycleTransitionError(
                f"Stage {stage.value!r} cannot start from {status.value!r}."
            )
        update[status_field] = TaskStatus.RUNNING
    return lifecycle.model_copy(update=update)


def complete_stage(
    lifecycle: AnalysisLifecycle,
    stage: AnalysisStage,
) -> AnalysisLifecycle:
    _require_current_stage(lifecycle, stage)
    update: dict[str, object] = {
        "current_stage": None,
        "last_successful_stage": stage.value,
    }
    status_field = _STATUS_FIELDS.get(stage)
    if status_field is not None:
        if getattr(lifecycle, status_field) is not TaskStatus.RUNNING:
            raise LifecycleTransitionError("Stage was not running.")
        update[status_field] = TaskStatus.COMPLETED
    return lifecycle.model_copy(update=update)


def fail_stage(
    lifecycle: AnalysisLifecycle,
    stage: AnalysisStage,
) -> AnalysisLifecycle:
    _require_current_stage(lifecycle, stage)
    update: dict[str, object] = {
        "current_stage": None,
        "status": LifecycleStatus.FAILED,
        "validity": ValidityStatus.INVALID,
    }
    status_field = _STATUS_FIELDS.get(stage)
    if status_field is not None:
        update[status_field] = TaskStatus.FAILED
    return lifecycle.model_copy(update=update)


def _require_current_stage(
    lifecycle: AnalysisLifecycle,
    stage: AnalysisStage,
) -> None:
    if lifecycle.current_stage != stage.value:
        raise LifecycleTransitionError(
            f"Stage {stage.value!r} is not the current running stage."
        )
