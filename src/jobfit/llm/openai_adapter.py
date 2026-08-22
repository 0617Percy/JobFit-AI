"""Production OpenAI SDK adapter behind the provider-neutral LLMClient."""

from __future__ import annotations

from collections.abc import Sequence
from time import perf_counter
from typing import Any, TypeVar

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    RateLimitError,
)
from pydantic import BaseModel, ValidationError

from jobfit.errors import ErrorCode, LLMError
from jobfit.llm.exceptions import (
    ProviderAuthenticationError,
    ProviderConnectionError,
    ProviderError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderServerError,
    ProviderTimeoutError,
)
from jobfit.llm.protocol import (
    LLMMessage,
    LLMResponse,
    LLMSettings,
    LLMTask,
    TokenUsage,
)
from jobfit.llm.retry import RetryExecutor
from jobfit.llm.structured_runner import build_repair_message
from jobfit.llm.telemetry import log_llm_call

T = TypeVar("T", bound=BaseModel)


class OpenAIAdapter:
    """Use the SDK structured parse API while keeping SDK types at the boundary."""

    provider_name = "openai"

    def __init__(
        self,
        client: Any,
        *,
        retry_executor: RetryExecutor | None = None,
    ) -> None:
        self._client = client
        self._retry = retry_executor or RetryExecutor()

    def generate_structured(
        self,
        *,
        task: LLMTask,
        response_model: type[T],
        messages: Sequence[LLMMessage],
        settings: LLMSettings,
    ) -> T:
        del task
        original_messages = tuple(messages)
        current_messages = original_messages
        response_schema = response_model.model_json_schema()
        last_error: ValidationError | None = None

        for stage in ("initial", "repair", "full_retry"):
            started = perf_counter()
            response = self._retry.run(
                lambda active_messages=current_messages: self._parse_once(
                    response_model=response_model,
                    messages=active_messages,
                    settings=settings,
                ),
                max_retries=settings.max_retries,
            )
            parsed = getattr(response, "output_parsed", None)
            raw_output = getattr(response, "output_text", "") or str(parsed) or "{}"
            usage = self._extract_usage(getattr(response, "usage", None))
            log_llm_call(
                response=LLMResponse(
                    content=raw_output,
                    provider=self.provider_name,
                    model=settings.model,
                    usage=usage,
                ),
                messages=current_messages,
                settings=settings,
                elapsed_ms=max(0, int((perf_counter() - started) * 1000)),
            )
            try:
                return response_model.model_validate(parsed)
            except ValidationError as exc:
                last_error = exc
                if stage == "initial":
                    current_messages = (
                        *original_messages,
                        build_repair_message(
                            invalid_output=raw_output,
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

    def _parse_once(
        self,
        *,
        response_model: type[T],
        messages: Sequence[LLMMessage],
        settings: LLMSettings,
    ) -> object:
        try:
            return self._client.responses.parse(
                model=settings.model,
                input=[{"role": message.role, "content": message.content} for message in messages],
                text_format=response_model,
                temperature=settings.temperature,
                timeout=settings.timeout_seconds,
                store=False,
            )
        except ProviderError:
            raise
        except ValidationError as exc:
            raise LLMError(
                code=ErrorCode.LLM_SCHEMA_INVALID,
                user_message="大模型返回结果不符合结构化Schema，请重试。",
                recoverable=True,
                cause=exc,
            ) from exc
        except Exception as exc:
            raise self._translate_exception(exc) from exc

    @staticmethod
    def _translate_exception(exc: Exception) -> ProviderError:
        if isinstance(exc, AuthenticationError):
            return ProviderAuthenticationError(type(exc).__name__)
        if isinstance(exc, APITimeoutError):
            return ProviderTimeoutError(type(exc).__name__)
        if isinstance(exc, RateLimitError):
            return ProviderRateLimitError(type(exc).__name__)
        if isinstance(exc, APIConnectionError):
            return ProviderConnectionError(type(exc).__name__)
        if isinstance(exc, APIStatusError):
            if exc.status_code in {401, 403}:
                return ProviderAuthenticationError(type(exc).__name__)
            if exc.status_code == 429:
                return ProviderRateLimitError(type(exc).__name__)
            if exc.status_code >= 500:
                return ProviderServerError(type(exc).__name__)
        return ProviderResponseError(type(exc).__name__)

    @staticmethod
    def _extract_usage(usage: object | None) -> TokenUsage | None:
        if usage is None:
            return None
        return TokenUsage(
            input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
            total_tokens=int(getattr(usage, "total_tokens", 0) or 0),
        )
