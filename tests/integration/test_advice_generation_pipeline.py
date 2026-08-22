"""Offline AdviceBundle generation with deterministic local assembly."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from jobfit.errors import ErrorCode, JobFitError
from jobfit.generators import AdviceBundleGenerator
from jobfit.llm import LLMSettings, LLMTask, MockLLMClient, MockLLMProvider
from jobfit.llm.prompt_registry import PromptRegistry
from jobfit.models import EvidenceRegistry


def test_mock_advice_pipeline_is_single_call_deterministic_and_grounded(
    advice_case,
) -> None:
    response = _fixture_text()
    provider = MockLLMProvider(
        {LLMTask.GENERATE_ADVICE_BUNDLE: [response, response]}
    )
    generator = _generator(provider)

    first = generator.generate(
        advice_case.resume,
        advice_case.job,
        advice_case.matches,
        advice_case.score,
        advice_case.registry,
        request_id="advice-first",
    )
    second = generator.generate(
        advice_case.resume,
        advice_case.job,
        advice_case.matches,
        advice_case.score,
        advice_case.registry,
        request_id="advice-second",
    )

    assert first == second
    assert first.recommendation.level is advice_case.score.recommendation_level
    assert len(first.interview_questions) == 5
    assert len(first.strengths) <= 3
    assert len(first.gaps) <= 3
    assert first.rewrite_suggestions == [
        *first.direct_rewrites,
        *first.confirmation_required_rewrites,
    ]
    assert provider.call_count == 2
    assert all(call.task is LLMTask.GENERATE_ADVICE_BUNDLE for call in provider.calls)
    assert provider.calls[0].settings.prompt_version == "1.1"


def test_false_llm_level_is_repaired_but_cannot_change_local_level(
    advice_case,
) -> None:
    invalid = json.loads(_fixture_text())
    invalid["recommendation_level"] = "priority_apply"
    invalid["final_score"] = "99"
    provider = MockLLMProvider(
        {
            LLMTask.GENERATE_ADVICE_BUNDLE: [
                json.dumps(invalid, ensure_ascii=False),
                _fixture_text(),
            ]
        }
    )
    result = _generator(provider).generate(
        advice_case.resume,
        advice_case.job,
        advice_case.matches,
        advice_case.score,
        advice_case.registry,
        request_id="advice-false-level",
    )

    assert result.recommendation.level is advice_case.score.recommendation_level
    assert provider.call_count == 2


def test_invalid_score_summary_is_rejected_before_llm(advice_case) -> None:
    provider = MockLLMProvider(
        {LLMTask.GENERATE_ADVICE_BUNDLE: [_fixture_text()]}
    )
    invalid_score = advice_case.score.model_copy(
        update={"final_score": Decimal("0.00")}
    )

    with pytest.raises(JobFitError) as exc_info:
        _generator(provider).generate(
            advice_case.resume,
            advice_case.job,
            advice_case.matches,
            invalid_score,
            advice_case.registry,
            request_id="advice-invalid-score",
        )

    assert exc_info.value.code is ErrorCode.ADVICE_VALIDATION_FAILED
    assert provider.call_count == 0


def test_generator_rejects_incomplete_match_set_before_llm(advice_case) -> None:
    _assert_rejected_before_llm(
        advice_case,
        matches=advice_case.matches[:-1],
    )


def test_generator_rejects_non_normalized_requirement_weights(
    advice_case,
) -> None:
    requirements = [
        item.model_copy(update={"weight": Decimal("0")})
        if item.requirement_id == "req-python"
        else item
        for item in advice_case.job.requirements.items
    ]
    job = advice_case.job.model_copy(
        update={
            "requirements": advice_case.job.requirements.model_copy(
                update={"items": requirements}
            )
        }
    )

    _assert_rejected_before_llm(advice_case, job=job)


@pytest.mark.parametrize("invalid_kind", ["effective", "earned", "coverage"])
def test_generator_rejects_inconsistent_score_dimensions(
    advice_case,
    invalid_kind: str,
) -> None:
    dimensions = list(advice_case.score.dimension_scores)
    position = next(index for index, item in enumerate(dimensions) if item.active)
    dimension = dimensions[position]
    if invalid_kind == "effective":
        replacement = dimension.model_copy(
            update={"effective_points": dimension.effective_points - Decimal("1")}
        )
    elif invalid_kind == "earned":
        replacement = dimension.model_copy(
            update={"earned_points": max(
                Decimal("0"),
                dimension.earned_points - Decimal("1"),
            )}
        )
    else:
        replacement = dimension.model_copy(
            update={"requirement_ids": dimension.requirement_ids[:-1]}
        )
    dimensions[position] = replacement
    invalid_score = advice_case.score.model_copy(
        update={"dimension_scores": dimensions}
    )

    _assert_rejected_before_llm(advice_case, score=invalid_score)


def test_generator_rejects_noncanonical_match_score_or_evidence(
    advice_case,
) -> None:
    matches = [
        match.model_copy(update={"match_score": Decimal("0.99")})
        if match.requirement_id == "req-python"
        else match
        for match in advice_case.matches
    ]
    _assert_rejected_before_llm(advice_case, matches=matches)

    changed_evidence = advice_case.registry.get("ev-python").model_copy(
        update={"confidence": Decimal("0.50")}
    )
    registry = EvidenceRegistry(
        [
            changed_evidence
            if evidence_id == "ev-python"
            else advice_case.registry.get(evidence_id)
            for evidence_id in advice_case.registry.ids
        ]
    )
    _assert_rejected_before_llm(advice_case, registry=registry)


@pytest.mark.parametrize("blocker_kind", ["unknown_id", "confirmed", "unverified"])
def test_generator_rejects_inconsistent_score_blockers(
    advice_case,
    blocker_kind: str,
) -> None:
    if blocker_kind == "unknown_id":
        update = {"confirmed_hard_blockers": ["req-invented"]}
    elif blocker_kind == "confirmed":
        update = {"confirmed_hard_blockers": ["req-java"]}
    else:
        update = {"unverified_hard_blockers": ["req-sql"]}
    invalid_score = advice_case.score.model_copy(update=update)

    _assert_rejected_before_llm(advice_case, score=invalid_score)


def test_generator_rejects_prompt_without_input_placeholder(
    advice_case,
    tmp_path: Path,
) -> None:
    (tmp_path / "generate_advice_bundle.md").write_text(
        "\n".join(
            [
                "---",
                "task: generate_advice_bundle",
                'version: "1.1"',
                "---",
                "## System",
                "输入边界内生成建议。",
                "## User",
                "缺少输入占位符。",
            ]
        ),
        encoding="utf-8",
    )
    provider = MockLLMProvider(
        {LLMTask.GENERATE_ADVICE_BUNDLE: [_fixture_text()]}
    )
    generator = AdviceBundleGenerator(
        client=MockLLMClient(provider),
        prompt_registry=PromptRegistry(tmp_path),
        settings=LLMSettings(model="mock-model", max_retries=0),
    )

    with pytest.raises(JobFitError) as exc_info:
        generator.generate(
            advice_case.resume,
            advice_case.job,
            advice_case.matches,
            advice_case.score,
            advice_case.registry,
            request_id="advice-missing-placeholder",
        )

    assert exc_info.value.code is ErrorCode.ADVICE_VALIDATION_FAILED
    assert provider.call_count == 0


def test_advice_payload_excludes_resume_contact_details(advice_case) -> None:
    provider = MockLLMProvider(
        {LLMTask.GENERATE_ADVICE_BUNDLE: [_fixture_text()]}
    )
    resume = advice_case.resume.model_copy(
        update={
            "basic_info": advice_case.resume.basic_info.model_copy(
                update={
                    "email": "private@example.test",
                    "phone": "13800000000",
                }
            )
        }
    )

    _generator(provider).generate(
        resume,
        advice_case.job,
        advice_case.matches,
        advice_case.score,
        advice_case.registry,
        request_id="advice-no-pii",
    )

    payload = provider.calls[0].messages[1].content
    assert "private@example.test" not in payload
    assert "13800000000" not in payload


def test_invalid_evidence_id_fails_safely(advice_case) -> None:
    invalid = json.loads(_fixture_text())
    invalid["strengths"][0]["evidence_ids"] = ["ev-invented"]
    provider = MockLLMProvider(
        {
            LLMTask.GENERATE_ADVICE_BUNDLE: [
                json.dumps(invalid, ensure_ascii=False)
            ]
        }
    )

    with pytest.raises(JobFitError) as exc_info:
        _generator(provider).generate(
            advice_case.resume,
            advice_case.job,
            advice_case.matches,
            advice_case.score,
            advice_case.registry,
            request_id="advice-invalid-evidence",
        )

    assert exc_info.value.code is ErrorCode.ADVICE_VALIDATION_FAILED


def test_high_risk_rewrite_is_partitioned_for_confirmation(advice_case) -> None:
    payload = json.loads(_fixture_text())
    payload["rewrite_suggestions"][0]["rewritten_text"] = (
        "主导Python生产部署并提升效率30%。"
    )
    provider = MockLLMProvider(
        {
            LLMTask.GENERATE_ADVICE_BUNDLE: [
                json.dumps(payload, ensure_ascii=False)
            ]
        }
    )

    result = _generator(provider).generate(
        advice_case.resume,
        advice_case.job,
        advice_case.matches,
        advice_case.score,
        advice_case.registry,
        request_id="advice-risky-rewrite",
    )

    assert result.direct_rewrites == []
    assert len(result.confirmation_required_rewrites) == 1
    assert result.confirmation_required_rewrites[0].introduced_claims


def _generator(provider: MockLLMProvider) -> AdviceBundleGenerator:
    return AdviceBundleGenerator(
        client=MockLLMClient(provider),
        prompt_registry=PromptRegistry(
            Path(__file__).parents[2] / "src" / "jobfit" / "prompts"
        ),
        settings=LLMSettings(
            model="mock-model",
            max_retries=0,
            prompt_version="1.1",
        ),
    )


def _assert_rejected_before_llm(
    advice_case,
    *,
    job=None,
    matches=None,
    score=None,
    registry=None,
) -> None:
    provider = MockLLMProvider(
        {LLMTask.GENERATE_ADVICE_BUNDLE: [_fixture_text()]}
    )
    with pytest.raises(JobFitError) as exc_info:
        _generator(provider).generate(
            advice_case.resume,
            job or advice_case.job,
            matches if matches is not None else advice_case.matches,
            score or advice_case.score,
            registry or advice_case.registry,
            request_id="advice-invalid-input",
        )

    assert exc_info.value.code is ErrorCode.ADVICE_VALIDATION_FAILED
    assert provider.call_count == 0


def _fixture_text() -> str:
    return (
        Path(__file__).parents[1]
        / "fixtures"
        / "llm_responses"
        / "generate_advice_bundle.json"
    ).read_text(encoding="utf-8")
