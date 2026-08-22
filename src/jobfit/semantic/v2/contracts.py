"""Strict execution contracts shared by candidate semantic stages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

from jobfit.llm.protocol import LLMFinishReason, TokenUsage
from jobfit.models.common import NonEmptyStr, StrictModel
from jobfit.semantic.v2.severity import SemanticValidationIssue

T = TypeVar("T", bound=BaseModel)


class PromptAttemptRecord(StrictModel):
    attempt: int = Field(ge=1, le=3)
    stage: NonEmptyStr
    syntax_valid: bool
    schema_valid: bool
    business_valid: bool
    cross_object_valid: bool
    error_code: str | None = None
    validation_error_count: int = Field(default=0, ge=0)
    validation_paths: tuple[NonEmptyStr, ...] = ()
    validation_types: tuple[NonEmptyStr, ...] = ()
    validation_categories: tuple[NonEmptyStr, ...] = ()
    validation_issues: tuple[SemanticValidationIssue, ...] = ()
    finish_reason: LLMFinishReason = LLMFinishReason.OTHER
    output_char_count: int = Field(default=0, ge=0)
    token_usage: TokenUsage | None = None
    output_truncation_suspected: bool = False


class PromptValidationRecord(StrictModel):
    syntax_valid: bool
    schema_valid: bool
    business_valid: bool
    cross_object_valid: bool


class PromptExecutionRecord(StrictModel):
    prompt_id: NonEmptyStr
    prompt_version: NonEmptyStr
    global_rules_version: NonEmptyStr
    prompt_pack_version: NonEmptyStr
    attempt_count: int = Field(ge=1, le=3)
    attempts: tuple[PromptAttemptRecord, ...]
    input_object_ids: tuple[NonEmptyStr, ...]
    output_object_ids: tuple[NonEmptyStr, ...] = ()
    warnings: tuple[NonEmptyStr, ...] = ()
    validation_issues: tuple[SemanticValidationIssue, ...] = ()
    validation: PromptValidationRecord
    provider: NonEmptyStr
    model: NonEmptyStr
    failure_code: str | None = None


@dataclass(frozen=True, slots=True)
class SemanticPromptResult(Generic[T]):
    output: T
    record: PromptExecutionRecord
