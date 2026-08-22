"""Tests for the unified JobFit exception hierarchy."""

from __future__ import annotations

import pytest

from jobfit.errors import (
    ConfigurationError,
    DocumentParseError,
    ErrorCode,
    InputError,
    JobFitError,
    LLMError,
    ReportGenerationError,
    SchemaValidationError,
    ScoringError,
)


@pytest.mark.parametrize(
    "error_type",
    [
        InputError,
        DocumentParseError,
        ConfigurationError,
        LLMError,
        SchemaValidationError,
        ScoringError,
        ReportGenerationError,
    ],
)
def test_domain_errors_share_one_base_type(error_type: type[JobFitError]) -> None:
    assert issubclass(error_type, JobFitError)


def test_error_exposes_stable_code_and_safe_message() -> None:
    cause = ValueError("internal secret details")
    error = DocumentParseError(
        code=ErrorCode.DOCUMENT_PARSE_FAILED,
        user_message="无法读取该文件，请改用文本输入。",
        recoverable=True,
        cause=cause,
    )

    assert error.code is ErrorCode.DOCUMENT_PARSE_FAILED
    assert error.recoverable is True
    assert error.cause is cause
    assert str(error) == "无法读取该文件，请改用文本输入。"
    assert "internal secret details" not in str(error)


def test_error_codes_are_machine_readable_strings() -> None:
    assert ErrorCode.INPUT_EMPTY.value == "INPUT_EMPTY"
    assert ErrorCode.LLM_CREDENTIALS_MISSING.value == "LLM_CREDENTIALS_MISSING"
    assert ErrorCode.SCORING_INVARIANT_FAILED.value == "SCORING_INVARIANT_FAILED"
    assert ErrorCode.REPORT_GENERATION_FAILED.value == "REPORT_GENERATION_FAILED"


def test_knowledge_error_codes_are_stable_and_machine_readable() -> None:
    assert ErrorCode.KNOWLEDGE_CONFIG_INVALID.value == "KNOWLEDGE_CONFIG_INVALID"
    assert ErrorCode.KNOWLEDGE_DISABLED.value == "KNOWLEDGE_DISABLED"
    assert (
        ErrorCode.KNOWLEDGE_DB_UNAVAILABLE.value
        == "KNOWLEDGE_DB_UNAVAILABLE"
    )
    assert (
        ErrorCode.KNOWLEDGE_VERSION_UNAVAILABLE.value
        == "KNOWLEDGE_VERSION_UNAVAILABLE"
    )
    assert ErrorCode.KNOWLEDGE_NO_ROLE_MATCH.value == "KNOWLEDGE_NO_ROLE_MATCH"
    assert (
        ErrorCode.KNOWLEDGE_AMBIGUOUS_ROLE.value
        == "KNOWLEDGE_AMBIGUOUS_ROLE"
    )
    assert (
        ErrorCode.KNOWLEDGE_RETRIEVAL_FAILED.value
        == "KNOWLEDGE_RETRIEVAL_FAILED"
    )
    assert (
        ErrorCode.KNOWLEDGE_CITATION_INVALID.value
        == "KNOWLEDGE_CITATION_INVALID"
    )
    assert (
        ErrorCode.KNOWLEDGE_VERSION_MISMATCH.value
        == "KNOWLEDGE_VERSION_MISMATCH"
    )
    assert (
        ErrorCode.KNOWLEDGE_BOUNDARY_VIOLATION.value
        == "KNOWLEDGE_BOUNDARY_VIOLATION"
    )
    assert ErrorCode.KNOWLEDGE_SEED_INVALID.value == "KNOWLEDGE_SEED_INVALID"
