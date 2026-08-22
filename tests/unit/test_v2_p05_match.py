"""P05 semantic-relation matching and decision-boundary tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jobfit.llm import LLMSettings, MockLLMProvider
from jobfit.models import Importance
from jobfit.models.v2 import (
    AbilityStatus,
    ClarityLevel,
    CriticalStatus,
    Evidence,
    EvidenceLevel,
    EvidenceSourceOrigin,
    EvidenceStatus,
    JobFamily,
    JobProfile,
    KnowledgeCoverage,
    MatchCoverage,
    PersonalContribution,
    Requirement,
    RequirementExplicitness,
    RequirementSource,
    RequirementType,
)
from jobfit.semantic.v2.contracts import (
    PromptExecutionRecord,
    PromptValidationRecord,
)
from jobfit.semantic.v2.executor import (
    SemanticLLMTask,
    SemanticPromptError,
    SemanticPromptExecutor,
)
from jobfit.semantic.v2.p03_requirements import P03RequirementResult
from jobfit.semantic.v2.p04_evidence import P04EvidenceResult
from jobfit.semantic.v2.p05_match import P05SemanticMatcher

PROMPT_ROOT = Path(__file__).parents[2] / "src" / "jobfit" / "prompts" / "v2"


def _execution(prompt_id: str) -> PromptExecutionRecord:
    return PromptExecutionRecord(
        prompt_id=prompt_id,
        prompt_version="1.0.0",
        global_rules_version="1.0.0",
        prompt_pack_version="1.0.0-candidate",
        attempt_count=1,
        attempts=(),
        input_object_ids=("analysis-1",),
        output_object_ids=(),
        validation=PromptValidationRecord(
            syntax_valid=True,
            schema_valid=True,
            business_valid=True,
            cross_object_valid=True,
        ),
        provider="mock",
        model="semantic-mock",
    )


def _requirement_result(analysis_id: str = "analysis-1") -> P03RequirementResult:
    requirement = Requirement(
        requirement_id="requirement-1",
        jd_snapshot_id="jd-snapshot-1",
        raw_requirement_ids=["raw-requirement-1"],
        raw_text="Python is required.",
        normalized_capability="Python application development",
        requirement_type=RequirementType.CORE,
        importance=Importance.HIGH,
        explicitness=RequirementExplicitness.EXPLICIT,
        source=RequirementSource.JD,
        critical_status=CriticalStatus.NOT_CRITICAL,
        classification_reason="Explicit core implementation capability.",
    )
    profile = JobProfile(
        jd_snapshot_id="jd-snapshot-1",
        job_title="AI Application Intern",
        job_family=JobFamily.AI_APPLICATION,
        knowledge_coverage=KnowledgeCoverage.BASE_ONLY,
        raw_requirement_ids=["raw-requirement-1"],
        requirement_ids=["requirement-1"],
    )
    return P03RequirementResult(
        analysis_id=analysis_id,
        job_profile=profile,
        requirements=(requirement,),
        warnings=(),
        execution=_execution("P03"),
    )


def _evidence_result(analysis_id: str = "analysis-1") -> P04EvidenceResult:
    evidence = Evidence(
        evidence_id="evidence-1",
        resume_version_id="resume-version-1",
        source_origin=EvidenceSourceOrigin.RESUME,
        source_type="project",
        source_text="Built and tested an API.",
        normalized_capabilities=["API integration", "Python"],
        personal_contribution=PersonalContribution.CLEAR,
        task_clarity=ClarityLevel.HIGH,
        method_tool_clarity=ClarityLevel.HIGH,
        result_clarity=ClarityLevel.HIGH,
        verification_strength=ClarityLevel.MEDIUM,
        practical_use=ClarityLevel.HIGH,
        evidence_level=EvidenceLevel.L4,
        document_id="doc-resume-1",
        segment_id="segment-resume-1",
        start_char=0,
        end_char=24,
    )
    return P04EvidenceResult(
        analysis_id=analysis_id,
        resume_version_id="resume-version-1",
        evidence=(evidence,),
        warnings=(),
        execution=_execution("P04"),
    )


def _valid_output(**updates: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "matches": [
            {
                "requirement_id": "requirement-1",
                "matched_evidence": [
                    {
                        "evidence_id": "evidence-1",
                        "relevance": "high",
                        "support_type": "direct",
                    }
                ],
                "coverage": "full",
                "evidence_status": "present",
                "ability_status": "confirmed",
                "reason": "The project directly demonstrates implementation.",
            }
        ],
        "warnings": [],
    }
    payload.update(updates)
    return payload


def _matcher(*outputs: dict[str, object]) -> tuple[P05SemanticMatcher, MockLLMProvider]:
    provider = MockLLMProvider(
        {SemanticLLMTask.P05_SEMANTIC_MATCHER: [json.dumps(item) for item in outputs]}
    )
    executor = SemanticPromptExecutor(
        provider=provider,
        prompt_root=PROMPT_ROOT,
        settings=LLMSettings(model="semantic-mock", max_retries=0),
    )
    return P05SemanticMatcher(executor), provider


def test_p05_builds_relation_only_requirement_match() -> None:
    matcher, _ = _matcher(_valid_output())

    result = matcher.match(_requirement_result(), _evidence_result())

    assert len(result.matches) == 1
    match = result.matches[0]
    assert match.requirement_id == "requirement-1"
    assert match.coverage is MatchCoverage.FULL
    assert match.evidence_status is EvidenceStatus.PRESENT
    assert match.ability_status is AbilityStatus.CONFIRMED
    assert match.best_evidence_level is None
    assert match.match_score_component is None


def test_p05_missing_evidence_must_keep_ability_unknown() -> None:
    missing = _valid_output(
        matches=[
            {
                "requirement_id": "requirement-1",
                "matched_evidence": [],
                "coverage": "none",
                "evidence_status": "missing",
                "ability_status": "unknown",
                "reason": "No candidate evidence was found.",
            }
        ]
    )
    matcher, _ = _matcher(missing)

    result = matcher.match(_requirement_result(), _evidence_result())

    assert result.matches[0].evidence_status is EvidenceStatus.MISSING
    assert result.matches[0].ability_status is AbilityStatus.UNKNOWN
    assert result.matches[0].matched_evidence == []


def test_p05_cannot_create_confirmed_gap_from_missing_evidence() -> None:
    gap = _valid_output(
        matches=[
            {
                "requirement_id": "requirement-1",
                "matched_evidence": [],
                "coverage": "none",
                "evidence_status": "missing",
                "ability_status": "confirmed_gap",
                "reason": "Unsupported gap claim.",
            }
        ]
    )
    matcher, provider = _matcher(gap)

    with pytest.raises(SemanticPromptError, match="P05"):
        matcher.match(_requirement_result(), _evidence_result())

    assert provider.call_count == 3


def test_p05_rejects_numeric_decisions_and_recommendations() -> None:
    unauthorized = _valid_output()
    unauthorized["matches"][0]["match_score_component"] = "1.0000"
    unauthorized["matches"][0]["recommendation"] = "priority"
    matcher, provider = _matcher(unauthorized)

    with pytest.raises(SemanticPromptError, match="P05"):
        matcher.match(_requirement_result(), _evidence_result())

    assert provider.call_count == 3


def test_p05_rejects_dangling_evidence_reference() -> None:
    dangling = _valid_output()
    dangling["matches"][0]["matched_evidence"][0]["evidence_id"] = "evidence-other"
    matcher, provider = _matcher(dangling)

    with pytest.raises(SemanticPromptError, match="P05"):
        matcher.match(_requirement_result(), _evidence_result())

    assert provider.call_count == 3


def test_p05_rejects_cross_analysis_inputs_before_model_call() -> None:
    matcher, provider = _matcher(_valid_output())

    with pytest.raises(SemanticPromptError, match="P05"):
        matcher.match(_requirement_result("analysis-job"), _evidence_result("analysis-resume"))

    assert provider.call_count == 0


def test_p05_preserves_transferable_relation_without_numeric_stacking() -> None:
    transferable = _valid_output()
    transferable["matches"][0]["matched_evidence"][0].update(
        {"relevance": "medium", "support_type": "transferable"}
    )
    transferable["matches"][0]["coverage"] = "partial"
    matcher, _ = _matcher(transferable)

    match = matcher.match(_requirement_result(), _evidence_result()).matches[0]

    assert match.matched_evidence[0].support_type.value == "transferable"
    assert match.match_score_component is None


def _requirement_result_two() -> P03RequirementResult:
    base = _requirement_result()
    second = Requirement(
        requirement_id="requirement-2",
        jd_snapshot_id="jd-snapshot-1",
        raw_requirement_ids=["raw-requirement-2"],
        raw_text="SQL is required.",
        normalized_capability="SQL application development",
        requirement_type=RequirementType.SUPPORTING,
        importance=Importance.MEDIUM,
        explicitness=RequirementExplicitness.EXPLICIT,
        source=RequirementSource.JD,
        critical_status=CriticalStatus.NOT_CRITICAL,
        classification_reason="Explicit supporting capability.",
    )
    return P03RequirementResult(
        analysis_id=base.analysis_id,
        job_profile=base.job_profile.model_copy(
            update={
                "raw_requirement_ids": ["raw-requirement-1", "raw-requirement-2"],
                "requirement_ids": ["requirement-1", "requirement-2"],
            }
        ),
        requirements=(base.requirements[0], second),
        warnings=(),
        execution=base.execution,
    )


def _match_draft(
    requirement_id: str,
    *,
    matched_evidence: list[dict[str, str]] | None = None,
    coverage: str = "full",
    evidence_status: str = "present",
    ability_status: str = "confirmed",
) -> dict[str, object]:
    if matched_evidence is None:
        matched_evidence = [
            {"evidence_id": "evidence-1", "relevance": "high", "support_type": "direct"}
        ]
    return {
        "requirement_id": requirement_id,
        "matched_evidence": matched_evidence,
        "coverage": coverage,
        "evidence_status": evidence_status,
        "ability_status": ability_status,
        "reason": "Synthetic relation description.",
    }


def _valid_two() -> dict[str, object]:
    return {
        "matches": [_match_draft("requirement-1"), _match_draft("requirement-2")],
        "warnings": [],
    }


def test_p05_prompt_declares_legal_state_machine() -> None:
    prompt = (PROMPT_ROOT / "p05_semantic_matcher.md").read_text(encoding="utf-8")
    folded = prompt.casefold()

    assert "exactly one requirementmatch" in folded
    assert "matched_evidence must be empty" in folded
    assert "coverage must be none" in folded
    assert "ability_status must be unknown" in folded
    assert "confirmed_gap" in folded
    assert "at least one" in folded


def test_p05_missing_state_targeted_repair_reaches_valid_closure() -> None:
    invalid = _valid_output(
        matches=[
            _match_draft(
                "requirement-1",
                coverage="full",
                evidence_status="missing",
                ability_status="confirmed",
            )
        ]
    )
    valid = _valid_output(
        matches=[
            _match_draft(
                "requirement-1",
                matched_evidence=[],
                coverage="none",
                evidence_status="missing",
                ability_status="unknown",
            )
        ]
    )
    matcher, provider = _matcher(invalid, valid)

    result = matcher.match(_requirement_result(), _evidence_result())

    assert result.execution.attempt_count == 2
    assert [attempt.stage for attempt in result.execution.attempts] == [
        "normal",
        "targeted_repair",
    ]
    instruction = json.loads(provider.calls[1].messages[-1].content)[
        "instruction"
    ].casefold()
    assert "matched_evidence" in instruction
    assert "ability_status" in instruction
    assert result.matches[0].evidence_status is EvidenceStatus.MISSING
    assert result.matches[0].matched_evidence == []


def test_p05_present_without_evidence_targeted_repair_reaches_valid_closure() -> None:
    invalid = _valid_output(
        matches=[
            _match_draft(
                "requirement-1",
                matched_evidence=[],
                coverage="partial",
                evidence_status="present",
                ability_status="unknown",
            )
        ]
    )
    matcher, provider = _matcher(invalid, _valid_output())

    result = matcher.match(_requirement_result(), _evidence_result())

    assert result.execution.attempt_count == 2
    assert [attempt.stage for attempt in result.execution.attempts] == [
        "normal",
        "targeted_repair",
    ]
    assert result.matches[0].matched_evidence
    assert "at least one" in json.loads(
        provider.calls[1].messages[-1].content
    )["instruction"].casefold()


def test_p05_exact_coverage_targeted_repair_recovers_missing_match() -> None:
    incomplete = _valid_output()  # only requirement-1
    matcher, provider = _matcher(incomplete, _valid_two())

    result = matcher.match(_requirement_result_two(), _evidence_result())

    assert result.execution.attempt_count == 2
    assert [attempt.stage for attempt in result.execution.attempts] == [
        "normal",
        "targeted_repair",
    ]
    assert [item.requirement_id for item in result.matches] == [
        "requirement-1",
        "requirement-2",
    ]
    assert "exactly" in json.loads(
        provider.calls[1].messages[-1].content
    )["instruction"].casefold()


def test_p05_duplicate_match_targeted_repair_recovers_exact_coverage() -> None:
    duplicated = _valid_output(
        matches=[_match_draft("requirement-1"), _match_draft("requirement-1")]
    )
    matcher, provider = _matcher(duplicated, _valid_two())

    result = matcher.match(_requirement_result_two(), _evidence_result())

    assert result.execution.attempt_count == 2
    assert [attempt.stage for attempt in result.execution.attempts] == [
        "normal",
        "targeted_repair",
    ]
    assert len(result.matches) == 2
    assert len({item.requirement_id for item in result.matches}) == 2
