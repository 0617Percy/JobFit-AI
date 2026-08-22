"""Deterministic JSON validation and bounded schema-repair workflow."""

from __future__ import annotations

import json
from collections.abc import Sequence
from time import perf_counter
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from jobfit.errors import ErrorCode, LLMError
from jobfit.llm.protocol import (
    LLMMessage,
    LLMProvider,
    LLMSettings,
    LLMTask,
)
from jobfit.llm.retry import RetryExecutor
from jobfit.llm.telemetry import log_llm_call

T = TypeVar("T", bound=BaseModel)


class StructuredRunner:
    """Validate raw provider JSON without inventing or mutating business fields."""

    def __init__(
        self,
        provider: LLMProvider,
        *,
        retry_executor: RetryExecutor | None = None,
    ) -> None:
        self._provider = provider
        self._retry = retry_executor or RetryExecutor()

    def run(
        self,
        *,
        task: LLMTask,
        response_model: type[T],
        messages: Sequence[LLMMessage],
        settings: LLMSettings,
    ) -> T:
        original_messages = tuple(messages)
        current_messages = original_messages
        response_schema = response_model.model_json_schema()
        last_error: ValidationError | None = None

        for stage in ("initial", "repair", "full_retry"):
            started = perf_counter()
            response = self._retry.run(
                lambda messages=current_messages: self._provider.generate(
                    task=task,
                    messages=messages,
                    settings=settings,
                    response_schema=response_schema,
                ),
                max_retries=settings.max_retries,
            )
            log_llm_call(
                response=response,
                messages=current_messages,
                settings=settings,
                elapsed_ms=max(0, int((perf_counter() - started) * 1000)),
            )
            try:
                return response_model.model_validate_json(response.content)
            except ValidationError as exc:
                last_error = exc
                if stage == "initial":
                    current_messages = (
                        *original_messages,
                        build_repair_message(
                            invalid_output=response.content,
                            error=exc,
                            response_schema=response_schema,
                        ),
                    )
                elif stage == "repair":
                    current_messages = original_messages

        raise LLMError(
            code=ErrorCode.LLM_SCHEMA_INVALID,
            user_message="大模型返回结果不符合结构化Schema，请重试。",
            recoverable=True,
            cause=last_error,
        )


def build_repair_message(
    *,
    invalid_output: str,
    error: ValidationError,
    response_schema: dict[str, object],
) -> LLMMessage:
    """Create a bounded repair request without locally changing business data."""

    simplified_errors = [
        {
            "location": ".".join(str(part) for part in item["loc"]),
            "type": item["type"],
            "message": item["msg"],
        }
        for item in error.errors(include_url=False, include_input=False)
    ]
    payload = {
        "instruction": (
            "仅修复JSON格式或Schema问题。不得新增经历、评分、ID或权重；"
            "无法确认的信息保持unknown或Schema允许的空值。"
        ),
        "invalid_output": invalid_output,
        "validation_errors": simplified_errors,
        "json_schema": response_schema,
    }
    return LLMMessage(
        role="user",
        content=json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    )
