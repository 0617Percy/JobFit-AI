"""Knowledge-scope and repair gates for governed P06-P08 prompts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jobfit.llm import LLMSettings, MockLLMProvider
from jobfit.semantic.v2.advisory_contracts import (
    P06ActionOutput,
    P07InterviewOutput,
    P08ReportOutput,
)
from jobfit.semantic.v2.executor import (
    SemanticLLMTask,
    SemanticPromptError,
    SemanticPromptExecutor,
)
from jobfit.semantic.v2.governance import KnowledgeTier

PROMPT_ROOT = Path(__file__).parents[2] / "src" / "jobfit" / "prompts" / "v2"


def _executor(
    scripts: dict[SemanticLLMTask, list[str]] | None = None,
) -> SemanticPromptExecutor:
    return SemanticPromptExecutor(
        provider=MockLLMProvider(scripts or {}),
        prompt_root=PROMPT_ROOT,
        settings=LLMSettings(model="semantic-mock", max_retries=0),
    )


@pytest.mark.parametrize(
    ("prompt_id", "scope"),
    [
        ("P01", (KnowledgeTier.JOB_EXPLANATION,)),
        ("P06", (KnowledgeTier.INTERVIEW,)),
        ("P07", (KnowledgeTier.BUILD,)),
        ("P08", (KnowledgeTier.BUILD,)),
    ],
)
def test_prompt_executor_rejects_cross_tier_knowledge_access(
    prompt_id: str,
    scope: tuple[KnowledgeTier, ...],
) -> None:
    with pytest.raises(SemanticPromptError, match="knowledge access is forbidden"):
        _executor().execute_prompt(
            prompt_id=prompt_id,
            input_payload={"analysis_id": "analysis-1"},
            input_object_ids=("analysis-1",),
            response_model=P06ActionOutput,
            knowledge_scope=scope,
        )


def test_candidate_grounded_p06_rejects_hidden_knowledge_payload() -> None:
    with pytest.raises(SemanticPromptError, match="knowledge access is forbidden"):
        _executor().execute_prompt(
            prompt_id="P06",
            input_payload={
                "analysis_id": "analysis-1",
                "knowledge_context": [{"citation_id": "forbidden"}],
            },
            input_object_ids=("analysis-1",),
            response_model=P06ActionOutput,
        )


@pytest.mark.parametrize(
    ("prompt_id", "task", "response_model", "valid_payload"),
    [
        (
            "P06",
            SemanticLLMTask.P06_ACTIONS,
            P06ActionOutput,
            {"actions": [], "warnings": []},
        ),
        (
            "P07",
            SemanticLLMTask.P07_INTERVIEW,
            P07InterviewOutput,
            {"questions": [], "warnings": []},
        ),
        (
            "P08",
            SemanticLLMTask.P08_REPORT,
            P08ReportOutput,
            {
                "job_explanations": [],
                "implicit_explanations": [],
                "application_strategy_notes": [],
                "boundary_notes": [],
                "warnings": [],
            },
        ),
    ],
)
def test_p06_to_p08_share_bounded_repair_and_four_layer_records(
    prompt_id: str,
    task: SemanticLLMTask,
    response_model: type,
    valid_payload: dict[str, object],
) -> None:
    executor = _executor(
        {task: ["not-json", json.dumps(valid_payload)]}
    )

    result = executor.execute_prompt(
        prompt_id=prompt_id,
        input_payload={"analysis_id": "analysis-1"},
        input_object_ids=("analysis-1",),
        response_model=response_model,
    )

    assert result.record.attempt_count == 2
    assert result.record.attempts[0].error_code == "INVALID_JSON"
    assert result.record.validation.syntax_valid is True
    assert result.record.validation.schema_valid is True
    assert result.record.validation.business_valid is True
    assert result.record.validation.cross_object_valid is True
