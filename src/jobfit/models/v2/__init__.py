"""Isolated target-domain contracts for the product architecture upgrade."""

from jobfit.models.v2.analysis import ActionRecommendation as ActionRecommendation
from jobfit.models.v2.analysis import AnalysisCore as AnalysisCore
from jobfit.models.v2.analysis import InterviewQuestion as InterviewQuestion
from jobfit.models.v2.analysis import UserClarification as UserClarification
from jobfit.models.v2.bundle import JobFitDomainBundle as JobFitDomainBundle
from jobfit.models.v2.clarification import (
    ClarificationAnswer as ClarificationAnswer,
)
from jobfit.models.v2.clarification import (
    ClarificationAnswerSchema as ClarificationAnswerSchema,
)
from jobfit.models.v2.clarification import (
    ClarificationConflict as ClarificationConflict,
)
from jobfit.models.v2.clarification import (
    ClarificationQuestion as ClarificationQuestion,
)
from jobfit.models.v2.clarification import (
    ClarificationResolution as ClarificationResolution,
)
from jobfit.models.v2.clarification import (
    UnresolvedClarificationFact as UnresolvedClarificationFact,
)
from jobfit.models.v2.enums import AbilityStatus as AbilityStatus
from jobfit.models.v2.enums import ActionTiming as ActionTiming
from jobfit.models.v2.enums import ActionType as ActionType
from jobfit.models.v2.enums import AnalysisChangeType as AnalysisChangeType
from jobfit.models.v2.enums import AnalysisReadiness as AnalysisReadiness
from jobfit.models.v2.enums import AnalysisStage as AnalysisStage
from jobfit.models.v2.enums import CandidateStatus as CandidateStatus
from jobfit.models.v2.enums import ChangeSemanticScope as ChangeSemanticScope
from jobfit.models.v2.enums import CitationUsage as CitationUsage
from jobfit.models.v2.enums import (
    ClarificationAnswerStatus as ClarificationAnswerStatus,
)
from jobfit.models.v2.enums import ClarificationAnswerType as ClarificationAnswerType
from jobfit.models.v2.enums import (
    ClarificationConflictType as ClarificationConflictType,
)
from jobfit.models.v2.enums import ClarificationCoreImpact as ClarificationCoreImpact
from jobfit.models.v2.enums import (
    ClarificationQuestionStatus as ClarificationQuestionStatus,
)
from jobfit.models.v2.enums import (
    ClarificationQuestionType as ClarificationQuestionType,
)
from jobfit.models.v2.enums import (
    ClarificationResolutionStatus as ClarificationResolutionStatus,
)
from jobfit.models.v2.enums import ClarityLevel as ClarityLevel
from jobfit.models.v2.enums import Confidence as Confidence
from jobfit.models.v2.enums import CriticalStatus as CriticalStatus
from jobfit.models.v2.enums import Effort as Effort
from jobfit.models.v2.enums import EligibilityStatus as EligibilityStatus
from jobfit.models.v2.enums import EvidenceLevel as EvidenceLevel
from jobfit.models.v2.enums import EvidenceSourceOrigin as EvidenceSourceOrigin
from jobfit.models.v2.enums import EvidenceStatus as EvidenceStatus
from jobfit.models.v2.enums import EvidenceVisibility as EvidenceVisibility
from jobfit.models.v2.enums import FailureCategory as FailureCategory
from jobfit.models.v2.enums import FailureImpactLevel as FailureImpactLevel
from jobfit.models.v2.enums import InterviewQuestionType as InterviewQuestionType
from jobfit.models.v2.enums import JobFamily as JobFamily
from jobfit.models.v2.enums import KnowledgeCoverage as KnowledgeCoverage
from jobfit.models.v2.enums import LifecycleStatus as LifecycleStatus
from jobfit.models.v2.enums import MatchCoverage as MatchCoverage
from jobfit.models.v2.enums import ParseCompleteness as ParseCompleteness
from jobfit.models.v2.enums import PersonalContribution as PersonalContribution
from jobfit.models.v2.enums import Priority as Priority
from jobfit.models.v2.enums import ReasonCode as ReasonCode
from jobfit.models.v2.enums import Recommendation as Recommendation
from jobfit.models.v2.enums import RecomputeFrom as RecomputeFrom
from jobfit.models.v2.enums import Relevance as Relevance
from jobfit.models.v2.enums import Reliability as Reliability
from jobfit.models.v2.enums import (
    RequirementExplicitness as RequirementExplicitness,
)
from jobfit.models.v2.enums import RequirementSource as RequirementSource
from jobfit.models.v2.enums import RequirementType as RequirementType
from jobfit.models.v2.enums import SeniorityAlignment as SeniorityAlignment
from jobfit.models.v2.enums import SupportType as SupportType
from jobfit.models.v2.enums import TaskStatus as TaskStatus
from jobfit.models.v2.enums import Transferability as Transferability
from jobfit.models.v2.enums import ValidityStatus as ValidityStatus
from jobfit.models.v2.evidence import CandidateProfile as CandidateProfile
from jobfit.models.v2.evidence import Evidence as Evidence
from jobfit.models.v2.evidence import ResumeProfile as ResumeProfile
from jobfit.models.v2.governance import (
    NOT_EXPLICITLY_VERSIONED as NOT_EXPLICITLY_VERSIONED,
)
from jobfit.models.v2.governance import AnalysisLifecycle as AnalysisLifecycle
from jobfit.models.v2.governance import (
    AnalysisVersionIdentity as AnalysisVersionIdentity,
)
from jobfit.models.v2.governance import Failure as Failure
from jobfit.models.v2.governance import JDSnapshotIdentity as JDSnapshotIdentity
from jobfit.models.v2.governance import (
    ResumeVersionIdentity as ResumeVersionIdentity,
)
from jobfit.models.v2.governance import VersionManifest as VersionManifest
from jobfit.models.v2.job import JobProfile as JobProfile
from jobfit.models.v2.job import MatchedEvidence as MatchedEvidence
from jobfit.models.v2.job import Requirement as Requirement
from jobfit.models.v2.job import RequirementMatch as RequirementMatch
from jobfit.models.v2.lifecycle import AnalysisChangeEvent as AnalysisChangeEvent
from jobfit.models.v2.lifecycle import AnalysisInputSnapshot as AnalysisInputSnapshot
from jobfit.models.v2.lifecycle import AnalysisRun as AnalysisRun
from jobfit.models.v2.lifecycle import ArtifactGraph as ArtifactGraph
from jobfit.models.v2.lifecycle import ArtifactRecord as ArtifactRecord
from jobfit.models.v2.lifecycle import ArtifactValidity as ArtifactValidity
from jobfit.models.v2.lifecycle import (
    ClarificationInputSnapshot as ClarificationInputSnapshot,
)
from jobfit.models.v2.lifecycle import FrozenVersionManifest as FrozenVersionManifest
from jobfit.models.v2.lifecycle import RecomputePlan as RecomputePlan
from jobfit.models.v2.lifecycle import VersionDelta as VersionDelta
from jobfit.models.v2.report import JobFitReport as JobFitReport
from jobfit.models.v2.report import KnowledgeCitation as KnowledgeCitation

__all__ = [
    "AbilityStatus",
    "ActionRecommendation",
    "ActionTiming",
    "ActionType",
    "AnalysisCore",
    "AnalysisChangeEvent",
    "AnalysisChangeType",
    "AnalysisInputSnapshot",
    "AnalysisLifecycle",
    "AnalysisReadiness",
    "AnalysisRun",
    "AnalysisStage",
    "AnalysisVersionIdentity",
    "ArtifactGraph",
    "ArtifactRecord",
    "ArtifactValidity",
    "CandidateProfile",
    "CandidateStatus",
    "CitationUsage",
    "ClarityLevel",
    "ChangeSemanticScope",
    "Confidence",
    "ClarificationAnswer",
    "ClarificationAnswerSchema",
    "ClarificationAnswerStatus",
    "ClarificationAnswerType",
    "ClarificationConflict",
    "ClarificationConflictType",
    "ClarificationInputSnapshot",
    "ClarificationCoreImpact",
    "ClarificationQuestion",
    "ClarificationQuestionStatus",
    "ClarificationQuestionType",
    "ClarificationResolution",
    "ClarificationResolutionStatus",
    "CriticalStatus",
    "Effort",
    "EligibilityStatus",
    "EvidenceLevel",
    "EvidenceSourceOrigin",
    "EvidenceStatus",
    "EvidenceVisibility",
    "Evidence",
    "Failure",
    "FailureCategory",
    "FailureImpactLevel",
    "FrozenVersionManifest",
    "InterviewQuestion",
    "InterviewQuestionType",
    "JDSnapshotIdentity",
    "JobFamily",
    "JobFitReport",
    "JobFitDomainBundle",
    "JobProfile",
    "KnowledgeCitation",
    "KnowledgeCoverage",
    "LifecycleStatus",
    "MatchCoverage",
    "MatchedEvidence",
    "NOT_EXPLICITLY_VERSIONED",
    "ParseCompleteness",
    "PersonalContribution",
    "Priority",
    "Recommendation",
    "ReasonCode",
    "RecomputeFrom",
    "RecomputePlan",
    "Relevance",
    "Reliability",
    "RequirementExplicitness",
    "Requirement",
    "RequirementMatch",
    "RequirementSource",
    "RequirementType",
    "SeniorityAlignment",
    "ResumeProfile",
    "ResumeVersionIdentity",
    "SupportType",
    "TaskStatus",
    "Transferability",
    "UserClarification",
    "UnresolvedClarificationFact",
    "ValidityStatus",
    "VersionManifest",
    "VersionDelta",
]
