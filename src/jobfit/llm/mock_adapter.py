"""Completely offline scripted and fixture-backed LLM implementation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from jobfit.errors import ErrorCode, LLMError
from jobfit.llm.exceptions import ProviderError, ProviderResponseError
from jobfit.llm.protocol import (
    LLMMessage,
    LLMResponse,
    LLMSettings,
    LLMTask,
)
from jobfit.llm.structured_runner import StructuredRunner

T = TypeVar("T", bound=BaseModel)
MockOutcome = str | LLMResponse | Exception


@dataclass(frozen=True, slots=True)
class MockCall:
    task: LLMTask
    messages: tuple[LLMMessage, ...]
    settings: LLMSettings
    response_schema: Mapping[str, Any]


class MockLLMProvider:
    provider_name = "mock"

    def __init__(
        self,
        scripts: Mapping[LLMTask, Sequence[MockOutcome]] | None = None,
        *,
        fixture_dir: str | Path | None = None,
    ) -> None:
        self._scripts = {task: list(outcomes) for task, outcomes in (scripts or {}).items()}
        self._fixture_dir = Path(fixture_dir) if fixture_dir else None
        self._positions: dict[LLMTask, int] = {}
        self.calls: list[MockCall] = []

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def generate(
        self,
        *,
        task: LLMTask,
        messages: Sequence[LLMMessage],
        settings: LLMSettings,
        response_schema: Mapping[str, Any],
    ) -> LLMResponse:
        self.calls.append(
            MockCall(
                task=task,
                messages=tuple(messages),
                settings=settings,
                response_schema=response_schema,
            )
        )
        outcome = self._next_outcome(task)
        if isinstance(outcome, Exception):
            if isinstance(outcome, ProviderError):
                raise outcome
            raise ProviderResponseError(type(outcome).__name__) from outcome
        if isinstance(outcome, LLMResponse):
            return outcome
        return LLMResponse(
            content=outcome,
            provider=self.provider_name,
            model=settings.model,
        )

    def _next_outcome(self, task: LLMTask) -> MockOutcome:
        outcomes = self._scripts.get(task)
        if outcomes is None and self._fixture_dir is not None:
            fixture_path = self._fixture_dir / f"{task.value}.json"
            try:
                outcomes = [fixture_path.read_text(encoding="utf-8")]
            except OSError as exc:
                raise LLMError(
                    code=ErrorCode.MOCK_FIXTURE_MISSING,
                    user_message=f"缺少离线Mock响应：{task.value}。",
                    recoverable=False,
                    cause=exc,
                ) from exc
            self._scripts[task] = outcomes
        if not outcomes:
            raise LLMError(
                code=ErrorCode.MOCK_FIXTURE_MISSING,
                user_message=f"缺少离线Mock响应：{task.value}。",
                recoverable=False,
            )
        position = self._positions.get(task, 0)
        self._positions[task] = position + 1
        return outcomes[min(position, len(outcomes) - 1)]


class MockLLMClient:
    def __init__(self, provider: MockLLMProvider) -> None:
        self.provider = provider
        self._runner = StructuredRunner(provider)

    @classmethod
    def from_directory(cls, fixture_dir: str | Path) -> MockLLMClient:
        return cls(MockLLMProvider(fixture_dir=fixture_dir))

    def generate_structured(
        self,
        *,
        task: LLMTask,
        response_model: type[T],
        messages: Sequence[LLMMessage],
        settings: LLMSettings,
    ) -> T:
        return self._runner.run(
            task=task,
            response_model=response_model,
            messages=messages,
            settings=settings,
        )
