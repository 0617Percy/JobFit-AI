"""Fail-closed P08 validation against the immutable decision snapshot."""

from __future__ import annotations

from jobfit.models.v2 import (
    ActionType,
    JobFitDomainBundle,
    JobFitReport,
    RequirementSource,
)


class B5ReportValidationError(ValueError):
    """A P08 report is incomplete or drifts from its validated inputs."""


class P08ReportValidator:
    """Validate module completeness, decision identity, and source isolation."""

    _module_fields = (
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
    )

    def validate_or_raise(
        self,
        report: JobFitReport,
        bundle: JobFitDomainBundle,
    ) -> None:
        core = bundle.analysis_core
        versions = bundle.versions
        if core is None or versions is None:
            raise B5ReportValidationError("REPORT_INPUT_INCOMPLETE")
        if any(getattr(report, field_name) is None for field_name in self._module_fields):
            raise B5ReportValidationError("REPORT_MODULE_INCOMPLETE")
        if report.analysis_id != core.analysis_id:
            raise B5ReportValidationError("REPORT_DECISION_DRIFT: analysis_id")

        expected_summary = {
            "analysis_readiness": core.analysis_readiness.value,
            "eligibility_status": core.eligibility_status.value,
            "seniority_alignment": core.seniority_alignment.value,
            "confidence": core.confidence.value,
            "recommendation": core.recommendation.value,
            "critical_gap_requirement_ids": list(core.critical_gap_requirement_ids),
        }
        for key, value in expected_summary.items():
            if report.summary.get(key) != value:
                raise B5ReportValidationError(f"REPORT_DECISION_DRIFT: {key}")
        expected_scores = {
            "base_fit_score": str(core.base_fit_score),
            "preferred_bonus": str(core.preferred_bonus),
            "final_fit_score": str(core.final_fit_score),
            "confidence": core.confidence.value,
            "recommendation_reason_codes": [
                item.value for item in core.recommendation_reason_codes
            ],
        }
        for key, value in expected_scores.items():
            if report.score_explanation.get(key) != value:
                raise B5ReportValidationError(f"REPORT_DECISION_DRIFT: {key}")
        expected_hard = {
            "hard_blocker_ids": list(core.hard_blocker_ids),
            "hard_pending_ids": list(core.hard_pending_ids),
        }
        for key, value in expected_hard.items():
            if report.hard_check.get(key) != value:
                raise B5ReportValidationError(f"REPORT_DECISION_DRIFT: {key}")
        if report.application_strategy.get("recommendation") != (
            core.recommendation.value
        ):
            raise B5ReportValidationError(
                "REPORT_DECISION_DRIFT: application_strategy recommendation"
            )

        expected_resume_evidence = {
            "resume_version_id": core.resume_version_id,
            "candidate_evidence": [
                item.model_dump(mode="json")
                for item in sorted(bundle.evidence, key=lambda value: value.evidence_id)
            ],
        }
        if report.resume_evidence_profile != expected_resume_evidence:
            raise B5ReportValidationError(
                "REPORT_DECISION_DRIFT: candidate evidence"
            )

        expected_matches = [
            item.model_dump(mode="json")
            for item in sorted(
                bundle.requirement_matches,
                key=lambda value: (value.requirement_id, value.match_id),
            )
        ]
        if report.requirement_match != expected_matches:
            raise B5ReportValidationError("REPORT_DECISION_DRIFT: requirement_match")

        actions = sorted(bundle.actions, key=lambda value: value.action_id)
        expected_resume_optimization = {
            "rewrite": [
                item.model_dump(mode="json")
                for item in actions
                if item.action_type is ActionType.REWRITE
            ],
            "recover": [
                item.model_dump(mode="json")
                for item in actions
                if item.action_type is ActionType.RECOVER
            ],
        }
        expected_build = [
            item.model_dump(mode="json")
            for item in actions
            if item.action_type is ActionType.BUILD
        ]
        expected_interview = [
            item.model_dump(mode="json")
            for item in sorted(
                bundle.interview_questions,
                key=lambda value: value.question_id,
            )
        ]
        if (
            report.resume_optimization != expected_resume_optimization
            or report.build_recommendations != expected_build
            or report.interview_preparation != expected_interview
        ):
            raise B5ReportValidationError("REPORT_ADVISORY_DRIFT")
        expected_explicit_ids = [
            item.requirement_id
            for item in sorted(bundle.requirements, key=lambda value: value.requirement_id)
            if item.source is RequirementSource.JD
        ]
        actual_explicit_ids = [
            item.get("requirement_id")
            for item in report.job_profile.get("explicit_requirements", [])
        ]
        if actual_explicit_ids != expected_explicit_ids:
            raise B5ReportValidationError("REPORT_EXPLICIT_REQUIREMENT_DRIFT")
        implicit_ids = {
            item.requirement_id
            for item in bundle.requirements
            if item.source is RequirementSource.KNOWLEDGE
        }
        report_implicit_ids = {
            item.get("requirement_id")
            for item in report.job_profile.get("implicit_context", [])
        }
        if not report_implicit_ids <= implicit_ids:
            raise B5ReportValidationError("REPORT_IMPLICIT_EXPLICIT_MIXED")
        if report.analysis_basis_and_limits.get("versions") != versions.model_dump(
            mode="json"
        ):
            raise B5ReportValidationError("REPORT_VERSION_IDENTITY_DRIFT")
