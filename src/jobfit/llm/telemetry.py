"""Privacy-safe LLM call metrics logging."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from jobfit.llm.protocol import LLMMessage, LLMResponse, LLMSettings
from jobfit.logging_config import log_event

_LOGGER = logging.getLogger("jobfit.llm")


def log_llm_call(
    *,
    response: LLMResponse,
    messages: Sequence[LLMMessage],
    settings: LLMSettings,
    elapsed_ms: int,
) -> None:
    """Log counts and identifiers only, never prompt or response content."""

    token_usage = response.usage.total_tokens if response.usage else 0
    log_event(
        _LOGGER,
        "llm_call",
        request_id=settings.request_id,
        provider=response.provider,
        model=response.model,
        prompt_version=settings.prompt_version,
        input_char_count=sum(len(message.content) for message in messages),
        output_char_count=len(response.content),
        elapsed_ms=elapsed_ms,
        token_usage=token_usage,
        status="success",
    )
