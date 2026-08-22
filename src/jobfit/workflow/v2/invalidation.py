"""Pure deterministic B6 change-impact and validity propagation."""

from __future__ import annotations

from dataclasses import dataclass

from jobfit.models.v2 import (
    AnalysisChangeEvent,
    AnalysisChangeType,
    AnalysisStage,
    ArtifactGraph,
    ArtifactValidity,
    ChangeSemanticScope,
    ValidityStatus,
)
from jobfit.workflow.v2.dependencies import DEFAULT_DEPENDENCY_GRAPH, DependencyGraph


class RecomputePlanningError(ValueError):
    """A change cannot be mapped safely to authorized recompute semantics."""


@dataclass(frozen=True, slots=True)
class ChangeImpact:
    roots: tuple[AnalysisStage, ...]
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class InvalidationResult:
    root_stages: tuple[AnalysisStage, ...]
    affected_stages: tuple[AnalysisStage, ...]
    artifact_validity: tuple[ArtifactValidity, ...]
    reason_codes: tuple[str, ...]


def classify_change(event: AnalysisChangeEvent) -> ChangeImpact:
    change_type = event.change_type
    if change_type is AnalysisChangeType.SCORING_RULE_VERSION_CHANGED:
        if (
            event.semantic_scope is not ChangeSemanticScope.SCORING_ONLY
            or any(stage is not AnalysisStage.SCORING for stage in event.affected_stages)
        ):
            raise RecomputePlanningError("MATCH_SEMANTICS_CHANGED_UNSUPPORTED")
        return ChangeImpact(
            roots=(AnalysisStage.SCORING,),
            reason_codes=("CHANGE_SCORING_RULE_VERSION_CHANGED",),
        )
    direct: dict[AnalysisChangeType, AnalysisStage | None] = {
        AnalysisChangeType.UI_OR_NOTE_ONLY: None,
        AnalysisChangeType.NEW_RESUME: AnalysisStage.RESUME_PARSE,
        AnalysisChangeType.RESUME_TEXT_CHANGED: AnalysisStage.RESUME_PARSE,
        AnalysisChangeType.USER_CONFIRMED_EXPERIENCE: AnalysisStage.EVIDENCE,
        AnalysisChangeType.HARD_CLARIFICATION_CHANGED: AnalysisStage.ELIGIBILITY,
        AnalysisChangeType.NEW_JD: AnalysisStage.JD_PARSE,
        AnalysisChangeType.JD_SEMANTIC_CHANGED: AnalysisStage.JD_PARSE,
        AnalysisChangeType.KNOWLEDGE_VERSION_CHANGED: AnalysisStage.ACTIONS,
        AnalysisChangeType.PROMPT_P01_CHANGED: AnalysisStage.RESUME_PARSE,
        AnalysisChangeType.PROMPT_P02_CHANGED: AnalysisStage.JD_PARSE,
        AnalysisChangeType.PROMPT_P03_CHANGED: AnalysisStage.REQUIREMENT_CLASSIFICATION,
        AnalysisChangeType.PROMPT_P04_CHANGED: AnalysisStage.EVIDENCE,
        AnalysisChangeType.PROMPT_P05_CHANGED: AnalysisStage.MATCHING,
        AnalysisChangeType.PROMPT_P06_CHANGED: AnalysisStage.ACTIONS,
        AnalysisChangeType.PROMPT_P07_CHANGED: AnalysisStage.INTERVIEW,
        AnalysisChangeType.PROMPT_P08_CHANGED: AnalysisStage.REPORT,
    }
    if change_type in direct:
        stage = direct[change_type]
        return ChangeImpact(
            roots=(() if stage is None else (stage,)),
            reason_codes=(f"CHANGE_{change_type.value}",),
        )
    if change_type is AnalysisChangeType.SCHEMA_VERSION_CHANGED:
        if event.semantic_scope is ChangeSemanticScope.PRESENTATION_ONLY:
            return ChangeImpact(
                roots=(AnalysisStage.REPORT,),
                reason_codes=("SCHEMA_PRESENTATION_COMPATIBLE",),
            )
        if (
            event.semantic_scope is ChangeSemanticScope.DOMAIN_SEMANTIC
            and event.affected_stages
        ):
            return ChangeImpact(
                roots=event.affected_stages,
                reason_codes=("SCHEMA_DOMAIN_SEMANTIC_CHANGE",),
            )
        raise RecomputePlanningError("SCHEMA_RECOMPUTE_AUTHORITY_UNKNOWN")
    if change_type is AnalysisChangeType.ANALYSIS_ENGINE_VERSION_CHANGED:
        if event.affected_stages:
            return ChangeImpact(
                roots=event.affected_stages,
                reason_codes=("ANALYSIS_ENGINE_CLASSIFIED_CHANGE",),
            )
        return ChangeImpact(
            roots=(AnalysisStage.MATCHING,),
            reason_codes=("RECOMPUTE_CONSERVATIVE_FALLBACK",),
        )
    raise RecomputePlanningError("UNKNOWN_RECOMPUTE_IMPACT")


def propagate_validity(
    artifacts: ArtifactGraph,
    events: tuple[AnalysisChangeEvent, ...],
    *,
    graph: DependencyGraph = DEFAULT_DEPENDENCY_GRAPH,
    recovery_roots: tuple[AnalysisStage, ...] = (),
) -> InvalidationResult:
    roots: set[AnalysisStage] = set(recovery_roots)
    reasons: list[str] = []
    for stage in recovery_roots:
        statuses = {
            artifact.validity
            for artifact in artifacts.artifacts
            if artifact.stage is stage
        }
        if ValidityStatus.INVALID in statuses:
            reasons.append("RECOVER_INVALID_ARTIFACT")
        elif ValidityStatus.STALE in statuses:
            reasons.append("REFRESH_STALE_ARTIFACT")
    for event in sorted(events, key=lambda item: item.change_id):
        impact = classify_change(event)
        roots.update(impact.roots)
        reasons.extend(impact.reason_codes)
    minimal_roots = _minimal_roots(roots, graph)
    affected = graph.closure(minimal_roots)
    affected_set = set(affected)
    validity = tuple(
        ArtifactValidity(
            artifact_id=artifact.artifact_id,
            validity=(
                ValidityStatus.INVALID
                if artifact.validity is ValidityStatus.INVALID
                else (
                    ValidityStatus.STALE
                    if artifact.stage in affected_set
                    else artifact.validity
                )
            ),
        )
        for artifact in artifacts.artifacts
    )
    return InvalidationResult(
        root_stages=minimal_roots,
        affected_stages=affected,
        artifact_validity=validity,
        reason_codes=tuple(dict.fromkeys(reasons)),
    )


def _minimal_roots(
    roots: set[AnalysisStage],
    graph: DependencyGraph,
) -> tuple[AnalysisStage, ...]:
    redundant = {
        candidate
        for root in roots
        for candidate in roots
        if candidate is not root and candidate in graph.downstream_of(root)
    }
    return tuple(stage for stage in graph.topological_order() if stage in roots - redundant)
