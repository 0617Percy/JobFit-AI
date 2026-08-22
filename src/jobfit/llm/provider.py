"""Configuration-driven LLM client factory."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jobfit.config import Settings
from jobfit.errors import ConfigurationError, ErrorCode
from jobfit.llm.mock_adapter import MockLLMClient
from jobfit.llm.openai_adapter import OpenAIAdapter
from jobfit.llm.protocol import LLMClient


def build_llm_client(
    settings: Settings,
    *,
    mock_fixture_dir: str | Path | None = None,
    openai_client: Any | None = None,
) -> LLMClient:
    if settings.llm_provider == "mock":
        if mock_fixture_dir is None:
            raise ConfigurationError(
                code=ErrorCode.CONFIG_INVALID,
                user_message="Mock模式缺少离线响应目录。",
                recoverable=False,
            )
        return MockLLMClient.from_directory(mock_fixture_dir)

    settings.validate_runtime("provider")
    client = openai_client or _create_openai_client(settings)
    return OpenAIAdapter(client)


def _create_openai_client(settings: Settings) -> Any:
    from openai import OpenAI

    kwargs: dict[str, Any] = {
        "api_key": settings.llm_api_key.get_secret_value() if settings.llm_api_key else None,
        "timeout": settings.llm_timeout_seconds,
        "max_retries": 0,
    }
    if settings.llm_base_url is not None:
        kwargs["base_url"] = str(settings.llm_base_url)
    return OpenAI(**kwargs)
