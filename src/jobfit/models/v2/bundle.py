"""Root target-domain snapshot used for cross-object validation."""

from pydantic import Field

from jobfit.models.common import StrictModel
from jobfit.models.v2.analysis import (
    ActionRecommendation,
    AnalysisCore,
    InterviewQuestion,
    UserClarification,
)
from jobfit.models.v2.evidence import Evidence, ResumeProfile
from jobfit.models.v2.governance import AnalysisLifecycle, Failure, VersionManifest
from jobfit.models.v2.job import JobProfile, Requirement, RequirementMatch
from jobfit.models.v2.report import JobFitReport, KnowledgeCitation


class JobFitDomainBundle(StrictModel):
    """Planning-schema root without persistence or decision-engine behavior."""

    resume_profile: ResumeProfile | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    job_profile: JobProfile | None = None
    requirements: list[Requirement] = Field(default_factory=list)
    requirement_matches: list[RequirementMatch] = Field(default_factory=list)
    analysis_core: AnalysisCore | None = None
    actions: list[ActionRecommendation] = Field(default_factory=list)
    interview_questions: list[InterviewQuestion] = Field(default_factory=list)
    knowledge_citations: list[KnowledgeCitation] = Field(default_factory=list)
    user_clarifications: list[UserClarification] = Field(default_factory=list)
    report: JobFitReport | None = None
    versions: VersionManifest | None = None
    failures: list[Failure] = Field(default_factory=list)
    analysis_lifecycle: AnalysisLifecycle | None = None
