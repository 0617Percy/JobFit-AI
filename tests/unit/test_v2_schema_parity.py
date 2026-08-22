"""Parity checks against the frozen structured-output field contract."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from jobfit.models import AnalysisReport as LegacyAnalysisReport
from jobfit.models import ResumeProfile as LegacyResumeProfile
from jobfit.models.v2 import (
    ActionRecommendation,
    AnalysisCore,
    Evidence,
    JobFitDomainBundle,
    JobFitReport,
    JobProfile,
    KnowledgeCitation,
    Requirement,
    RequirementMatch,
    ResumeProfile,
    UserClarification,
    VersionManifest,
)


@pytest.mark.parametrize(
    ("model", "expected_fields"),
    [
        (
            Evidence,
            {
                "evidence_id",
                "resume_version_id",
                "source_origin",
                "source_type",
                "source_record_id",
                "source_text",
                "normalized_capabilities",
                "personal_contribution",
                "task_clarity",
                "method_tool_clarity",
                "result_clarity",
                "verification_strength",
                "practical_use",
                "evidence_level",
                "ambiguity",
            },
        ),
        (
            ResumeProfile,
            {
                "resume_version_id",
                "candidate_profile",
                "education",
                "skills",
                "projects",
                "internships",
                "work_experience",
                "research",
                "competitions",
                "campus_experience",
                "achievements",
                "evidence_ids",
                "ambiguity_ids",
                "parse_completeness",
            },
        ),
        (
            Requirement,
            {
                "requirement_id",
                "jd_snapshot_id",
                "raw_requirement_ids",
                "raw_text",
                "normalized_capability",
                "requirement_type",
                "importance",
                "explicitness",
                "source",
                "critical_status",
                "classification_reason",
                "knowledge_citation_ids",
            },
        ),
        (
            JobProfile,
            {
                "jd_snapshot_id",
                "company",
                "job_title",
                "location",
                "employment_type",
                "job_family",
                "knowledge_coverage",
                "seniority_signals",
                "responsibility_ids",
                "raw_requirement_ids",
                "requirement_ids",
            },
        ),
        (
            RequirementMatch,
            {
                "match_id",
                "requirement_id",
                "matched_evidence",
                "coverage",
                "evidence_status",
                "ability_status",
                "best_evidence_level",
                "match_score_component",
                "reason",
            },
        ),
        (
            AnalysisCore,
            {
                "analysis_id",
                "resume_version_id",
                "jd_snapshot_id",
                "analysis_readiness",
                "eligibility_status",
                "seniority_alignment",
                "base_fit_score",
                "preferred_bonus",
                "final_fit_score",
                "critical_gap_requirement_ids",
                "confidence",
                "recommendation",
                "recommendation_reason_codes",
                "hard_blocker_ids",
                "hard_pending_ids",
                "forced_continue",
            },
        ),
        (
            ActionRecommendation,
            {
                "action_id",
                "action_type",
                "priority",
                "related_requirement_ids",
                "related_evidence_ids",
                "supported_by_evidence_ids",
                "title",
                "why_it_matters",
                "recommended_action",
                "completion_criteria",
                "effort",
                "time_to_complete",
                "evidence_visibility",
                "transferability",
                "timing",
                "potential_impact",
            },
        ),
        (
            KnowledgeCitation,
            {
                "citation_id",
                "knowledge_version",
                "source_id",
                "role_family",
                "title",
                "source_type",
                "reliability",
                "usage",
                "supported_claim",
            },
        ),
        (
            UserClarification,
            {
                "clarification_id",
                "analysis_id",
                "question_type",
                "question",
                "answer",
                "normalized_fact",
                "creates_evidence",
                "affects_recommendation",
            },
        ),
        (
            JobFitReport,
            {
                "report_id",
                "analysis_id",
                "summary",
                "job_profile",
                "resume_evidence_profile",
                "requirement_match",
                "score_explanation",
                "strengths_and_gaps",
                "hard_check",
                "resume_optimization",
                "build_recommendations",
                "application_strategy",
                "interview_preparation",
                "analysis_basis_and_limits",
            },
        ),
    ],
)
def test_models_include_every_frozen_structured_output_field(
    model: type,
    expected_fields: set[str],
) -> None:
    assert expected_fields <= set(model.model_fields)


def test_version_manifest_covers_independent_version_governance() -> None:
    assert set(VersionManifest.model_fields) == {
        "software_version",
        "prompt_pack_version",
        "schema_version",
        "scoring_rule_version",
        "knowledge_version",
        "analysis_engine_version",
        "business_test_set_version",
        "golden_set_version",
    }


def test_root_contract_forbids_unknown_sections_while_domain_objects_are_extensible(
) -> None:
    evidence_schema = Evidence.model_json_schema()
    root_schema = JobFitDomainBundle.model_json_schema()

    assert evidence_schema["additionalProperties"] is True
    assert root_schema["additionalProperties"] is False
    with pytest.raises(ValidationError, match="extra"):
        JobFitDomainBundle(unexpected_section={})


def test_v2_names_are_isolated_from_current_production_models() -> None:
    assert ResumeProfile is not LegacyResumeProfile
    assert LegacyAnalysisReport.model_fields["schema_version"].annotation is not None
