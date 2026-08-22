"""Provider-neutral LLM request, response, and client contracts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Any, Literal, Protocol, TypeVar

from pydantic import BaseModel, Field

from jobfit.config import Settings
from jobfit.models import StrictModel

T = TypeVar("T", bound=BaseModel)


class LLMTask(StrEnum):
    EXTRACT_RESUME = "extract_resume"
    EXTRACT_JOB = "extract_job"
    MATCH_EVIDENCE = "match_evidence"
    GENERATE_ADVICE_BUNDLE = "generate_advice_bundle"


class LLMMessage(StrictModel):
    role: Literal["system", "user"]
    content: str = Field(min_length=1)


class LLMSettings(StrictModel):
    model: str = Field(min_length=1)
    timeout_seconds: int = Field(default=60, ge=1, le=300)
    max_retries: int = Field(default=2, ge=0, le=2)
    temperature: float = Field(default=0.0, ge=0, le=2)
    request_id: str = "-"
    prompt_version: str = "unknown"

    @classmethod
    def from_app_settings(
        cls,
        settings: Settings,
        *,
        request_id: str = "-",
        prompt_version: str = "unknown",
    ) -> LLMSettings:
        return cls(
            model=settings.llm_model or "mock",
            timeout_seconds=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
            temperature=0,
            request_id=request_id,
            prompt_version=prompt_version,
        )


class TokenUsage(StrictModel):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)


class LLMFinishReason(StrEnum):
    STOP = "stop"
    LENGTH = "length"
    CONTENT_FILTER = "content_filter"
    INSUFFICIENT_SYSTEM_RESOURCE = "insufficient_system_resource"
    OTHER = "other"


class LLMResponse(StrictModel):
    content: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    usage: TokenUsage | None = None
    finish_reason: LLMFinishReason = LLMFinishReason.OTHER


class PromptTemplate(StrictModel):
    task_name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    system_text: str = Field(min_length=1)
    user_template: str = Field(min_length=1)


class LLMProvider(Protocol):
    """Raw text provider consumed by the deterministic structured runner."""

    provider_name: str

    def generate(
        self,
        *,
        task: LLMTask,
        messages: Sequence[LLMMessage],
        settings: LLMSettings,
        response_schema: Mapping[str, Any],
    ) -> LLMResponse: ...


class LLMClient(Protocol):
    """Validated structured interface consumed by extractors and generators."""

    def generate_structured(
        self,
        *,
        task: LLMTask,
        response_model: type[T],
        messages: Sequence[LLMMessage],
        settings: LLMSettings,
    ) -> T: ...
