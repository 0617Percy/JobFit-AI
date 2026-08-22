"""Connection-check safe error mapping contract for the v2 UI."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from jobfit.errors import ErrorCode, LLMError
from jobfit.llm.exceptions import (
    ProviderAuthenticationError,
    ProviderConnectionError,
    ProviderRateLimitError,
    ProviderServerError,
    ProviderTimeoutError,
)

REPO_ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(REPO_ROOT))

spec = importlib.util.spec_from_file_location("app_v2", REPO_ROOT / "app_v2.py")
app_v2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app_v2)


@pytest.mark.parametrize(
    ("cause", "code", "expected"),
    [
        (ProviderAuthenticationError("secret"), ErrorCode.LLM_AUTH_FAILED, "API Key无效"),
        (ProviderTimeoutError("secret"), ErrorCode.LLM_TRANSIENT_ERROR, "请求超时"),
        (ProviderConnectionError("secret"), ErrorCode.LLM_TRANSIENT_ERROR, "网络连接失败"),
        (ProviderRateLimitError("secret"), ErrorCode.LLM_TRANSIENT_ERROR, "请求频率受限"),
        (ProviderServerError("secret"), ErrorCode.LLM_TRANSIENT_ERROR, "服务返回异常响应"),
    ],
    ids=["auth", "timeout", "connection", "rate-limit", "server"],
)
def test_connection_error_mapping_is_specific_and_safe(
    cause: Exception,
    code: ErrorCode,
    expected: str,
) -> None:
    error = LLMError(code=code, user_message="internal", recoverable=True, cause=cause)

    message = app_v2._deepseek_connection_error(error)

    assert expected in message
    assert "secret" not in message
    assert "internal" not in message
