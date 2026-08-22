"""Offline structured advice generation with bounded knowledge references."""

from __future__ import annotations

import json
from pathlib import Path

from jobfit.generators import AdviceBundleGenerator, KnowledgeGenerationResult
from jobfit.llm import LLMSettings, LLMTask, MockLLMClient, MockLLMProvider
from jobfit.llm.prompt_registry import PromptRegistry
from jobfit.models import AdviceBundleDraft


def test_available_knowledge_is_added_only_to_the_advice_user_message(
    advice_case,
    available_knowledge_context,
) -> None:
    payload = json.loads(_fixture_text())
    payload["knowledge_citation_uses"] = [
        {
            "citation_id": "cite-1111111111111111",
            "target_type": "recommendation",
            "target_index": 0,
            "purpose": "role_requirement_context",
        }
    ]
    provider = MockLLMProvider(
        {
            LLMTask.GENERATE_ADVICE_BUNDLE: [
                json.dumps(payload, ensure_ascii=False)
            ]
        }
    )

    result = _generator(provider).generate_with_knowledge(
        advice_case.resume,
        advice_case.job,
        advice_case.matches,
        advice_case.score,
        advice_case.registry,
        knowledge_context=available_knowledge_context,
        request_id="knowledge-advice",
    )

    assert isinstance(result, KnowledgeGenerationResult)
    assert result.citation_uses[0].citation_id == "cite-1111111111111111"
    assert result.provided_citation_ids == ("cite-1111111111111111",)
    assert provider.call_count == 1
    assert "<REFERENCE_KNOWLEDGE" in provider.calls[0].messages[1].content
    assert "2026.07.1" in provider.calls[0].messages[1].content
    assert "<REFERENCE_KNOWLEDGE" not in provider.calls[0].messages[0].content
    assert provider.calls[0].settings.prompt_version == "1.2"


def test_plain_generation_keeps_v1_behavior_and_accepts_legacy_fixture(
    advice_case,
) -> None:
    provider = MockLLMProvider(
        {LLMTask.GENERATE_ADVICE_BUNDLE: [_fixture_text()]}
    )

    result = _generator(provider).generate(
        advice_case.resume,
        advice_case.job,
        advice_case.matches,
        advice_case.score,
        advice_case.registry,
        request_id="plain-advice",
    )

    assert len(result.interview_questions) == 5
    assert "<REFERENCE_KNOWLEDGE" not in provider.calls[0].messages[1].content
    assert AdviceBundleDraft.model_validate_json(
        _fixture_text()
    ).knowledge_citation_uses == []


def _generator(provider: MockLLMProvider) -> AdviceBundleGenerator:
    return AdviceBundleGenerator(
        client=MockLLMClient(provider),
        prompt_registry=PromptRegistry(
            Path(__file__).parents[2] / "src" / "jobfit" / "prompts"
        ),
        settings=LLMSettings(model="mock-model", max_retries=0),
        prompt_version="1.2",
        knowledge_prompt_char_limit=4_000,
    )


def _fixture_text() -> str:
    return (
        Path(__file__).parents[1]
        / "fixtures"
        / "llm_responses"
        / "generate_advice_bundle.json"
    ).read_text(encoding="utf-8")
