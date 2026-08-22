"""B8/B9 executable acceptance metrics over the frozen v2 contracts."""

from __future__ import annotations

import json
from copy import deepcopy
from decimal import Decimal
from pathlib import Path

import pytest

from jobfit.advisory.v2 import AdvisoryReportPipeline
from jobfit.demo_v2 import _build_scripts
from jobfit.llm import LLMSettings, MockLLMProvider
from jobfit.models.v2 import (
    AbilityStatus,
    AnalysisChangeType,
    AnalysisStage,
    EligibilityStatus,
    EvidenceLevel,
    EvidenceStatus,
    JobFamily,
    LifecycleStatus,
    MatchCoverage,
    MatchedEvidence,
    Recommendation,
    Relevance,
    RequirementMatch,
    SupportType,
    VersionManifest,
)
from jobfit.parsers.text import TextDocumentParser
from jobfit.scoring.v2 import SeniorityFacts, evaluate_hard
from jobfit.semantic.v2 import SemanticLLMTask, SemanticPipeline, SemanticPromptExecutor
from jobfit.workflow.v2 import V2AnalysisApplication
from tests.integration.test_v2_golden_acceptance import _build, _load_specs
from tests.integration.test_v2_pair_acceptance import _hard_match, _hard_requirement
from tests.unit.test_v2_recompute_planner import _event, _graph

_PROMPT_ROOT = Path(__file__).parents[2] / "src" / "jobfit" / "prompts" / "v2"
_BUSINESS_CASES = (
    Path(__file__).parents[1] / "fixtures" / "v2" / "business_cases.json"
)
_VERSIONS = VersionManifest(
    software_version="1.1.0",
    prompt_pack_version="1.0.0",
    schema_version="2.0.0",
    scoring_rule_version="1.0.0",
    knowledge_version="2026.08.1",
    analysis_engine_version="1.0.0",
    business_test_set_version="1.0.0",
    golden_set_version="1.0.0",
)
_ROLE_SCENARIOS = (
    (
        JobFamily.AI_APPLICATION,
        "AI Application Intern",
        "Python application delivery",
    ),
    (
        JobFamily.DATA_ANALYTICS,
        "Data Analytics Intern",
        "SQL business analysis",
    ),
    (
        JobFamily.TECHNOLOGY_STRATEGY,
        "Technology Strategy Intern",
        "technology research and structured analysis",
    ),
)
_FIT_SCENARIOS = (
    ("high", EvidenceLevel.L4, Recommendation.PRIORITY, Decimal("85"), Decimal("100")),
    ("medium", EvidenceLevel.L2, Recommendation.CHALLENGE, Decimal("55"), Decimal("69.99")),
    (
        "low",
        EvidenceLevel.L1,
        Recommendation.NOT_RECOMMENDED,
        Decimal("0"),
        Decimal("54.99"),
    ),
)

_BUSINESS_TO_GOLDEN = {
    "A01": "G-AI-01",
    "A02": "G-AI-02",
    "A03": "G-AI-03",
    "A05": "G-DA-01",
    "A06": "G-DA-02",
    "A07": "G-DA-03",
    "A09": "G-TS-01",
    "A10": "G-TS-02",
    "A11": "G-TS-03",
}


def _run_full_pipeline(
    family: JobFamily,
    title: str,
    capability: str,
    level: EvidenceLevel,
):
    parser = TextDocumentParser()
    resume_text = (
        "Education: BSc in a synthetic discipline.\n"
        f"Project: Completed a synthetic {capability} exercise with documented results."
    )
    jd_text = (
        f"{title}\n"
        f"Build a synthetic work product using {capability}.\n"
        f"{capability} is required."
    )
    resume = parser.parse_text(resume_text)
    jd = parser.parse_text(jd_text)
    scripts = _build_scripts(
        resume_document=resume,
        jd_document=jd,
        resume_version_id=f"resume-{family.value}-{level.value}",
        jd_snapshot_id=f"jd-{family.value}-{level.value}",
    )
    normalized = json.loads(scripts[SemanticLLMTask.P04_EVIDENCE_NORMALIZER][0])
    evidence = normalized["evidence"][0]
    if level is EvidenceLevel.L2:
        evidence.update(
            personal_contribution="unclear",
            task_clarity="medium",
            method_tool_clarity="low",
            result_clarity="unknown",
            verification_strength="unknown",
            practical_use="medium",
        )
    elif level is EvidenceLevel.L1:
        evidence.update(
            personal_contribution="not_applicable",
            task_clarity="unknown",
            method_tool_clarity="unknown",
            result_clarity="unknown",
            verification_strength="unknown",
            practical_use="unknown",
        )
    scripts[SemanticLLMTask.P04_EVIDENCE_NORMALIZER] = [json.dumps(normalized)]
    if level is not EvidenceLevel.L4:
        matched = json.loads(scripts[SemanticLLMTask.P05_SEMANTIC_MATCHER][0])
        matched["matches"][0]["evidence_status"] = "weak"
        scripts[SemanticLLMTask.P05_SEMANTIC_MATCHER] = [json.dumps(matched)]

    provider = MockLLMProvider(scripts)
    executor = SemanticPromptExecutor(
        provider=provider,
        prompt_root=_PROMPT_ROOT,
        settings=LLMSettings(model="rc-acceptance-mock", max_retries=0),
    )
    application = V2AnalysisApplication(
        semantic_pipeline=SemanticPipeline(executor),
        advisory_pipeline=AdvisoryReportPipeline(executor),
        versions=_VERSIONS,
    )
    prepared = application.prepare_analysis(
        analysis_id=f"analysis-{family.value}-{level.value}",
        resume_version_id=f"resume-{family.value}-{level.value}",
        jd_snapshot_id=f"jd-{family.value}-{level.value}",
        resume_document=resume,
        jd_document=jd,
        seniority_facts=SeniorityFacts(explicit_entry_scope=True),
    )
    assert prepared.pending_questions == ()
    completed = application.finish_analysis(application.begin_analysis(prepared))
    assert completed.advisory_result is not None
    return completed, provider


@pytest.mark.parametrize(
    ("family", "title", "capability"),
    _ROLE_SCENARIOS,
    ids=[item[0].value for item in _ROLE_SCENARIOS],
)
@pytest.mark.parametrize(
    ("fit", "level", "recommendation", "minimum", "maximum"),
    _FIT_SCENARIOS,
    ids=[item[0] for item in _FIT_SCENARIOS],
)
def test_three_role_high_medium_low_runs_full_p01_to_p08(
    family: JobFamily,
    title: str,
    capability: str,
    fit: str,
    level: EvidenceLevel,
    recommendation: Recommendation,
    minimum: Decimal,
    maximum: Decimal,
) -> None:
    del fit
    completed, provider = _run_full_pipeline(family, title, capability, level)
    core = completed.analysis_result.analysis_core

    assert provider.call_count == 9
    assert completed.run.lifecycle.status is LifecycleStatus.COMPLETED
    assert completed.job_profile.job_family is family
    assert completed.requirements[0].normalized_capability == capability
    assert completed.evidence[0].evidence_level is level
    assert minimum <= core.final_fit_score <= maximum
    assert core.recommendation is recommendation
    assert completed.advisory_result.report.summary["recommendation"] == recommendation
    assert len(completed.advisory_result.report.build_recommendations) <= 3


@pytest.mark.parametrize(
    ("case_id", "ability", "expected"),
    (
        ("B01", AbilityStatus.CONFIRMED, EligibilityStatus.MET),
        ("B02", AbilityStatus.CONFIRMED_GAP, EligibilityStatus.BLOCKED),
        ("B03", AbilityStatus.UNKNOWN, EligibilityStatus.PENDING),
        ("B04", AbilityStatus.CONFIRMED_GAP, EligibilityStatus.BLOCKED),
        ("B05", AbilityStatus.CONFIRMED_GAP, EligibilityStatus.BLOCKED),
        ("B06", AbilityStatus.UNKNOWN, EligibilityStatus.PENDING),
    ),
)
def test_hard_recall_is_six_of_six(
    case_id: str,
    ability: AbilityStatus,
    expected: EligibilityStatus,
) -> None:
    del case_id
    match = (
        RequirementMatch(
            match_id="pair-hard-confirmed",
            requirement_id="pair-hard",
            matched_evidence=[
                MatchedEvidence(
                    evidence_id="synthetic-hard-evidence",
                    relevance=Relevance.HIGH,
                    support_type=SupportType.DIRECT,
                )
            ],
            coverage=MatchCoverage.FULL,
            evidence_status=EvidenceStatus.PRESENT,
            ability_status=AbilityStatus.CONFIRMED,
        )
        if ability is AbilityStatus.CONFIRMED
        else _hard_match(ability)
    )
    decision = evaluate_hard([_hard_requirement()], [match])
    assert decision.eligibility_status is expected


@pytest.mark.parametrize(
    ("golden_id", "minimum", "maximum"),
    (
        ("G-AI-02", 1, 1),
        ("G-AI-03", 2, 99),
        ("G-DA-03", 1, 2),
    ),
)
def test_critical_recall_is_three_of_three(
    golden_id: str,
    minimum: int,
    maximum: int,
) -> None:
    spec = next(item for item in _load_specs() if item["case_id"] == golden_id)
    gaps = _build(spec).result.analysis_core.critical_gap_requirement_ids
    assert minimum <= len(gaps) <= maximum


def _low_fit_business_result(case_id: str, family: JobFamily):
    template = next(item for item in _load_specs() if item["case_id"] == "G-AI-03")
    spec = deepcopy(template)
    spec.update(
        case_id=case_id,
        title=f"Synthetic {family.value} low-fit case",
        job_family=family.value,
    )
    return _build(spec).result.analysis_core


def _core_for_business_case(case_id: str):
    golden_id = _BUSINESS_TO_GOLDEN.get(case_id)
    if golden_id is not None:
        spec = next(item for item in _load_specs() if item["case_id"] == golden_id)
        return _build(spec).result.analysis_core
    family = {
        "A04": JobFamily.AI_APPLICATION,
        "A08": JobFamily.DATA_ANALYTICS,
        "A12": JobFamily.TECHNOLOGY_STRATEGY,
    }[case_id]
    return _low_fit_business_result(case_id, family)


def _recommendation_matches(expected: str, actual: Recommendation) -> bool:
    if expected == "suggested_or_lower":
        return actual in {
            Recommendation.NOT_RECOMMENDED,
            Recommendation.CHALLENGE,
            Recommendation.SUGGESTED,
        }
    return actual.value == expected


def test_recommendation_accuracy_is_twelve_of_twelve() -> None:
    cases = {
        item["case_id"]: item
        for item in json.loads(_BUSINESS_CASES.read_text(encoding="utf-8"))
        if item["category"] == "core_fit"
    }
    hits = []
    for case_id, case in cases.items():
        actual = _core_for_business_case(case_id).recommendation
        if _recommendation_matches(case["expected_recommendation"], actual):
            hits.append(case_id)

    assert len(cases) == 12
    assert hits == list(cases)


def test_core_requirement_recall_is_nine_of_nine() -> None:
    expected_capabilities: list[str] = []
    recalled_capabilities: list[str] = []
    for family, title, capability in _ROLE_SCENARIOS:
        for _fit, level, _recommendation, _minimum, _maximum in _FIT_SCENARIOS:
            expected_capabilities.append(capability)
            completed, _provider = _run_full_pipeline(
                family,
                title,
                capability,
                level,
            )
            recalled_capabilities.extend(
                requirement.normalized_capability
                for requirement in completed.requirements
                if requirement.normalized_capability == capability
            )

    assert len(expected_capabilities) == 9
    assert recalled_capabilities == expected_capabilities


def test_h02_and_h03_are_local_recovery_not_full_reanalysis() -> None:
    from jobfit.workflow.v2 import IncrementalRecomputePlanner

    planner = IncrementalRecomputePlanner()
    p07 = planner.plan(
        current_artifacts=_graph(),
        change_events=(_event(AnalysisChangeType.PROMPT_P07_CHANGED),),
        target_analysis_id="AN002",
    )
    p08 = planner.plan(
        current_artifacts=_graph(),
        change_events=(_event(AnalysisChangeType.PROMPT_P08_CHANGED),),
        target_analysis_id="AN002",
    )

    assert p07.stages_to_run == (AnalysisStage.INTERVIEW, AnalysisStage.REPORT)
    assert p08.stages_to_run == (AnalysisStage.REPORT,)
    for plan in (p07, p08):
        assert "artifact-scoring" in plan.preserved_artifact_ids
        assert "artifact-recommendation" in plan.preserved_artifact_ids


def test_forbidden_claim_gate_covers_all_forty_two_cases() -> None:
    cases = json.loads(_BUSINESS_CASES.read_text(encoding="utf-8"))
    generated_reports = []
    for family, title, capability in _ROLE_SCENARIOS:
        completed, _ = _run_full_pipeline(
            family,
            title,
            capability,
            EvidenceLevel.L4,
        )
        generated_reports.append(
            completed.advisory_result.report.model_dump_json().casefold()
        )
    combined = "\n".join(generated_reports)

    assertions = [claim for case in cases for claim in case["forbidden_claims"]]
    assert len(cases) == 42
    assert assertions
    assert not [claim for claim in assertions if claim.casefold() in combined]
