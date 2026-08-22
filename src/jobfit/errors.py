"""Unified, machine-readable errors for JobFit Agent."""

from __future__ import annotations

from enum import StrEnum


class ErrorCode(StrEnum):
    """Stable error codes shared by domain modules and the user interface."""

    INPUT_EMPTY = "INPUT_EMPTY"
    INPUT_TOO_LARGE = "INPUT_TOO_LARGE"
    FILE_TYPE_UNSUPPORTED = "FILE_TYPE_UNSUPPORTED"

    DOCUMENT_PARSE_FAILED = "DOCUMENT_PARSE_FAILED"
    PDF_TEXT_EMPTY = "PDF_TEXT_EMPTY"

    CONFIG_INVALID = "CONFIG_INVALID"
    LLM_CREDENTIALS_MISSING = "LLM_CREDENTIALS_MISSING"
    LLM_PROVIDER_UNSUPPORTED = "LLM_PROVIDER_UNSUPPORTED"

    LLM_AUTH_FAILED = "LLM_AUTH_FAILED"
    LLM_TRANSIENT_ERROR = "LLM_TRANSIENT_ERROR"
    LLM_SCHEMA_INVALID = "LLM_SCHEMA_INVALID"
    MOCK_FIXTURE_MISSING = "MOCK_FIXTURE_MISSING"
    PROMPT_NOT_FOUND = "PROMPT_NOT_FOUND"

    SCHEMA_VALIDATION_FAILED = "SCHEMA_VALIDATION_FAILED"
    EVIDENCE_INVALID = "EVIDENCE_INVALID"
    SCORING_INVARIANT_FAILED = "SCORING_INVARIANT_FAILED"
    ADVICE_VALIDATION_FAILED = "ADVICE_VALIDATION_FAILED"
    REPORT_GENERATION_FAILED = "REPORT_GENERATION_FAILED"
    REPORT_VALIDATION_FAILED = "REPORT_VALIDATION_FAILED"

    KNOWLEDGE_CONFIG_INVALID = "KNOWLEDGE_CONFIG_INVALID"
    KNOWLEDGE_DISABLED = "KNOWLEDGE_DISABLED"
    KNOWLEDGE_DB_UNAVAILABLE = "KNOWLEDGE_DB_UNAVAILABLE"
    KNOWLEDGE_VERSION_UNAVAILABLE = "KNOWLEDGE_VERSION_UNAVAILABLE"
    KNOWLEDGE_NO_ROLE_MATCH = "KNOWLEDGE_NO_ROLE_MATCH"
    KNOWLEDGE_AMBIGUOUS_ROLE = "KNOWLEDGE_AMBIGUOUS_ROLE"
    KNOWLEDGE_RETRIEVAL_FAILED = "KNOWLEDGE_RETRIEVAL_FAILED"
    KNOWLEDGE_CITATION_INVALID = "KNOWLEDGE_CITATION_INVALID"
    KNOWLEDGE_VERSION_MISMATCH = "KNOWLEDGE_VERSION_MISMATCH"
    KNOWLEDGE_BOUNDARY_VIOLATION = "KNOWLEDGE_BOUNDARY_VIOLATION"
    KNOWLEDGE_SEED_INVALID = "KNOWLEDGE_SEED_INVALID"
    KNOWLEDGE_SEED_FILE_INVALID = "KNOWLEDGE_SEED_FILE_INVALID"
    KNOWLEDGE_SEED_SCHEMA_INVALID = "KNOWLEDGE_SEED_SCHEMA_INVALID"
    KNOWLEDGE_SEED_DUPLICATE_KEY = "KNOWLEDGE_SEED_DUPLICATE_KEY"
    KNOWLEDGE_SEED_TOO_LARGE = "KNOWLEDGE_SEED_TOO_LARGE"
    KNOWLEDGE_SEED_REFERENCE_INVALID = "KNOWLEDGE_SEED_REFERENCE_INVALID"
    KNOWLEDGE_SEED_CONTENT_UNSAFE = "KNOWLEDGE_SEED_CONTENT_UNSAFE"
    KNOWLEDGE_SEED_HASH_MISMATCH = "KNOWLEDGE_SEED_HASH_MISMATCH"
    KNOWLEDGE_VERSION_ALREADY_EXISTS = "KNOWLEDGE_VERSION_ALREADY_EXISTS"
    KNOWLEDGE_DRAFT_CONFLICT = "KNOWLEDGE_DRAFT_CONFLICT"
    KNOWLEDGE_VERSION_NOT_DRAFT = "KNOWLEDGE_VERSION_NOT_DRAFT"
    KNOWLEDGE_VERSION_NOT_PUBLISHABLE = "KNOWLEDGE_VERSION_NOT_PUBLISHABLE"
    KNOWLEDGE_PUBLISHED_IMMUTABLE = "KNOWLEDGE_PUBLISHED_IMMUTABLE"
    KNOWLEDGE_VERSION_RETIRE_INVALID = "KNOWLEDGE_VERSION_RETIRE_INVALID"
    KNOWLEDGE_SEARCH_UNAVAILABLE = "KNOWLEDGE_SEARCH_UNAVAILABLE"
    KNOWLEDGE_SEARCH_FAILED = "KNOWLEDGE_SEARCH_FAILED"
    KNOWLEDGE_SEARCH_INDEX_INVALID = "KNOWLEDGE_SEARCH_INDEX_INVALID"


class JobFitError(Exception):
    """Base exception carrying a safe message and stable error code."""

    def __init__(
        self,
        *,
        code: ErrorCode,
        user_message: str,
        recoverable: bool = False,
        cause: Exception | None = None,
    ) -> None:
        super().__init__(user_message)
        self.code = code
        self.user_message = user_message
        self.recoverable = recoverable
        self.cause = cause


class InputError(JobFitError):
    """Invalid or incomplete user input."""


class DocumentParseError(JobFitError):
    """A resume document could not be parsed safely."""


class ConfigurationError(JobFitError):
    """Runtime configuration is missing or invalid."""


class KnowledgeDatabaseError(JobFitError):
    """Knowledge persistence failed without exposing storage internals."""


class KnowledgeSeedError(JobFitError):
    """A versioned knowledge package or lifecycle transition is invalid."""


class LLMError(JobFitError):
    """A model-provider request or response failed."""


class SchemaValidationError(JobFitError):
    """Structured data does not satisfy its schema."""


class ScoringError(JobFitError):
    """A deterministic scoring invariant failed."""


class ReportGenerationError(JobFitError):
    """A report could not be validated or rendered."""
