"""Side-by-side deterministic JobFit v2 decision engine."""

from jobfit.scoring.v2.decision import (
    ClarificationCandidate as ClarificationCandidate,
)
from jobfit.scoring.v2.decision import ClarificationImpact as ClarificationImpact
from jobfit.scoring.v2.decision import CriticalDecision as CriticalDecision
from jobfit.scoring.v2.decision import HardDecision as HardDecision
from jobfit.scoring.v2.decision import (
    RecommendationDecision as RecommendationDecision,
)
from jobfit.scoring.v2.decision import SeniorityFacts as SeniorityFacts
from jobfit.scoring.v2.decision import SeniorScopeDemand as SeniorScopeDemand
from jobfit.scoring.v2.decision import evaluate_confidence as evaluate_confidence
from jobfit.scoring.v2.decision import evaluate_critical as evaluate_critical
from jobfit.scoring.v2.decision import evaluate_eligibility as evaluate_eligibility
from jobfit.scoring.v2.decision import evaluate_hard as evaluate_hard
from jobfit.scoring.v2.decision import evaluate_readiness as evaluate_readiness
from jobfit.scoring.v2.decision import (
    evaluate_recommendation as evaluate_recommendation,
)
from jobfit.scoring.v2.decision import evaluate_seniority as evaluate_seniority
from jobfit.scoring.v2.decision import (
    select_clarifications as select_clarifications,
)
from jobfit.scoring.v2.decision import should_force_continue as should_force_continue
from jobfit.scoring.v2.engine import ANALYSIS_ENGINE_VERSION as ANALYSIS_ENGINE_VERSION
from jobfit.scoring.v2.engine import CALIBRATION_STATUS as CALIBRATION_STATUS
from jobfit.scoring.v2.engine import SCORING_RULE_VERSION as SCORING_RULE_VERSION
from jobfit.scoring.v2.engine import AnalysisCoreResult as AnalysisCoreResult
from jobfit.scoring.v2.engine import (
    DeterministicDecisionEngine as DeterministicDecisionEngine,
)
from jobfit.scoring.v2.engine import build_v2_version_manifest as build_v2_version_manifest
from jobfit.scoring.v2.errors import DecisionInputError as DecisionInputError
from jobfit.scoring.v2.errors import (
    DecisionNotFinalizableError as DecisionNotFinalizableError,
)
from jobfit.scoring.v2.evidence import (
    MatchComputation as MatchComputation,
)
from jobfit.scoring.v2.evidence import (
    compute_requirement_match as compute_requirement_match,
)
from jobfit.scoring.v2.evidence import (
    determine_evidence_level as determine_evidence_level,
)
from jobfit.scoring.v2.evidence import (
    validate_evidence_level as validate_evidence_level,
)
from jobfit.scoring.v2.score import ScoreComputation as ScoreComputation
from jobfit.scoring.v2.score import compute_scores as compute_scores

__all__ = [
    "DecisionInputError",
    "DecisionNotFinalizableError",
    "ANALYSIS_ENGINE_VERSION",
    "AnalysisCoreResult",
    "CALIBRATION_STATUS",
    "ClarificationCandidate",
    "ClarificationImpact",
    "CriticalDecision",
    "HardDecision",
    "MatchComputation",
    "ScoreComputation",
    "RecommendationDecision",
    "SCORING_RULE_VERSION",
    "SeniorScopeDemand",
    "SeniorityFacts",
    "compute_requirement_match",
    "compute_scores",
    "build_v2_version_manifest",
    "DeterministicDecisionEngine",
    "determine_evidence_level",
    "evaluate_confidence",
    "evaluate_critical",
    "evaluate_eligibility",
    "evaluate_hard",
    "evaluate_readiness",
    "evaluate_recommendation",
    "evaluate_seniority",
    "select_clarifications",
    "should_force_continue",
    "validate_evidence_level",
]
