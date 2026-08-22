"""Side-by-side B6 lifecycle and incremental-recompute APIs."""

from jobfit.workflow.v2.application import (
    V2AnalysisApplication as V2AnalysisApplication,
)
from jobfit.workflow.v2.application import V2AnalysisSession as V2AnalysisSession
from jobfit.workflow.v2.application import V2ApplicationError as V2ApplicationError
from jobfit.workflow.v2.application import stable_run_identity as stable_run_identity
from jobfit.workflow.v2.coordinator import (
    IncrementalRecomputeCoordinator as IncrementalRecomputeCoordinator,
)
from jobfit.workflow.v2.coordinator import (
    RecomputeExecutionError as RecomputeExecutionError,
)
from jobfit.workflow.v2.coordinator import (
    RecomputeExecutionResult as RecomputeExecutionResult,
)
from jobfit.workflow.v2.coordinator import (
    StageExecutionContext as StageExecutionContext,
)
from jobfit.workflow.v2.coordinator import (
    StageExecutionFailure as StageExecutionFailure,
)
from jobfit.workflow.v2.dependencies import (
    DEFAULT_DEPENDENCY_GRAPH as DEFAULT_DEPENDENCY_GRAPH,
)
from jobfit.workflow.v2.dependencies import DependencyGraph as DependencyGraph
from jobfit.workflow.v2.dependencies import (
    DependencyGraphError as DependencyGraphError,
)
from jobfit.workflow.v2.history import AnalysisHistoryError as AnalysisHistoryError
from jobfit.workflow.v2.history import AnalysisRepository as AnalysisRepository
from jobfit.workflow.v2.history import (
    InMemoryAnalysisRepository as InMemoryAnalysisRepository,
)
from jobfit.workflow.v2.history import PersistedAnalysis as PersistedAnalysis
from jobfit.workflow.v2.invalidation import (
    RecomputePlanningError as RecomputePlanningError,
)
from jobfit.workflow.v2.lifecycle import (
    LifecycleTransitionError as LifecycleTransitionError,
)
from jobfit.workflow.v2.lifecycle import complete_stage as complete_stage
from jobfit.workflow.v2.lifecycle import create_analysis_run as create_analysis_run
from jobfit.workflow.v2.lifecycle import fail_stage as fail_stage
from jobfit.workflow.v2.lifecycle import fork_analysis_run as fork_analysis_run
from jobfit.workflow.v2.lifecycle import start_stage as start_stage
from jobfit.workflow.v2.lifecycle import transition_run as transition_run
from jobfit.workflow.v2.persistence import (
    ANALYSIS_SCHEMA_VERSION as ANALYSIS_SCHEMA_VERSION,
)
from jobfit.workflow.v2.persistence import AnalysisDatabase as AnalysisDatabase
from jobfit.workflow.v2.persistence import (
    AnalysisPersistenceError as AnalysisPersistenceError,
)
from jobfit.workflow.v2.persistence import (
    SQLiteAnalysisRepository as SQLiteAnalysisRepository,
)
from jobfit.workflow.v2.persistence import (
    build_analysis_repository as build_analysis_repository,
)
from jobfit.workflow.v2.persistence import (
    initialize_analysis_schema as initialize_analysis_schema,
)
from jobfit.workflow.v2.persistence import (
    resolve_analysis_db_path as resolve_analysis_db_path,
)
from jobfit.workflow.v2.planner import (
    IncrementalRecomputePlanner as IncrementalRecomputePlanner,
)

__all__ = [
    "DEFAULT_DEPENDENCY_GRAPH",
    "ANALYSIS_SCHEMA_VERSION",
    "AnalysisDatabase",
    "AnalysisHistoryError",
    "AnalysisPersistenceError",
    "AnalysisRepository",
    "DependencyGraph",
    "DependencyGraphError",
    "IncrementalRecomputePlanner",
    "IncrementalRecomputeCoordinator",
    "InMemoryAnalysisRepository",
    "LifecycleTransitionError",
    "V2AnalysisApplication",
    "V2AnalysisSession",
    "V2ApplicationError",
    "RecomputePlanningError",
    "PersistedAnalysis",
    "RecomputeExecutionError",
    "RecomputeExecutionResult",
    "StageExecutionContext",
    "StageExecutionFailure",
    "SQLiteAnalysisRepository",
    "build_analysis_repository",
    "complete_stage",
    "create_analysis_run",
    "fail_stage",
    "fork_analysis_run",
    "initialize_analysis_schema",
    "resolve_analysis_db_path",
    "start_stage",
    "transition_run",
    "stable_run_identity",
]
