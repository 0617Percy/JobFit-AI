"""Target lifecycle, failure, and version identity contracts."""

from __future__ import annotations

from pydantic import Field

from jobfit.models.common import NonEmptyStr, StrictModel
from jobfit.models.v2.enums import (
    FailureCategory,
    FailureImpactLevel,
    LifecycleStatus,
    RecomputeFrom,
    TaskStatus,
    ValidityStatus,
)

NOT_EXPLICITLY_VERSIONED = "NOT_EXPLICITLY_VERSIONED"


class ResumeVersionIdentity(StrictModel):
    resume_version_id: NonEmptyStr


class JDSnapshotIdentity(StrictModel):
    jd_snapshot_id: NonEmptyStr


class VersionManifest(StrictModel):
    software_version: NonEmptyStr
    prompt_pack_version: NonEmptyStr
    schema_version: NonEmptyStr
    scoring_rule_version: NonEmptyStr
    knowledge_version: NonEmptyStr
    analysis_engine_version: NonEmptyStr
    business_test_set_version: NonEmptyStr = NOT_EXPLICITLY_VERSIONED
    golden_set_version: NonEmptyStr = NOT_EXPLICITLY_VERSIONED


class AnalysisVersionIdentity(StrictModel):
    analysis_id: NonEmptyStr
    resume_version_id: NonEmptyStr
    jd_snapshot_id: NonEmptyStr
    versions: VersionManifest


class AnalysisLifecycle(StrictModel):
    analysis_id: NonEmptyStr
    status: LifecycleStatus
    validity: ValidityStatus
    recompute_from: RecomputeFrom = RecomputeFrom.NONE
    resume_parse_status: TaskStatus = TaskStatus.NOT_STARTED
    jd_parse_status: TaskStatus = TaskStatus.NOT_STARTED
    match_status: TaskStatus = TaskStatus.NOT_STARTED
    score_status: TaskStatus = TaskStatus.NOT_STARTED
    recommendation_status: TaskStatus = TaskStatus.NOT_STARTED
    actions_status: TaskStatus = TaskStatus.NOT_STARTED
    interview_status: TaskStatus = TaskStatus.NOT_STARTED
    report_status: TaskStatus = TaskStatus.NOT_STARTED
    knowledge_status: TaskStatus = TaskStatus.NOT_STARTED
    current_stage: str | None = None
    last_successful_stage: str | None = None


class Failure(StrictModel):
    failure_id: NonEmptyStr
    failure_stage: NonEmptyStr
    failure_code: NonEmptyStr
    category: FailureCategory | None = None
    impact_level: FailureImpactLevel
    retryable: bool
    user_action_required: bool
    last_successful_stage: str | None = None
    technical_message: str = Field(min_length=1)
    user_message: str = Field(min_length=1)
