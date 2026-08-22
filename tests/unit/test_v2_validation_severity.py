"""Deterministic semantic validation severity boundaries."""

from jobfit.semantic.v2.severity import (
    SemanticValidationSeverity,
    validation_severity,
)


def test_frozen_trust_boundaries_are_hard_blocks() -> None:
    categories = (
        "EVIDENCE_QUOTE_NOT_FOUND",
        "UNKNOWN_EVIDENCE_REFERENCE",
        "CANDIDATE_FACT_FABRICATION",
        "SEMANTIC_STRENGTH_INCREASE",
        "FORBIDDEN_AUTHORITATIVE_FIELD",
        "REPORT_CORE_INVARIANCE_VIOLATION",
    )

    assert {
        validation_severity(category) for category in categories
    } == {SemanticValidationSeverity.HARD_BLOCK}


def test_repairable_contract_issues_are_recoverable_errors() -> None:
    categories = (
        "EVIDENCE_QUOTE_AMBIGUOUS",
        "P01_EVIDENCE_REQUIRED",
        "P05_MISSING_EVIDENCE_ABILITY_INVALID",
        "STRICT_TOOL_CALL_MISSING",
        "missing",
        "enum",
    )

    assert {
        validation_severity(category) for category in categories
    } == {SemanticValidationSeverity.RECOVERABLE_ERROR}


def test_only_explicit_quality_categories_are_warnings() -> None:
    categories = (
        "P01_EDUCATION_NOT_EXTRACTED",
        "P01_EXPERIENCE_NOT_EXTRACTED",
        "ACTION_QUALITY_TOO_GENERIC",
        "DUPLICATE_INTERVIEW_QUESTION",
        "INTERVIEW_GUIDANCE_TOO_GENERIC",
    )

    assert {
        validation_severity(category) for category in categories
    } == {SemanticValidationSeverity.QUALITY_WARNING}
    assert validation_severity("UNKNOWN_UNAUDITED_RULE") is (
        SemanticValidationSeverity.HARD_BLOCK
    )
