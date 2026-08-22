"""Privilege-escalation and prompt-scope security tests for P01-P08."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from jobfit.semantic.v2.stage_contracts import (
    PROMPT_INPUT_MODELS,
    PROMPT_OUTPUT_MODELS,
    P01ResumeOutput,
    P03RequirementOutput,
    P04EvidenceOutput,
    P05MatchOutput,
)

PROMPT_ROOT = Path(__file__).parents[2] / "src" / "jobfit" / "prompts" / "v2"
FORBIDDEN_DECISION_FIELDS = {
    "analysis_readiness",
    "eligibility_status",
    "evidence_level",
    "final_fit_score",
    "hard_blocker_ids",
    "match_score_component",
    "recommendation",
    "score",
}


def test_p01_candidate_profile_rejects_score_and_recommendation_escalation() -> None:
    payload = {
        "candidate_profile": {
            "name": None,
            "education_level": "bachelor",
            "current_status": "student",
            "graduation_date": None,
            "years_of_full_time_experience": "0",
            "score": 100,
            "recommendation": "priority",
        },
        "education": [],
        "skills": [],
        "projects": [],
        "internships": [],
        "work_experience": [],
        "research": [],
        "competitions": [],
        "campus_experience": [],
        "achievements": [],
        "evidence_items": [],
        "ambiguities": [],
        "parse_completeness": "insufficient",
    }

    with pytest.raises(ValidationError, match="extra_forbidden"):
        P01ResumeOutput.model_validate(payload)


@pytest.mark.parametrize(
    "model",
    [P03RequirementOutput, P04EvidenceOutput, P05MatchOutput],
)
def test_downstream_prompt_schema_has_no_final_decision_fields(model: type) -> None:
    schema_text = str(model.model_json_schema()).casefold()

    for field in FORBIDDEN_DECISION_FIELDS:
        assert f"'{field}'" not in schema_text


def test_candidate_prompt_pack_contains_governed_p06_to_p08_prompts() -> None:
    filenames = {path.name.casefold() for path in PROMPT_ROOT.iterdir()}

    assert {
        "p06_actions.md",
        "p07_interview.md",
        "p08_report.md",
    } <= filenames


def test_manifest_schema_names_resolve_to_strict_input_and_output_contracts() -> None:
    assert [model.__name__ for model in PROMPT_INPUT_MODELS.values()] == [
        "P01ResumeInput",
        "P02JobInput",
        "P03RequirementInput",
        "P04EvidenceInput",
        "P05MatchInput",
        "P06ActionInput",
        "P07InterviewInput",
        "P08ReportInput",
    ]
    assert [model.__name__ for model in PROMPT_OUTPUT_MODELS.values()] == [
        "P01ResumeLLMOutput",
        "P02JobLLMOutput",
        "P03RequirementOutput",
        "P04EvidenceOutput",
        "P05MatchOutput",
        "P06ActionOutput",
        "P07InterviewOutput",
        "P08ReportOutput",
    ]
    for model in (*PROMPT_INPUT_MODELS.values(), *PROMPT_OUTPUT_MODELS.values()):
        assert model.model_config["extra"] == "forbid"
