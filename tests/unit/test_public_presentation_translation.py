"""Presentation-only Chinese translation contract tests."""

import json

import pytest

from jobfit.llm.protocol import LLMFinishReason, LLMResponse


class _RecordingProvider:
    provider_name = "fake"

    def __init__(self, content: str) -> None:
        self._content = content
        self.calls: list[dict[str, object]] = []

    def generate(self, **kwargs) -> LLMResponse:
        self.calls.append(kwargs)
        return LLMResponse(
            content=self._content,
            provider="fake",
            model="fake-model",
            finish_reason=LLMFinishReason.STOP,
        )


def test_deepseek_presentation_translator_sends_one_keyed_batch() -> None:
    from jobfit.ui.presentation_translation import (
        DeepSeekPresentationTranslator,
        PresentationTranslationItem,
    )

    provider = _RecordingProvider(
        json.dumps(
            {
                "items": [
                    {
                        "key": "requirement_match.0.reason",
                        "translated_text": "2028 年毕业时间无法确认。",
                    },
                    {
                        "key": "interview_preparation.0.question",
                        "translated_text": "你如何验证 Python 与 AI 工作流？",
                    },
                ]
            },
            ensure_ascii=False,
        )
    )
    translator = DeepSeekPresentationTranslator(
        provider=provider,
        model="deepseek-v4-flash",
    )
    items = (
        PresentationTranslationItem(
            key="requirement_match.0.reason",
            text="Graduation year 2028 cannot be confirmed.",
        ),
        PresentationTranslationItem(
            key="interview_preparation.0.question",
            text="How did you validate the Python and AI workflow?",
        ),
    )

    result = translator.translate(items)

    assert result == {
        "requirement_match.0.reason": "2028 年毕业时间无法确认。",
        "interview_preparation.0.question": "你如何验证 Python 与 AI 工作流？",
    }
    assert len(provider.calls) == 1
    call = provider.calls[0]
    assert "TRANSLATE ONLY" in call["messages"][0].content
    request = json.loads(call["messages"][1].content)
    assert request == {
        "items": [
            {
                "key": "requirement_match.0.reason",
                "text": "Graduation year 2028 cannot be confirmed.",
            },
            {
                "key": "interview_preparation.0.question",
                "text": "How did you validate the Python and AI workflow?",
            },
        ]
    }


def test_deepseek_presentation_translator_rejects_key_or_number_drift() -> None:
    from jobfit.ui.presentation_translation import (
        DeepSeekPresentationTranslator,
        PresentationTranslationError,
        PresentationTranslationItem,
    )

    provider = _RecordingProvider(
        json.dumps(
            {
                "items": [
                    {
                        "key": "wrong.key",
                        "translated_text": "毕业时间无法确认。",
                    }
                ]
            },
            ensure_ascii=False,
        )
    )
    translator = DeepSeekPresentationTranslator(
        provider=provider,
        model="deepseek-v4-flash",
    )

    with pytest.raises(PresentationTranslationError):
        translator.translate(
            (
                PresentationTranslationItem(
                    key="requirement_match.0.reason",
                    text="Graduation year 2028 cannot be confirmed.",
                ),
            )
        )
