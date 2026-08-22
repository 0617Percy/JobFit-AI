"""Stable public data contracts for JobFit Agent."""

from jobfit.models.advice import AdviceBundleDraft as AdviceBundleDraft
from jobfit.models.advice import (
    ApplicationRecommendation as ApplicationRecommendation,
)
from jobfit.models.advice import GapItem as GapItem
from jobfit.models.advice import InterviewQuestion as InterviewQuestion
from jobfit.models.advice import InterviewQuestionDraft as InterviewQuestionDraft
from jobfit.models.advice import RewriteSuggestion as RewriteSuggestion
from jobfit.models.advice import RewriteSuggestionDraft as RewriteSuggestionDraft
from jobfit.models.advice import StrengthItem as StrengthItem
from jobfit.models.common import AnalysisRequest as AnalysisRequest
from jobfit.models.common import ConfidenceLevel as ConfidenceLevel
from jobfit.models.common import DocumentSourceKind as DocumentSourceKind
from jobfit.models.common import EvidenceKind as EvidenceKind
from jobfit.models.common import EvidenceSourceType as EvidenceSourceType
from jobfit.models.common import GapRemediability as GapRemediability
from jobfit.models.common import HardConditionKind as HardConditionKind
from jobfit.models.common import Importance as Importance
from jobfit.models.common import LanguageCode as LanguageCode
from jobfit.models.common import MatchStatus as MatchStatus
from jobfit.models.common import ProgressEvent as ProgressEvent
from jobfit.models.common import RecommendationLevel as RecommendationLevel
from jobfit.models.common import RequirementCategory as RequirementCategory
from jobfit.models.common import RequirementType as RequirementType
from jobfit.models.common import SkillType as SkillType
from jobfit.models.common import StrictModel as StrictModel
from jobfit.models.common import UploadedDocumentInput as UploadedDocumentInput
from jobfit.models.common import ValidationSeverity as ValidationSeverity
from jobfit.models.common import WorkflowStage as WorkflowStage
from jobfit.models.document import DocumentContent as DocumentContent
from jobfit.models.document import EvidenceItem as EvidenceItem
from jobfit.models.document import EvidenceRegistry as EvidenceRegistry
from jobfit.models.document import TextSegment as TextSegment
from jobfit.models.job import JobExtractionDraft as JobExtractionDraft
from jobfit.models.job import JobProfile as JobProfile
from jobfit.models.job import JobRequirement as JobRequirement
from jobfit.models.job import (
    JobRequirementCollection as JobRequirementCollection,
)
from jobfit.models.job import JobRequirementDraft as JobRequirementDraft
from jobfit.models.knowledge import (
    EvidencePatternStrength as EvidencePatternStrength,
)
from jobfit.models.knowledge import InterviewDifficulty as InterviewDifficulty
from jobfit.models.knowledge import (
    KnowledgeBaseVersionInfo as KnowledgeBaseVersionInfo,
)
from jobfit.models.knowledge import KnowledgeCitation as KnowledgeCitation
from jobfit.models.knowledge import KnowledgeContext as KnowledgeContext
from jobfit.models.knowledge import KnowledgeQuestionType as KnowledgeQuestionType
from jobfit.models.knowledge import (
    KnowledgeRetrievalResult as KnowledgeRetrievalResult,
)
from jobfit.models.knowledge import (
    KnowledgeRetrievalStatus as KnowledgeRetrievalStatus,
)
from jobfit.models.knowledge import (
    KnowledgeReviewStatus as KnowledgeReviewStatus,
)
from jobfit.models.knowledge import (
    KnowledgeSearchBackend as KnowledgeSearchBackend,
)
from jobfit.models.knowledge import (
    KnowledgeSearchCapabilities as KnowledgeSearchCapabilities,
)
from jobfit.models.knowledge import (
    KnowledgeSearchCapabilityStatus as KnowledgeSearchCapabilityStatus,
)
from jobfit.models.knowledge import KnowledgeSearchMode as KnowledgeSearchMode
from jobfit.models.knowledge import KnowledgeSourceType as KnowledgeSourceType
from jobfit.models.knowledge import (
    KnowledgeVersionStatus as KnowledgeVersionStatus,
)
from jobfit.models.knowledge import KnowledgeWarning as KnowledgeWarning
from jobfit.models.knowledge import KnowledgeWarningCode as KnowledgeWarningCode
from jobfit.models.knowledge import ReliabilityLevel as ReliabilityLevel
from jobfit.models.knowledge import (
    RetrievedEvidencePattern as RetrievedEvidencePattern,
)
from jobfit.models.knowledge import (
    RetrievedInterviewQuestion as RetrievedInterviewQuestion,
)
from jobfit.models.knowledge import RetrievedRequirement as RetrievedRequirement
from jobfit.models.knowledge import RetrievedRoleProfile as RetrievedRoleProfile
from jobfit.models.knowledge_advice import (
    KnowledgeAdviceTargetType as KnowledgeAdviceTargetType,
)
from jobfit.models.knowledge_advice import (
    KnowledgeAdviceTrace as KnowledgeAdviceTrace,
)
from jobfit.models.knowledge_advice import (
    KnowledgeCitationPurpose as KnowledgeCitationPurpose,
)
from jobfit.models.knowledge_advice import (
    KnowledgeCitationUse as KnowledgeCitationUse,
)
from jobfit.models.knowledge_advice import (
    KnowledgeCitationUseDraft as KnowledgeCitationUseDraft,
)
from jobfit.models.matching import DimensionScore as DimensionScore
from jobfit.models.matching import MatchScoreSummary as MatchScoreSummary
from jobfit.models.matching import RequirementMatch as RequirementMatch
from jobfit.models.matching import RequirementMatchDraft as RequirementMatchDraft
from jobfit.models.report import AnalysisReport as AnalysisReport
from jobfit.models.report import ValidationIssue as ValidationIssue
from jobfit.models.report import ValidationResult as ValidationResult
from jobfit.models.report_knowledge import ReportCitationStatus as ReportCitationStatus
from jobfit.models.report_knowledge import (
    ReportKnowledgeAdviceTrace as ReportKnowledgeAdviceTrace,
)
from jobfit.models.report_knowledge import (
    ReportKnowledgeCitation as ReportKnowledgeCitation,
)
from jobfit.models.report_knowledge import (
    ReportKnowledgeEvidencePattern as ReportKnowledgeEvidencePattern,
)
from jobfit.models.report_knowledge import (
    ReportKnowledgeInterviewReference as ReportKnowledgeInterviewReference,
)
from jobfit.models.report_knowledge import (
    ReportKnowledgeRequirement as ReportKnowledgeRequirement,
)
from jobfit.models.report_knowledge import (
    ReportKnowledgeSection as ReportKnowledgeSection,
)
from jobfit.models.report_knowledge import (
    ReportKnowledgeWarning as ReportKnowledgeWarning,
)
from jobfit.models.report_knowledge import (
    ReportRoleProfileReference as ReportRoleProfileReference,
)
from jobfit.models.resume import AchievementItem as AchievementItem
from jobfit.models.resume import BasicInfo as BasicInfo
from jobfit.models.resume import CertificateItem as CertificateItem
from jobfit.models.resume import EducationItem as EducationItem
from jobfit.models.resume import EvidenceCandidate as EvidenceCandidate
from jobfit.models.resume import ExperienceItem as ExperienceItem
from jobfit.models.resume import LanguageItem as LanguageItem
from jobfit.models.resume import ProjectItem as ProjectItem
from jobfit.models.resume import ResumeBullet as ResumeBullet
from jobfit.models.resume import ResumeExtractionDraft as ResumeExtractionDraft
from jobfit.models.resume import ResumeFact as ResumeFact
from jobfit.models.resume import ResumeFactDraft as ResumeFactDraft
from jobfit.models.resume import ResumeProfile as ResumeProfile
from jobfit.models.resume import SkillItem as SkillItem

__all__ = [
    "AchievementItem",
    "AdviceBundleDraft",
    "AnalysisReport",
    "AnalysisRequest",
    "ApplicationRecommendation",
    "BasicInfo",
    "CertificateItem",
    "ConfidenceLevel",
    "DimensionScore",
    "DocumentContent",
    "DocumentSourceKind",
    "EducationItem",
    "EvidencePatternStrength",
    "EvidenceCandidate",
    "EvidenceItem",
    "EvidenceKind",
    "EvidenceRegistry",
    "EvidenceSourceType",
    "ExperienceItem",
    "GapItem",
    "GapRemediability",
    "HardConditionKind",
    "Importance",
    "InterviewDifficulty",
    "InterviewQuestion",
    "InterviewQuestionDraft",
    "JobExtractionDraft",
    "JobProfile",
    "JobRequirement",
    "JobRequirementCollection",
    "JobRequirementDraft",
    "KnowledgeBaseVersionInfo",
    "KnowledgeAdviceTargetType",
    "KnowledgeAdviceTrace",
    "KnowledgeCitation",
    "KnowledgeCitationPurpose",
    "KnowledgeCitationUse",
    "KnowledgeCitationUseDraft",
    "KnowledgeContext",
    "KnowledgeQuestionType",
    "KnowledgeRetrievalResult",
    "KnowledgeRetrievalStatus",
    "KnowledgeReviewStatus",
    "KnowledgeSearchBackend",
    "KnowledgeSearchCapabilities",
    "KnowledgeSearchCapabilityStatus",
    "KnowledgeSearchMode",
    "KnowledgeSourceType",
    "KnowledgeVersionStatus",
    "KnowledgeWarning",
    "KnowledgeWarningCode",
    "LanguageCode",
    "LanguageItem",
    "MatchScoreSummary",
    "MatchStatus",
    "ProgressEvent",
    "ProjectItem",
    "RecommendationLevel",
    "ReportCitationStatus",
    "ReportKnowledgeAdviceTrace",
    "ReportKnowledgeCitation",
    "ReportKnowledgeEvidencePattern",
    "ReportKnowledgeInterviewReference",
    "ReportKnowledgeRequirement",
    "ReportKnowledgeSection",
    "ReportKnowledgeWarning",
    "ReportRoleProfileReference",
    "RequirementCategory",
    "RequirementMatch",
    "RequirementMatchDraft",
    "RequirementType",
    "ReliabilityLevel",
    "ResumeBullet",
    "ResumeExtractionDraft",
    "ResumeFact",
    "ResumeFactDraft",
    "ResumeProfile",
    "RetrievedEvidencePattern",
    "RetrievedInterviewQuestion",
    "RetrievedRequirement",
    "RetrievedRoleProfile",
    "RewriteSuggestion",
    "RewriteSuggestionDraft",
    "SkillItem",
    "SkillType",
    "StrengthItem",
    "StrictModel",
    "TextSegment",
    "UploadedDocumentInput",
    "ValidationIssue",
    "ValidationResult",
    "ValidationSeverity",
    "WorkflowStage",
]
