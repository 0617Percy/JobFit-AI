"""Dependency order, fail-closed behavior, and cache tests for the orchestrator."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from jobfit.errors import ErrorCode, JobFitError, KnowledgeDatabaseError
from jobfit.generators import KnowledgeGenerationResult
from jobfit.models import (
    AnalysisRequest,
    KnowledgeAdviceTargetType,
    KnowledgeBaseVersionInfo,
    KnowledgeCitation,
    KnowledgeCitationPurpose,
    KnowledgeCitationUseDraft,
    KnowledgeContext,
    KnowledgeRetrievalStatus,
    KnowledgeSearchBackend,
    KnowledgeSearchCapabilities,
    KnowledgeSearchCapabilityStatus,
    KnowledgeSourceType,
    KnowledgeVersionStatus,
    ReliabilityLevel,
    RetrievedRoleProfile,
    UploadedDocumentInput,
    WorkflowStage,
)
from jobfit.workflow import (
    WorkflowCache,
    WorkflowFingerprintContext,
    WorkflowOrchestrator,
)

_EXPECTED_STAGES = [
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
]


class RecordingSink:
    def __init__(self, *, fail: bool = False) -> None:
        self.events: list[Any] = []
        self._fail = fail

    def publish(self, event: Any) -> None:
        if self._fail:
            raise RuntimeError("UI sink is unavailable")
        self.events.append(event)


class RecordingKnowledgeRetriever:
    def __init__(
        self,
        doubles: Doubles,
        *contexts: KnowledgeContext,
        failure: Exception | None = None,
    ) -> None:
        self._doubles = doubles
        self._contexts = contexts or (KnowledgeContext(),)
        self._failure = failure
        self.calls: list[tuple[Any, int]] = []

    def retrieve_for_job(self, job_profile: Any, *, limit: int = 12) -> KnowledgeContext:
        self._doubles._record("knowledge_retriever")
        self.calls.append((job_profile, limit))
        if self._failure is not None:
            raise self._failure
        index = min(len(self.calls) - 1, len(self._contexts) - 1)
        return self._contexts[index]


class RecordingKnowledgeAdviceGenerator:
    def __init__(
        self,
        doubles: Doubles,
        *,
        citation_id: str = "cite-0000000000000001",
        failure: Exception | None = None,
    ) -> None:
        self._doubles = doubles
        self._citation_id = citation_id
        self._failure = failure
        self.calls: list[tuple[Any, ...]] = []

    def generate_with_knowledge(
        self,
        resume: Any,
        job: Any,
        matches: Any,
        score: Any,
        registry: Any,
        *,
        knowledge_context: KnowledgeContext,
        request_id: str,
    ) -> KnowledgeGenerationResult:
        self._doubles._record("knowledge_advice")
        self.calls.append(
            (
                resume,
                job,
                matches,
                score,
                registry,
                knowledge_context,
                request_id,
            )
        )
        if self._failure is not None:
            raise self._failure
        return KnowledgeGenerationResult(
            advice=self._doubles.case.advice,
            citation_uses=(
                KnowledgeCitationUseDraft(
                    citation_id=self._citation_id,
                    target_type=KnowledgeAdviceTargetType.RECOMMENDATION,
                    target_index=0,
                    purpose=KnowledgeCitationPurpose.ROLE_REQUIREMENT_CONTEXT,
                ),
            ),
            provided_citation_ids=("cite-0000000000000001",),
        )


class Doubles:
    def __init__(self, report_case, analysis_report, *, fail_at: str | None = None) -> None:
        self.case = report_case
        self.report = analysis_report
        self.fail_at = fail_at
        self.calls: list[str] = []
        self.matcher_inputs: list[tuple[Any, ...]] = []
        self.scoring_inputs: list[tuple[Any, ...]] = []
        self.advice_inputs: list[tuple[Any, ...]] = []
        self.report_inputs: list[dict[str, Any]] = []

    def _record(self, name: str) -> None:
        self.calls.append(name)
        if self.fail_at == name:
            raise JobFitError(
                code=ErrorCode.DOCUMENT_PARSE_FAILED,
                user_message=f"{name}阶段安全失败。",
                recoverable=name in {"parser", "resume_extractor", "job_extractor"},
            )

    def parse_request(self, request: AnalysisRequest, *, selected_source: str):
        del request, selected_source
        self._record("parser")
        return self.case.document

    def parse_text(self, text: str):
        del text
        self._record("jd_parser")
        return self.case.document.model_copy(
            update={"document_id": "job-document-test"}
        )

    def extract_resume(self, document):
        del document
        self._record("resume_extractor")
        return self.case.resume, self.case.registry

    def extract_job(self, document, *, title, company):
        del document, title, company
        self._record("job_extractor")
        return self.case.job

    def match(self, resume, job, document, registry, *, request_id):
        self.matcher_inputs.append((resume, job, document, registry, request_id))
        self._record("matcher")
        return self.case.matches

    def validate_or_raise(self, document, registry, requirements, matches):
        del document, registry, requirements, matches
        self._record("validator")

    def score(self, requirements, matches):
        self.scoring_inputs.append((requirements, matches))
        self._record("scorer")
        return self.case.score

    def generate(self, resume, job, matches, score, registry, *, request_id):
        self.advice_inputs.append(
            (resume, job, matches, score, registry, request_id)
        )
        self._record("advice")
        return self.case.advice

    def build_report(self, **kwargs):
        self.report_inputs.append(kwargs)
        self._record("report_builder")
        return self.report

    def markdown(self, report):
        assert report is self.report
        self._record("markdown")
        return "# validated report"

    def json(self, report):
        assert report is self.report
        self._record("json")
        return '{"schema_version":"1.0"}'


def _request(request_id: str = "request-orchestrator") -> AnalysisRequest:
    return AnalysisRequest(
        request_id=request_id,
        pasted_resume_text="匿名简历原文 SECRET-RESUME",
        job_description_text="匿名JD原文 SECRET-JD",
        job_title="AI应用开发实习生",
        company_name="匿名公司",
        llm_mode="mock",
    )


def _context(**updates: Any) -> WorkflowFingerprintContext:
    values: dict[str, Any] = {
        "provider": "mock",
        "model": "mock-model",
        "prompt_versions": {
            "extract_resume": "1.0",
            "extract_job": "1.0",
            "match_evidence": "1.0",
            "generate_advice_bundle": "1.1",
        },
    }
    values.update(updates)
    return WorkflowFingerprintContext(**values)


def _knowledge_context(
    *,
    status: KnowledgeRetrievalStatus = KnowledgeRetrievalStatus.AVAILABLE,
    version: str = "2026.07.1",
    hash_character: str = "a",
    role_id: str = "rp-synthetic-ai",
    strategy_version: str = "1.0",
) -> KnowledgeContext:
    if status is KnowledgeRetrievalStatus.DISABLED:
        return KnowledgeContext(retrieval_strategy_version=strategy_version)

    version_id = f"kbv-{version.replace('.', '-')}"
    version_info = KnowledgeBaseVersionInfo(
        id=version_id,
        version=version,
        name="Synthetic reviewed knowledge",
        status=KnowledgeVersionStatus.PUBLISHED,
        content_hash=hash_character * 64,
        published_at=datetime(2026, 7, 25, 8, 0, tzinfo=UTC),
    )
    capabilities = KnowledgeSearchCapabilities(
        mode=KnowledgeSearchBackend.KEYWORD_FALLBACK,
        status=KnowledgeSearchCapabilityStatus.AVAILABLE,
        keyword_fallback_available=True,
    )
    if status in {
        KnowledgeRetrievalStatus.NO_MATCH,
        KnowledgeRetrievalStatus.UNAVAILABLE,
    }:
        return KnowledgeContext(
            status=status,
            version=version_info,
            capabilities=capabilities,
            retrieval_strategy_version=strategy_version,
        )

    def citation(index: int) -> KnowledgeCitation:
        return KnowledgeCitation(
            citation_id=f"cite-{index:016x}",
            source_id=f"ks-synthetic-{index}",
            source_title=f"Synthetic reviewed source {index}",
            source_type=KnowledgeSourceType.INTERNAL_TEMPLATE,
            source_url=f"https://example.test/source/{index}",
            knowledge_version_id=version_id,
            reliability_level=ReliabilityLevel.HIGH,
            source_checksum=f"{index:x}" * 64,
        )

    def role(identifier: str, index: int, score: str) -> RetrievedRoleProfile:
        return RetrievedRoleProfile(
            role_profile_id=identifier,
            job_family_code=f"synthetic_family_{index}",
            code=identifier.removeprefix("rp-").replace("-", "_"),
            name=f"Synthetic role {index}",
            seniority="intern",
            description="Synthetic reviewed role profile.",
            relevance_score=Decimal(score),
            matched_terms=["synthetic"],
            matched_fields=["name"],
            citation_ids=[f"cite-{index:016x}"],
        )

    first_citation = citation(1)
    first_role = role(role_id, 1, "0.9000")
    if status is KnowledgeRetrievalStatus.AMBIGUOUS:
        second_citation = citation(2)
        second_role = role("rp-synthetic-data", 2, "0.8800")
        return KnowledgeContext(
            status=status,
            version=version_info,
            inferred_role_profiles=[first_role, second_role],
            citations=[first_citation, second_citation],
            capabilities=capabilities,
            retrieval_strategy_version=strategy_version,
        )
    return KnowledgeContext(
        status=status,
        version=version_info,
        inferred_role_profiles=[first_role],
        citations=[first_citation],
        capabilities=capabilities,
        retrieval_strategy_version=strategy_version,
    )


def _orchestrator(
    doubles: Doubles,
    *,
    cache: WorkflowCache | None = None,
    knowledge_retriever: Any | None = None,
    knowledge_advice_generator: Any | None = None,
    fingerprint_context: WorkflowFingerprintContext | None = None,
) -> WorkflowOrchestrator:
    kwargs: dict[str, Any] = {}
    if knowledge_retriever is not None:
        kwargs["knowledge_retriever"] = knowledge_retriever
    if knowledge_advice_generator is not None:
        kwargs["knowledge_advice_generator"] = knowledge_advice_generator
    return WorkflowOrchestrator(
        parser_service=doubles,
        jd_parser=doubles,
        resume_extractor=_MethodAdapter(doubles.extract_resume, "extract"),
        job_extractor=_MethodAdapter(doubles.extract_job, "extract"),
        matcher=doubles,
        evidence_validator=doubles,
        scoring_engine=doubles,
        advice_generator=doubles,
        report_builder=doubles.build_report,
        markdown_renderer=doubles.markdown,
        json_renderer=doubles.json,
        fingerprint_context=fingerprint_context or _context(),
        cache=cache,
        **kwargs,
    )


class _MethodAdapter:
    def __init__(self, function: Callable[..., Any], name: str) -> None:
        setattr(self, name, function)


def test_complete_workflow_calls_each_dependency_once_in_order(
    report_case,
    analysis_report,
) -> None:
    doubles = Doubles(report_case, analysis_report)
    sink = RecordingSink()

    result = _orchestrator(doubles).run(
        _request(),
        selected_source="text",
        progress=sink,
    )

    assert result.success is True
    assert result.stage is WorkflowStage.COMPLETED
    assert result.report is analysis_report
    assert result.markdown == "# validated report"
    assert result.json_text == '{"schema_version":"1.0"}'
    assert [event.stage for event in result.events] == _EXPECTED_STAGES
    assert sink.events == list(result.events)
    assert doubles.calls == [
        "parser",
        "resume_extractor",
        "jd_parser",
        "job_extractor",
        "matcher",
        "validator",
        "scorer",
        "advice",
        "report_builder",
        "markdown",
        "json",
    ]
    assert all(count == 1 for count in Counter(doubles.calls).values())


def test_retriever_runs_once_after_job_extraction_and_before_matching(
    report_case,
    analysis_report,
) -> None:
    doubles = Doubles(report_case, analysis_report)
    retriever = RecordingKnowledgeRetriever(doubles)

    result = _orchestrator(
        doubles,
        knowledge_retriever=retriever,
    ).run(_request(), selected_source="text")

    assert result.success is True
    assert retriever.calls == [(report_case.job, 12)]
    assert doubles.calls.index("job_extractor") < doubles.calls.index(
        "knowledge_retriever"
    )
    assert doubles.calls.index("knowledge_retriever") < doubles.calls.index("matcher")


@pytest.mark.parametrize(
    "status",
    [
        KnowledgeRetrievalStatus.DISABLED,
        KnowledgeRetrievalStatus.UNAVAILABLE,
        KnowledgeRetrievalStatus.NO_MATCH,
        KnowledgeRetrievalStatus.AMBIGUOUS,
    ],
)
def test_non_available_knowledge_statuses_continue_the_base_workflow(
    report_case,
    analysis_report,
    status: KnowledgeRetrievalStatus,
) -> None:
    doubles = Doubles(report_case, analysis_report)
    retriever = RecordingKnowledgeRetriever(
        doubles,
        _knowledge_context(status=status),
    )

    result = _orchestrator(
        doubles,
        knowledge_retriever=retriever,
    ).run(_request(), selected_source="text")

    assert result.success is True
    assert "matcher" in doubles.calls
    assert "scorer" in doubles.calls
    assert "advice" in doubles.calls


def test_available_knowledge_uses_grounded_advice_and_stores_validated_sidecar(
    report_case,
    analysis_report,
) -> None:
    doubles = Doubles(report_case, analysis_report)
    cache = WorkflowCache()
    context = _knowledge_context()
    retriever = RecordingKnowledgeRetriever(doubles, context)
    knowledge_advice = RecordingKnowledgeAdviceGenerator(doubles)
    orchestrator = _orchestrator(
        doubles,
        cache=cache,
        knowledge_retriever=retriever,
        knowledge_advice_generator=knowledge_advice,
    )
    base_fingerprint = orchestrator.fingerprint(_request(), selected_source="text")

    result = orchestrator.run(_request(), selected_source="text")
    trace = cache.get_knowledge_advice_trace(base_fingerprint)

    assert result.success is True
    assert len(knowledge_advice.calls) == 1
    assert "advice" not in doubles.calls
    assert trace is not None
    assert trace.validated is True
    assert trace.fallback_used is False
    assert trace.citation_uses[0].output_reference == "recommendation:0"
    assert doubles.report_inputs[0]["knowledge_context"] is context
    assert doubles.report_inputs[0]["knowledge_advice_trace"] == trace
    assert not hasattr(result.report, "knowledge_advice_trace")


def test_invalid_knowledge_citation_falls_back_once_without_knowledge(
    report_case,
    analysis_report,
) -> None:
    doubles = Doubles(report_case, analysis_report)
    cache = WorkflowCache()
    retriever = RecordingKnowledgeRetriever(doubles, _knowledge_context())
    knowledge_advice = RecordingKnowledgeAdviceGenerator(
        doubles,
        citation_id="cite-ffffffffffffffff",
    )
    orchestrator = _orchestrator(
        doubles,
        cache=cache,
        knowledge_retriever=retriever,
        knowledge_advice_generator=knowledge_advice,
    )
    base_fingerprint = orchestrator.fingerprint(_request(), selected_source="text")

    result = orchestrator.run(_request(), selected_source="text")
    trace = cache.get_knowledge_advice_trace(base_fingerprint)

    assert result.success is True
    assert len(knowledge_advice.calls) == 1
    assert doubles.calls.count("knowledge_advice") == 1
    assert doubles.calls.count("advice") == 1
    assert trace is not None
    assert trace.validated is False
    assert trace.fallback_used is True
    assert trace.citation_uses == []
    assert trace.warnings[0].code.value == "knowledge_citation_invalid"
    assert "cite-ffffffffffffffff" not in trace.model_dump_json()


@pytest.mark.parametrize(
    "status",
    [
        KnowledgeRetrievalStatus.DISABLED,
        KnowledgeRetrievalStatus.UNAVAILABLE,
        KnowledgeRetrievalStatus.NO_MATCH,
        KnowledgeRetrievalStatus.AMBIGUOUS,
    ],
)
def test_non_available_knowledge_never_calls_grounded_advice_generator(
    report_case,
    analysis_report,
    status: KnowledgeRetrievalStatus,
) -> None:
    doubles = Doubles(report_case, analysis_report)
    retriever = RecordingKnowledgeRetriever(
        doubles,
        _knowledge_context(status=status),
    )
    knowledge_advice = RecordingKnowledgeAdviceGenerator(doubles)

    result = _orchestrator(
        doubles,
        knowledge_retriever=retriever,
        knowledge_advice_generator=knowledge_advice,
    ).run(_request(), selected_source="text")

    assert result.success is True
    assert knowledge_advice.calls == []
    assert doubles.calls.count("advice") == 1


def test_grounded_advice_fallback_failure_still_fails_closed(
    report_case,
    analysis_report,
) -> None:
    doubles = Doubles(report_case, analysis_report, fail_at="advice")
    retriever = RecordingKnowledgeRetriever(doubles, _knowledge_context())
    knowledge_advice = RecordingKnowledgeAdviceGenerator(
        doubles,
        citation_id="cite-ffffffffffffffff",
    )

    result = _orchestrator(
        doubles,
        knowledge_retriever=retriever,
        knowledge_advice_generator=knowledge_advice,
    ).run(_request(), selected_source="text")

    assert result.success is False
    assert doubles.calls.count("knowledge_advice") == 1
    assert doubles.calls.count("advice") == 1
    assert "report_builder" not in doubles.calls


def test_known_knowledge_database_failure_becomes_safe_recoverable_context(
    report_case,
    analysis_report,
) -> None:
    doubles = Doubles(report_case, analysis_report)
    cache = WorkflowCache()
    failure = KnowledgeDatabaseError(
        code=ErrorCode.KNOWLEDGE_DB_UNAVAILABLE,
        user_message=(
            "SELECT secret FROM knowledge at C:\\Users\\private\\knowledge.sqlite3"
        ),
        recoverable=True,
    )
    retriever = RecordingKnowledgeRetriever(doubles, failure=failure)
    orchestrator = _orchestrator(
        doubles,
        cache=cache,
        knowledge_retriever=retriever,
    )
    base_fingerprint = orchestrator.fingerprint(_request(), selected_source="text")

    result = orchestrator.run(_request(), selected_source="text")
    context = cache.get_knowledge_context(base_fingerprint)

    assert result.success is True
    assert context is not None
    assert context.status is KnowledgeRetrievalStatus.UNAVAILABLE
    assert context.warnings[0].recoverable is True
    serialized = context.model_dump_json()
    assert "SELECT" not in serialized
    assert "C:\\\\Users" not in serialized
    assert "knowledge.sqlite3" not in serialized


def test_unknown_retriever_exception_is_not_silently_downgraded(
    report_case,
    analysis_report,
) -> None:
    doubles = Doubles(report_case, analysis_report)
    retriever = RecordingKnowledgeRetriever(
        doubles,
        failure=RuntimeError("programming defect"),
    )

    result = _orchestrator(
        doubles,
        knowledge_retriever=retriever,
    ).run(_request(), selected_source="text")

    assert result.success is False
    assert result.error is not None
    assert result.error.recoverable is False
    assert "matcher" not in doubles.calls


def test_knowledge_does_not_change_matcher_scoring_or_advice_inputs(
    report_case,
    analysis_report,
) -> None:
    disabled_doubles = Doubles(report_case, analysis_report)
    available_doubles = Doubles(report_case, analysis_report)
    disabled = RecordingKnowledgeRetriever(
        disabled_doubles,
        _knowledge_context(status=KnowledgeRetrievalStatus.DISABLED),
    )
    available = RecordingKnowledgeRetriever(
        available_doubles,
        _knowledge_context(),
    )

    disabled_result = _orchestrator(
        disabled_doubles,
        knowledge_retriever=disabled,
    ).run(_request("knowledge-boundary"), selected_source="text")
    available_result = _orchestrator(
        available_doubles,
        knowledge_retriever=available,
    ).run(_request("knowledge-boundary"), selected_source="text")

    assert disabled_result.success is True
    assert available_result.success is True
    assert disabled_doubles.matcher_inputs == available_doubles.matcher_inputs
    assert disabled_doubles.scoring_inputs == available_doubles.scoring_inputs
    assert disabled_doubles.advice_inputs == available_doubles.advice_inputs
    assert disabled_result.report is available_result.report
    assert not hasattr(available_result.report, "knowledge_context")
    assert available_result.markdown == "# validated report"
    assert available_result.json_text == '{"schema_version":"1.0"}'


@pytest.mark.parametrize(
    ("fail_at", "forbidden_call"),
    [
        ("parser", "resume_extractor"),
        ("resume_extractor", "job_extractor"),
        ("job_extractor", "matcher"),
        ("matcher", "validator"),
        ("validator", "scorer"),
        ("scorer", "advice"),
        ("advice", "report_builder"),
        ("report_builder", "markdown"),
        ("markdown", "json"),
    ],
)
def test_failure_stops_all_downstream_work(
    report_case,
    analysis_report,
    fail_at: str,
    forbidden_call: str,
) -> None:
    doubles = Doubles(report_case, analysis_report, fail_at=fail_at)

    result = _orchestrator(doubles).run(
        _request(),
        selected_source="text",
    )

    assert result.success is False
    assert result.stage is WorkflowStage.FAILED
    assert result.report is None
    assert result.markdown is None
    assert result.json_text is None
    assert result.error is not None
    assert result.error.recoverable is (
        fail_at in {"parser", "resume_extractor", "job_extractor"}
    )
    assert forbidden_call not in doubles.calls
    assert result.events[-1].stage is WorkflowStage.FAILED


def test_unexpected_exception_is_redacted_and_fail_closed(
    report_case,
    analysis_report,
) -> None:
    doubles = Doubles(report_case, analysis_report)

    def unsafe_failure(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise RuntimeError(
            "SECRET-RESUME SECRET-JD sk-example-secret C:\\Users\\private"
        )

    doubles.parse_request = unsafe_failure  # type: ignore[method-assign]

    result = _orchestrator(doubles).run(
        _request(),
        selected_source="text",
    )

    assert result.success is False
    assert result.error is not None
    rendered = repr(result.error) + repr(result.events)
    assert "SECRET-RESUME" not in rendered
    assert "SECRET-JD" not in rendered
    assert "sk-example" not in rendered
    assert "C:\\Users" not in rendered


def test_progress_sink_failure_does_not_break_core_workflow(
    report_case,
    analysis_report,
) -> None:
    doubles = Doubles(report_case, analysis_report)

    result = _orchestrator(doubles).run(
        _request(),
        selected_source="text",
        progress=RecordingSink(fail=True),
    )

    assert result.success is True
    assert result.stage is WorkflowStage.COMPLETED


def test_successful_identical_request_is_reused_without_repeat_calls(
    report_case,
    analysis_report,
) -> None:
    doubles = Doubles(report_case, analysis_report)
    orchestrator = _orchestrator(doubles, cache=WorkflowCache())

    first = orchestrator.run(_request("request-first"), selected_source="text")
    call_count = len(doubles.calls)
    second = orchestrator.run(_request("request-second"), selected_source="text")

    assert first.success is True
    assert second.success is True
    assert second.cache_hit is True
    assert second.report is first.report
    assert len(doubles.calls) == call_count


def test_same_knowledge_identity_reuses_final_report_after_one_retrieval_per_run(
    report_case,
    analysis_report,
) -> None:
    doubles = Doubles(report_case, analysis_report)
    cache = WorkflowCache()
    context = _knowledge_context()
    retriever = RecordingKnowledgeRetriever(doubles, context, context)
    orchestrator = _orchestrator(
        doubles,
        cache=cache,
        knowledge_retriever=retriever,
    )

    first = orchestrator.run(_request("request-first"), selected_source="text")
    second = orchestrator.run(_request("request-second"), selected_source="text")
    calls = Counter(doubles.calls)

    assert first.success is True
    assert second.success is True
    assert second.cache_hit is True
    assert first.fingerprint == second.fingerprint
    assert len(retriever.calls) == 2
    assert calls["parser"] == 1
    assert calls["resume_extractor"] == 1
    assert calls["job_extractor"] == 1
    assert calls["matcher"] == 1
    assert calls["scorer"] == 1
    assert calls["advice"] == 1


@pytest.mark.parametrize(
    "changed_context",
    [
        _knowledge_context(version="2026.07.2"),
        _knowledge_context(hash_character="b"),
        _knowledge_context(role_id="rp-synthetic-data"),
        _knowledge_context(strategy_version="2.0"),
        _knowledge_context(status=KnowledgeRetrievalStatus.AMBIGUOUS),
        _knowledge_context(status=KnowledgeRetrievalStatus.NO_MATCH),
        _knowledge_context(status=KnowledgeRetrievalStatus.DISABLED),
    ],
    ids=[
        "version",
        "content-hash",
        "selected-role",
        "strategy-version",
        "ambiguous-status",
        "no-match-status",
        "disabled-status",
    ],
)
def test_changed_knowledge_identity_invalidates_only_the_final_report_cache(
    report_case,
    analysis_report,
    changed_context: KnowledgeContext,
) -> None:
    doubles = Doubles(report_case, analysis_report)
    cache = WorkflowCache()
    retriever = RecordingKnowledgeRetriever(
        doubles,
        _knowledge_context(),
        changed_context,
    )
    orchestrator = _orchestrator(
        doubles,
        cache=cache,
        knowledge_retriever=retriever,
    )

    first = orchestrator.run(_request("request-first"), selected_source="text")
    second = orchestrator.run(_request("request-second"), selected_source="text")
    calls = Counter(doubles.calls)

    assert first.success is True
    assert second.success is True
    assert second.cache_hit is False
    assert first.fingerprint != second.fingerprint
    assert len(retriever.calls) == 2
    assert calls["parser"] == 1
    assert calls["resume_extractor"] == 1
    assert calls["job_extractor"] == 1
    assert calls["matcher"] == 2
    assert calls["scorer"] == 2
    assert calls["advice"] == 2


@pytest.mark.parametrize(
    "second_fingerprint_context",
    [
        _context(knowledge_requirement_limit=11),
        _context(knowledge_prompt_char_limit=7_000),
    ],
    ids=["requirement-limit", "prompt-char-limit"],
)
def test_knowledge_budget_change_invalidates_final_cache_without_reextracting(
    report_case,
    analysis_report,
    second_fingerprint_context: WorkflowFingerprintContext,
) -> None:
    doubles = Doubles(report_case, analysis_report)
    cache = WorkflowCache()
    context = _knowledge_context()
    first_retriever = RecordingKnowledgeRetriever(doubles, context)
    second_retriever = RecordingKnowledgeRetriever(doubles, context)
    first_orchestrator = _orchestrator(
        doubles,
        cache=cache,
        knowledge_retriever=first_retriever,
        fingerprint_context=_context(),
    )
    second_orchestrator = _orchestrator(
        doubles,
        cache=cache,
        knowledge_retriever=second_retriever,
        fingerprint_context=second_fingerprint_context,
    )

    first = first_orchestrator.run(
        _request("request-first"),
        selected_source="text",
    )
    second = second_orchestrator.run(
        _request("request-second"),
        selected_source="text",
    )
    calls = Counter(doubles.calls)

    assert first.success is True
    assert second.success is True
    assert second.cache_hit is False
    assert first.fingerprint != second.fingerprint
    assert calls["parser"] == 1
    assert calls["resume_extractor"] == 1
    assert calls["job_extractor"] == 1
    assert calls["matcher"] == 2


@pytest.mark.parametrize(
    "second_fingerprint_context",
    [
        _context(knowledge_advice_prompt_version="1.3"),
        _context(knowledge_citation_validator_version="2.0"),
        _context(knowledge_advice_strategy_version="2.0"),
    ],
    ids=["advice-prompt", "citation-validator", "advice-strategy"],
)
def test_knowledge_advice_rule_change_invalidates_only_final_report_cache(
    report_case,
    analysis_report,
    second_fingerprint_context: WorkflowFingerprintContext,
) -> None:
    doubles = Doubles(report_case, analysis_report)
    cache = WorkflowCache()
    context = _knowledge_context()
    first_retriever = RecordingKnowledgeRetriever(doubles, context)
    second_retriever = RecordingKnowledgeRetriever(doubles, context)
    first_knowledge_advice = RecordingKnowledgeAdviceGenerator(doubles)
    second_knowledge_advice = RecordingKnowledgeAdviceGenerator(doubles)
    first_orchestrator = _orchestrator(
        doubles,
        cache=cache,
        knowledge_retriever=first_retriever,
        knowledge_advice_generator=first_knowledge_advice,
        fingerprint_context=_context(),
    )
    second_orchestrator = _orchestrator(
        doubles,
        cache=cache,
        knowledge_retriever=second_retriever,
        knowledge_advice_generator=second_knowledge_advice,
        fingerprint_context=second_fingerprint_context,
    )

    first = first_orchestrator.run(
        _request("request-first"),
        selected_source="text",
    )
    second = second_orchestrator.run(
        _request("request-second"),
        selected_source="text",
    )
    calls = Counter(doubles.calls)

    assert first.success is True
    assert second.success is True
    assert second.cache_hit is False
    assert first.fingerprint != second.fingerprint
    assert calls["parser"] == 1
    assert calls["resume_extractor"] == 1
    assert calls["job_extractor"] == 1
    assert calls["matcher"] == 2
    assert calls["scorer"] == 2
    assert calls["knowledge_advice"] == 2


def test_database_path_is_not_part_of_workflow_knowledge_identity() -> None:
    assert "knowledge_db_path" not in WorkflowFingerprintContext.__dataclass_fields__


def test_failed_request_is_not_cached_as_success(
    report_case,
    analysis_report,
) -> None:
    doubles = Doubles(report_case, analysis_report, fail_at="parser")
    orchestrator = _orchestrator(doubles, cache=WorkflowCache())

    first = orchestrator.run(_request("request-first"), selected_source="text")
    second = orchestrator.run(_request("request-second"), selected_source="text")

    assert first.success is False
    assert second.success is False
    assert doubles.calls == ["parser", "parser"]


def test_in_flight_duplicate_does_not_start_dependencies(
    report_case,
    analysis_report,
) -> None:
    cache = WorkflowCache()
    doubles = Doubles(report_case, analysis_report)
    orchestrator = _orchestrator(doubles, cache=cache)
    fingerprint = orchestrator.fingerprint(
        _request(),
        selected_source="text",
    )
    assert cache.begin(fingerprint) is True

    result = orchestrator.run(_request(), selected_source="text")

    assert result.success is False
    assert result.error is not None
    assert result.error.recoverable is True
    assert not doubles.calls


@pytest.mark.parametrize(
    ("input_request", "selected_source"),
    [
        (
            AnalysisRequest(
                request_id="missing-text",
                resume_file=UploadedDocumentInput(
                    filename="resume.txt",
                    media_type="text/plain",
                    content=b"resume",
                    size_bytes=6,
                ),
                job_description_text="匿名JD",
                llm_mode="mock",
            ),
            "text",
        ),
        (_request("missing-file"), "file"),
        (_request("invalid-source"), "other"),
    ],
)
def test_invalid_source_choice_fails_during_input_validation(
    report_case,
    analysis_report,
    input_request: AnalysisRequest,
    selected_source: str,
) -> None:
    doubles = Doubles(report_case, analysis_report)

    result = _orchestrator(doubles).run(
        input_request,
        selected_source=selected_source,
    )

    assert result.success is False
    assert result.stage is WorkflowStage.FAILED
    assert not doubles.calls


def test_file_source_runs_through_the_same_pipeline(
    report_case,
    analysis_report,
) -> None:
    doubles = Doubles(report_case, analysis_report)
    upload = UploadedDocumentInput(
        filename="resume.txt",
        media_type="text/plain",
        content=b"anonymous resume",
        size_bytes=len(b"anonymous resume"),
    )
    request = _request("file-request").model_copy(
        update={"resume_file": upload}
    )

    result = _orchestrator(doubles).run(
        request,
        selected_source="file",
    )

    assert result.success is True
    assert doubles.calls[0] == "parser"
