"""Explicit acyclic dependency graph for the side-by-side v2 pipeline."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from jobfit.models.v2 import AnalysisStage


class DependencyGraphError(ValueError):
    """The dependency graph is incomplete or cyclic."""


STAGE_ORDER = (
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
_ORDER = {stage: index for index, stage in enumerate(STAGE_ORDER)}


@dataclass(frozen=True, slots=True)
class DependencyGraph:
    _dependencies: Mapping[AnalysisStage, tuple[AnalysisStage, ...]]

    def __init__(
        self,
        dependencies: Mapping[AnalysisStage, Sequence[AnalysisStage]],
    ) -> None:
        normalized = {
            stage: tuple(sorted(set(required), key=_ORDER.__getitem__))
            for stage, required in dependencies.items()
        }
        nodes = set(normalized)
        missing = {
            dependency
            for required in normalized.values()
            for dependency in required
            if dependency not in nodes
        }
        if missing:
            raise DependencyGraphError("Dependency graph references a missing node.")
        object.__setattr__(self, "_dependencies", MappingProxyType(normalized))
        self.topological_order()

    @property
    def cycle_count(self) -> int:
        return 0

    @property
    def stages(self) -> tuple[AnalysisStage, ...]:
        return tuple(sorted(self._dependencies, key=_ORDER.__getitem__))

    def dependencies_of(self, stage: AnalysisStage) -> tuple[AnalysisStage, ...]:
        try:
            return self._dependencies[stage]
        except KeyError as exc:
            raise DependencyGraphError("Dependency graph is missing a stage.") from exc

    def downstream_of(self, stage: AnalysisStage) -> tuple[AnalysisStage, ...]:
        if stage not in self._dependencies:
            raise DependencyGraphError("Dependency graph is missing a stage.")
        found: set[AnalysisStage] = set()
        pending = [stage]
        while pending:
            parent = pending.pop()
            for candidate, dependencies in self._dependencies.items():
                if parent in dependencies and candidate not in found:
                    found.add(candidate)
                    pending.append(candidate)
        return tuple(item for item in self.topological_order() if item in found)

    def closure(self, roots: Sequence[AnalysisStage]) -> tuple[AnalysisStage, ...]:
        affected = set(roots)
        for root in roots:
            affected.update(self.downstream_of(root))
        return tuple(item for item in self.topological_order() if item in affected)

    def topological_order(self) -> tuple[AnalysisStage, ...]:
        remaining = {
            stage: set(dependencies)
            for stage, dependencies in self._dependencies.items()
        }
        ordered: list[AnalysisStage] = []
        while remaining:
            ready = sorted(
                (stage for stage, dependencies in remaining.items() if not dependencies),
                key=_ORDER.__getitem__,
            )
            if not ready:
                raise DependencyGraphError("Dependency graph contains a cycle.")
            for stage in ready:
                ordered.append(stage)
                del remaining[stage]
            for dependencies in remaining.values():
                dependencies.difference_update(ready)
        return tuple(ordered)


DEFAULT_DEPENDENCY_GRAPH = DependencyGraph(
    {
        AnalysisStage.RESUME_PARSE: (),
        AnalysisStage.JD_PARSE: (),
        AnalysisStage.REQUIREMENT_CLASSIFICATION: (AnalysisStage.JD_PARSE,),
        AnalysisStage.EVIDENCE: (AnalysisStage.RESUME_PARSE,),
        AnalysisStage.READINESS: (
            AnalysisStage.REQUIREMENT_CLASSIFICATION,
            AnalysisStage.EVIDENCE,
        ),
        AnalysisStage.MATCHING: (
            AnalysisStage.REQUIREMENT_CLASSIFICATION,
            AnalysisStage.EVIDENCE,
            AnalysisStage.READINESS,
        ),
        AnalysisStage.ELIGIBILITY: (
            AnalysisStage.MATCHING,
        ),
        AnalysisStage.SCORING: (AnalysisStage.MATCHING,),
        AnalysisStage.RECOMMENDATION: (
            AnalysisStage.READINESS,
            AnalysisStage.ELIGIBILITY,
            AnalysisStage.SCORING,
        ),
        AnalysisStage.ACTIONS: (AnalysisStage.RECOMMENDATION,),
        AnalysisStage.INTERVIEW: (
            AnalysisStage.RECOMMENDATION,
            AnalysisStage.ACTIONS,
        ),
        AnalysisStage.REPORT: (
            AnalysisStage.RECOMMENDATION,
            AnalysisStage.ACTIONS,
            AnalysisStage.INTERVIEW,
        ),
    }
)
