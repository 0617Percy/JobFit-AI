"""Side-by-side v2 application service for the release-candidate UI."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, replace

from jobfit.advisory.v2 import AdvisoryReportPipeline, AdvisoryReportResult
from jobfit.clarification.v2 import (
    ClarificationFlowStart,
    resolve_clarification,
    start_clarification_flow,
)
from jobfit.models import DocumentContent
from jobfit.models.v2 import (
    AnalysisInputSnapshot,
    AnalysisRun,
    AnalysisStage,
    ClarificationAnswer,
    ClarificationAnswerStatus,
    ClarificationQuestion,
    Evidence,
    JobFitDomainBundle,
    JobProfile,
    LifecycleStatus,
    Requirement,
    RequirementMatch,
    ResumeProfile,
    UserClarification,
    VersionManifest,
)
from jobfit.scoring.v2 import (
    AnalysisCoreResult,
    DeterministicDecisionEngine,
    SeniorityFacts,
)
from jobfit.semantic.v2 import SemanticPipeline, SemanticPreparationResult
from jobfit.workflow.v2.history import (
    AnalysisRepository,
    InMemoryAnalysisRepository,
    PersistedAnalysis,
)
from jobfit.workflow.v2.lifecycle import (
    complete_stage,
    create_analysis_run,
    fork_analysis_run,
    start_stage,
    transition_run,
)


class V2ApplicationError(ValueError):
    """The requested UI workflow action is not valid for the current run."""


@dataclass(frozen=True, slots=True)
class V2AnalysisSession:
    """Immutable application state backed by B1-B6 domain objects."""

    run: AnalysisRun
    preparation: SemanticPreparationResult
    seniority_facts: SeniorityFacts
    clarification: ClarificationFlowStart
    resume_profile: ResumeProfile
    job_profile: JobProfile
    requirements: tuple[Requirement, ...]
    matches: tuple[RequirementMatch, ...]
    evidence: tuple[Evidence, ...]
    pending_questions: tuple[ClarificationQuestion, ...]
    user_clarifications: tuple[UserClarification, ...] = ()
    analysis_result: AnalysisCoreResult | None = None
    advisory_result: AdvisoryReportResult | None = None
    resume_document: DocumentContent | None = None
    jd_document: DocumentContent | None = None

    def persistence_record(self) -> PersistedAnalysis:
        if self.resume_document is None or self.jd_document is None:
            raise V2ApplicationError("Analysis source documents are unavailable.")
        return PersistedAnalysis.from_documents(
            run=self.run,
            resume_version_id=self.resume_profile.resume_version_id,
            jd_snapshot_id=self.job_profile.jd_snapshot_id,
            resume_document=self.resume_document,
            jd_document=self.jd_document,
            user_clarifications=self.user_clarifications,
        )


class V2AnalysisApplication:
    """Orchestrate P01-P08 without moving decision logic into the UI."""

    def __init__(
        self,
        *,
        semantic_pipeline: SemanticPipeline,
        advisory_pipeline: AdvisoryReportPipeline | None,
        versions: VersionManifest,
        history: AnalysisRepository | None = None,
        decision_engine: DeterministicDecisionEngine | None = None,
    ) -> None:
        self._semantic = semantic_pipeline
        self._advisory = advisory_pipeline
        self._versions = versions
        self._history = history or InMemoryAnalysisRepository()
        self._decision_engine = decision_engine or DeterministicDecisionEngine()

    def prepare_analysis(
        self,
        *,
        analysis_id: str,
        resume_version_id: str,
        jd_snapshot_id: str,
        resume_document: DocumentContent,
        jd_document: DocumentContent,
        seniority_facts: SeniorityFacts,
        parent_analysis_id: str | None = None,
        reanalysis_reason: str = "Inputs updated.",
    ) -> V2AnalysisSession:
        run = self._new_run(
            analysis_id=analysis_id,
            parent_analysis_id=parent_analysis_id,
            reanalysis_reason=reanalysis_reason,
        )
        run = transition_run(run, LifecycleStatus.PARSING)
        preparation = self._semantic.prepare(
            analysis_id=analysis_id,
            resume_version_id=resume_version_id,
            jd_snapshot_id=jd_snapshot_id,
            resume_document=resume_document,
            jd_document=jd_document,
        )
        run = _mark_stages_completed(
            run,
            (AnalysisStage.RESUME_PARSE, AnalysisStage.JD_PARSE, AnalysisStage.MATCHING),
        )
        clarification = start_clarification_flow(
            analysis_id=analysis_id,
            resume_profile=preparation.p01.profile,
            job_profile=preparation.p03.job_profile,
            requirements=preparation.p03.requirements,
            matches=preparation.p05.matches,
            evidence=preparation.p04.evidence,
            seniority_facts=seniority_facts,
            role_scope_valid=preparation.p02.role_scope_valid,
        )
        pending = tuple(item for item in clarification.questions if item.required)
        if pending:
            run = transition_run(run, LifecycleStatus.REVIEW_REQUIRED)
        else:
            run = self._freeze_ready_run(
                run,
                resume_version_id=resume_version_id,
                jd_snapshot_id=jd_snapshot_id,
                clarifications=(),
            )
            run = _mark_stages_completed(
                run,
                (AnalysisStage.SCORING, AnalysisStage.RECOMMENDATION),
            )
        session = V2AnalysisSession(
            run=run,
            preparation=preparation,
            seniority_facts=seniority_facts,
            clarification=clarification,
            resume_profile=preparation.p01.profile,
            job_profile=preparation.p03.job_profile,
            requirements=tuple(preparation.p03.requirements),
            matches=tuple(preparation.p05.matches),
            evidence=tuple(preparation.p04.evidence),
            pending_questions=pending,
            analysis_result=clarification.analysis_result,
            resume_document=resume_document,
            jd_document=jd_document,
        )
        self._history.save_working_analysis(session.persistence_record())
        return session

    def answer_clarification(
        self,
        session: V2AnalysisSession,
        *,
        question_id: str,
        answer: ClarificationAnswer,
    ) -> V2AnalysisSession:
        if session.run.lifecycle.status is not LifecycleStatus.REVIEW_REQUIRED:
            raise V2ApplicationError("Clarifications require a review_required run.")
        question = next(
            (item for item in session.pending_questions if item.question_id == question_id),
            None,
        )
        if question is None:
            raise V2ApplicationError("Clarification question is not active.")
        outcome = resolve_clarification(
            analysis_id=session.run.analysis_id,
            resume_profile=session.resume_profile,
            job_profile=session.job_profile,
            requirements=session.requirements,
            matches=session.matches,
            evidence=session.evidence,
            seniority_facts=session.seniority_facts,
            question=question,
            answer=answer,
            prior_clarifications=session.user_clarifications,
        )
        if outcome.conflicts or answer.status is ClarificationAnswerStatus.UNABLE_TO_CONFIRM:
            updated = replace(
                session,
                resume_profile=outcome.updated_resume_profile,
                job_profile=outcome.updated_job_profile,
                requirements=outcome.updated_requirements,
                matches=outcome.updated_matches,
                evidence=outcome.updated_evidence,
                user_clarifications=(*session.user_clarifications, outcome.clarification),
            )
            self._history.save_working_analysis(updated.persistence_record())
            return updated
        remaining = tuple(
            item for item in session.pending_questions if item.question_id != question_id
        )
        clarifications = (*session.user_clarifications, outcome.clarification)
        analysis_result = outcome.analysis_result
        run = session.run
        if not remaining:
            if analysis_result is None or any(
                item.answer_status is ClarificationAnswerStatus.SKIPPED
                for item in clarifications
            ):
                analysis_result = self._decision_engine.build_analysis_core(
                    analysis_id=run.analysis_id,
                    resume_profile=outcome.updated_resume_profile,
                    job_profile=outcome.updated_job_profile,
                    requirements=outcome.updated_requirements,
                    matches=outcome.updated_matches,
                    evidence=outcome.updated_evidence,
                    seniority_facts=session.seniority_facts,
                    explicitly_skipped_required_clarification=any(
                        item.answer_status is ClarificationAnswerStatus.SKIPPED
                        for item in clarifications
                    ),
                    role_scope_valid=session.preparation.p02.role_scope_valid,
                )
            run = self._freeze_ready_run(
                run,
                resume_version_id=session.preparation.p01.profile.resume_version_id,
                jd_snapshot_id=session.preparation.p03.job_profile.jd_snapshot_id,
                clarifications=clarifications,
            )
            run = _mark_stages_completed(
                run,
                (AnalysisStage.SCORING, AnalysisStage.RECOMMENDATION),
            )
        updated = replace(
            session,
            run=run,
            resume_profile=outcome.updated_resume_profile,
            job_profile=outcome.updated_job_profile,
            requirements=outcome.updated_requirements,
            matches=outcome.updated_matches,
            evidence=outcome.updated_evidence,
            pending_questions=remaining,
            user_clarifications=clarifications,
            analysis_result=analysis_result if not remaining else None,
        )
        self._history.save_working_analysis(updated.persistence_record())
        return updated

    def begin_analysis(self, session: V2AnalysisSession) -> V2AnalysisSession:
        if session.run.lifecycle.status is not LifecycleStatus.ANALYSIS_READY:
            raise V2ApplicationError("Analysis can begin only after the readiness gate.")
        if session.analysis_result is None:
            raise V2ApplicationError("The frozen B2 result is missing.")
        updated = replace(
            session,
            run=transition_run(session.run, LifecycleStatus.ANALYZING),
        )
        self._history.save_working_analysis(updated.persistence_record())
        return updated

    def finish_analysis(self, session: V2AnalysisSession) -> V2AnalysisSession:
        if session.run.lifecycle.status is not LifecycleStatus.ANALYZING:
            raise V2ApplicationError("Analysis has not entered the analyzing stage.")
        if self._advisory is None:
            raise V2ApplicationError("Advisory pipeline is not configured.")
        assert session.analysis_result is not None
        bundle = JobFitDomainBundle(
            resume_profile=session.resume_profile,
            evidence=list(session.evidence),
            job_profile=session.job_profile,
            requirements=list(session.requirements),
            requirement_matches=list(session.analysis_result.computed_matches),
            analysis_core=session.analysis_result.analysis_core,
            user_clarifications=list(session.user_clarifications),
            versions=self._versions,
        )
        advisory = self._advisory.run(bundle)
        run = _mark_stages_completed(
            session.run,
            (AnalysisStage.ACTIONS, AnalysisStage.INTERVIEW),
        )
        run = transition_run(run, LifecycleStatus.REPORT_GENERATING)
        run = _mark_stages_completed(run, (AnalysisStage.REPORT,))
        run = transition_run(run, LifecycleStatus.COMPLETED)
        run = run.model_copy(
            update={
                "analysis_core": advisory.analysis_core,
                "report": advisory.report,
            }
        )
        self._history.append_analysis(run)
        return replace(session, run=run, advisory_result=advisory)

    def list_history(self) -> tuple[AnalysisRun, ...]:
        return self._history.list_analysis_versions()

    def _new_run(
        self,
        *,
        analysis_id: str,
        parent_analysis_id: str | None,
        reanalysis_reason: str,
    ) -> AnalysisRun:
        if parent_analysis_id is None:
            return transition_run(
                create_analysis_run(analysis_id),
                LifecycleStatus.INPUT_READY,
            )
        parent = self._history.get_analysis(parent_analysis_id)
        if parent is None:
            raise V2ApplicationError("Parent analysis does not exist in this session.")
        return fork_analysis_run(
            parent,
            target_analysis_id=analysis_id,
            reason=reanalysis_reason,
        )

    def _freeze_ready_run(
        self,
        run: AnalysisRun,
        *,
        resume_version_id: str,
        jd_snapshot_id: str,
        clarifications: Sequence[UserClarification],
    ) -> AnalysisRun:
        snapshot = AnalysisInputSnapshot.freeze(
            analysis_id=run.analysis_id,
            resume_version_id=resume_version_id,
            jd_snapshot_id=jd_snapshot_id,
            user_clarifications=clarifications,
            versions=self._versions,
        )
        return transition_run(run, LifecycleStatus.ANALYSIS_READY, snapshot=snapshot)


def _mark_stages_completed(
    run: AnalysisRun,
    stages: Sequence[AnalysisStage],
) -> AnalysisRun:
    lifecycle = run.lifecycle
    for stage in stages:
        lifecycle = start_stage(lifecycle, stage)
        lifecycle = complete_stage(lifecycle, stage)
    return run.model_copy(update={"lifecycle": lifecycle})


def stable_run_identity(*parts: str) -> str:
    """Build a deterministic, non-sensitive identity for one analysis revision."""
    payload = "\x1f".join(parts).encode("utf-8")
    return f"analysis-{hashlib.sha256(payload).hexdigest()[:20]}"
