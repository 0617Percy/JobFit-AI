"""Workflow state, progress, request fingerprint, and session-only cache."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

from jobfit.generators import GeneratedAdvice
from jobfit.models import (
    AnalysisReport,
    AnalysisRequest,
    DocumentContent,
    EvidenceRegistry,
    JobProfile,
    KnowledgeAdviceTrace,
    KnowledgeContext,
    MatchScoreSummary,
    ProgressEvent,
    RequirementMatch,
    ResumeProfile,
    WorkflowStage,
)
from jobfit.parsers.normalizer import normalize_text

logger = logging.getLogger(__name__)

_STAGE_SEQUENCE = (
    WorkflowStage.VALIDATING_INPUT,
    WorkflowStage.PARSING_RESUME,
    WorkflowStage.EXTRACTING_RESUME,
    WorkflowStage.EXTRACTING_JOB,
    WorkflowStage.RETRIEVING_KNOWLEDGE,
    WorkflowStage.MATCHING_EVIDENCE,
    WorkflowStage.VALIDATING_MATCHES,
    WorkflowStage.SCORING,
    WorkflowStage.GENERATING_ADVICE,
    WorkflowStage.VALIDATING_REPORT,
    WorkflowStage.COMPLETED,
)
_STAGE_PROGRESS = {
    WorkflowStage.VALIDATING_INPUT: 5,
    WorkflowStage.PARSING_RESUME: 12,
    WorkflowStage.EXTRACTING_RESUME: 25,
    WorkflowStage.EXTRACTING_JOB: 38,
    WorkflowStage.RETRIEVING_KNOWLEDGE: 45,
    WorkflowStage.MATCHING_EVIDENCE: 55,
    WorkflowStage.VALIDATING_MATCHES: 64,
    WorkflowStage.SCORING: 74,
    WorkflowStage.GENERATING_ADVICE: 85,
    WorkflowStage.VALIDATING_REPORT: 94,
    WorkflowStage.COMPLETED: 100,
}
_STAGE_MESSAGE_KEYS = {
    stage: f"workflow.{stage.value.casefold()}" for stage in _STAGE_SEQUENCE
}


class ProgressSink(Protocol):
    def publish(self, event: ProgressEvent) -> None: ...


@dataclass(frozen=True, slots=True)
class WorkflowFingerprintContext:
    provider: str
    model: str
    prompt_versions: Mapping[str, str]
    schema_version: str = "1.1"
    knowledge_requirement_limit: int = 12
    knowledge_prompt_char_limit: int = 8_000
    knowledge_retrieval_strategy_version: str = "1.0"
    knowledge_advice_prompt_version: str = "1.0"
    knowledge_citation_validator_version: str = "1.0"
    knowledge_advice_strategy_version: str = "1.0"


@dataclass(frozen=True, slots=True)
class WorkflowFailure:
    code: str
    message: str
    recoverable: bool


@dataclass(frozen=True, slots=True)
class WorkflowResult:
    request_id: str
    fingerprint: str
    stage: WorkflowStage
    success: bool
    report: AnalysisReport | None
    markdown: str | None
    json_text: str | None
    events: tuple[ProgressEvent, ...]
    error: WorkflowFailure | None
    recoverable: bool
    cache_hit: bool = False

    @classmethod
    def successful(
        cls,
        *,
        request_id: str,
        fingerprint: str,
        report: AnalysisReport | None,
        markdown: str,
        json_text: str,
        events: tuple[ProgressEvent, ...],
    ) -> WorkflowResult:
        return cls(
            request_id=request_id,
            fingerprint=fingerprint,
            stage=WorkflowStage.COMPLETED,
            success=True,
            report=report,
            markdown=markdown,
            json_text=json_text,
            events=events,
            error=None,
            recoverable=False,
        )

    @classmethod
    def failed(
        cls,
        *,
        request_id: str,
        fingerprint: str,
        events: tuple[ProgressEvent, ...],
        code: str,
        message: str,
        recoverable: bool,
    ) -> WorkflowResult:
        return cls(
            request_id=request_id,
            fingerprint=fingerprint,
            stage=WorkflowStage.FAILED,
            success=False,
            report=None,
            markdown=None,
            json_text=None,
            events=events,
            error=WorkflowFailure(
                code=code,
                message=message,
                recoverable=recoverable,
            ),
            recoverable=recoverable,
        )


@dataclass(slots=True)
class WorkflowState:
    request: AnalysisRequest
    progress_sink: ProgressSink | None = None
    stage: WorkflowStage = WorkflowStage.IDLE
    events: list[ProgressEvent] = field(default_factory=list)
    document: DocumentContent | None = None
    resume: ResumeProfile | None = None
    evidence_registry: EvidenceRegistry | None = None
    job: JobProfile | None = None
    knowledge_context: KnowledgeContext | None = None
    knowledge_cache_identity: str | None = None
    knowledge_fallback: bool = False
    knowledge_advice_trace: KnowledgeAdviceTrace | None = None
    matches: list[RequirementMatch] | None = None
    score: MatchScoreSummary | None = None
    advice: GeneratedAdvice | None = None
    report: AnalysisReport | None = None
    markdown: str | None = None
    json_text: str | None = None
    error: WorkflowFailure | None = None

    def advance(self, next_stage: WorkflowStage) -> ProgressEvent:
        if self.stage in {WorkflowStage.COMPLETED, WorkflowStage.FAILED}:
            raise ValueError("Cannot transition from a terminal workflow stage")
        current_index = (
            -1
            if self.stage is WorkflowStage.IDLE
            else _STAGE_SEQUENCE.index(self.stage)
        )
        expected_index = current_index + 1
        if (
            expected_index >= len(_STAGE_SEQUENCE)
            or _STAGE_SEQUENCE[expected_index] is not next_stage
        ):
            raise ValueError(
                f"Illegal workflow transition: {self.stage.value} -> {next_stage.value}"
            )
        self.stage = next_stage
        event = ProgressEvent(
            request_id=self.request.request_id,
            stage=next_stage,
            progress_percent=_STAGE_PROGRESS[next_stage],
            message_key=_STAGE_MESSAGE_KEYS[next_stage],
            recoverable=False,
        )
        self._publish(event)
        return event

    def fail(
        self,
        *,
        code: str,
        message: str,
        recoverable: bool,
    ) -> ProgressEvent:
        if self.stage in {WorkflowStage.COMPLETED, WorkflowStage.FAILED}:
            raise ValueError("Cannot fail a terminal workflow stage")
        progress_percent = self.events[-1].progress_percent if self.events else 0
        self.stage = WorkflowStage.FAILED
        self.error = WorkflowFailure(
            code=code,
            message=message,
            recoverable=recoverable,
        )
        event = ProgressEvent(
            request_id=self.request.request_id,
            stage=WorkflowStage.FAILED,
            progress_percent=progress_percent,
            message_key=f"workflow.failed.{code.casefold()}",
            recoverable=recoverable,
        )
        self._publish(event)
        return event

    def _publish(self, event: ProgressEvent) -> None:
        self.events.append(event)
        if self.progress_sink is None:
            return
        try:
            self.progress_sink.publish(event)
        except Exception as exc:  # UI callback errors must not alter business flow.
            logger.warning(
                "progress_sink_failed request_id=%s error_type=%s",
                self.request.request_id,
                type(exc).__name__,
            )


class WorkflowCache:
    """Current-session success cache with explicit in-flight deduplication."""

    def __init__(self) -> None:
        self._successful: dict[str, WorkflowResult] = {}
        self._running: set[str] = set()
        self._extraction_artifacts: dict[str, _WorkflowExtractionArtifacts] = {}
        self._knowledge_contexts: dict[str, KnowledgeContext] = {}
        self._knowledge_advice_traces: dict[str, KnowledgeAdviceTrace] = {}

    def get_success(self, fingerprint: str) -> WorkflowResult | None:
        return self._successful.get(fingerprint)

    def begin(self, fingerprint: str) -> bool:
        if fingerprint in self._running:
            return False
        self._running.add(fingerprint)
        return True

    def get_extraction_artifacts(
        self,
        fingerprint: str,
    ) -> _WorkflowExtractionArtifacts | None:
        return self._extraction_artifacts.get(fingerprint)

    def store_extraction_artifacts(
        self,
        fingerprint: str,
        *,
        document: DocumentContent,
        resume: ResumeProfile,
        evidence_registry: EvidenceRegistry,
        job: JobProfile,
    ) -> None:
        self._extraction_artifacts[fingerprint] = _WorkflowExtractionArtifacts(
            document=document,
            resume=resume,
            evidence_registry=evidence_registry,
            job=job,
        )

    def get_knowledge_context(self, fingerprint: str) -> KnowledgeContext | None:
        return self._knowledge_contexts.get(fingerprint)

    def store_knowledge_context(
        self,
        fingerprint: str,
        context: KnowledgeContext,
    ) -> None:
        self._knowledge_contexts[fingerprint] = context

    def get_knowledge_advice_trace(
        self,
        fingerprint: str,
    ) -> KnowledgeAdviceTrace | None:
        return self._knowledge_advice_traces.get(fingerprint)

    def store_knowledge_advice_trace(
        self,
        fingerprint: str,
        trace: KnowledgeAdviceTrace,
    ) -> None:
        self._knowledge_advice_traces[fingerprint] = trace

    def release(self, fingerprint: str) -> None:
        self._running.discard(fingerprint)

    def finish(
        self,
        result: WorkflowResult,
        *,
        running_fingerprint: str | None = None,
    ) -> None:
        self._running.discard(running_fingerprint or result.fingerprint)
        if result.success:
            self._successful[result.fingerprint] = result

    def clear(self) -> None:
        self._successful.clear()
        self._running.clear()
        self._extraction_artifacts.clear()
        self._knowledge_contexts.clear()
        self._knowledge_advice_traces.clear()


@dataclass(frozen=True, slots=True)
class _WorkflowExtractionArtifacts:
    document: DocumentContent
    resume: ResumeProfile
    evidence_registry: EvidenceRegistry
    job: JobProfile


def build_request_fingerprint(
    request: AnalysisRequest,
    *,
    selected_source: str,
    context: WorkflowFingerprintContext,
) -> str:
    """Hash source and runtime identity without including raw text or secrets."""

    if selected_source == "text":
        normalized_resume, _ = normalize_text(request.pasted_resume_text or "")
        resume_hash = _sha256(normalized_resume.encode("utf-8"))
    elif selected_source == "file":
        content = request.resume_file.content if request.resume_file else b""
        resume_hash = _sha256(content)
    else:
        resume_hash = _sha256(b"invalid-source")
    normalized_jd, _ = normalize_text(request.job_description_text)
    payload = {
        "resume_hash": resume_hash,
        "jd_hash": _sha256(normalized_jd.encode("utf-8")),
        "selected_source": selected_source,
        "job_title": (request.job_title or "").strip(),
        "company_name": (request.company_name or "").strip(),
        "llm_mode": request.llm_mode,
        "provider": context.provider,
        "model": context.model,
        "prompt_versions": sorted(context.prompt_versions.items()),
        "schema_version": context.schema_version,
    }
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _sha256(serialized)


def build_analysis_fingerprint(
    base_fingerprint: str,
    knowledge_cache_identity: str,
) -> str:
    """Bind the final report cache to reviewed knowledge identity."""

    payload = {
        "base_fingerprint": base_fingerprint,
        "knowledge_cache_identity": knowledge_cache_identity,
    }
    serialized = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _sha256(serialized)


def build_knowledge_advice_cache_identity(
    knowledge_cache_identity: str,
    *,
    prompt_version: str,
    validator_version: str,
    strategy_version: str,
) -> str:
    """Bind advice cache reuse to all local knowledge-generation rules."""

    payload = {
        "knowledge_cache_identity": knowledge_cache_identity,
        "prompt_version": prompt_version,
        "validator_version": validator_version,
        "strategy_version": strategy_version,
    }
    serialized = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _sha256(serialized)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()
