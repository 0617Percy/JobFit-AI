"""P06 action contracts for the side-by-side v2 advisory layer."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from jobfit.advisory.v2.actions import (
    P06ActionGenerator,
    _map_build_output,
    _map_candidate_output,
)
from jobfit.llm import LLMSettings, MockLLMProvider
from jobfit.models import Importance
from jobfit.models.v2 import (
    AbilityStatus,
    ActionType,
    AnalysisCore,
    AnalysisReadiness,
    CandidateProfile,
    CitationUsage,
    ClarityLevel,
    Confidence,
    CriticalStatus,
    EligibilityStatus,
    Evidence,
    EvidenceLevel,
    EvidenceSourceOrigin,
    EvidenceStatus,
    JobFamily,
    JobFitDomainBundle,
    JobProfile,
    KnowledgeCitation,
    KnowledgeCoverage,
    MatchCoverage,
    MatchedEvidence,
    ParseCompleteness,
    PersonalContribution,
    Recommendation,
    Relevance,
    Requirement,
    RequirementExplicitness,
    RequirementMatch,
    RequirementSource,
    RequirementType,
    ResumeProfile,
    SeniorityAlignment,
    SupportType,
    UserClarification,
    VersionManifest,
)
from jobfit.semantic.v2.advisory_contracts import (
    P06ActionDraft,
    P06ActionOutput,
    P06BuildOutput,
    P06CandidateOutput,
)
from jobfit.semantic.v2.executor import (
    SemanticLLMTask,
    SemanticPromptError,
    SemanticPromptExecutor,
)
from jobfit.semantic.v2.severity import SemanticValidationSeverity

PROMPT_ROOT = Path(__file__).parents[2] / "src" / "jobfit" / "prompts" / "v2"


def _bundle() -> JobFitDomainBundle:
    resume_text = "Built a Python API and validated JSON output."
    resume_evidence = Evidence(
        evidence_id="ev-resume",
        resume_version_id="resume-v1",
        source_origin=EvidenceSourceOrigin.RESUME,
        source_type="project",
        source_text=resume_text,
        normalized_capabilities=["Python", "structured output"],
        personal_contribution=PersonalContribution.CLEAR,
        task_clarity=ClarityLevel.HIGH,
        method_tool_clarity=ClarityLevel.HIGH,
        result_clarity=ClarityLevel.MEDIUM,
        verification_strength=ClarityLevel.MEDIUM,
        practical_use=ClarityLevel.HIGH,
        evidence_level=EvidenceLevel.L4,
        document_id="doc-resume",
        segment_id="seg-resume",
        start_char=0,
        end_char=len(resume_text),
    )
    clarified_evidence = Evidence(
        evidence_id="ev-clarified",
        source_origin=EvidenceSourceOrigin.USER_CLARIFICATION,
        source_type="clarification",
        source_record_id="clarification-1",
        source_text="Implemented retry handling in the clarified project.",
        normalized_capabilities=["reliability"],
        evidence_level=EvidenceLevel.L2,
    )
    clarification = UserClarification(
        clarification_id="clarification-1",
        analysis_id="analysis-1",
        question="Did you implement failure handling?",
        answer="Yes, I implemented retry handling.",
        normalized_fact={"capability": "retry handling"},
        creates_evidence=True,
        created_evidence_ids=[clarified_evidence.evidence_id],
        affected_requirement_ids=["req-core"],
    )
    resume = ResumeProfile(
        resume_version_id="resume-v1",
        candidate_profile=CandidateProfile(),
        evidence_ids=[resume_evidence.evidence_id],
        parse_completeness=ParseCompleteness.COMPLETE,
    )
    requirement = Requirement(
        requirement_id="req-core",
        jd_snapshot_id="jd-v1",
        raw_requirement_ids=["raw-core"],
        raw_text="Build reliable Python AI applications.",
        normalized_capability="reliable AI application delivery",
        requirement_type=RequirementType.CORE,
        importance=Importance.HIGH,
        explicitness=RequirementExplicitness.EXPLICIT,
        source=RequirementSource.JD,
        critical_status=CriticalStatus.NOT_CRITICAL,
    )
    job = JobProfile(
        jd_snapshot_id="jd-v1",
        job_title="Synthetic AI Application Intern",
        job_family=JobFamily.AI_APPLICATION,
        knowledge_coverage=KnowledgeCoverage.ENHANCED,
        raw_requirement_ids=["raw-core"],
        requirement_ids=[requirement.requirement_id],
    )
    match = RequirementMatch(
        match_id="match-core",
        requirement_id=requirement.requirement_id,
        matched_evidence=[
            MatchedEvidence(
                evidence_id=resume_evidence.evidence_id,
                relevance=Relevance.HIGH,
                support_type=SupportType.DIRECT,
            )
        ],
        coverage=MatchCoverage.SUBSTANTIAL,
        evidence_status=EvidenceStatus.PRESENT,
        ability_status=AbilityStatus.CONFIRMED,
        best_evidence_level=EvidenceLevel.L4,
        match_score_component=Decimal("0.8"),
    )
    core = AnalysisCore(
        analysis_id="analysis-1",
        resume_version_id=resume.resume_version_id,
        jd_snapshot_id=job.jd_snapshot_id,
        analysis_readiness=AnalysisReadiness.READY,
        eligibility_status=EligibilityStatus.MET,
        seniority_alignment=SeniorityAlignment.ALIGNED,
        base_fit_score=Decimal("78.00"),
        preferred_bonus=Decimal("2.00"),
        final_fit_score=Decimal("80.00"),
        confidence=Confidence.HIGH,
        recommendation=Recommendation.SUGGESTED,
        recommendation_reason_codes=["CORE_COVERAGE_STRONG"],
    )
    build_citation = KnowledgeCitation(
        citation_id="citation-build",
        knowledge_version="2026.08.1",
        source_id="source-build",
        role_family=JobFamily.AI_APPLICATION,
        title="Synthetic role guidance",
        usage=CitationUsage.BUILD_RECOMMENDATION,
        supported_claim="Reliable AI applications benefit from explicit evaluation.",
    )
    return JobFitDomainBundle(
        resume_profile=resume,
        evidence=[resume_evidence, clarified_evidence],
        job_profile=job,
        requirements=[requirement],
        requirement_matches=[match],
        analysis_core=core,
        knowledge_citations=[build_citation],
        user_clarifications=[clarification],
        versions=VersionManifest(
            software_version="1.1.0",
            prompt_pack_version="1.0.0",
            schema_version="2.0.0",
            scoring_rule_version="1.0.0",
            knowledge_version="2026.08.1",
            analysis_engine_version="1.0.0",
        ),
    )


def _rewrite(**updates: object) -> dict[str, object]:
    item: dict[str, object] = {
        "action_type": "rewrite",
        "priority": "p0",
        "related_requirement_ids": ["req-core"],
        "related_evidence_ids": ["ev-resume"],
        "supported_by_evidence_ids": ["ev-resume"],
        "source_clarification_ids": [],
        "knowledge_citation_ids": [],
        "title": "Clarify the existing structured-output work",
        "why_it_matters": "The evidence exists but its job relevance can be clearer.",
        "recommended_action": "Built a Python API and validated JSON output.",
        "completion_criteria": "The bullet remains fully traceable to ev-resume.",
        "effort": "low",
        "time_to_complete": "30-45 minutes",
        "timing": "before_apply",
        "introduced_claims": [],
    }
    item.update(updates)
    return item


def _recover(**updates: object) -> dict[str, object]:
    item: dict[str, object] = {
        "action_type": "recover",
        "priority": "p0",
        "related_requirement_ids": ["req-core"],
        "related_evidence_ids": ["ev-clarified"],
        "supported_by_evidence_ids": ["ev-clarified"],
        "source_clarification_ids": ["clarification-1"],
        "knowledge_citation_ids": [],
        "title": "Add the confirmed retry-handling fact to a future resume version",
        "why_it_matters": "The confirmed fact is absent from the current resume.",
        "recommended_action": "Add the confirmed retry-handling contribution.",
        "completion_criteria": "The next resume version cites the confirmed fact.",
        "effort": "low",
        "time_to_complete": "20-30 minutes",
        "timing": "before_apply",
        "introduced_claims": [],
    }
    item.update(updates)
    return item


def _build(**updates: object) -> dict[str, object]:
    item: dict[str, object] = {
        "priority": "p0",
        "related_requirement_ids": ["req-core"],
        "knowledge_citation_ids": ["citation-build"],
        "title": "Build a small evaluation harness",
        "why_it_matters": "This can create future evidence for reliability work.",
        "recommended_action": (
            "Create a reproducible evaluation script and document how to run it."
        ),
        "completion_criteria": "A reproducible artifact and evaluation notes exist.",
        "effort": "medium",
        "time_to_complete": "4-6 focused hours",
        "timing": "parallel_with_applications",
    }
    item.update(updates)
    return item


def _output(*actions: dict[str, object]) -> dict[str, object]:
    return {"actions": list(actions), "warnings": []}


def _generator(
    candidate_output: dict[str, object],
    build_output: dict[str, object],
) -> tuple[P06ActionGenerator, MockLLMProvider]:
    provider = MockLLMProvider(
        {
            SemanticLLMTask.P06_ACTIONS: [
                json.dumps(candidate_output),
                json.dumps(build_output),
            ]
        }
    )
    executor = SemanticPromptExecutor(
        provider=provider,
        prompt_root=PROMPT_ROOT,
        settings=LLMSettings(model="semantic-mock", max_retries=0),
    )
    return P06ActionGenerator(executor), provider


def _scripted_generator(
    *outputs: dict[str, object],
) -> tuple[P06ActionGenerator, MockLLMProvider]:
    provider = MockLLMProvider(
        {
            SemanticLLMTask.P06_ACTIONS: [
                json.dumps(output) for output in outputs
            ]
        }
    )
    executor = SemanticPromptExecutor(
        provider=provider,
        prompt_root=PROMPT_ROOT,
        settings=LLMSettings(model="semantic-mock", max_retries=0),
    )
    return P06ActionGenerator(executor), provider


def _semantic_input(provider: MockLLMProvider, call_index: int) -> dict[str, object]:
    content = provider.calls[call_index].messages[1].content.strip()
    return json.loads(content.rsplit("\n", 1)[-1])


def test_p06_generates_traceable_actions_without_mutating_analysis_core() -> None:
    bundle = _bundle()
    generator, _ = _generator(
        _output(_rewrite(), _recover()),
        _output(_build()),
    )

    result = generator.generate(bundle)

    assert result.analysis_core is bundle.analysis_core
    assert [item.action_type for item in result.actions] == [
        ActionType.REWRITE,
        ActionType.RECOVER,
        ActionType.BUILD,
    ]
    assert bundle.analysis_core.final_fit_score == Decimal("80.00")
    assert bundle.analysis_core.recommendation is Recommendation.SUGGESTED
    assert len(result.executions) == 2


def test_p06_preserves_execution_time_for_each_action_type() -> None:
    generator, _ = _generator(
        _output(
            _rewrite(time_to_complete="30-45 minutes"),
            _recover(time_to_complete="20-30 minutes"),
        ),
        _output(_build(time_to_complete="4-6 focused hours")),
    )

    result = generator.generate(_bundle())

    assert [item.time_to_complete for item in result.actions] == [
        "30-45 minutes",
        "20-30 minutes",
        "4-6 focused hours",
    ]


@pytest.mark.parametrize(
    ("candidate_actions", "build_actions"),
    [
        (
            [_rewrite(
                why_it_matters="The evidence is relevant.",
            )],
            [],
        ),
        (
            [],
            [_build(
                recommended_action="Build a validation artifact.",
                completion_criteria="Finish it.",
            )],
        ),
    ],
    ids=["generic-rewrite", "generic-build"],
)
def test_p06_accepts_low_information_action_copy_with_quality_warning(
    candidate_actions: list[dict[str, object]],
    build_actions: list[dict[str, object]],
) -> None:
    generator, _ = _generator(
        _output(*(candidate_actions or [_rewrite()])),
        _output(*(build_actions or [_build()])),
    )

    result = generator.generate(_bundle())

    records = result.executions
    warnings = tuple(warning for record in records for warning in record.warnings)
    issues = tuple(issue for record in records for issue in record.validation_issues)
    assert "ACTION_QUALITY_TOO_GENERIC" in warnings
    assert any(
        issue.category == "ACTION_QUALITY_TOO_GENERIC"
        and issue.severity is SemanticValidationSeverity.QUALITY_WARNING
        for issue in issues
    )


def test_p06_prompt_demands_actionable_and_verifiable_guidance() -> None:
    generator, provider = _generator(
        _output(_rewrite()),
        _output(_build()),
    )

    generator.generate(_bundle())

    system_prompt = provider.calls[0].messages[0].content.casefold()
    assert "what to change" in system_prompt
    assert "completion" in system_prompt
    assert "time" in system_prompt
    assert "must not invent" in system_prompt
    build_prompt = provider.calls[1].messages[0].content.casefold()
    assert "verifiable artifact" in build_prompt


def test_p06_prompt_exposes_mode_types_and_rewrite_strength_boundary() -> None:
    generator, provider = _generator(
        _output(_rewrite()),
        _output(_build()),
    )

    generator.generate(_bundle())

    prompt = provider.calls[0].messages[0].content.casefold()
    assert 'action_type must be exactly "rewrite" or "recover"' in prompt
    assert 'action_type is system-fixed to exactly "build"' in prompt
    assert "must not increase factual strength" in prompt


def test_p06_prompt_exposes_recover_traceability_contract() -> None:
    prompt = (PROMPT_ROOT / "p06_actions.md").read_text(encoding="utf-8")
    folded = prompt.casefold()
    # A/B: recover requires confirmed non-resume evidence through
    # supported_by_evidence_ids, which must be non-empty.
    assert "confirmed non-resume evidence" in folded
    assert "supported_by_evidence_ids" in folded
    assert "non-empty" in folded
    # C: user-clarification evidence keeps source_clarification_ids traceability.
    assert "source_clarification_ids" in folded
    # D: resume evidence alone can never justify a recover action.
    assert "resume evidence alone" in folded
    # E: no valid non-resume evidence => do not emit a recover action.
    assert "do not emit" in folded
    assert "recover" in folded
    # F: never invent evidence/clarification/source identities.
    assert "never invent" in folded


def test_p06_prompt_exposes_rewrite_traceability_contract() -> None:
    prompt = (PROMPT_ROOT / "p06_actions.md").read_text(encoding="utf-8")
    folded = prompt.casefold()
    assert "rewrite traceability" in folded
    assert "action_type = rewrite" in folded
    # A: supported_by_evidence_ids must be non-empty.
    assert "supported_by_evidence_ids" in folded
    assert "non-empty" in folded
    # B/C: must reference actual Resume evidence from the authoritative input
    # belonging to the applicable resume version.
    assert "resume evidence" in folded
    assert "authoritative input" in folded
    # D: related_requirement_ids does not replace evidence traceability.
    assert "related_requirement_ids" in folded
    assert "does not replace" in folded
    # E: never emit a rewrite with empty supported_by_evidence_ids.
    assert "do not emit" in folded
    # F: never invent evidence IDs.
    assert "never invent" in folded
    # G: clarification/knowledge references are not substitutes for Resume support.
    assert "source_clarification_ids" in folded
    assert "substitute" in folded


def test_p06_normal_input_exposes_compact_authoritative_reference_catalogs() -> None:
    generator, provider = _generator(_output(_rewrite()), _output(_build()))

    generator.generate(_bundle())

    payload = _semantic_input(provider, 0)
    assert payload["requirement_reference_catalog"] == [
        {
            "requirement_id": "req-core",
            "descriptor": "reliable AI application delivery",
        }
    ]
    assert payload["evidence_reference_catalog"] == [
        {
            "evidence_id": "ev-resume",
            "descriptor": "Python; structured output",
            "source_origin": "resume",
            "source_record_id": None,
            "eligible_for_rewrite": True,
            "eligible_for_recover": False,
        },
        {
            "evidence_id": "ev-clarified",
            "descriptor": "reliability",
            "source_origin": "user_clarification",
            "source_record_id": "clarification-1",
            "eligible_for_rewrite": False,
            "eligible_for_recover": True,
        },
    ]
    assert payload["clarification_reference_catalog"] == [
        {
            "clarification_id": "clarification-1",
            "descriptor": "answered clarification",
            "created_evidence_ids": ["ev-clarified"],
        }
    ]


@pytest.mark.parametrize(
    ("invalid_action", "valid_action", "expected_category", "repair_terms"),
    (
        (
            _rewrite(related_requirement_ids=["req-unknown"]),
            _rewrite(),
            "UNKNOWN_REQUIREMENT_REFERENCE",
            ("requirement_reference_catalog", "copy", "verbatim"),
        ),
        (
            _rewrite(
                related_evidence_ids=["ev-unknown"],
                supported_by_evidence_ids=["ev-unknown"],
            ),
            _rewrite(),
            "UNKNOWN_EVIDENCE_REFERENCE",
            ("evidence_reference_catalog", "copy", "verbatim"),
        ),
        (
            _recover(supported_by_evidence_ids=[]),
            _recover(),
            "RECOVER_TRACEABILITY_MISSING",
            (
                "eligible_for_recover",
                "supported_by_evidence_ids",
                "source_clarification_ids",
            ),
        ),
    ),
    ids=["requirement", "evidence", "recover-traceability"],
)
def test_p06_reference_repairs_are_category_specific_and_converge_in_two_attempts(
    invalid_action: dict[str, object],
    valid_action: dict[str, object],
    expected_category: str,
    repair_terms: tuple[str, ...],
) -> None:
    generator, provider = _scripted_generator(
        _output(invalid_action),
        _output(valid_action),
        _output(_build()),
    )

    result = generator.generate(_bundle())

    assert result.executions[0].attempt_count == 2
    assert result.executions[0].attempts[0].validation_categories == (
        expected_category,
    )
    repair = json.loads(provider.calls[1].messages[-1].content)
    instruction = repair["instruction"].casefold()
    assert all(term.casefold() in instruction for term in repair_terms)


def test_p06_hat_failure_chain_is_reproduced_without_silent_reference_autofix() -> None:
    generator, _ = _scripted_generator(
        _output(_rewrite(related_requirement_ids=["req-unknown"])),
        _output(
            _recover(
                related_evidence_ids=["ev-unknown"],
                supported_by_evidence_ids=["ev-unknown"],
            )
        ),
        _output(_recover(supported_by_evidence_ids=[])),
    )

    with pytest.raises(SemanticPromptError) as caught:
        generator.generate(_bundle())

    assert [attempt.validation_categories for attempt in caught.value.attempts] == [
        ("UNKNOWN_REQUIREMENT_REFERENCE",),
        ("UNKNOWN_EVIDENCE_REFERENCE",),
        ("RECOVER_TRACEABILITY_MISSING",),
    ]


def test_p06_unknown_evidence_remains_fail_closed_after_all_attempts() -> None:
    invalid = _output(
        _rewrite(
            related_evidence_ids=["ev-unknown"],
            supported_by_evidence_ids=["ev-unknown"],
        )
    )
    generator, _ = _scripted_generator(invalid, invalid, invalid)

    with pytest.raises(SemanticPromptError) as caught:
        generator.generate(_bundle())

    assert len(caught.value.attempts) == 3
    assert all(
        attempt.validation_categories == ("UNKNOWN_EVIDENCE_REFERENCE",)
        for attempt in caught.value.attempts
    )


def test_p06_rejects_incomplete_validated_input_before_model_call() -> None:
    generator, provider = _generator(_output(), _output())

    with pytest.raises(SemanticPromptError, match="INCOMPLETE_VALIDATED_INPUT"):
        generator.generate(_bundle().model_copy(update={"job_profile": None}))

    assert provider.calls == []


@pytest.mark.parametrize(
    "invalid_rewrite",
    [
        _rewrite(supported_by_evidence_ids=[]),
        _rewrite(
            recommended_action=(
                "Built a Python API and improved output accuracy by 35%."
            )
        ),
        _rewrite(recommended_action="Led a five-person team to build a Python API."),
        _rewrite(knowledge_citation_ids=["citation-build"]),
    ],
    ids=["no-evidence", "invented-result", "ownership-escalation", "k3-leak"],
)
def test_p06_rejects_unsupported_or_knowledge_polluted_rewrites(
    invalid_rewrite: dict[str, object],
) -> None:
    invalid_output = _output(invalid_rewrite)
    generator, _ = _generator(invalid_output, _output(_build()))

    with pytest.raises(SemanticPromptError):
        generator.generate(_bundle())


def test_p06_rejects_rewrite_from_another_resume_version() -> None:
    bundle = _bundle()
    foreign = bundle.evidence[0].model_copy(
        update={"resume_version_id": "resume-v2"}
    )
    bundle = bundle.model_copy(update={"evidence": [foreign, bundle.evidence[1]]})
    invalid_output = _output(_rewrite())
    generator, _ = _generator(invalid_output, _output(_build()))

    with pytest.raises(SemanticPromptError):
        generator.generate(bundle)


def test_p06_unknown_requirement_has_safe_stage_specific_diagnostic() -> None:
    generator, _ = _generator(
        _output(_rewrite(related_requirement_ids=["req-unknown"])),
        _output(_build()),
    )

    with pytest.raises(SemanticPromptError) as caught:
        generator.generate(_bundle())

    assert caught.value.prompt_id == "P06"
    assert caught.value.attempts
    assert caught.value.attempts[0].validation_paths == (
        "actions[0].related_requirement_ids",
    )
    assert caught.value.attempts[0].validation_categories == (
        "UNKNOWN_REQUIREMENT_REFERENCE",
    )
    assert (
        caught.value.attempts[0].validation_issues[0].severity
        is SemanticValidationSeverity.HARD_BLOCK
    )


def test_p06_invalid_action_type_has_safe_exact_diagnostic() -> None:
    generator, _ = _scripted_generator(
        _output(_rewrite(action_type="build")),
    )

    with pytest.raises(SemanticPromptError) as caught:
        generator.generate(_bundle())

    assert caught.value.code == "BUSINESS_VALIDATION_FAILED"
    assert caught.value.attempts[0].validation_paths == (
        "actions[0].action_type",
    )
    assert caught.value.attempts[0].validation_categories == (
        "INVALID_ACTION_TYPE",
    )


def test_p06_semantic_strength_increase_has_safe_exact_diagnostic() -> None:
    strengthened = _rewrite(
        recommended_action=(
            "Built a Python API, validated JSON output, and improved accuracy by 35%."
        )
    )
    generator, _ = _scripted_generator(_output(strengthened))

    with pytest.raises(SemanticPromptError) as caught:
        generator.generate(_bundle())

    assert caught.value.code == "BUSINESS_VALIDATION_FAILED"
    assert caught.value.attempts[0].validation_paths == (
        "actions[0].recommended_action",
    )
    assert caught.value.attempts[0].validation_categories == (
        "SEMANTIC_STRENGTH_INCREASE",
    )
    assert (
        caught.value.attempts[0].validation_issues[0].severity
        is SemanticValidationSeverity.HARD_BLOCK
    )


@pytest.mark.parametrize(
    ("invalid_action", "expected_category", "repair_rule"),
    (
        (
            _rewrite(action_type="build"),
            "INVALID_ACTION_TYPE",
            "candidate_grounded permits only rewrite or recover",
        ),
        (
            _rewrite(
                recommended_action=(
                    "Built a Python API, validated JSON output, and improved accuracy "
                    "by 35%."
                )
            ),
            "SEMANTIC_STRENGTH_INCREASE",
            "must not increase factual strength",
        ),
    ),
    ids=["action-type", "semantic-strength"],
)
def test_p06_targeted_repair_explains_static_business_rule(
    invalid_action: dict[str, object],
    expected_category: str,
    repair_rule: str,
) -> None:
    generator, provider = _scripted_generator(
        _output(invalid_action),
        _output(_rewrite()),
        _output(_build()),
    )

    result = generator.generate(_bundle())

    repair = json.loads(provider.calls[1].messages[-1].content)
    assert repair["validation_issues"] == [
        {
            "path": (
                "actions[0].action_type"
                if expected_category == "INVALID_ACTION_TYPE"
                else "actions[0].recommended_action"
            ),
            "category": expected_category,
        }
    ]
    assert repair_rule in repair["instruction"]
    assert result.executions[0].attempt_count == 2


def test_p06_full_retry_preserves_clean_complete_output_contract() -> None:
    strengthened = _rewrite(
        recommended_action=(
            "Built a Python API, validated JSON output, and improved accuracy by 35%."
        )
    )
    generator, provider = _scripted_generator(
        _output(_rewrite(action_type="build")),
        _output(strengthened),
        _output(_rewrite()),
        _output(_build()),
    )

    result = generator.generate(_bundle())

    assert [attempt.stage for attempt in result.executions[0].attempts] == [
        "normal",
        "targeted_repair",
        "full_retry",
    ]
    retry_guidance = provider.calls[2].messages[-1].content
    assert "complete replacement JSON object" in retry_guidance
    assert "validation_issues" not in retry_guidance


@pytest.mark.parametrize(
    "invalid_recover",
    [
        _recover(supported_by_evidence_ids=[], source_clarification_ids=[]),
        _recover(
            related_evidence_ids=["ev-resume"],
            supported_by_evidence_ids=["ev-resume"],
            source_clarification_ids=[],
        ),
    ],
    ids=["no-confirmed-source", "jd-only-not-confirmed"],
)
def test_p06_rejects_recover_without_confirmed_non_resume_source(
    invalid_recover: dict[str, object],
) -> None:
    invalid_output = _output(invalid_recover)
    generator, _ = _generator(invalid_output, _output(_build()))

    with pytest.raises(SemanticPromptError):
        generator.generate(_bundle())


def test_p06_rejects_recover_without_external_source_identity() -> None:
    bundle = _bundle()
    portfolio = Evidence(
        evidence_id="ev-portfolio",
        source_origin=EvidenceSourceOrigin.PORTFOLIO,
        source_type="portfolio",
        source_text="A portfolio artifact exists.",
        evidence_level=EvidenceLevel.L2,
    )
    bundle = bundle.model_copy(update={"evidence": [*bundle.evidence, portfolio]})
    invalid_recover = _recover(
        related_evidence_ids=[portfolio.evidence_id],
        supported_by_evidence_ids=[portfolio.evidence_id],
        source_clarification_ids=[],
    )
    invalid_output = _output(invalid_recover)
    generator, _ = _generator(invalid_output, _output(_build()))

    with pytest.raises(SemanticPromptError):
        generator.generate(bundle)


def test_p06_build_transport_schema_excludes_evidence_and_identity_fields() -> None:
    from pydantic import ValidationError

    schema = P06BuildOutput.model_json_schema()
    item_properties = schema["$defs"]["P06BuildActionDraft"]["properties"]
    assert "action_id" not in item_properties
    assert "action_type" not in item_properties
    assert "related_evidence_ids" not in item_properties
    assert "supported_by_evidence_ids" not in item_properties
    assert "source_clarification_ids" not in item_properties
    assert "future_only" not in item_properties
    assert "introduced_claims" not in item_properties
    # The model cannot even express current-evidence claims in build mode.
    with pytest.raises(ValidationError):
        P06BuildOutput.model_validate(
            _output(_build(related_evidence_ids=["ev-resume"]))
        )


def test_p06_build_claiming_current_candidate_evidence_is_schema_invalid() -> None:
    generator, _ = _generator(
        _output(),
        _output(
            _build(
                related_evidence_ids=["ev-resume"],
                supported_by_evidence_ids=["ev-resume"],
            )
        ),
    )

    with pytest.raises(SemanticPromptError):
        generator.generate(_bundle())


def test_p06_vague_build_completion_remains_fail_closed_across_attempts() -> None:
    vague_build = _output(
        _build(
            recommended_action="Improve prototype skills.",
            completion_criteria="The candidate feels more prepared.",
        )
    )
    generator, _ = _scripted_generator(
        _output(_rewrite()),
        vague_build,
        vague_build,
        vague_build,
    )

    with pytest.raises(SemanticPromptError) as caught:
        generator.generate(_bundle())

    assert [attempt.validation_paths for attempt in caught.value.attempts] == [
        ("actions[0].completion_criteria",),
        ("actions[0].completion_criteria",),
        ("actions[0].completion_criteria",),
    ]
    assert all(
        attempt.validation_categories == ("BUILD_TRACEABILITY_MISSING",)
        for attempt in caught.value.attempts
    )


def test_p06_build_traceability_repair_converges_without_full_retry() -> None:
    invalid = _build(
        recommended_action="Improve prototype skills.",
        completion_criteria="The candidate feels more prepared.",
    )
    generator, provider = _scripted_generator(
        _output(_rewrite()),
        _output(invalid),
        _output(_build()),
    )

    result = generator.generate(_bundle())

    build_execution = result.executions[1]
    assert build_execution.attempt_count == 2
    assert provider.call_count == 3
    assert build_execution.attempts[0].validation_paths == (
        "actions[0].completion_criteria",
    )
    assert build_execution.attempts[0].validation_categories == (
        "BUILD_TRACEABILITY_MISSING",
    )
    repair = json.loads(provider.calls[2].messages[-1].content)
    instruction = repair["instruction"].casefold()
    assert "observable future artifact" in instruction
    assert "completion_criteria" in instruction
    assert "future-only" in instruction
    assert "do not cite existing evidence" in instruction
    assert "do not invent candidate facts" in instruction
    assert "complete corrected json object" in instruction


def test_p06_normal_and_full_retry_share_observable_build_contract() -> None:
    invalid = _output(
        _build(
            recommended_action="Improve prototype skills.",
            completion_criteria="The candidate feels more prepared.",
        )
    )
    generator, provider = _scripted_generator(
        _output(_rewrite()),
        invalid,
        invalid,
        _output(_build()),
    )

    result = generator.generate(_bundle())

    assert result.executions[1].attempt_count == 3
    normal_prompt = provider.calls[1].messages[0].content.casefold()
    full_retry_prompt = provider.calls[3].messages[0].content.casefold()
    for prompt in (normal_prompt, full_retry_prompt):
        assert "observable future artifact" in prompt
        assert "completion_criteria" in prompt
        assert "future-only" in prompt
        assert "must exist and be reviewable or verifiable" in prompt


def test_p06_build_transport_rejects_declared_candidate_facts() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        P06BuildOutput.model_validate(
            _output(_build(introduced_claims=["Candidate already shipped it."]))
        )


def test_p06_rejects_build_that_attempts_to_enter_current_score() -> None:
    invalid_output = _output(_build(match_score_component="0.9"))
    generator, _ = _generator(_output(), invalid_output)

    with pytest.raises(SemanticPromptError):
        generator.generate(_bundle())


@pytest.mark.parametrize(
    "invalid_rewrite",
    [
        _rewrite(related_requirement_ids=["req-unknown"]),
        _rewrite(
            related_evidence_ids=["ev-unknown"],
            supported_by_evidence_ids=["ev-unknown"],
        ),
        _rewrite(source_clarification_ids=["clarification-unknown"]),
        _rewrite(knowledge_citation_ids=["citation-unknown"]),
        _rewrite(introduced_claims=["invented claim"]),
    ],
    ids=[
        "unknown-requirement",
        "unknown-evidence",
        "unknown-clarification",
        "unknown-citation",
        "declared-new-claim",
    ],
)
def test_p06_rejects_dangling_or_declared_rewrite_claims(
    invalid_rewrite: dict[str, object],
) -> None:
    generator, _ = _generator(
        _output(invalid_rewrite),
        _output(_build()),
    )

    with pytest.raises(SemanticPromptError):
        generator.generate(_bundle())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("usage", CitationUsage.INTERVIEW_PREPARATION),
        ("knowledge_version", "2026.09.1"),
        ("role_family", JobFamily.DATA_ANALYTICS),
    ],
)
def test_p06_rejects_build_citation_outside_k3_identity(
    field: str,
    value: object,
) -> None:
    bundle = _bundle()
    citation = bundle.knowledge_citations[0].model_copy(update={field: value})
    bundle = bundle.model_copy(update={"knowledge_citations": [citation]})
    generator, _ = _generator(_output(), _output(_build()))

    with pytest.raises(SemanticPromptError):
        generator.generate(bundle)


def test_p06_action_ids_are_unique_across_isolated_contexts() -> None:
    generator, _ = _generator(
        _output(_rewrite(), _recover()),
        _output(_build(), _build(priority="p1")),
    )

    result = generator.generate(_bundle())

    action_ids = [item.action_id for item in result.actions]
    assert len(action_ids) == len(set(action_ids))
    assert any(action_id.startswith("p06-candidate-") for action_id in action_ids)
    assert any(action_id.startswith("p06-build-") for action_id in action_ids)


def test_p06_enforces_structural_k3_isolation_between_execution_contexts() -> None:
    generator, provider = _generator(_output(_rewrite()), _output(_build()))

    generator.generate(_bundle())

    candidate_payload = provider.calls[0].messages[1].content
    build_payload = provider.calls[1].messages[1].content
    assert "citation-build" not in candidate_payload
    assert "Synthetic role guidance" not in candidate_payload
    assert "citation-build" in build_payload
    assert "Synthetic role guidance" in build_payload


def test_p06_top3_is_deterministic_and_prefers_grounded_actions_on_ties() -> None:
    builds = [_build() for _ in range(4)]
    generator, _ = _generator(
        _output(_recover(), _rewrite()),
        _output(*reversed(builds)),
    )

    first = generator.generate(_bundle())
    second_generator, _ = _generator(
        _output(_rewrite(), _recover()),
        _output(*builds),
    )
    second = second_generator.generate(_bundle())

    assert [item.action_type for item in first.actions] == [
        item.action_type for item in second.actions
    ]
    assert len(first.actions) == 3
    assert [item.action_type for item in first.actions[:2]] == [
        ActionType.REWRITE,
        ActionType.RECOVER,
    ]
    assert first.actions[0].recommended_action == second.actions[0].recommended_action


def test_p06_top3_code_prioritizes_validated_critical_gap_over_model_priority() -> None:
    bundle = _bundle()
    critical = Requirement(
        requirement_id="req-critical",
        jd_snapshot_id="jd-v1",
        raw_requirement_ids=["raw-critical"],
        raw_text="Validate AI application reliability.",
        normalized_capability="AI application reliability validation",
        requirement_type=RequirementType.CORE,
        importance=Importance.CRITICAL,
        explicitness=RequirementExplicitness.EXPLICIT,
        source=RequirementSource.JD,
        critical_status=CriticalStatus.CONFIRMED,
    )
    missing = RequirementMatch(
        match_id="match-critical",
        requirement_id=critical.requirement_id,
        matched_evidence=[],
        coverage=MatchCoverage.NONE,
        evidence_status=EvidenceStatus.MISSING,
        ability_status=AbilityStatus.UNKNOWN,
    )
    core = bundle.analysis_core.model_copy(
        update={"critical_gap_requirement_ids": [critical.requirement_id]}
    )
    bundle = bundle.model_copy(
        update={
            "requirements": [*bundle.requirements, critical],
            "requirement_matches": [*bundle.requirement_matches, missing],
            "analysis_core": core,
        }
    )
    critical_build = _build(
        priority="p2",
        related_requirement_ids=[critical.requirement_id],
    )
    routine_builds = [
        _build(priority="p0", title=f"Routine build {index}")
        for index in range(3)
    ]
    generator, _ = _generator(
        _output(_rewrite()),
        _output(*routine_builds, critical_build),
    )

    result = generator.generate(bundle)

    assert any(
        critical.requirement_id in item.related_requirement_ids
        for item in result.actions
    )


def test_p06_accepts_english_benign_paraphrase_rewrite() -> None:
    generator, _ = _generator(
        _output(
            _rewrite(
                recommended_action=(
                    "Built the Python API and validated the JSON output format."
                )
            )
        ),
        _output(_build()),
    )

    result = generator.generate(_bundle())

    assert [item.action_type for item in result.actions] == [
        ActionType.REWRITE,
        ActionType.BUILD,
    ]


def test_p06_accepts_cross_language_benign_rewrite() -> None:
    generator, _ = _generator(
        _output(_rewrite(recommended_action="构建了 Python API 并验证了 JSON 输出。")),
        _output(_build()),
    )

    result = generator.generate(_bundle())

    assert result.actions[0].action_type is ActionType.REWRITE


def test_p06_rejects_unsupported_quality_escalation_in_rewrite() -> None:
    generator, _ = _generator(
        _output(
            _rewrite(
                recommended_action=(
                    "Built a robust, reliable Python API with validated JSON output."
                )
            )
        ),
        _output(_build()),
    )

    with pytest.raises(SemanticPromptError):
        generator.generate(_bundle())


def test_p06_rejects_unsupported_new_tool_in_rewrite() -> None:
    generator, _ = _generator(
        _output(
            _rewrite(
                recommended_action="Built a Python API with Tableau dashboards."
            )
        ),
        _output(_build()),
    )

    with pytest.raises(SemanticPromptError):
        generator.generate(_bundle())


def test_p06_rewrite_may_reuse_normalized_capability_vocabulary() -> None:
    generator, _ = _generator(
        _output(
            _rewrite(
                recommended_action=(
                    "Built the Python API with Structured Output reporting."
                )
            )
        ),
        _output(_build()),
    )

    result = generator.generate(_bundle())

    assert result.actions[0].action_type is ActionType.REWRITE


def test_p06_action_draft_omits_future_only_from_transport_schema() -> None:
    schema = P06ActionDraft.model_json_schema()
    assert "future_only" not in schema["properties"]
    assert "future_only" not in schema["required"]


def test_p06_strict_transport_omits_future_only() -> None:
    from jobfit.llm.deepseek_strict import build_deepseek_strict_contract

    contract = build_deepseek_strict_contract(
        SemanticLLMTask.P06_ACTIONS,
        P06ActionOutput.model_json_schema(),
    )
    assert "future_only" not in json.dumps(contract.parameters)


def test_p06_assembly_derives_future_only_from_action_type() -> None:
    generator, _ = _scripted_generator(
        _output(_rewrite(), _recover()),
        _output(_build()),
    )

    result = generator.generate(_bundle())

    by_type = {item.action_type: item for item in result.actions}
    assert by_type[ActionType.REWRITE].future_only is False
    assert by_type[ActionType.RECOVER].future_only is False
    assert by_type[ActionType.BUILD].future_only is True
    assert "future_only" in by_type[ActionType.REWRITE].model_dump()


def test_p06_rejects_legacy_model_future_only_extra() -> None:
    from pydantic import ValidationError

    payload = _output(
        {
            **_rewrite(),
            "action_id": "action-rewrite",
            "future_only": False,
        }
    )
    with pytest.raises(ValidationError):
        P06ActionOutput.model_validate(payload)


def test_p06_prompt_omits_model_future_only_instruction() -> None:
    prompt = (PROMPT_ROOT / "p06_actions.md").read_text(encoding="utf-8")
    folded = prompt.casefold()
    # The bool is code-derived; the model must not be told to emit it.
    assert "future_only" not in folded
    # The current-vs-future conceptual distinction remains in prose.
    assert "current" in folded
    assert "future" in folded


def test_p06_targeted_repair_rewrite_traceability_is_evidence_only() -> None:
    generator, provider = _scripted_generator(
        _output(_rewrite(supported_by_evidence_ids=[])),
        _output(_rewrite()),
        _output(_build()),
    )

    result = generator.generate(_bundle())

    repair = json.loads(provider.calls[1].messages[-1].content)
    assert repair["validation_issues"] == [
        {
            "path": "actions[0].supported_by_evidence_ids",
            "category": "REWRITE_TRACEABILITY_MISSING",
        }
    ]
    instruction = repair["instruction"].casefold()
    assert "supported_by_evidence_ids" in instruction
    assert "at least one" in instruction
    assert "future_only" not in instruction
    assert result.executions[0].attempt_count == 2


def test_p06_prompt_exposes_rewrite_recommended_action_contract() -> None:
    prompt = (PROMPT_ROOT / "p06_actions.md").read_text(encoding="utf-8")
    folded = prompt.casefold()
    assert "resume-ready" in folded
    assert "replacement wording" in folded
    assert "not advice" in folded
    assert "meta-instruction" in folded


def test_p06_prompt_distinguishes_rewrite_recover_build_field_semantics() -> None:
    prompt = (PROMPT_ROOT / "p06_actions.md").read_text(encoding="utf-8")
    folded = prompt.casefold()
    # rewrite: resume-ready replacement wording
    assert "resume-ready" in folded
    # recover: action using confirmed non-resume evidence
    assert "confirmed non-resume evidence" in folded
    # build: future evidence-building action
    assert "minimum viable task" in folded


def test_p06_prompt_forbids_filler_and_allows_safe_omission() -> None:
    prompt = (PROMPT_ROOT / "p06_actions.md").read_text(encoding="utf-8")
    folded = prompt.casefold()
    assert "omit" in folded
    assert "fewer" in folded
    assert "speculative" in folded


def test_p06_semantic_repair_rechecks_every_rewrite() -> None:
    generator, provider = _scripted_generator(
        _output(
            _rewrite(
                recommended_action=(
                    "Built a Python API and improved accuracy by 35%."
                )
            )
        ),
        _output(_rewrite()),
        _output(_build()),
    )

    result = generator.generate(_bundle())

    instruction = json.loads(provider.calls[1].messages[-1].content)[
        "instruction"
    ].casefold()
    assert "every" in instruction
    assert "complete" in instruction
    assert "resume-ready" in instruction
    assert "omit" in instruction
    assert result.executions[0].attempt_count == 2


def test_p06_reports_all_strength_paths_in_one_failure() -> None:
    bad0 = _rewrite(
        recommended_action="Built a Python API and improved accuracy by 35%.",
    )
    bad1 = _rewrite(
        recommended_action=(
            "Built a robust Python API with Kubernetes deployment."
        ),
    )
    generator, _ = _scripted_generator(_output(bad0, bad1))

    with pytest.raises(SemanticPromptError) as caught:
        generator.generate(_bundle())

    attempt = caught.value.attempts[0]
    assert attempt.validation_paths == (
        "actions[0].recommended_action",
        "actions[1].recommended_action",
    )
    assert attempt.validation_categories == (
        "SEMANTIC_STRENGTH_INCREASE",
        "SEMANTIC_STRENGTH_INCREASE",
    )


def test_p06_one_targeted_repair_resolves_multiple_strength_actions() -> None:
    bad0 = _rewrite(
        recommended_action="Built a Python API and improved accuracy by 35%.",
    )
    bad1 = _rewrite(
        recommended_action=(
            "Built a robust Python API with Kubernetes deployment."
        ),
    )
    generator, _ = _scripted_generator(
        _output(bad0, bad1),
        _output(_rewrite()),
        _output(_build()),
    )

    result = generator.generate(_bundle())

    assert result.executions[0].attempt_count == 2
    assert [item.action_type for item in result.actions] == [
        ActionType.REWRITE,
        ActionType.BUILD,
    ]


def test_p06_build_mapper_injects_system_fixed_fields() -> None:
    build_output = P06BuildOutput.model_validate(_output(_build()))

    canonical = _map_build_output(build_output)

    action = canonical.actions[0]
    assert action.action_type is ActionType.BUILD
    assert action.related_evidence_ids == []
    assert action.supported_by_evidence_ids == []
    assert action.source_clarification_ids == []
    assert action.introduced_claims == []
    assert action.action_id == "p06-build-001"


def test_p06_mapper_ids_are_deterministic_for_identical_inputs() -> None:
    build_output = P06BuildOutput.model_validate(_output(_build()))
    candidate_output = P06CandidateOutput.model_validate(_output(_rewrite()))

    first_build = _map_build_output(build_output)
    second_build = _map_build_output(build_output)
    first_candidate = _map_candidate_output(candidate_output)
    second_candidate = _map_candidate_output(candidate_output)

    assert first_build == second_build
    assert first_candidate == second_candidate
    assert first_build.actions[0].action_id == "p06-build-001"
    assert first_candidate.actions[0].action_id == "p06-candidate-001"


def test_p06_generator_ids_are_stable_across_identical_runs() -> None:
    first, _ = _generator(_output(_rewrite(), _recover()), _output(_build()))
    second, _ = _generator(_output(_rewrite(), _recover()), _output(_build()))

    first_ids = [item.action_id for item in first.generate(_bundle()).actions]
    second_ids = [item.action_id for item in second.generate(_bundle()).actions]

    assert first_ids == second_ids
    assert first_ids == ["p06-candidate-001", "p06-candidate-002", "p06-build-001"]


def test_p06_mapper_output_passes_existing_canonical_validation() -> None:
    build_output = P06BuildOutput.model_validate(_output(_build()))
    candidate_output = P06CandidateOutput.model_validate(_output(_rewrite()))

    build_canonical = _map_build_output(build_output)
    candidate_canonical = _map_candidate_output(candidate_output)

    for canonical in (build_canonical, candidate_canonical):
        P06ActionOutput.model_validate(canonical.model_dump())
        P06ActionDraft.model_validate(canonical.actions[0].model_dump())


def test_p06_runtime_provider_schema_excludes_system_owned_build_fields() -> None:
    generator, provider = _generator(_output(_rewrite()), _output(_build()))

    generator.generate(_bundle())

    candidate_schema = provider.calls[0].response_schema
    build_schema = provider.calls[1].response_schema
    candidate_item = candidate_schema["$defs"]["P06CandidateActionDraft"]["properties"]
    build_item = build_schema["$defs"]["P06BuildActionDraft"]["properties"]
    assert "action_id" not in candidate_item
    assert "action_id" not in build_item
    for field in (
        "action_type",
        "related_evidence_ids",
        "supported_by_evidence_ids",
        "source_clarification_ids",
        "future_only",
    ):
        assert field not in build_item
    assert "action_type" in candidate_item
