"""Candidate P01-P05 pipeline feeding only validated objects to frozen B2."""

from __future__ import annotations

from dataclasses import dataclass

from jobfit.models import DocumentContent
from jobfit.scoring.v2 import (
    AnalysisCoreResult,
    DeterministicDecisionEngine,
    SeniorityFacts,
)
from jobfit.semantic.v2.contracts import PromptExecutionRecord
from jobfit.semantic.v2.executor import SemanticPromptError, SemanticPromptExecutor
from jobfit.semantic.v2.p01_resume import P01ResumeParser, P01ResumeResult
from jobfit.semantic.v2.p02_job import P02JobParser, P02JobResult
from jobfit.semantic.v2.p03_requirements import (
    P03RequirementClassifier,
    P03RequirementResult,
)
from jobfit.semantic.v2.p04_evidence import P04EvidenceNormalizer, P04EvidenceResult
from jobfit.semantic.v2.p05_match import P05MatchResult, P05SemanticMatcher
from jobfit.semantic.v2.validation import (
    SemanticPipelineValidator,
    SemanticValidationResult,
)


@dataclass(frozen=True, slots=True)
class SemanticPreparationResult:
    p01: P01ResumeResult
    p02: P02JobResult
    p03: P03RequirementResult
    p04: P04EvidenceResult
    p05: P05MatchResult
    validation: SemanticValidationResult
    executions: tuple[PromptExecutionRecord, ...]


@dataclass(frozen=True, slots=True)
class SemanticPipelineResult(SemanticPreparationResult):
    analysis: AnalysisCoreResult


class SemanticPipeline:
    """Side-by-side candidate flow; it is not wired into production workflow."""

    def __init__(
        self,
        executor: SemanticPromptExecutor,
        *,
        validator: SemanticPipelineValidator | None = None,
        decision_engine: DeterministicDecisionEngine | None = None,
    ) -> None:
        self._p01 = P01ResumeParser(executor)
        self._p02 = P02JobParser(executor)
        self._p03 = P03RequirementClassifier(executor)
        self._p04 = P04EvidenceNormalizer(executor)
        self._p05 = P05SemanticMatcher(executor)
        self._validator = validator or SemanticPipelineValidator()
        self._decision_engine = decision_engine or DeterministicDecisionEngine()

    def run(
        self,
        *,
        analysis_id: str,
        resume_version_id: str,
        jd_snapshot_id: str,
        resume_document: DocumentContent,
        jd_document: DocumentContent,
        seniority_facts: SeniorityFacts,
    ) -> SemanticPipelineResult:
        prepared = self.prepare(
            analysis_id=analysis_id,
            resume_version_id=resume_version_id,
            jd_snapshot_id=jd_snapshot_id,
            resume_document=resume_document,
            jd_document=jd_document,
        )
        analysis = self._decision_engine.build_analysis_core(
            analysis_id=analysis_id,
            resume_profile=prepared.p01.profile,
            job_profile=prepared.p03.job_profile,
            requirements=prepared.p03.requirements,
            matches=prepared.p05.matches,
            evidence=prepared.p04.evidence,
            seniority_facts=seniority_facts,
            role_scope_valid=prepared.p02.role_scope_valid,
        )
        return SemanticPipelineResult(
            p01=prepared.p01,
            p02=prepared.p02,
            p03=prepared.p03,
            p04=prepared.p04,
            p05=prepared.p05,
            validation=prepared.validation,
            executions=prepared.executions,
            analysis=analysis,
        )

    def prepare(
        self,
        *,
        analysis_id: str,
        resume_version_id: str,
        jd_snapshot_id: str,
        resume_document: DocumentContent,
        jd_document: DocumentContent,
    ) -> SemanticPreparationResult:
        """Run validated P01-P05 work and stop before B4/B2 decisioning."""
        p01 = self._p01.parse(
            analysis_id=analysis_id,
            resume_version_id=resume_version_id,
            document=resume_document,
        )
        p02 = self._p02.parse(
            analysis_id=analysis_id,
            jd_snapshot_id=jd_snapshot_id,
            document=jd_document,
        )
        p03 = self._p03.classify(p02)
        p04 = self._p04.normalize(p01)
        p05 = self._p05.match(p03, p04)
        executions = (
            p01.execution,
            p02.execution,
            p03.execution,
            p04.execution,
            p05.execution,
        )
        validation = self._validator.validate(
            analysis_id=analysis_id,
            resume_profile=p01.profile,
            evidence=p04.evidence,
            job_profile=p03.job_profile,
            requirements=p03.requirements,
            matches=p05.matches,
            execution_records=executions,
        )
        if not validation.valid:
            raise SemanticPromptError("PIPELINE", "FOUR_LAYER_VALIDATION_FAILED")
        return SemanticPreparationResult(
            p01=p01,
            p02=p02,
            p03=p03,
            p04=p04,
            p05=p05,
            validation=validation,
            executions=executions,
        )
