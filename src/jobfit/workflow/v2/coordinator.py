"""Side-by-side B6 stage coordinator with explicit failure capture."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from jobfit.models.v2 import (
    AnalysisLifecycle,
    AnalysisRun,
    AnalysisStage,
    ArtifactGraph,
    ArtifactRecord,
    ArtifactValidity,
    Failure,
    FailureCategory,
    FailureImpactLevel,
    LifecycleStatus,
    RecomputePlan,
    ValidityStatus,
)
from jobfit.workflow.v2.dependencies import DEFAULT_DEPENDENCY_GRAPH
from jobfit.workflow.v2.lifecycle import (
    complete_stage,
    fail_stage,
    start_stage,
    transition_run,
)


class RecomputeExecutionError(ValueError):
    """A recompute plan cannot be executed safely."""


class StageExecutionFailure(Exception):
    """Expected stage failure carrying the structured B1 failure contract."""

    def __init__(
        self,
        *,
        failure_code: str,
        category: FailureCategory,
        impact_level: FailureImpactLevel,
        retryable: bool,
        user_action_required: bool,
        technical_message: str,
        user_message: str,
    ) -> None:
        super().__init__(technical_message)
        self.failure_code = failure_code
        self.category = category
        self.impact_level = impact_level
        self.retryable = retryable
        self.user_action_required = user_action_required
        self.technical_message = technical_message
        self.user_message = user_message


@dataclass(frozen=True, slots=True)
class StageExecutionContext:
    analysis_id: str
    stage: AnalysisStage
    available_artifacts: tuple[ArtifactRecord, ...]


StageRunner = Callable[[StageExecutionContext], ArtifactRecord]


@dataclass(frozen=True, slots=True)
class RecomputeExecutionResult:
    lifecycle: AnalysisLifecycle
    produced_artifacts: tuple[ArtifactRecord, ...]
    preserved_artifact_ids: tuple[str, ...]
    artifact_validity: tuple[ArtifactValidity, ...]
    failure: Failure | None = None
    invalid_stage: AnalysisStage | None = None


class IncrementalRecomputeCoordinator:
    """Execute a validated plan without changing B2-B5 business logic."""

    def execute(
        self,
        *,
        run: AnalysisRun,
        plan: RecomputePlan,
        current_artifacts: ArtifactGraph,
        stage_runners: Mapping[AnalysisStage, StageRunner],
    ) -> RecomputeExecutionResult:
        self._validate_inputs(run, plan, current_artifacts, stage_runners)
        preserved = tuple(
            artifact
            for artifact in current_artifacts.artifacts
            if artifact.artifact_id in set(plan.preserved_artifact_ids)
        )
        produced: list[ArtifactRecord] = []
        active = transition_run(run, LifecycleStatus.ANALYZING)
        for stage in plan.stages_to_run:
            if stage is AnalysisStage.REPORT:
                active = transition_run(active, LifecycleStatus.REPORT_GENERATING)
            active = active.model_copy(
                update={"lifecycle": start_stage(active.lifecycle, stage)}
            )
            context = StageExecutionContext(
                analysis_id=run.analysis_id,
                stage=stage,
                available_artifacts=(*preserved, *produced),
            )
            try:
                artifact = stage_runners[stage](context)
            except StageExecutionFailure as exc:
                lifecycle = fail_stage(active.lifecycle, stage)
                failure = Failure(
                    failure_id=f"{run.analysis_id}-{stage.value}-failure",
                    failure_stage=stage.value,
                    failure_code=exc.failure_code,
                    category=exc.category,
                    impact_level=exc.impact_level,
                    retryable=exc.retryable,
                    user_action_required=exc.user_action_required,
                    last_successful_stage=lifecycle.last_successful_stage,
                    technical_message=exc.technical_message,
                    user_message=exc.user_message,
                )
                return RecomputeExecutionResult(
                    lifecycle=lifecycle,
                    produced_artifacts=tuple(produced),
                    preserved_artifact_ids=plan.preserved_artifact_ids,
                    artifact_validity=tuple(
                        ArtifactValidity(
                            artifact_id=artifact.artifact_id,
                            validity=(
                                ValidityStatus.INVALID
                                if artifact.stage is stage
                                else next(
                                    item.validity
                                    for item in plan.artifact_validity
                                    if item.artifact_id == artifact.artifact_id
                                )
                            ),
                        )
                        for artifact in current_artifacts.artifacts
                    ),
                    failure=failure,
                    invalid_stage=stage,
                )
            if artifact.analysis_id != run.analysis_id or artifact.stage is not stage:
                raise RecomputeExecutionError(
                    "Stage runner output belongs to another analysis or stage."
                )
            produced.append(artifact)
            active = active.model_copy(
                update={"lifecycle": complete_stage(active.lifecycle, stage)}
            )
        if active.lifecycle.status is not LifecycleStatus.REPORT_GENERATING:
            raise RecomputeExecutionError("Recompute plan did not reach report stage.")
        active = transition_run(active, LifecycleStatus.COMPLETED)
        return RecomputeExecutionResult(
            lifecycle=active.lifecycle,
            produced_artifacts=tuple(produced),
            preserved_artifact_ids=plan.preserved_artifact_ids,
            artifact_validity=plan.artifact_validity,
        )

    @staticmethod
    def _validate_inputs(
        run: AnalysisRun,
        plan: RecomputePlan,
        current_artifacts: ArtifactGraph,
        stage_runners: Mapping[AnalysisStage, StageRunner],
    ) -> None:
        if run.lifecycle.status is not LifecycleStatus.ANALYSIS_READY:
            raise RecomputeExecutionError("Run must be analysis_ready.")
        if plan.source_analysis_id != current_artifacts.analysis_id:
            raise RecomputeExecutionError("Plan source does not match artifacts.")
        if plan.target_analysis_id != run.analysis_id:
            raise RecomputeExecutionError("Plan target does not match run.")
        missing = set(plan.stages_to_run) - set(stage_runners)
        if missing:
            raise RecomputeExecutionError("Recompute plan has a missing stage runner.")
        if not plan.stages_to_run:
            raise RecomputeExecutionError("No-op plan does not require execution.")
        expected_stages = DEFAULT_DEPENDENCY_GRAPH.closure(plan.root_stages)
        if plan.stages_to_run != expected_stages:
            raise RecomputeExecutionError(
                "Recompute stages violate dependency order or closure."
            )
        expected_skips = tuple(
            stage
            for stage in DEFAULT_DEPENDENCY_GRAPH.topological_order()
            if stage not in set(expected_stages)
        )
        if plan.stages_to_skip != expected_skips:
            raise RecomputeExecutionError("Recompute skip stages violate dependency closure.")
        source_ids = {artifact.artifact_id for artifact in current_artifacts.artifacts}
        validity = {item.artifact_id: item.validity for item in plan.artifact_validity}
        if len(validity) != len(plan.artifact_validity) or set(validity) != source_ids:
            raise RecomputeExecutionError(
                "Recompute artifact partition does not match the source graph."
            )
        partitions = {
            ValidityStatus.VALID: set(plan.preserved_artifact_ids),
            ValidityStatus.STALE: set(plan.stale_artifact_ids),
            ValidityStatus.INVALID: set(plan.invalid_artifact_ids),
        }
        if any(
            partitions[status]
            != {artifact_id for artifact_id, value in validity.items() if value is status}
            for status in ValidityStatus
        ):
            raise RecomputeExecutionError(
                "Recompute artifact partition does not match declared validity."
            )
