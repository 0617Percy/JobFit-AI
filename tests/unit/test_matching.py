"""Tests for LLM-backed semantic matching and deterministic assembly."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from jobfit.errors import ErrorCode, JobFitError
from jobfit.llm import LLMSettings, LLMTask, MockLLMClient, MockLLMProvider
from jobfit.llm.prompt_registry import PromptRegistry
from jobfit.matching import EvidenceMatcher, assemble_match
from jobfit.models import MatchStatus, RequirementMatchDraft


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (MatchStatus.MATCHED, Decimal("1.0")),
        (MatchStatus.PARTIAL_MATCH, Decimal("0.6")),
        (MatchStatus.NOT_MATCHED, Decimal("0.0")),
        (MatchStatus.UNKNOWN, Decimal("0.0")),
    ],
)
def test_match_score_is_written_by_code(
    matching_case,
    status: MatchStatus,
    expected: Decimal,
) -> None:
    evidence_ids = (
        ("ev-python",)
        if status in {MatchStatus.MATCHED, MatchStatus.PARTIAL_MATCH}
        else ()
    )
    note = (
        "当前简历未提供足够证据确认该能力。"
        if status in {MatchStatus.UNKNOWN, MatchStatus.NOT_MATCHED}
        else None
    )
    draft = matching_case.draft(
        "req-python",
        status,
        evidence_ids,
        missing_note=note,
    )

    match = assemble_match(draft, matching_case.registry)

    assert match.match_score == expected


def test_match_draft_rejects_llm_supplied_match_score(matching_case) -> None:
    payload = matching_case.draft(
        "req-python",
        MatchStatus.MATCHED,
        ("ev-python",),
    ).model_dump(mode="json")
    payload["match_score"] = "0.99"

    with pytest.raises(ValidationError):
        RequirementMatchDraft.model_validate(payload)


def test_matcher_returns_one_match_per_requirement_in_job_order(
    matching_case,
    tmp_path: Path,
) -> None:
    drafts = _valid_drafts(matching_case)
    provider = MockLLMProvider(
        {LLMTask.MATCH_EVIDENCE: [_batch_json(drafts)]}
    )
    matcher = _matcher(provider, tmp_path)

    matches = matcher.match(
        matching_case.resume,
        matching_case.job,
        matching_case.document,
        matching_case.registry,
        request_id="request-matching",
    )

    assert [item.requirement_id for item in matches] == [
        item.requirement_id for item in matching_case.job.requirements.items
    ]
    assert [item.match_status for item in matches] == [
        MatchStatus.MATCHED,
        MatchStatus.PARTIAL_MATCH,
        MatchStatus.NOT_MATCHED,
        MatchStatus.UNKNOWN,
    ]
    assert provider.call_count == 1
    assert provider.calls[0].task is LLMTask.MATCH_EVIDENCE
    assert provider.calls[0].settings.request_id == "request-matching"


def test_matcher_repairs_missing_requirement_once(
    matching_case,
    tmp_path: Path,
) -> None:
    drafts = _valid_drafts(matching_case)
    provider = MockLLMProvider(
        {
            LLMTask.MATCH_EVIDENCE: [
                _batch_json(drafts[:-1]),
                _batch_json(drafts),
            ]
        }
    )
    matcher = _matcher(provider, tmp_path)

    matches = matcher.match(
        matching_case.resume,
        matching_case.job,
        matching_case.document,
        matching_case.registry,
        request_id="request-repair",
    )

    assert len(matches) == 4
    assert provider.call_count == 2
    assert "req-sql" in provider.calls[1].messages[-1].content


@pytest.mark.parametrize("mode", ["missing", "duplicate", "unknown"])
def test_matcher_fails_safely_after_invalid_repair(
    matching_case,
    tmp_path: Path,
    mode: str,
) -> None:
    drafts = _valid_drafts(matching_case)
    if mode == "missing":
        invalid = drafts[:-1]
    elif mode == "duplicate":
        invalid = [*drafts, drafts[0]]
    else:
        invalid = [
            *drafts,
            matching_case.draft(
                "req-unknown",
                MatchStatus.UNKNOWN,
                missing_note="当前简历未提供足够证据确认该能力。",
            ),
        ]
    response = _batch_json(invalid)
    provider = MockLLMProvider(
        {LLMTask.MATCH_EVIDENCE: [response, response]}
    )
    matcher = _matcher(provider, tmp_path)

    with pytest.raises(JobFitError) as exc_info:
        matcher.match(
            matching_case.resume,
            matching_case.job,
            matching_case.document,
            matching_case.registry,
            request_id="request-invalid",
        )

    assert exc_info.value.code is ErrorCode.EVIDENCE_INVALID
    assert provider.call_count == 2


def test_matcher_schema_repair_cannot_preserve_llm_match_score(
    matching_case,
    tmp_path: Path,
) -> None:
    drafts = _valid_drafts(matching_case)
    invalid_payload = json.loads(_batch_json(drafts))
    invalid_payload["matches"][0]["match_score"] = "0.99"
    provider = MockLLMProvider(
        {
            LLMTask.MATCH_EVIDENCE: [
                json.dumps(invalid_payload, ensure_ascii=False),
                _batch_json(drafts),
            ]
        }
    )
    matcher = _matcher(provider, tmp_path)

    matches = matcher.match(
        matching_case.resume,
        matching_case.job,
        matching_case.document,
        matching_case.registry,
        request_id="request-score-override",
    )

    assert matches[0].match_score == Decimal("1.0")
    assert provider.call_count == 2


def _matcher(
    provider: MockLLMProvider,
    prompt_root: Path,
) -> EvidenceMatcher:
    del prompt_root
    return EvidenceMatcher(
        client=MockLLMClient(provider),
        prompt_registry=PromptRegistry(
            Path(__file__).parents[2] / "src" / "jobfit" / "prompts"
        ),
        settings=LLMSettings(
            model="mock-model",
            max_retries=0,
            request_id="default-request",
            prompt_version="1.0",
        ),
    )


def _valid_drafts(matching_case) -> list[RequirementMatchDraft]:
    return [
        matching_case.draft(
            "req-python",
            MatchStatus.MATCHED,
            ("ev-python",),
            reasoning="简历明确写明使用Python完成数据处理。",
        ),
        matching_case.draft(
            "req-production",
            MatchStatus.PARTIAL_MATCH,
            ("ev-course",),
            reasoning="课程项目与机器学习相关，但未证明生产级部署经验。",
        ),
        matching_case.draft(
            "req-java",
            MatchStatus.NOT_MATCHED,
            ("ev-no-java",),
            reasoning="简历明确写明没有Java经验。",
            missing_note="简历存在明确否定表述。",
        ),
        matching_case.draft(
            "req-sql",
            MatchStatus.UNKNOWN,
            reasoning="当前简历没有足够证据确认SQL能力。",
            missing_note="当前简历未提供足够证据确认该能力。",
        ),
    ]


def _batch_json(drafts: list[RequirementMatchDraft]) -> str:
    return json.dumps(
        {"matches": [item.model_dump(mode="json") for item in drafts]},
        ensure_ascii=False,
    )
