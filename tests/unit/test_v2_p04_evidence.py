"""P04 evidence-feature normalization and deterministic level tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jobfit.llm import LLMSettings, MockLLMProvider
from jobfit.models.v2 import (
    CandidateProfile,
    CandidateStatus,
    EvidenceLevel,
    ParseCompleteness,
    ResumeProfile,
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
from jobfit.semantic.v2.p01_resume import P01ResumeResult
from jobfit.semantic.v2.p04_evidence import P04EvidenceNormalizer
from jobfit.semantic.v2.stage_contracts import CandidateEvidence

PROMPT_ROOT = Path(__file__).parents[2] / "src" / "jobfit" / "prompts" / "v2"


def _execution() -> PromptExecutionRecord:
    return PromptExecutionRecord(
        prompt_id="P01",
        prompt_version="1.0.0",
        global_rules_version="1.0.0",
        prompt_pack_version="1.0.0-candidate",
        attempt_count=1,
        attempts=(),
        input_object_ids=("analysis-1",),
        output_object_ids=("evidence-1",),
        validation=PromptValidationRecord(
            syntax_valid=True,
            schema_valid=True,
            business_valid=True,
            cross_object_valid=True,
        ),
        provider="mock",
        model="semantic-mock",
    )


def _p01_result(source_type: str = "project") -> P01ResumeResult:
    evidence = CandidateEvidence(
        evidence_id="evidence-1",
        resume_version_id="resume-version-1",
        source_type=source_type,
        quote="Built and tested an API.",
        document_id="doc-resume-1",
        segment_id="segment-resume-1",
        start_char=0,
        end_char=24,
    )
    profile = ResumeProfile(
        resume_version_id="resume-version-1",
        candidate_profile=CandidateProfile(
            current_status=CandidateStatus.STUDENT,
            years_of_full_time_experience=0,
        ),
        education=[{"label": "Synthetic degree"}],
        projects=[{"label": "Synthetic project", "evidence_ids": ["evidence-1"]}],
        evidence_ids=["evidence-1"],
        parse_completeness=ParseCompleteness.COMPLETE,
    )
    return P01ResumeResult(
        analysis_id="analysis-1",
        profile=profile,
        candidate_evidence=(evidence,),
        ambiguities=(),
        execution=_execution(),
    )


def _valid_output(**updates: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "evidence": [
            {
                "evidence_id": "evidence-1",
                "normalized_capabilities": ["API integration"],
                "personal_contribution": "clear",
                "task_clarity": "high",
                "method_tool_clarity": "high",
                "result_clarity": "high",
                "verification_strength": "medium",
                "practical_use": "high",
                "ambiguity": False,
            }
        ],
        "warnings": [],
    }
    payload.update(updates)
    return payload


def _normalizer(
    *outputs: dict[str, object],
) -> tuple[P04EvidenceNormalizer, MockLLMProvider]:
    provider = MockLLMProvider(
        {
            SemanticLLMTask.P04_EVIDENCE_NORMALIZER: [
                json.dumps(item) for item in outputs
            ]
        }
    )
    executor = SemanticPromptExecutor(
        provider=provider,
        prompt_root=PROMPT_ROOT,
        settings=LLMSettings(model="semantic-mock", max_retries=0),
    )
    return P04EvidenceNormalizer(executor), provider


def test_p04_normalizes_features_then_code_assigns_frozen_evidence_level() -> None:
    normalizer, _ = _normalizer(_valid_output())

    result = normalizer.normalize(_p01_result())

    assert len(result.evidence) == 1
    evidence = result.evidence[0]
    assert evidence.evidence_id == "evidence-1"
    assert evidence.source_text == "Built and tested an API."
    assert evidence.normalized_capabilities == ["API integration"]
    assert evidence.evidence_level is EvidenceLevel.L4


def test_p04_model_cannot_submit_evidence_level() -> None:
    unauthorized = _valid_output()
    unauthorized["evidence"][0]["evidence_level"] = "L4"
    normalizer, provider = _normalizer(unauthorized)

    with pytest.raises(SemanticPromptError, match="P04"):
        normalizer.normalize(_p01_result())

    assert provider.call_count == 3


def test_p04_cannot_replace_source_quote_or_grounding() -> None:
    unauthorized = _valid_output()
    unauthorized["evidence"][0]["source_text"] = "Fabricated stronger result."
    normalizer, provider = _normalizer(unauthorized)

    with pytest.raises(SemanticPromptError, match="P04"):
        normalizer.normalize(_p01_result())

    assert provider.call_count == 3


def test_p04_requires_each_p01_evidence_exactly_once() -> None:
    duplicated = _valid_output()
    duplicated["evidence"].append(dict(duplicated["evidence"][0]))
    normalizer, provider = _normalizer(duplicated)

    with pytest.raises(SemanticPromptError, match="P04"):
        normalizer.normalize(_p01_result())

    assert provider.call_count == 3


def test_p04_skills_only_claim_remains_low_level_without_use_signals() -> None:
    weak = _valid_output()
    weak["evidence"][0].update(
        {
            "normalized_capabilities": ["Python"],
            "personal_contribution": "not_applicable",
            "task_clarity": "unknown",
            "method_tool_clarity": "unknown",
            "result_clarity": "unknown",
            "verification_strength": "unknown",
            "practical_use": "unknown",
        }
    )
    normalizer, _ = _normalizer(weak)

    result = normalizer.normalize(_p01_result(source_type="skill"))

    assert result.evidence[0].evidence_level is EvidenceLevel.L1


def test_p04_unclear_team_ownership_is_capped_and_keeps_ambiguity() -> None:
    ambiguous = _valid_output()
    ambiguous["evidence"][0].update(
        {
            "personal_contribution": "unclear",
            "ambiguity": True,
        }
    )
    normalizer, _ = _normalizer(ambiguous)

    evidence = normalizer.normalize(_p01_result()).evidence[0]

    assert evidence.ambiguity is True
    assert evidence.evidence_level is EvidenceLevel.L2


def _p01_three() -> P01ResumeResult:
    quotes = {
        "evidence-1": "Built and tested an API.",
        "evidence-2": "Wrote SQL queries for reporting.",
        "evidence-3": "Documented deployment steps.",
    }
    evidence = tuple(
        CandidateEvidence(
            evidence_id=evidence_id,
            resume_version_id="resume-version-1",
            source_type="project",
            quote=quote,
            document_id="doc-resume-1",
            segment_id="segment-resume-1",
            start_char=0,
            end_char=len(quote),
        )
        for evidence_id, quote in quotes.items()
    )
    profile = ResumeProfile(
        resume_version_id="resume-version-1",
        candidate_profile=CandidateProfile(
            current_status=CandidateStatus.STUDENT,
            years_of_full_time_experience=0,
        ),
        education=[{"label": "Synthetic degree"}],
        projects=[{"label": "Synthetic project", "evidence_ids": list(quotes)}],
        evidence_ids=list(quotes),
        parse_completeness=ParseCompleteness.COMPLETE,
    )
    return P01ResumeResult(
        analysis_id="analysis-1",
        profile=profile,
        candidate_evidence=evidence,
        ambiguities=(),
        execution=_execution(),
    )


def _feature(evidence_id: str) -> dict[str, object]:
    return {
        "evidence_id": evidence_id,
        "normalized_capabilities": ["API integration"],
        "personal_contribution": "clear",
        "task_clarity": "high",
        "method_tool_clarity": "high",
        "result_clarity": "high",
        "verification_strength": "medium",
        "practical_use": "high",
        "ambiguity": False,
    }


def test_p04_provider_order_freedom_is_reordered_to_p01_input_order() -> None:
    shuffled = _valid_output(
        evidence=[
            _feature("evidence-3"),
            _feature("evidence-1"),
            _feature("evidence-2"),
        ]
    )
    normalizer, _ = _normalizer(shuffled)

    result = normalizer.normalize(_p01_three())

    assert [item.evidence_id for item in result.evidence] == [
        "evidence-1",
        "evidence-2",
        "evidence-3",
    ]
    assert result.evidence[0].source_text == "Built and tested an API."


def test_p04_missing_evidence_id_still_fails_coverage() -> None:
    incomplete = _valid_output(
        evidence=[_feature("evidence-1"), _feature("evidence-3")]
    )
    normalizer, provider = _normalizer(incomplete)

    with pytest.raises(SemanticPromptError, match="P04"):
        normalizer.normalize(_p01_three())

    assert provider.call_count == 3


def test_p04_duplicate_evidence_id_still_fails_coverage() -> None:
    duplicated = _valid_output(
        evidence=[
            _feature("evidence-1"),
            _feature("evidence-1"),
            _feature("evidence-2"),
            _feature("evidence-3"),
        ]
    )
    normalizer, provider = _normalizer(duplicated)

    with pytest.raises(SemanticPromptError, match="P04"):
        normalizer.normalize(_p01_three())

    assert provider.call_count == 3


def test_p04_unknown_evidence_id_still_fails_coverage() -> None:
    invented = _valid_output(
        evidence=[
            _feature("evidence-1"),
            _feature("evidence-2"),
            _feature("evidence-99"),
        ]
    )
    normalizer, provider = _normalizer(invented)

    with pytest.raises(SemanticPromptError, match="P04"):
        normalizer.normalize(_p01_three())

    assert provider.call_count == 3


def test_p04_prompt_requires_exact_coverage_without_order_contract() -> None:
    prompt = (PROMPT_ROOT / "p04_evidence_normalizer.md").read_text(encoding="utf-8")
    folded = prompt.casefold()

    assert "exactly once" in folded
    assert "omit" in folded
    assert "duplicate" in folded
    assert "invent" in folded
    assert "order" not in folded
