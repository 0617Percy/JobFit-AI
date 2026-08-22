"""Safe-minimal deterministic B6 recompute planner."""

from __future__ import annotations

from collections.abc import Sequence

from jobfit.models.v2 import (
    AnalysisChangeEvent,
    AnalysisChangeType,
    AnalysisStage,
    ArtifactGraph,
    RecomputeFrom,
    RecomputePlan,
    ValidityStatus,
    VersionDelta,
)
from jobfit.workflow.v2.dependencies import DEFAULT_DEPENDENCY_GRAPH, DependencyGraph
from jobfit.workflow.v2.invalidation import (
    RecomputePlanningError,
    propagate_validity,
)

_SUMMARY_STAGE = {
    AnalysisStage.RESUME_PARSE: RecomputeFrom.RESUME_PARSE,
    AnalysisStage.JD_PARSE: RecomputeFrom.JD_PARSE,
    AnalysisStage.REQUIREMENT_CLASSIFICATION: RecomputeFrom.JD_PARSE,
    AnalysisStage.EVIDENCE: RecomputeFrom.EVIDENCE,
    AnalysisStage.READINESS: RecomputeFrom.READINESS,
    AnalysisStage.MATCHING: RecomputeFrom.MATCHING,
    AnalysisStage.ELIGIBILITY: RecomputeFrom.ELIGIBILITY,
    AnalysisStage.SCORING: RecomputeFrom.SCORING,
    AnalysisStage.RECOMMENDATION: RecomputeFrom.RECOMMENDATION,
    AnalysisStage.ACTIONS: RecomputeFrom.ACTIONS,
    AnalysisStage.INTERVIEW: RecomputeFrom.INTERVIEW,
    AnalysisStage.REPORT: RecomputeFrom.REPORT,
}


class IncrementalRecomputePlanner:
    def __init__(
        self,
        graph: DependencyGraph = DEFAULT_DEPENDENCY_GRAPH,
    ) -> None:
        self._graph = graph

    def plan(
        self,
        *,
        current_artifacts: ArtifactGraph,
        change_events: Sequence[AnalysisChangeEvent],
        target_analysis_id: str,
    ) -> RecomputePlan:
        events = tuple(sorted(change_events, key=lambda item: item.change_id))
        recovery_roots = tuple(
            stage
            for stage in self._graph.topological_order()
            if any(
                artifact.stage is stage
                and artifact.validity is not ValidityStatus.VALID
                for artifact in current_artifacts.artifacts
            )
        )
        if not events and not recovery_roots:
            raise RecomputePlanningError("At least one change event is required.")
        if len({item.change_id for item in events}) != len(events):
            raise RecomputePlanningError("Change event IDs must be unique.")
        if any(item.analysis_id != current_artifacts.analysis_id for item in events):
            raise RecomputePlanningError("Change event belongs to another analysis.")
        substantive = bool(recovery_roots) or any(
            item.change_type is not AnalysisChangeType.UI_OR_NOTE_ONLY
            for item in events
        )
        if substantive and target_analysis_id == current_artifacts.analysis_id:
            raise RecomputePlanningError(
                "Substantive change requires a new analysis identity."
            )

        result = propagate_validity(
            current_artifacts,
            events,
            graph=self._graph,
            recovery_roots=recovery_roots,
        )
        validity_by_id = {
            item.artifact_id: item.validity for item in result.artifact_validity
        }
        preserved = tuple(
            item.artifact_id
            for item in current_artifacts.artifacts
            if validity_by_id[item.artifact_id] is ValidityStatus.VALID
        )
        stale = tuple(
            item.artifact_id
            for item in current_artifacts.artifacts
            if validity_by_id[item.artifact_id] is ValidityStatus.STALE
        )
        invalid = tuple(
            item.artifact_id
            for item in current_artifacts.artifacts
            if validity_by_id[item.artifact_id] is ValidityStatus.INVALID
        )
        stages_to_run = result.affected_stages
        stages_to_skip = tuple(
            stage
            for stage in self._graph.topological_order()
            if stage not in set(stages_to_run)
        )
        recompute_from = (
            RecomputeFrom.NONE
            if not result.root_stages
            else _SUMMARY_STAGE[result.root_stages[0]]
        )
        deltas = tuple(
            VersionDelta(
                change_id=event.change_id,
                change_type=event.change_type,
                old_identity=event.old_version_identity,
                new_identity=event.new_version_identity,
            )
            for event in events
            if event.old_version_identity is not None
            and event.new_version_identity is not None
        )
        return RecomputePlan(
            source_analysis_id=current_artifacts.analysis_id,
            target_analysis_id=target_analysis_id,
            change_event_ids=tuple(item.change_id for item in events),
            recompute_from=recompute_from,
            root_stages=result.root_stages,
            artifact_validity=result.artifact_validity,
            preserved_artifact_ids=preserved,
            stale_artifact_ids=stale,
            invalid_artifact_ids=invalid,
            stages_to_run=stages_to_run,
            stages_to_skip=stages_to_skip,
            reason_codes=result.reason_codes,
            version_delta=deltas,
        )
