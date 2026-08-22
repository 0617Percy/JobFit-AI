"""DeepSeek OpenAI-compatible chat-completions provider for BYOK sessions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from time import perf_counter
from typing import Any

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    OpenAI,
    RateLimitError,
)

from jobfit.llm.deepseek_strict import build_deepseek_strict_contract
from jobfit.llm.exceptions import (
    ProviderAuthenticationError,
    ProviderConnectionError,
    ProviderError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderServerError,
    ProviderTimeoutError,
    StrictTransportError,
)
from jobfit.llm.protocol import (
    LLMFinishReason,
    LLMMessage,
    LLMResponse,
    LLMSettings,
    LLMTask,
    TokenUsage,
)
from jobfit.llm.retry import RetryExecutor
from jobfit.llm.telemetry import log_llm_call

DEEPSEEK_BASE_URL = "https://api.deepseek.com/beta"
STANDARD_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODELS = ("deepseek-v4-flash", "deepseek-v4-pro")


class DeepSeekProvider:
    """Call DeepSeek through the OpenAI SDK without retaining model reasoning."""

    provider_name = "deepseek"

    def __init__(
        self,
        *,
        api_key: str,
        thinking_enabled: bool = False,
        client: Any | None = None,
        connection_client: Any | None = None,
    ) -> None:
        key = api_key.strip()
        if not key:
            raise ValueError("DeepSeek API key is required.")
        self._client = client or OpenAI(
            api_key=key,
            base_url=DEEPSEEK_BASE_URL,
            max_retries=0,
        )
        self._connection_client = connection_client or OpenAI(
            api_key=key,
            base_url=STANDARD_DEEPSEEK_BASE_URL,
            max_retries=0,
        )
        self._thinking_enabled = thinking_enabled
        self._retry = RetryExecutor()

    def generate(
        self,
        *,
        task: LLMTask,
        messages: Sequence[LLMMessage],
        settings: LLMSettings,
        response_schema: Mapping[str, Any],
    ) -> LLMResponse:
        if settings.model not in DEEPSEEK_MODELS:
            raise ValueError("A supported DeepSeek model is required.")
        contract = build_deepseek_strict_contract(task, response_schema)
        transport_messages = [
            {"role": message.role, "content": message.content} for message in messages
        ]
        started = perf_counter()
        response = self._create_completion(
            messages=transport_messages,
            settings=settings,
            function_name=contract.function_name,
            parameters=contract.parameters,
        )
        arguments = _strict_tool_arguments(response, contract.function_name)
        content = contract.decode_arguments(arguments)
        result = LLMResponse(
            content=content,
            provider=self.provider_name,
            model=settings.model,
            usage=_extract_usage(getattr(response, "usage", None)),
            finish_reason=_extract_finish_reason(response),
        )
        log_llm_call(
            response=result,
            messages=messages,
            settings=settings,
            elapsed_ms=max(0, int((perf_counter() - started) * 1000)),
        )
        return result

    def check_connection(self) -> None:
        """Validate the current session credential through the models endpoint."""

        def operation() -> object:
            try:
                return self._connection_client.models.list()
            except ProviderError:
                raise
            except Exception as exc:
                raise _translate_exception(exc) from exc

        self._retry.run(operation, max_retries=0)

    def _create_completion(
        self,
        *,
        messages: list[dict[str, str]],
        settings: LLMSettings,
        function_name: str,
        parameters: Mapping[str, Any],
    ) -> object:
        kwargs: dict[str, Any] = {
            "model": settings.model,
            "messages": messages,
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": function_name,
                        "description": "Return the complete validated JobFit stage output.",
                        "strict": True,
                        "parameters": parameters,
                    },
                }
            ],
            "extra_body": {
                "thinking": {
                    "type": "enabled" if self._thinking_enabled else "disabled"
                }
            },
            "timeout": settings.timeout_seconds,
        }
        if self._thinking_enabled:
            kwargs["reasoning_effort"] = "high"
        try:
            return self._client.chat.completions.create(**kwargs)
        except ProviderError:
            raise
        except Exception as exc:
            if isinstance(exc, APIStatusError) and exc.status_code == 400:
                raise ProviderResponseError(
                    "STRICT_SCHEMA_PROVIDER_REJECTED"
                ) from None
            raise _translate_exception(exc) from exc


def _strict_tool_arguments(response: object, expected_name: str) -> str:
    choices = getattr(response, "choices", None)
    if not choices:
        raise StrictTransportError("STRICT_TOOL_CALL_MISSING")
    message = getattr(choices[0], "message", None)
    tool_calls = getattr(message, "tool_calls", None)
    if not isinstance(tool_calls, Sequence) or not tool_calls:
        raise StrictTransportError("STRICT_TOOL_CALL_MISSING")
    if len(tool_calls) != 1:
        raise StrictTransportError("STRICT_TOOL_CALL_MULTIPLE")
    function = getattr(tool_calls[0], "function", None)
    if getattr(function, "name", None) != expected_name:
        raise StrictTransportError("STRICT_TOOL_NAME_MISMATCH")
    arguments = getattr(function, "arguments", None)
    if not isinstance(arguments, str) or not arguments.strip():
        raise StrictTransportError("STRICT_ARGUMENTS_MISSING")
    return arguments


def _extract_usage(usage: object | None) -> TokenUsage | None:
    if usage is None:
        return None
    return TokenUsage(
        input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
        output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
        total_tokens=int(getattr(usage, "total_tokens", 0) or 0),
    )


def _extract_finish_reason(response: object) -> LLMFinishReason:
    choices = getattr(response, "choices", None)
    if not choices:
        return LLMFinishReason.OTHER
    raw_reason = getattr(choices[0], "finish_reason", None)
    try:
        return LLMFinishReason(raw_reason)
    except ValueError:
        return LLMFinishReason.OTHER


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


__all__ = [
    "DEEPSEEK_BASE_URL",
    "STANDARD_DEEPSEEK_BASE_URL",
    "DEEPSEEK_MODELS",
    "DeepSeekProvider",
]
