"""Presentation-only Chinese translation for validated public report prose."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from hashlib import sha256

from pydantic import Field

from jobfit.llm.protocol import LLMMessage, LLMProvider, LLMSettings, LLMTask
from jobfit.models import StrictModel

_TRANSLATION_PROMPT_VERSION = "public-beta-presentation-zh-v1"
_TECHNICAL_NAMES = (
    "PostgreSQL",
    "Python",
    "Pandas",
    "Figma",
    "Linux",
    "LLM",
    "MMO",
    "MOBA",
    "FPS",
    "AI",
)
_TECHNICAL_NAME_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(?:"
    + "|".join(re.escape(value) for value in _TECHNICAL_NAMES)
    + r")(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_NUMBER_TOKEN = re.compile(r"\d+(?:[./:-]\d+)*")
_CJK_CHARACTER = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
_LATIN_CHARACTER = re.compile(r"[A-Za-z]")


class PresentationTranslationError(RuntimeError):
    """A safe presentation translation failure that must not fail analysis."""


@dataclass(frozen=True, slots=True)
class PresentationTranslationItem:
    """One stable display field and its already-sanitized source prose."""

    key: str
    text: str


class _TranslatedItem(StrictModel):
    key: str = Field(min_length=1)
    translated_text: str = Field(min_length=1)


class _TranslatedBatch(StrictModel):
    items: list[_TranslatedItem] = Field(min_length=1)


class DeepSeekPresentationTranslator:
    """Use the configured analysis provider for one keyed translation batch."""

    def __init__(self, *, provider: LLMProvider, model: str) -> None:
        self._provider = provider
        self._model = model

    def translate(
        self,
        items: Sequence[PresentationTranslationItem],
    ) -> dict[str, str]:
        source_items = tuple(items)
        if not source_items:
            return {}
        expected = {item.key: item.text for item in source_items}
        if len(expected) != len(source_items):
            raise PresentationTranslationError("Duplicate presentation translation key.")
        messages = (
            LLMMessage(
                role="system",
                content=(
                    "TRANSLATE ONLY. Translate each user-visible report text to natural "
                    "Simplified Chinese. Return every key exactly once. Do not summarize, "
                    "add, remove, infer, or change facts, recommendation strength, "
                    "uncertainty, negation, numbers, dates, IDs, or technical product names. "
                    "Preserve AI, LLM, Python, Pandas, Figma, Linux, PostgreSQL, MMO, MOBA, "
                    "and FPS when they occur."
                ),
            ),
            LLMMessage(
                role="user",
                content=json.dumps(
                    {
                        "items": [
                            {"key": item.key, "text": item.text}
                            for item in source_items
                        ]
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            ),
        )
        try:
            response = self._provider.generate(
                task=LLMTask.GENERATE_ADVICE_BUNDLE,
                messages=messages,
                settings=LLMSettings(
                    model=self._model,
                    max_retries=0,
                    temperature=0,
                    prompt_version=_TRANSLATION_PROMPT_VERSION,
                ),
                response_schema=_TranslatedBatch.model_json_schema(),
            )
            translated = _TranslatedBatch.model_validate_json(response.content)
        except Exception as exc:
            raise PresentationTranslationError(
                "Presentation translation provider failed."
            ) from exc
        result = {item.key: item.translated_text for item in translated.items}
        if len(result) != len(translated.items) or set(result) != set(expected):
            raise PresentationTranslationError(
                "Presentation translation keys do not match the request."
            )
        for key, source in expected.items():
            _validate_invariant_tokens(source, result[key])
        return result


def presentation_translation_cache_key(
    report_id: str,
    items: Sequence[PresentationTranslationItem],
) -> str:
    """Bind cached display copies to one report and exact sanitized prose."""
    payload = json.dumps(
        [{"key": item.key, "text": item.text} for item in items],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"{report_id}:{sha256(payload).hexdigest()}"


def needs_chinese_translation(value: str) -> bool:
    """Skip Chinese-first copy and standalone technical names deterministically."""
    text = value.strip()
    if not text:
        return False
    without_names = _TECHNICAL_NAME_PATTERN.sub("", text)
    latin_count = len(_LATIN_CHARACTER.findall(without_names))
    if latin_count == 0:
        return False
    cjk_count = len(_CJK_CHARACTER.findall(text))
    return cjk_count == 0 or latin_count > cjk_count


def _validate_invariant_tokens(source: str, translated: str) -> None:
    source_numbers = _NUMBER_TOKEN.findall(source)
    target_numbers = _NUMBER_TOKEN.findall(translated)
    if source_numbers != target_numbers:
        raise PresentationTranslationError(
            "Presentation translation changed a number or date token."
        )
    translated_lower = translated.lower()
    for name in _TECHNICAL_NAMES:
        if re.search(
            rf"(?<![A-Za-z0-9]){re.escape(name)}(?![A-Za-z0-9])",
            source,
            re.IGNORECASE,
        ) and name.lower() not in translated_lower:
            raise PresentationTranslationError(
                "Presentation translation changed a technical name."
            )


__all__ = [
    "DeepSeekPresentationTranslator",
    "PresentationTranslationError",
    "PresentationTranslationItem",
    "needs_chinese_translation",
    "presentation_translation_cache_key",
]
