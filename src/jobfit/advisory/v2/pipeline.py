"""P06-P08 side-by-side advisory and report pipeline."""

from __future__ import annotations

from dataclasses import dataclass

from jobfit.advisory.v2.actions import P06ActionGenerator
from jobfit.advisory.v2.interview import P07InterviewGenerator
from jobfit.models.v2 import AnalysisCore, JobFitDomainBundle, JobFitReport
from jobfit.reporting.v2.assembler import P08ReportAssembler
from jobfit.semantic.v2.contracts import PromptExecutionRecord
from jobfit.semantic.v2.executor import SemanticPromptError, SemanticPromptExecutor
from jobfit.validators.v2 import DomainValidator


@dataclass(frozen=True, slots=True)
class AdvisoryReportResult:
    """Validated P06-P08 result with the original immutable decision core."""

    analysis_core: AnalysisCore
    bundle: JobFitDomainBundle
    report: JobFitReport
    executions: tuple[PromptExecutionRecord, ...]


class AdvisoryReportPipeline:
    """Run validated advisory stages without touching production workflow."""

    def __init__(self, executor: SemanticPromptExecutor) -> None:
        self._actions = P06ActionGenerator(executor)
        self._interview = P07InterviewGenerator(executor)
        self._report = P08ReportAssembler(executor)
        self._domain_validator = DomainValidator()

    def run(self, bundle: JobFitDomainBundle) -> AdvisoryReportResult:
        core = bundle.analysis_core
        if core is None:
            raise SemanticPromptError("P06", "MISSING_ANALYSIS_CORE")

        actions = self._actions.generate(bundle)
        if actions.analysis_core is not core:
            raise SemanticPromptError("P06", "ANALYSIS_CORE_IDENTITY_DRIFT")
        with_actions = bundle.model_copy(update={"actions": list(actions.actions)})

        interview = self._interview.generate(with_actions)
        if interview.analysis_core is not core:
            raise SemanticPromptError("P07", "ANALYSIS_CORE_IDENTITY_DRIFT")
        with_questions = with_actions.model_copy(
            update={"interview_questions": list(interview.questions)}
        )

        report = self._report.generate(with_questions)
        if report.analysis_core is not core:
            raise SemanticPromptError("P08", "ANALYSIS_CORE_IDENTITY_DRIFT")
        completed = with_questions.model_copy(update={"report": report.report})
        self._domain_validator.validate_or_raise(completed)

        return AdvisoryReportResult(
            analysis_core=core,
            bundle=completed,
            report=report.report,
            executions=(*actions.executions, interview.execution, report.execution),
        )
