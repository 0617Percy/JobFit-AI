"""P03 candidate-blind explicit requirement classification tests."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from jobfit.llm import LLMSettings, MockLLMProvider
from jobfit.models.v2 import (
    CriticalStatus,
    JobFamily,
    KnowledgeCoverage,
    ParseCompleteness,
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
from jobfit.semantic.v2.p02_job import P02JobResult
from jobfit.semantic.v2.p03_requirements import P03RequirementClassifier
from jobfit.semantic.v2.stage_contracts import JDSourceItem

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


def _p02_result() -> P02JobResult:
    return P02JobResult(
        analysis_id="analysis-1",
        jd_snapshot_id="jd-snapshot-1",
        job_title="AI Application Intern",
        company=None,
        location=None,
        employment_type="internship",
        job_family=JobFamily.AI_APPLICATION,
        responsibilities=(
            JDSourceItem(
                object_id="responsibility-1",
                text="Build reliable model API workflows.",
                document_id="doc-jd-1",
                segment_id="segment-jd-1",
                start_char=22,
                end_char=57,
            ),
        ),
        raw_requirements=(
            JDSourceItem(
                object_id="raw-requirement-1",
                text="Python is required.",
                document_id="doc-jd-1",
                segment_id="segment-jd-1",
                start_char=58,
                end_char=77,
            ),
        ),
        explicit_constraints=(),
        seniority_signals=(),
        ambiguities=(),
        parse_completeness=ParseCompleteness.COMPLETE,
        role_scope_valid=True,
        execution=_execution("P02"),
    )


def _p02_two_raws() -> P02JobResult:
    second = JDSourceItem(
        object_id="raw-requirement-2",
        text="SQL experience is expected.",
        document_id="doc-jd-1",
        segment_id="segment-jd-1",
        start_char=78,
        end_char=103,
    )
    base = _p02_result()
    return replace(base, raw_requirements=(*base.raw_requirements, second))


def _valid_output(**updates: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "requirements": [
            {
                "local_id": "classified-1",
                "raw_requirement_ids": ["raw-requirement-1"],
                "normalized_capability": "Python application development",
                "requirement_type": "core",
                "importance": "high",
                "critical_status": "candidate",
                "classification_reason": "Explicitly required for implementation.",
            }
        ],
        "warnings": [],
    }
    payload.update(updates)
    return payload


def _classifier(
    *outputs: dict[str, object],
) -> tuple[P03RequirementClassifier, MockLLMProvider]:
    provider = MockLLMProvider(
        {
            SemanticLLMTask.P03_REQUIREMENT_CLASSIFIER: [
                json.dumps(item) for item in outputs
            ]
        }
    )
    executor = SemanticPromptExecutor(
        provider=provider,
        prompt_root=PROMPT_ROOT,
        settings=LLMSettings(model="semantic-mock", max_retries=0),
    )
    return P03RequirementClassifier(executor), provider


def test_p03_builds_explicit_jd_requirements_and_job_profile() -> None:
    classifier, _ = _classifier(_valid_output())

    result = classifier.classify(_p02_result())

    assert len(result.requirements) == 1
    requirement = result.requirements[0]
    assert requirement.requirement_type is RequirementType.CORE
    assert requirement.explicitness is RequirementExplicitness.EXPLICIT
    assert requirement.source is RequirementSource.JD
    assert requirement.critical_status is CriticalStatus.CANDIDATE
    assert requirement.jd_snapshot_id == "jd-snapshot-1"
    assert result.job_profile.knowledge_coverage is KnowledgeCoverage.BASE_ONLY
    assert result.job_profile.requirement_ids == [requirement.requirement_id]


def test_p03_input_is_candidate_blind_and_has_no_knowledge_access() -> None:
    classifier, provider = _classifier(_valid_output())

    classifier.classify(_p02_result())

    payload = provider.calls[0].messages[-1].content.casefold()
    assert "resume_profile" not in payload
    assert "candidate_profile" not in payload
    assert "candidate_evidence" not in payload
    assert "knowledge_context" not in payload
    assert "knowledge_citation" not in payload


@pytest.mark.parametrize("unauthorized_type", ["implicit", "must_have"])
def test_p03_rejects_non_frozen_requirement_types(unauthorized_type: str) -> None:
    output = _valid_output()
    output["requirements"][0]["requirement_type"] = unauthorized_type
    classifier, provider = _classifier(output)

    with pytest.raises(SemanticPromptError, match="P03"):
        classifier.classify(_p02_result())

    assert provider.call_count == 3


def test_p03_rejects_score_or_final_hard_guard_fields() -> None:
    output = _valid_output()
    output["requirements"][0]["eligibility_status"] = "blocked"
    output["requirements"][0]["score"] = 0
    classifier, provider = _classifier(output)

    with pytest.raises(SemanticPromptError, match="P03"):
        classifier.classify(_p02_result())

    assert provider.call_count == 3


def test_p03_requires_each_raw_requirement_to_be_classified_once() -> None:
    classifier, provider = _classifier(_valid_output(requirements=[]))

    with pytest.raises(SemanticPromptError, match="P03"):
        classifier.classify(_p02_result())

    assert provider.call_count == 3


def test_p03_can_mark_explicit_hard_candidate_without_deciding_eligibility() -> None:
    hard = _valid_output()
    hard["requirements"][0].update(
        {
            "requirement_type": "hard",
            "importance": "critical",
            "critical_status": "candidate",
        }
    )
    classifier, _ = _classifier(hard)

    requirement = classifier.classify(_p02_result()).requirements[0]

    assert requirement.requirement_type is RequirementType.HARD
    assert requirement.critical_status is CriticalStatus.CANDIDATE
    assert "eligibility_status" not in requirement.model_fields_set


def test_p03_prompt_establishes_exact_raw_coverage() -> None:
    prompt = (PROMPT_ROOT / "p03_requirement_classifier.md").read_text(encoding="utf-8")
    folded = prompt.casefold()

    assert "raw_requirement_ids" in folded
    assert "object_id" in folded
    assert "exactly once" in folded
    assert "omit" in folded
    assert "group" in folded


def test_p03_grouped_requirement_preserves_all_raw_ids() -> None:
    grouped = _valid_output(
        requirements=[
            {
                "local_id": "classified-1",
                "raw_requirement_ids": ["raw-requirement-1", "raw-requirement-2"],
                "normalized_capability": "Python and SQL application development",
                "requirement_type": "core",
                "importance": "high",
                "critical_status": "candidate",
                "classification_reason": "Grouped development capability.",
            }
        ]
    )
    classifier, _ = _classifier(grouped)

    requirement = classifier.classify(_p02_two_raws()).requirements[0]

    assert requirement.raw_requirement_ids == [
        "raw-requirement-1",
        "raw-requirement-2",
    ]


def test_p03_missing_raw_id_rejected() -> None:
    incomplete = _valid_output()  # covers only raw-requirement-1
    classifier, provider = _classifier(incomplete)

    with pytest.raises(SemanticPromptError, match="P03"):
        classifier.classify(_p02_two_raws())

    assert provider.call_count == 3


def test_p03_duplicate_raw_id_rejected() -> None:
    duplicated = _valid_output(
        requirements=[
            {
                "local_id": "classified-1",
                "raw_requirement_ids": ["raw-requirement-1"],
                "normalized_capability": "Python application development",
                "requirement_type": "core",
                "importance": "high",
                "critical_status": "candidate",
                "classification_reason": "First classification.",
            },
            {
                "local_id": "classified-2",
                "raw_requirement_ids": ["raw-requirement-1", "raw-requirement-2"],
                "normalized_capability": "SQL application development",
                "requirement_type": "core",
                "importance": "high",
                "critical_status": "candidate",
                "classification_reason": "Second classification.",
            },
        ]
    )
    classifier, provider = _classifier(duplicated)

    with pytest.raises(SemanticPromptError, match="P03"):
        classifier.classify(_p02_two_raws())

    assert provider.call_count == 3


def test_p03_invented_raw_id_rejected() -> None:
    invented = _valid_output(
        requirements=[
            {
                "local_id": "classified-1",
                "raw_requirement_ids": ["raw-requirement-1", "raw-requirement-invented"],
                "normalized_capability": "Python application development",
                "requirement_type": "core",
                "importance": "high",
                "critical_status": "candidate",
                "classification_reason": "Claimed coverage.",
            }
        ]
    )
    classifier, provider = _classifier(invented)

    with pytest.raises(SemanticPromptError, match="P03"):
        classifier.classify(_p02_two_raws())

    assert provider.call_count == 3


def test_p03_targeted_repair_covers_missing_raw_ids() -> None:
    incomplete = _valid_output()  # omits raw-requirement-2
    complete = _valid_output(
        requirements=[
            {
                "local_id": "classified-1",
                "raw_requirement_ids": ["raw-requirement-1", "raw-requirement-2"],
                "normalized_capability": "Python and SQL application development",
                "requirement_type": "core",
                "importance": "high",
                "critical_status": "candidate",
                "classification_reason": "Complete coverage.",
            }
        ]
    )
    classifier, provider = _classifier(incomplete, complete)

    result = classifier.classify(_p02_two_raws())

    assert result.execution.attempt_count == 2
    instruction = json.loads(provider.calls[1].messages[-1].content)["instruction"].casefold()
    assert "exactly once" in instruction
    assert "complete" in instruction
    assert "raw_requirement_ids" in instruction
    assert "group" in instruction
    assert "omit" in instruction


def test_p03_prompt_requires_merged_capability_uniqueness() -> None:
    prompt = (PROMPT_ROOT / "p03_requirement_classifier.md").read_text(encoding="utf-8")
    folded = prompt.casefold()

    assert "case-insensitive" in folded
    assert "merged" in folded
    assert "same normalized capability" in folded
    assert "grouping" in folded
    assert "exactly one requirement" in folded


def test_p03_duplicate_normalized_capability_targeted_repair_merges_requirements() -> None:
    duplicate = _valid_output(
        requirements=[
            {
                "local_id": "classified-1",
                "raw_requirement_ids": ["raw-requirement-1"],
                "normalized_capability": "Python application development",
                "requirement_type": "core",
                "importance": "high",
                "critical_status": "candidate",
                "classification_reason": "First split classification.",
            },
            {
                "local_id": "classified-2",
                "raw_requirement_ids": ["raw-requirement-2"],
                "normalized_capability": "python application development",
                "requirement_type": "core",
                "importance": "high",
                "critical_status": "candidate",
                "classification_reason": "Second split classification.",
            },
        ]
    )
    merged = _valid_output(
        requirements=[
            {
                "local_id": "classified-1",
                "raw_requirement_ids": ["raw-requirement-1", "raw-requirement-2"],
                "normalized_capability": "Python application development",
                "requirement_type": "core",
                "importance": "high",
                "critical_status": "candidate",
                "classification_reason": "Merged equivalent capability.",
            }
        ]
    )
    classifier, provider = _classifier(duplicate, merged)

    result = classifier.classify(_p02_two_raws())

    assert result.execution.attempt_count == 2
    assert [attempt.stage for attempt in result.execution.attempts] == [
        "normal",
        "targeted_repair",
    ]
    instruction = json.loads(provider.calls[1].messages[-1].content)[
        "instruction"
    ].casefold()
    assert "merge" in instruction
    assert "complete" in instruction
    assert "raw_requirement_ids" in instruction
    assert "patch fragment" in instruction
    assert len(result.requirements) == 1
    assert result.requirements[0].raw_requirement_ids == [
        "raw-requirement-1",
        "raw-requirement-2",
    ]
