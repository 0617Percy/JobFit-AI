"""B6 explicit dependency, invalidation, and minimal recompute behavior."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from jobfit.models.v2 import (
    AnalysisChangeEvent,
    AnalysisChangeType,
    AnalysisStage,
    ArtifactGraph,
    ArtifactRecord,
    ChangeSemanticScope,
    RecomputeFrom,
    ValidityStatus,
)
from jobfit.workflow.v2 import (
    DEFAULT_DEPENDENCY_GRAPH,
    DependencyGraph,
    DependencyGraphError,
    IncrementalRecomputePlanner,
    RecomputePlanningError,
)

_STAGES = (
    AnalysisStage.RESUME_PARSE,
    AnalysisStage.JD_PARSE,
    AnalysisStage.REQUIREMENT_CLASSIFICATION,
    AnalysisStage.EVIDENCE,
    AnalysisStage.READINESS,
    AnalysisStage.MATCHING,
    AnalysisStage.ELIGIBILITY,
    AnalysisStage.SCORING,
    AnalysisStage.RECOMMENDATION,
    AnalysisStage.ACTIONS,
    AnalysisStage.INTERVIEW,
    AnalysisStage.REPORT,
)

_DEPENDENCY_IDS = {
    AnalysisStage.RESUME_PARSE: (),
    AnalysisStage.JD_PARSE: (),
    AnalysisStage.REQUIREMENT_CLASSIFICATION: ("artifact-jd_parse",),
    AnalysisStage.EVIDENCE: ("artifact-resume_parse",),
    AnalysisStage.READINESS: (
        "artifact-requirement_classification",
        "artifact-evidence",
    ),
    AnalysisStage.MATCHING: (
        "artifact-requirement_classification",
        "artifact-evidence",
        "artifact-readiness",
    ),
    AnalysisStage.ELIGIBILITY: ("artifact-matching",),
    AnalysisStage.SCORING: ("artifact-matching",),
    AnalysisStage.RECOMMENDATION: (
        "artifact-readiness",
        "artifact-eligibility",
        "artifact-scoring",
    ),
    AnalysisStage.ACTIONS: ("artifact-recommendation",),
    AnalysisStage.INTERVIEW: (
        "artifact-recommendation",
        "artifact-actions",
    ),
    AnalysisStage.REPORT: (
        "artifact-recommendation",
        "artifact-actions",
        "artifact-interview",
    ),
}


def _graph(*, status: ValidityStatus = ValidityStatus.VALID) -> ArtifactGraph:
    return ArtifactGraph(
        analysis_id="AN001",
        artifacts=tuple(
            ArtifactRecord(
                artifact_id=f"artifact-{stage.value}",
                analysis_id="AN001",
                stage=stage,
                validity=status,
                content_hash=f"{index + 1:064x}",
                source_artifact_ids=_DEPENDENCY_IDS[stage],
            )
            for index, stage in enumerate(_STAGES)
        ),
    )


def _graph_with_status(
    stage: AnalysisStage,
    status: ValidityStatus,
) -> ArtifactGraph:
    payload = _graph().model_dump(mode="python")
    for artifact in payload["artifacts"]:
        if artifact["stage"] is stage:
            artifact["validity"] = status
    return ArtifactGraph.model_validate(payload)


def _event(
    change_type: AnalysisChangeType,
    *,
    change_id: str | None = None,
    semantic_scope: ChangeSemanticScope = ChangeSemanticScope.INPUT_SEMANTIC,
    affected_stages: tuple[AnalysisStage, ...] = (),
    old: str | None = "old-v1",
    new: str | None = "new-v2",
) -> AnalysisChangeEvent:
    return AnalysisChangeEvent(
        change_id=change_id or f"change-{change_type.value.casefold()}",
        analysis_id="AN001",
        change_type=change_type,
        changed_object_ids=("object-001",),
        old_version_identity=old,
        new_version_identity=new,
        source="user",
        semantic_scope=semantic_scope,
        affected_stages=affected_stages,
        created_at=datetime(2026, 8, 9, 12, 0, tzinfo=UTC),
        reason="Synthetic deterministic change.",
    )


def _plan(*events: AnalysisChangeEvent):
    return IncrementalRecomputePlanner().plan(
        current_artifacts=_graph(),
        change_events=events,
        target_analysis_id=(
            "AN001"
            if all(
                item.change_type is AnalysisChangeType.UI_OR_NOTE_ONLY
                for item in events
            )
            else "AN002"
        ),
    )


def test_default_dependency_graph_is_acyclic_and_p06_feeds_p07_and_p08() -> None:
    assert DEFAULT_DEPENDENCY_GRAPH.cycle_count == 0
    assert DEFAULT_DEPENDENCY_GRAPH.dependencies_of(AnalysisStage.INTERVIEW) == (
        AnalysisStage.RECOMMENDATION,
        AnalysisStage.ACTIONS,
    )
    assert set(DEFAULT_DEPENDENCY_GRAPH.downstream_of(AnalysisStage.ACTIONS)) == {
        AnalysisStage.INTERVIEW,
        AnalysisStage.REPORT,
    }


def test_default_dependency_graph_preserves_frozen_readiness_before_matching() -> None:
    order = DEFAULT_DEPENDENCY_GRAPH.topological_order()

    assert order.index(AnalysisStage.READINESS) < order.index(AnalysisStage.MATCHING)
    assert DEFAULT_DEPENDENCY_GRAPH.dependencies_of(AnalysisStage.READINESS) == (
        AnalysisStage.REQUIREMENT_CLASSIFICATION,
        AnalysisStage.EVIDENCE,
    )
    assert AnalysisStage.READINESS in DEFAULT_DEPENDENCY_GRAPH.dependencies_of(
        AnalysisStage.MATCHING
    )


def test_dependency_graph_rejects_cycles_and_missing_nodes() -> None:
    with pytest.raises(DependencyGraphError, match="cycle"):
        DependencyGraph(
            {
                AnalysisStage.ACTIONS: (AnalysisStage.INTERVIEW,),
                AnalysisStage.INTERVIEW: (AnalysisStage.ACTIONS,),
            }
        )
    with pytest.raises(DependencyGraphError, match="missing"):
        DependencyGraph(
            {AnalysisStage.ACTIONS: (AnalysisStage.RECOMMENDATION,)}
        )


def test_artifact_graph_rejects_missing_and_cross_analysis_dependencies() -> None:
    payload = _graph().model_dump(mode="python")
    payload["artifacts"][0]["analysis_id"] = "AN999"
    with pytest.raises(ValidationError, match="another analysis"):
        ArtifactGraph.model_validate(payload)

    payload = _graph().model_dump(mode="python")
    payload["artifacts"][-1]["source_artifact_ids"] = ("artifact-missing",)
    with pytest.raises(ValidationError, match="unknown artifact"):
        ArtifactGraph.model_validate(payload)


def test_ui_only_change_preserves_every_artifact_and_runs_nothing() -> None:
    plan = _plan(
        _event(
            AnalysisChangeType.UI_OR_NOTE_ONLY,
            semantic_scope=ChangeSemanticScope.UI_ONLY,
            old=None,
            new=None,
        )
    )

    assert plan.recompute_from is RecomputeFrom.NONE
    assert plan.root_stages == ()
    assert plan.stages_to_run == ()
    assert len(plan.preserved_artifact_ids) == len(_STAGES)
    assert plan.stale_artifact_ids == ()


def test_resume_change_reuses_the_jd_branch_and_invalidates_match_downstream() -> None:
    plan = _plan(_event(AnalysisChangeType.RESUME_TEXT_CHANGED))

    assert plan.recompute_from is RecomputeFrom.RESUME_PARSE
    assert plan.root_stages == (AnalysisStage.RESUME_PARSE,)
    assert AnalysisStage.JD_PARSE not in plan.stages_to_run
    assert AnalysisStage.REQUIREMENT_CLASSIFICATION not in plan.stages_to_run
    assert "artifact-jd_parse" in plan.preserved_artifact_ids
    assert "artifact-requirement_classification" in plan.preserved_artifact_ids
    assert "artifact-matching" in plan.stale_artifact_ids
    assert AnalysisStage.REPORT in plan.stages_to_run


def test_jd_change_reuses_resume_and_evidence_artifacts() -> None:
    plan = _plan(_event(AnalysisChangeType.JD_SEMANTIC_CHANGED))

    assert plan.recompute_from is RecomputeFrom.JD_PARSE
    assert plan.root_stages == (AnalysisStage.JD_PARSE,)
    assert AnalysisStage.RESUME_PARSE not in plan.stages_to_run
    assert AnalysisStage.EVIDENCE not in plan.stages_to_run
    assert "artifact-resume_parse" in plan.preserved_artifact_ids
    assert "artifact-evidence" in plan.preserved_artifact_ids


def test_p03_change_reclassifies_requirements_without_reparsing_the_jd() -> None:
    plan = _plan(_event(AnalysisChangeType.PROMPT_P03_CHANGED))

    assert plan.recompute_from is RecomputeFrom.JD_PARSE
    assert plan.root_stages == (AnalysisStage.REQUIREMENT_CLASSIFICATION,)
    assert AnalysisStage.JD_PARSE not in plan.stages_to_run
    assert "artifact-jd_parse" in plan.preserved_artifact_ids


def test_evidence_change_makes_matching_and_all_decision_outputs_stale() -> None:
    plan = _plan(_event(AnalysisChangeType.USER_CONFIRMED_EXPERIENCE))

    assert plan.recompute_from is RecomputeFrom.EVIDENCE
    assert "artifact-resume_parse" in plan.preserved_artifact_ids
    assert "artifact-evidence" in plan.stale_artifact_ids
    assert "artifact-matching" in plan.stale_artifact_ids
    assert "artifact-scoring" in plan.stale_artifact_ids
    assert "artifact-report" in plan.stale_artifact_ids


def test_hard_clarification_preserves_match_and_base_score_identity() -> None:
    plan = _plan(_event(AnalysisChangeType.HARD_CLARIFICATION_CHANGED))

    assert plan.recompute_from is RecomputeFrom.ELIGIBILITY
    assert plan.root_stages == (AnalysisStage.ELIGIBILITY,)
    assert "artifact-matching" in plan.preserved_artifact_ids
    assert "artifact-scoring" in plan.preserved_artifact_ids
    assert "artifact-recommendation" in plan.stale_artifact_ids


def test_knowledge_change_never_invalidates_core_recommendation() -> None:
    plan = _plan(
        _event(
            AnalysisChangeType.KNOWLEDGE_VERSION_CHANGED,
            semantic_scope=ChangeSemanticScope.KNOWLEDGE_ADVISORY,
        )
    )

    assert plan.recompute_from is RecomputeFrom.ACTIONS
    assert plan.stages_to_run == (
        AnalysisStage.ACTIONS,
        AnalysisStage.INTERVIEW,
        AnalysisStage.REPORT,
    )
    assert "artifact-recommendation" in plan.preserved_artifact_ids
    assert "artifact-scoring" in plan.preserved_artifact_ids


@pytest.mark.parametrize(
    ("change_type", "recompute_from", "stages"),
    [
        (
            AnalysisChangeType.PROMPT_P06_CHANGED,
            RecomputeFrom.ACTIONS,
            (
                AnalysisStage.ACTIONS,
                AnalysisStage.INTERVIEW,
                AnalysisStage.REPORT,
            ),
        ),
        (
            AnalysisChangeType.PROMPT_P07_CHANGED,
            RecomputeFrom.INTERVIEW,
            (AnalysisStage.INTERVIEW, AnalysisStage.REPORT),
        ),
        (
            AnalysisChangeType.PROMPT_P08_CHANGED,
            RecomputeFrom.REPORT,
            (AnalysisStage.REPORT,),
        ),
    ],
)
def test_advisory_prompt_changes_have_exact_downstream_scope(
    change_type: AnalysisChangeType,
    recompute_from: RecomputeFrom,
    stages: tuple[AnalysisStage, ...],
) -> None:
    plan = _plan(
        _event(change_type, semantic_scope=ChangeSemanticScope.PROMPT_SEMANTIC)
    )

    assert plan.recompute_from is recompute_from
    assert plan.stages_to_run == stages
    assert "artifact-scoring" in plan.preserved_artifact_ids


def test_scoring_rule_change_preserves_requirements_evidence_and_match() -> None:
    plan = _plan(
        _event(
            AnalysisChangeType.SCORING_RULE_VERSION_CHANGED,
            semantic_scope=ChangeSemanticScope.SCORING_ONLY,
        )
    )

    assert plan.recompute_from is RecomputeFrom.SCORING
    assert "artifact-matching" in plan.preserved_artifact_ids
    assert plan.stages_to_run[0] is AnalysisStage.SCORING


def test_resume_and_jd_changes_keep_both_independent_roots() -> None:
    plan = _plan(
        _event(AnalysisChangeType.NEW_RESUME, change_id="change-resume"),
        _event(AnalysisChangeType.NEW_JD, change_id="change-jd"),
    )

    assert plan.root_stages == (
        AnalysisStage.RESUME_PARSE,
        AnalysisStage.JD_PARSE,
    )
    assert plan.recompute_from is RecomputeFrom.RESUME_PARSE
    assert AnalysisStage.EVIDENCE in plan.stages_to_run
    assert AnalysisStage.REQUIREMENT_CLASSIFICATION in plan.stages_to_run
    assert AnalysisStage.MATCHING in plan.stages_to_run


def test_planning_is_idempotent_and_independent_of_event_order() -> None:
    events = (
        _event(AnalysisChangeType.PROMPT_P08_CHANGED, change_id="change-z"),
        _event(AnalysisChangeType.RESUME_TEXT_CHANGED, change_id="change-a"),
    )
    planner = IncrementalRecomputePlanner()

    first = planner.plan(
        current_artifacts=_graph(),
        change_events=events,
        target_analysis_id="AN002",
    )
    second = planner.plan(
        current_artifacts=_graph(),
        change_events=tuple(reversed(events)),
        target_analysis_id="AN002",
    )

    assert first == second
    assert first.root_stages == (AnalysisStage.RESUME_PARSE,)


def test_unknown_schema_impact_fails_closed() -> None:
    with pytest.raises(RecomputePlanningError, match="SCHEMA_RECOMPUTE_AUTHORITY_UNKNOWN"):
        _plan(
            _event(
                AnalysisChangeType.SCHEMA_VERSION_CHANGED,
                semantic_scope=ChangeSemanticScope.UNKNOWN,
            )
        )


def test_presentation_compatible_schema_change_only_rebuilds_report() -> None:
    plan = _plan(
        _event(
            AnalysisChangeType.SCHEMA_VERSION_CHANGED,
            semantic_scope=ChangeSemanticScope.PRESENTATION_ONLY,
        )
    )

    assert plan.recompute_from is RecomputeFrom.REPORT
    assert plan.stages_to_run == (AnalysisStage.REPORT,)


def test_classified_domain_schema_change_starts_at_declared_earliest_stage() -> None:
    plan = _plan(
        _event(
            AnalysisChangeType.SCHEMA_VERSION_CHANGED,
            semantic_scope=ChangeSemanticScope.DOMAIN_SEMANTIC,
            affected_stages=(AnalysisStage.EVIDENCE,),
        )
    )

    assert plan.recompute_from is RecomputeFrom.EVIDENCE
    assert plan.root_stages == (AnalysisStage.EVIDENCE,)


def test_analysis_engine_unknown_impact_uses_documented_matching_fallback() -> None:
    plan = _plan(
        _event(
            AnalysisChangeType.ANALYSIS_ENGINE_VERSION_CHANGED,
            semantic_scope=ChangeSemanticScope.UNKNOWN,
        )
    )

    assert plan.recompute_from is RecomputeFrom.MATCHING
    assert plan.root_stages == (AnalysisStage.MATCHING,)
    assert "RECOMPUTE_CONSERVATIVE_FALLBACK" in plan.reason_codes


def test_scoring_rule_match_semantics_change_fails_closed() -> None:
    with pytest.raises(
        RecomputePlanningError,
        match="MATCH_SEMANTICS_CHANGED_UNSUPPORTED",
    ):
        _plan(
            _event(
                AnalysisChangeType.SCORING_RULE_VERSION_CHANGED,
                semantic_scope=ChangeSemanticScope.DOMAIN_SEMANTIC,
                affected_stages=(AnalysisStage.MATCHING,),
            )
        )


def test_existing_invalid_artifact_is_recomputed_while_downstream_is_stale() -> None:
    graph = _graph_with_status(AnalysisStage.EVIDENCE, ValidityStatus.INVALID)

    plan = IncrementalRecomputePlanner().plan(
        current_artifacts=graph,
        change_events=(),
        target_analysis_id="AN002",
    )

    assert plan.recompute_from is RecomputeFrom.EVIDENCE
    assert "artifact-evidence" in plan.invalid_artifact_ids
    assert "artifact-matching" in plan.stale_artifact_ids
    assert "artifact-resume_parse" in plan.preserved_artifact_ids
    assert "RECOVER_INVALID_ARTIFACT" in plan.reason_codes


def test_existing_stale_artifact_triggers_safe_refresh_without_becoming_invalid() -> None:
    graph = _graph_with_status(AnalysisStage.REPORT, ValidityStatus.STALE)

    plan = IncrementalRecomputePlanner().plan(
        current_artifacts=graph,
        change_events=(),
        target_analysis_id="AN002",
    )

    assert plan.recompute_from is RecomputeFrom.REPORT
    assert plan.invalid_artifact_ids == ()
    assert plan.stale_artifact_ids == ("artifact-report",)
    assert plan.stages_to_run == (AnalysisStage.REPORT,)
    assert "REFRESH_STALE_ARTIFACT" in plan.reason_codes


def test_no_change_and_all_valid_artifacts_is_not_a_recompute_request() -> None:
    with pytest.raises(RecomputePlanningError, match="change event"):
        IncrementalRecomputePlanner().plan(
            current_artifacts=_graph(),
            change_events=(),
            target_analysis_id="AN002",
        )


def test_change_event_rejects_a_version_delta_without_an_identity_change() -> None:
    with pytest.raises(ValidationError, match="Version delta"):
        _event(AnalysisChangeType.PROMPT_P08_CHANGED, old="1.0.0", new="1.0.0")


def test_substantive_change_cannot_overwrite_the_source_analysis() -> None:
    event = _event(AnalysisChangeType.NEW_RESUME)

    with pytest.raises(RecomputePlanningError, match="new analysis identity"):
        IncrementalRecomputePlanner().plan(
            current_artifacts=_graph(),
            change_events=(event,),
            target_analysis_id="AN001",
        )
