"""Deterministic severity policy for safe semantic-validation diagnostics."""

from __future__ import annotations

from enum import StrEnum

from jobfit.models.common import NonEmptyStr, StrictModel

_HARD_BLOCK_PREFIXES = (
    "CANDIDATE_FACT_",
    "EVIDENCE_",
    "FORBIDDEN_",
    "INVENTED_",
    "JD_SOURCE_",
    "KNOWLEDGE_SCOPE_",
    "OWNERSHIP_",
    "REPORT_",
    "SEMANTIC_STRENGTH_",
    "UNKNOWN_",
)

_HARD_BLOCK_CATEGORIES = frozenset(
    {
        "EXTERNAL_SOURCE_IDENTITY_MISSING",
        "INVALID_ACTION_TIMING",
        "INVALID_ACTION_TYPE",
        "RECOVER_SOURCE_IDENTITY_MISSING",
        "RECOVER_SOURCE_INVALID",
        "REWRITE_SOURCE_INVALID",
        "UNCONFIRMED_CLARIFICATION_REFERENCE",
    }
)


class SemanticValidationSeverity(StrEnum):
    """Trust impact of a post-schema semantic validation issue."""

    HARD_BLOCK = "hard_block"
    RECOVERABLE_ERROR = "recoverable_error"
    QUALITY_WARNING = "quality_warning"


class SemanticValidationIssue(StrictModel):
    """Safe issue metadata; it never contains source or model values."""

    stage: NonEmptyStr
    category: NonEmptyStr
    severity: SemanticValidationSeverity
    safe_path: NonEmptyStr


_QUALITY_WARNING_CATEGORIES = frozenset(
    {
        "ACTION_QUALITY_TOO_GENERIC",
        "DUPLICATE_INTERVIEW_QUESTION",
        "INTERVIEW_GUIDANCE_TOO_GENERIC",
        "P01_EDUCATION_NOT_EXTRACTED",
        "P01_EXPERIENCE_NOT_EXTRACTED",
    }
)

_RECOVERABLE_CATEGORIES = frozenset(
    {
        "BUSINESS_VALIDATION_FAILED",
        "CROSS_OBJECT_VALIDATION_FAILED",
        "EVIDENCE_QUOTE_AMBIGUOUS",
        "JD_SOURCE_TEXT_AMBIGUOUS",
        "P01_DUPLICATE_EVIDENCE_ID",
        "P01_EVIDENCE_REQUIRED",
        "P02_MEANINGFUL_REQUIREMENT_REQUIRED",
        "P02_RESPONSIBILITY_REQUIRED",
        "P02_SOURCE_ID_DUPLICATE",
        "P03_CLASSIFICATION_INCOMPLETE",
        "P03_REQUIREMENT_ID_DUPLICATE",
        "P03_REQUIREMENT_NORMALIZATION_DUPLICATE",
        "P04_EVIDENCE_ID_DUPLICATE",
        "P04_NORMALIZED_CAPABILITY_DUPLICATE",
        "P04_NORMALIZATION_INCOMPLETE",
        "P05_MATCH_COUNT_INVALID",
        "P05_MATCH_ID_DUPLICATE",
        "P05_MISSING_EVIDENCE_ABILITY_INVALID",
        "P05_MISSING_EVIDENCE_COVERAGE_INVALID",
        "P05_MISSING_EVIDENCE_RELATION_INVALID",
        "P05_PRESENT_EVIDENCE_RELATION_REQUIRED",
        "P06_ACTION_ID_DUPLICATE",
        "P07_QUESTION_ID_DUPLICATE",
        "P08_EXPLANATION_CITATION_ID_DUPLICATE",
        "P08_IMPLICIT_EXPLANATION_DUPLICATE",
        "BUILD_TRACEABILITY_MISSING",
        "INTERVIEW_TRACEABILITY_MISSING",
        "RECOVER_TRACEABILITY_MISSING",
        "REWRITE_TRACEABILITY_MISSING",
    }
)

_RECOVERABLE_SCHEMA_CATEGORIES = frozenset(
    {
        "bool_type",
        "decimal_parsing",
        "enum",
        "extra_forbidden",
        "int_parsing",
        "int_type",
        "less_than_equal",
        "list_type",
        "literal_error",
        "missing",
        "string_too_long",
        "string_too_short",
        "string_type",
        "too_long",
        "too_short",
        "value_error",
    }
)

_RECOVERABLE_EXACT_CATEGORIES = frozenset(
    {
        "INVALID_JSON",
        "STRICT_ARGUMENTS_EXTRA_KEY",
        "STRICT_ARGUMENTS_INVALID",
        "STRICT_ARGUMENTS_JSON_INVALID",
        "STRICT_ARGUMENTS_MISSING_KEY",
        "STRICT_ARGUMENTS_MISSING",
        "STRICT_SCHEMA_PROVIDER_REJECTED",
        "STRICT_TOOL_CALL_MISSING",
        "STRICT_TOOL_CALL_MULTIPLE",
        "STRICT_TOOL_NAME_MISMATCH",
    }
)


def validation_severity(category: str) -> SemanticValidationSeverity:
    """Classify an audited safe category, defaulting unknown rules fail-closed."""
    if category in _QUALITY_WARNING_CATEGORIES:
        return SemanticValidationSeverity.QUALITY_WARNING
    if (
        category in _RECOVERABLE_CATEGORIES
        or category in _RECOVERABLE_SCHEMA_CATEGORIES
        or category in _RECOVERABLE_EXACT_CATEGORIES
    ):
        return SemanticValidationSeverity.RECOVERABLE_ERROR
    if category in _HARD_BLOCK_CATEGORIES or category.startswith(_HARD_BLOCK_PREFIXES):
        return SemanticValidationSeverity.HARD_BLOCK
    if category.startswith("P0"):
        return SemanticValidationSeverity.RECOVERABLE_ERROR
    return SemanticValidationSeverity.HARD_BLOCK


def validation_issue(
    *,
    stage: str,
    category: str,
    safe_path: str,
) -> SemanticValidationIssue:
    """Build one deterministic safe issue from the frozen severity policy."""
    return SemanticValidationIssue(
        stage=stage,
        category=category,
        severity=validation_severity(category),
        safe_path=safe_path,
    )
