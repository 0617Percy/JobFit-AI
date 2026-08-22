"""Immutable B6 analysis-input and run identity contracts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import datetime

from pydantic import ConfigDict, Field, model_validator

from jobfit.models.common import NonEmptyStr, StrictModel
from jobfit.models.v2.analysis import AnalysisCore, UserClarification
from jobfit.models.v2.enums import (
    AnalysisChangeType,
    AnalysisStage,
    ChangeSemanticScope,
    RecomputeFrom,
    ValidityStatus,
)
from jobfit.models.v2.governance import AnalysisLifecycle, Failure, VersionManifest
from jobfit.models.v2.report import JobFitReport


class FrozenVersionManifest(VersionManifest):
    """A run-scoped copy of version identity that cannot be edited in place."""

    model_config = ConfigDict(frozen=True)


class ClarificationInputSnapshot(StrictModel):
    """Canonical immutable representation of one accepted clarification."""

    model_config = ConfigDict(frozen=True)

    clarification_id: NonEmptyStr
    canonical_payload: NonEmptyStr
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class AnalysisInputSnapshot(StrictModel):
    """Inputs and version identities frozen at the analysis-ready gate."""

    model_config = ConfigDict(frozen=True)

    analysis_id: NonEmptyStr
    resume_version_id: NonEmptyStr
    jd_snapshot_id: NonEmptyStr
    user_clarifications: tuple[ClarificationInputSnapshot, ...] = ()
    versions: FrozenVersionManifest

    @model_validator(mode="after")
    def validate_clarification_ids(self) -> AnalysisInputSnapshot:
        ids = [item.clarification_id for item in self.user_clarifications]
        if len(ids) != len(set(ids)):
            raise ValueError("Snapshot clarification IDs must be unique.")
        return self

    @classmethod
    def freeze(
        cls,
        *,
        analysis_id: str,
        resume_version_id: str,
        jd_snapshot_id: str,
        user_clarifications: Sequence[UserClarification],
        versions: VersionManifest,
    ) -> AnalysisInputSnapshot:
        snapshots: list[ClarificationInputSnapshot] = []
        for clarification in sorted(
            user_clarifications,
            key=lambda item: item.clarification_id,
        ):
            if clarification.analysis_id != analysis_id:
                raise ValueError("Clarification belongs to another analysis.")
            payload = json.dumps(
                clarification.model_dump(mode="json"),
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            snapshots.append(
                ClarificationInputSnapshot(
                    clarification_id=clarification.clarification_id,
                    canonical_payload=payload,
                    content_hash=hashlib.sha256(payload.encode("utf-8")).hexdigest(),
                )
            )
        return cls(
            analysis_id=analysis_id,
            resume_version_id=resume_version_id,
            jd_snapshot_id=jd_snapshot_id,
            user_clarifications=tuple(snapshots),
            versions=FrozenVersionManifest.model_validate(
                versions.model_dump(mode="python")
            ),
        )


class ArtifactRecord(StrictModel):
    """Identity and dependency metadata for one immutable derived artifact."""

    model_config = ConfigDict(frozen=True)

    artifact_id: NonEmptyStr
    analysis_id: NonEmptyStr
    stage: AnalysisStage
    validity: ValidityStatus
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_artifact_ids: tuple[NonEmptyStr, ...] = ()

    @model_validator(mode="after")
    def validate_dependencies(self) -> ArtifactRecord:
        if len(self.source_artifact_ids) != len(set(self.source_artifact_ids)):
            raise ValueError("Artifact dependencies must be unique.")
        if self.artifact_id in self.source_artifact_ids:
            raise ValueError("Artifact cannot depend on itself.")
        return self


class ArtifactGraph(StrictModel):
    """Run-local artifact set; cross-analysis references fail closed."""

    model_config = ConfigDict(frozen=True)

    analysis_id: NonEmptyStr
    artifacts: tuple[ArtifactRecord, ...]

    @model_validator(mode="after")
    def validate_graph_identity(self) -> ArtifactGraph:
        artifact_ids = [item.artifact_id for item in self.artifacts]
        if len(artifact_ids) != len(set(artifact_ids)):
            raise ValueError("Artifact IDs must be unique.")
        known = set(artifact_ids)
        for artifact in self.artifacts:
            if artifact.analysis_id != self.analysis_id:
                raise ValueError("Artifact belongs to another analysis.")
            unknown = set(artifact.source_artifact_ids) - known
            if unknown:
                raise ValueError("Artifact references an unknown artifact dependency.")
        return self


class AnalysisChangeEvent(StrictModel):
    """Structured, stable change input for invalidation and planning."""

    model_config = ConfigDict(frozen=True)

    change_id: NonEmptyStr
    analysis_id: NonEmptyStr
    change_type: AnalysisChangeType
    changed_object_ids: tuple[NonEmptyStr, ...] = ()
    old_version_identity: NonEmptyStr | None = None
    new_version_identity: NonEmptyStr | None = None
    source: NonEmptyStr
    semantic_scope: ChangeSemanticScope
    affected_stages: tuple[AnalysisStage, ...] = ()
    created_at: datetime
    reason: NonEmptyStr

    @model_validator(mode="after")
    def validate_change(self) -> AnalysisChangeEvent:
        if len(self.changed_object_ids) != len(set(self.changed_object_ids)):
            raise ValueError("Changed object IDs must be unique.")
        if len(self.affected_stages) != len(set(self.affected_stages)):
            raise ValueError("Affected stages must be unique.")
        if (
            self.old_version_identity is not None
            and self.new_version_identity is not None
            and self.old_version_identity == self.new_version_identity
        ):
            raise ValueError("Version delta must change identity.")
        if (
            self.change_type is AnalysisChangeType.UI_OR_NOTE_ONLY
            and self.semantic_scope is not ChangeSemanticScope.UI_ONLY
        ):
            raise ValueError("UI-only change requires UI-only semantic scope.")
        return self


class ArtifactValidity(StrictModel):
    model_config = ConfigDict(frozen=True)

    artifact_id: NonEmptyStr
    validity: ValidityStatus


class VersionDelta(StrictModel):
    model_config = ConfigDict(frozen=True)

    change_id: NonEmptyStr
    change_type: AnalysisChangeType
    old_identity: NonEmptyStr
    new_identity: NonEmptyStr


class RecomputePlan(StrictModel):
    """Machine-testable safe-minimal recompute decision."""

    model_config = ConfigDict(frozen=True)

    source_analysis_id: NonEmptyStr
    target_analysis_id: NonEmptyStr
    change_event_ids: tuple[NonEmptyStr, ...]
    recompute_from: RecomputeFrom
    root_stages: tuple[AnalysisStage, ...]
    artifact_validity: tuple[ArtifactValidity, ...]
    preserved_artifact_ids: tuple[NonEmptyStr, ...]
    stale_artifact_ids: tuple[NonEmptyStr, ...]
    invalid_artifact_ids: tuple[NonEmptyStr, ...]
    stages_to_run: tuple[AnalysisStage, ...]
    stages_to_skip: tuple[AnalysisStage, ...]
    reason_codes: tuple[NonEmptyStr, ...]
    version_delta: tuple[VersionDelta, ...]

    @model_validator(mode="after")
    def validate_partition(self) -> RecomputePlan:
        groups = (
            set(self.preserved_artifact_ids),
            set(self.stale_artifact_ids),
            set(self.invalid_artifact_ids),
        )
        if any(
            groups[index] & groups[other]
            for index in range(3)
            for other in range(index + 1, 3)
        ):
            raise ValueError("Artifact plan partitions must be disjoint.")
        if len(self.change_event_ids) != len(set(self.change_event_ids)):
            raise ValueError("Change event IDs must be unique.")
        return self


class AnalysisRun(StrictModel):
    """One immutable run revision; transitions return a replacement object."""

    model_config = ConfigDict(frozen=True)

    analysis_id: NonEmptyStr
    parent_analysis_id: NonEmptyStr | None = None
    reanalysis_reason: NonEmptyStr | None = None
    lifecycle: AnalysisLifecycle
    input_snapshot: AnalysisInputSnapshot | None = None
    artifact_graph: ArtifactGraph | None = None
    analysis_core: AnalysisCore | None = None
    report: JobFitReport | None = None
    change_events: tuple[AnalysisChangeEvent, ...] = ()
    recompute_plan: RecomputePlan | None = None
    failures: tuple[Failure, ...] = ()

    @model_validator(mode="after")
    def validate_identity(self) -> AnalysisRun:
        if self.lifecycle.analysis_id != self.analysis_id:
            raise ValueError("Lifecycle belongs to another analysis.")
        if self.input_snapshot is not None and (
            self.input_snapshot.analysis_id != self.analysis_id
        ):
            raise ValueError("Input snapshot belongs to another analysis.")
        if self.parent_analysis_id == self.analysis_id:
            raise ValueError("Analysis cannot be its own parent.")
        if self.artifact_graph is not None and (
            self.artifact_graph.analysis_id != self.analysis_id
        ):
            raise ValueError("Artifact graph belongs to another analysis.")
        if self.analysis_core is not None and (
            self.analysis_core.analysis_id != self.analysis_id
        ):
            raise ValueError("Analysis core belongs to another analysis.")
        if self.report is not None and self.report.analysis_id != self.analysis_id:
            raise ValueError("Report belongs to another analysis.")
        if self.recompute_plan is not None and (
            self.recompute_plan.target_analysis_id != self.analysis_id
        ):
            raise ValueError("Recompute plan belongs to another analysis.")
        return self
