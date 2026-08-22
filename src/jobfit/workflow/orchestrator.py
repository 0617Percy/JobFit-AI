"""Fail-closed orchestration of the complete JobFit analysis pipeline."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from jobfit.errors import (
    ErrorCode,
    JobFitError,
    KnowledgeDatabaseError,
)
from jobfit.knowledge.protocol import KnowledgeRetriever
from jobfit.knowledge.retriever import (
    NoOpKnowledgeRetriever,
    build_knowledge_cache_identity,
)
from jobfit.models import (
    AnalysisReport,
    AnalysisRequest,
    KnowledgeAdviceTrace,
    KnowledgeContext,
    KnowledgeRetrievalStatus,
    KnowledgeWarning,
    KnowledgeWarningCode,
    WorkflowStage,
)
from jobfit.reporting import render_json, render_markdown
from jobfit.validators.knowledge import KnowledgeCitationValidator
from jobfit.validators.report import build_analysis_report
from jobfit.workflow.state import (
    ProgressSink,
    WorkflowCache,
    WorkflowFingerprintContext,
    WorkflowResult,
    WorkflowState,
    build_analysis_fingerprint,
    build_knowledge_advice_cache_identity,
    build_request_fingerprint,
)

logger = logging.getLogger(__name__)

ReportBuilder = Callable[..., AnalysisReport]
Renderer = Callable[[AnalysisReport], str]
_KNOWLEDGE_ADVICE_FALLBACK_CODES = {
    ErrorCode.ADVICE_VALIDATION_FAILED,
    ErrorCode.KNOWLEDGE_CITATION_INVALID,
    ErrorCode.LLM_SCHEMA_INVALID,
}


class WorkflowOrchestrator:
    """Call each public module once and stop on the first invalid stage."""

    def __init__(
        self,
        *,
        parser_service: Any,
        jd_parser: Any,
        resume_extractor: Any,
        job_extractor: Any,
        matcher: Any,
        evidence_validator: Any,
        scoring_engine: Any,
        advice_generator: Any,
        fingerprint_context: WorkflowFingerprintContext,
        knowledge_retriever: KnowledgeRetriever | None = None,
        knowledge_advice_generator: Any | None = None,
        knowledge_citation_validator: KnowledgeCitationValidator | None = None,
        report_builder: ReportBuilder = build_analysis_report,
        markdown_renderer: Renderer = render_markdown,
        json_renderer: Renderer = render_json,
        cache: WorkflowCache | None = None,
    ) -> None:
        self._parser_service = parser_service
        self._jd_parser = jd_parser
        self._resume_extractor = resume_extractor
        self._job_extractor = job_extractor
        self._matcher = matcher
        self._evidence_validator = evidence_validator
        self._scoring_engine = scoring_engine
        self._advice_generator = advice_generator
        self._knowledge_advice_generator = knowledge_advice_generator
        self._knowledge_citation_validator = (
            knowledge_citation_validator or KnowledgeCitationValidator()
        )
        self._knowledge_retriever = (
            knowledge_retriever
            if knowledge_retriever is not None
            else NoOpKnowledgeRetriever(
                retrieval_strategy_version=(
                    fingerprint_context.knowledge_retrieval_strategy_version
                )
            )
        )
        self._report_builder = report_builder
        self._markdown_renderer = markdown_renderer
        self._json_renderer = json_renderer
        self._fingerprint_context = fingerprint_context
        self._cache = cache or WorkflowCache()

    def fingerprint(
        self,
        request: AnalysisRequest,
        *,
        selected_source: str,
    ) -> str:
        return build_request_fingerprint(
            request,
            selected_source=selected_source,
            context=self._fingerprint_context,
        )

    def run(
        self,
        request: AnalysisRequest,
        *,
        selected_source: str,
        progress: ProgressSink | None = None,
    ) -> WorkflowResult:
        base_fingerprint = self.fingerprint(
            request,
            selected_source=selected_source,
        )
        fingerprint = base_fingerprint
        if not self._cache.begin(base_fingerprint):
            return WorkflowResult.failed(
                request_id=request.request_id,
                fingerprint=base_fingerprint,
                events=(),
                code="ANALYSIS_ALREADY_RUNNING",
                message="相同输入正在分析，请等待当前任务完成。",
                recoverable=True,
            )

        state = WorkflowState(request, progress_sink=progress)
        try:
            state.advance(WorkflowStage.VALIDATING_INPUT)
            self._validate_source(request, selected_source)

            artifacts = self._cache.get_extraction_artifacts(base_fingerprint)
            if artifacts is None:
                state.advance(WorkflowStage.PARSING_RESUME)
                state.document = self._parser_service.parse_request(
                    request,
                    selected_source=selected_source,
                )

                state.advance(WorkflowStage.EXTRACTING_RESUME)
                state.resume, state.evidence_registry = self._resume_extractor.extract(
                    state.document
                )

                state.advance(WorkflowStage.EXTRACTING_JOB)
                job_document = self._jd_parser.parse_text(
                    request.job_description_text
                )
                state.job = self._job_extractor.extract(
                    job_document,
                    title=request.job_title,
                    company=request.company_name,
                )
                self._cache.store_extraction_artifacts(
                    base_fingerprint,
                    document=state.document,
                    resume=state.resume,
                    evidence_registry=state.evidence_registry,
                    job=state.job,
                )
            else:
                state.advance(WorkflowStage.PARSING_RESUME)
                state.document = artifacts.document
                state.advance(WorkflowStage.EXTRACTING_RESUME)
                state.resume = artifacts.resume
                state.evidence_registry = artifacts.evidence_registry
                state.advance(WorkflowStage.EXTRACTING_JOB)
                state.job = artifacts.job

            state.advance(WorkflowStage.RETRIEVING_KNOWLEDGE)
            try:
                state.knowledge_context = (
                    self._knowledge_retriever.retrieve_for_job(
                        state.job,
                        limit=self._fingerprint_context.knowledge_requirement_limit,
                    )
                )
            except KnowledgeDatabaseError as exc:
                state.knowledge_context = self._knowledge_unavailable(exc)
                state.knowledge_fallback = True
            if state.knowledge_context.status in {
                KnowledgeRetrievalStatus.UNAVAILABLE,
                KnowledgeRetrievalStatus.NO_MATCH,
                KnowledgeRetrievalStatus.AMBIGUOUS,
            }:
                state.knowledge_fallback = True
            retrieval_identity = build_knowledge_cache_identity(
                state.knowledge_context,
                requirement_limit=(
                    self._fingerprint_context.knowledge_requirement_limit
                ),
                prompt_char_limit=(
                    self._fingerprint_context.knowledge_prompt_char_limit
                ),
            )
            state.knowledge_cache_identity = build_knowledge_advice_cache_identity(
                retrieval_identity,
                prompt_version=(
                    self._fingerprint_context.knowledge_advice_prompt_version
                ),
                validator_version=(
                    self._fingerprint_context.knowledge_citation_validator_version
                ),
                strategy_version=(
                    self._fingerprint_context.knowledge_advice_strategy_version
                ),
            )
            fingerprint = build_analysis_fingerprint(
                base_fingerprint,
                state.knowledge_cache_identity,
            )
            self._cache.store_knowledge_context(
                base_fingerprint,
                state.knowledge_context,
            )
            cached = self._cache.get_success(fingerprint)
            if cached is not None:
                self._cache.release(base_fingerprint)
                return replace(cached, cache_hit=True)

            state.advance(WorkflowStage.MATCHING_EVIDENCE)
            state.matches = self._matcher.match(
                state.resume,
                state.job,
                state.document,
                state.evidence_registry,
                request_id=request.request_id,
            )

            state.advance(WorkflowStage.VALIDATING_MATCHES)
            self._evidence_validator.validate_or_raise(
                state.document,
                state.evidence_registry,
                state.job.requirements.items,
                state.matches,
            )

            state.advance(WorkflowStage.SCORING)
            state.score = self._scoring_engine.score(
                state.job.requirements.items,
                state.matches,
            )

            state.advance(WorkflowStage.GENERATING_ADVICE)
            self._generate_advice(state)
            if state.knowledge_advice_trace is not None:
                self._cache.store_knowledge_advice_trace(
                    base_fingerprint,
                    state.knowledge_advice_trace,
                )

            state.advance(WorkflowStage.VALIDATING_REPORT)
            state.report = self._report_builder(
                document=state.document,
                resume=state.resume,
                job=state.job,
                matches=state.matches,
                score=state.score,
                advice=state.advice,
                registry=state.evidence_registry,
                knowledge_context=state.knowledge_context,
                knowledge_advice_trace=state.knowledge_advice_trace,
            )
            state.markdown = self._markdown_renderer(state.report)
            state.json_text = self._json_renderer(state.report)

            state.advance(WorkflowStage.COMPLETED)
            result = WorkflowResult.successful(
                request_id=request.request_id,
                fingerprint=fingerprint,
                report=state.report,
                markdown=state.markdown,
                json_text=state.json_text,
                events=tuple(state.events),
            )
        except JobFitError as exc:
            state.fail(
                code=exc.code.value,
                message=exc.user_message,
                recoverable=exc.recoverable,
            )
            result = WorkflowResult.failed(
                request_id=request.request_id,
                fingerprint=fingerprint,
                events=tuple(state.events),
                code=exc.code.value,
                message=exc.user_message,
                recoverable=exc.recoverable,
            )
        except Exception as exc:
            logger.error(
                "workflow_failed request_id=%s stage=%s error_type=%s",
                request.request_id,
                state.stage.value,
                type(exc).__name__,
            )
            code = ErrorCode.REPORT_GENERATION_FAILED.value
            message = "分析未完成，系统已停止生成不可信报告。"
            state.fail(
                code=code,
                message=message,
                recoverable=False,
            )
            result = WorkflowResult.failed(
                request_id=request.request_id,
                fingerprint=fingerprint,
                events=tuple(state.events),
                code=code,
                message=message,
                recoverable=False,
            )
        self._cache.finish(result, running_fingerprint=base_fingerprint)
        return result

    def _generate_advice(self, state: WorkflowState) -> None:
        context = state.knowledge_context
        if (
            context is None
            or context.status is not KnowledgeRetrievalStatus.AVAILABLE
            or self._knowledge_advice_generator is None
        ):
            state.advice = self._generate_base_advice(state)
            return

        try:
            generated = self._knowledge_advice_generator.generate_with_knowledge(
                state.resume,
                state.job,
                state.matches,
                state.score,
                state.evidence_registry,
                knowledge_context=context,
                request_id=state.request.request_id,
            )
            validated_uses = self._knowledge_citation_validator.validate_or_raise(
                context=context,
                citation_uses=generated.citation_uses,
                provided_citation_ids=generated.provided_citation_ids,
                advice=generated.advice,
            )
        except JobFitError as exc:
            if exc.code not in _KNOWLEDGE_ADVICE_FALLBACK_CODES:
                raise
            state.advice = self._generate_base_advice(state)
            state.knowledge_fallback = True
            state.knowledge_advice_trace = self._knowledge_advice_trace(
                context,
                citation_uses=(),
                validated=False,
                fallback_used=True,
                warnings=(
                    KnowledgeWarning(
                        code=KnowledgeWarningCode.CITATION_INVALID,
                        message=(
                            "Knowledge-grounded advice could not be validated; "
                            "the base advice path was used."
                        ),
                        recoverable=True,
                    ),
                ),
            )
            return

        state.advice = generated.advice
        state.knowledge_advice_trace = self._knowledge_advice_trace(
            context,
            citation_uses=validated_uses,
            validated=True,
            fallback_used=False,
            warnings=(),
        )

    def _generate_base_advice(self, state: WorkflowState) -> Any:
        return self._advice_generator.generate(
            state.resume,
            state.job,
            state.matches,
            state.score,
            state.evidence_registry,
            request_id=state.request.request_id,
        )

    def _knowledge_advice_trace(
        self,
        context: KnowledgeContext,
        *,
        citation_uses: tuple[Any, ...],
        validated: bool,
        fallback_used: bool,
        warnings: tuple[KnowledgeWarning, ...],
    ) -> KnowledgeAdviceTrace:
        if context.version is None or len(context.inferred_role_profiles) != 1:
            raise ValueError("available knowledge identity is incomplete")
        return KnowledgeAdviceTrace(
            knowledge_version=context.version.version,
            content_hash=context.version.content_hash,
            selected_role_profile_id=(
                context.inferred_role_profiles[0].role_profile_id
            ),
            citation_uses=list(citation_uses),
            validated=validated,
            fallback_used=fallback_used,
            warnings=list(warnings),
            prompt_version=(
                self._fingerprint_context.knowledge_advice_prompt_version
            ),
            validator_version=(
                self._fingerprint_context.knowledge_citation_validator_version
            ),
            generation_strategy_version=(
                self._fingerprint_context.knowledge_advice_strategy_version
            ),
        )

    def _knowledge_unavailable(
        self,
        error: KnowledgeDatabaseError,
    ) -> KnowledgeContext:
        code = (
            KnowledgeWarningCode.DB_UNAVAILABLE
            if error.code
            in {
                ErrorCode.KNOWLEDGE_DB_UNAVAILABLE,
                ErrorCode.KNOWLEDGE_SEARCH_UNAVAILABLE,
            }
            else KnowledgeWarningCode.RETRIEVAL_FAILED
        )
        message = (
            "The reviewed knowledge database is temporarily unavailable."
            if code is KnowledgeWarningCode.DB_UNAVAILABLE
            else "Reviewed knowledge retrieval could not be completed."
        )
        return KnowledgeContext(
            status=KnowledgeRetrievalStatus.UNAVAILABLE,
            warnings=[
                KnowledgeWarning(
                    code=code,
                    message=message,
                    recoverable=True,
                )
            ],
            retrieval_strategy_version=(
                self._fingerprint_context.knowledge_retrieval_strategy_version
            ),
        )

    @staticmethod
    def _validate_source(
        request: AnalysisRequest,
        selected_source: str,
    ) -> None:
        if not request.job_description_text.strip():
            raise JobFitError(
                code=ErrorCode.INPUT_EMPTY,
                user_message="请提供有效的岗位JD后再开始分析。",
                recoverable=True,
            )
        if selected_source == "text":
            if not request.pasted_resume_text or not request.pasted_resume_text.strip():
                raise JobFitError(
                    code=ErrorCode.INPUT_EMPTY,
                    user_message="请选择粘贴文本并提供有效简历内容。",
                    recoverable=True,
                )
            return
        if selected_source == "file":
            if request.resume_file is None:
                raise JobFitError(
                    code=ErrorCode.INPUT_EMPTY,
                    user_message="请选择上传文件并提供有效简历。",
                    recoverable=True,
                )
            return
        raise JobFitError(
            code=ErrorCode.INPUT_EMPTY,
            user_message="简历证据源选择无效，请重新选择。",
            recoverable=True,
        )
