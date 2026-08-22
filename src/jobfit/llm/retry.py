"""Bounded retry policy for provider transport failures."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from jobfit.errors import ErrorCode, LLMError
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

R = TypeVar("R")

_RETRYABLE_ERRORS = (
    ProviderTimeoutError,
    ProviderRateLimitError,
    ProviderServerError,
    ProviderConnectionError,
)


class RetryExecutor:
    """Execute an operation with a finite number of immediate retries."""

    def run(
        self,
        operation: Callable[[], R],
        *,
        max_retries: int,
    ) -> R:
        for attempt in range(max_retries + 1):
            try:
                return operation()
            except StrictTransportError:
                raise
            except ProviderAuthenticationError as exc:
                raise LLMError(
                    code=ErrorCode.LLM_AUTH_FAILED,
                    user_message="大模型服务认证失败，请检查API配置。",
                    recoverable=False,
                    cause=exc,
                ) from exc
            except _RETRYABLE_ERRORS as exc:
                if attempt < max_retries:
                    continue
                raise LLMError(
                    code=ErrorCode.LLM_TRANSIENT_ERROR,
                    user_message="大模型服务暂时不可用，请稍后重试。",
                    recoverable=True,
                    cause=exc,
                ) from exc
            except ProviderResponseError as exc:
                raise LLMError(
                    code=ErrorCode.LLM_TRANSIENT_ERROR,
                    user_message="大模型服务返回了无法处理的响应。",
                    recoverable=True,
                    cause=exc,
                ) from exc
            except ProviderError as exc:
                raise LLMError(
                    code=ErrorCode.LLM_TRANSIENT_ERROR,
                    user_message="大模型服务调用失败，请稍后重试。",
                    recoverable=True,
                    cause=exc,
                ) from exc
        raise RuntimeError("RetryExecutor reached an unreachable state")
