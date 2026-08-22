"""Business and cross-object validation for v2 domain snapshots."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from jobfit.errors import ErrorCode, SchemaValidationError
from jobfit.models import Importance, ValidationIssue, ValidationResult, ValidationSeverity
from jobfit.models.v2 import (
    CriticalStatus,
    EvidenceSourceOrigin,
    JobFitDomainBundle,
    RequirementSource,
    RequirementType,
)


class DomainValidator:
    """Fail closed on invalid references without computing business decisions."""

    checked_rules = [
        "unique_object_ids",
        "resume_evidence_references",
        "job_requirement_references",
        "requirement_match_references",
        "knowledge_candidate_evidence_isolation",
        "user_clarification_source_isolation",
        "implicit_requirement_decision_isolation",
        "version_identity_consistency",
        "analysis_report_identity_consistency",
    ]

    def validate(self, bundle: JobFitDomainBundle) -> ValidationResult:
        issues: list[ValidationIssue] = []
        issues.extend(self._validate_unique_ids(bundle))

        evidence_by_id = self._first_by_id(bundle.evidence, "evidence_id")
        requirement_by_id = self._first_by_id(
            bundle.requirements, "requirement_id"
        )
        clarification_by_id = self._first_by_id(
            bundle.user_clarifications, "clarification_id"
        )
        citation_by_id = self._first_by_id(
            bundle.knowledge_citations, "citation_id"
        )

        issues.extend(
            self._validate_resume_and_job(
                bundle,
                evidence_by_id,
                requirement_by_id,
            )
        )
        issues.extend(
            self._validate_matches(
                bundle,
                evidence_by_id,
                requirement_by_id,
                clarification_by_id,
            )
        )
        issues.extend(
            self._validate_advisory_references(
                bundle,
                evidence_by_id,
                requirement_by_id,
                citation_by_id,
            )
        )
        issues.extend(
            self._validate_clarifications(
                bundle,
                evidence_by_id,
                requirement_by_id,
            )
        )
        issues.extend(
            self._validate_decision_and_versions(bundle, requirement_by_id)
        )
        issues.extend(
            self._validate_knowledge_boundary(bundle, evidence_by_id)
        )
        return ValidationResult(
            valid=not issues,
            issues=issues,
            checked_rules=self.checked_rules,
        )

    def validate_or_raise(self, bundle: JobFitDomainBundle) -> ValidationResult:
        result = self.validate(bundle)
        if not result.valid:
            raise SchemaValidationError(
                code=ErrorCode.SCHEMA_VALIDATION_FAILED,
                user_message="The domain snapshot failed consistency validation.",
                recoverable=False,
            )
        return result

    def _validate_unique_ids(
        self,
        bundle: JobFitDomainBundle,
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        collections = (
            (bundle.evidence, "evidence_id", "DUPLICATE_EVIDENCE_ID"),
            (bundle.requirements, "requirement_id", "DUPLICATE_REQUIREMENT_ID"),
            (bundle.requirement_matches, "match_id", "DUPLICATE_MATCH_ID"),
            (bundle.actions, "action_id", "DUPLICATE_ACTION_ID"),
            (
                bundle.interview_questions,
                "question_id",
                "DUPLICATE_INTERVIEW_QUESTION_ID",
            ),
            (
                bundle.knowledge_citations,
                "citation_id",
                "DUPLICATE_KNOWLEDGE_CITATION_ID",
            ),
            (
                bundle.user_clarifications,
                "clarification_id",
                "DUPLICATE_CLARIFICATION_ID",
            ),
            (bundle.failures, "failure_id", "DUPLICATE_FAILURE_ID"),
        )
        for items, field_name, code in collections:
            counts = Counter(getattr(item, field_name) for item in items)
            for object_id in sorted(
                value for value, count in counts.items() if count > 1
            ):
                issues.append(self._issue(code, object_id, "Object ID is duplicated."))
        return issues

    def _validate_resume_and_job(
        self,
        bundle: JobFitDomainBundle,
        evidence_by_id: dict[str, object],
        requirement_by_id: dict[str, object],
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        resume = bundle.resume_profile
        if resume is not None:
            for evidence_id in resume.evidence_ids:
                if evidence_id not in evidence_by_id:
                    issues.append(
                        self._issue(
                            "DANGLING_RESUME_EVIDENCE_REFERENCE",
                            evidence_id,
                            "Resume profile references unknown evidence.",
                        )
                    )
            for evidence in bundle.evidence:
                if (
                    evidence.resume_version_id is not None
                    and evidence.resume_version_id != resume.resume_version_id
                ):
                    issues.append(
                        self._issue(
                            "EVIDENCE_RESUME_VERSION_MISMATCH",
                            evidence.evidence_id,
                            "Evidence belongs to another resume version.",
                        )
                    )
        job = bundle.job_profile
        if job is not None:
            for requirement_id in job.requirement_ids:
                if requirement_id not in requirement_by_id:
                    issues.append(
                        self._issue(
                            "DANGLING_JOB_REQUIREMENT_REFERENCE",
                            requirement_id,
                            "Job profile references an unknown requirement.",
                        )
                    )
            for requirement in bundle.requirements:
                if (
                    requirement.jd_snapshot_id is not None
                    and requirement.jd_snapshot_id != job.jd_snapshot_id
                ):
                    issues.append(
                        self._issue(
                            "REQUIREMENT_JD_VERSION_MISMATCH",
                            requirement.requirement_id,
                            "Requirement belongs to another JD snapshot.",
                        )
                    )
        return issues

    def _validate_matches(
        self,
        bundle: JobFitDomainBundle,
        evidence_by_id: dict[str, object],
        requirement_by_id: dict[str, object],
        clarification_by_id: dict[str, object],
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        for match in bundle.requirement_matches:
            requirement = requirement_by_id.get(match.requirement_id)
            if requirement is None:
                issues.append(
                    self._issue(
                        "DANGLING_MATCH_REQUIREMENT_REFERENCE",
                        match.match_id,
                        "Requirement match references an unknown requirement.",
                    )
                )
            for matched in match.matched_evidence:
                if matched.evidence_id not in evidence_by_id:
                    issues.append(
                        self._issue(
                            "DANGLING_MATCH_EVIDENCE_REFERENCE",
                            match.match_id,
                            "Requirement match references unknown evidence.",
                        )
                    )
            if match.ability_confirmation_id is not None:
                clarification = clarification_by_id.get(match.ability_confirmation_id)
                if clarification is None:
                    issues.append(
                        self._issue(
                            "DANGLING_ABILITY_CONFIRMATION_REFERENCE",
                            match.match_id,
                            "Ability confirmation references an unknown clarification.",
                        )
                    )
                elif match.requirement_id not in clarification.affected_requirement_ids:
                    issues.append(
                        self._issue(
                            "ABILITY_CONFIRMATION_TARGET_MISMATCH",
                            match.match_id,
                            "Clarification does not target the matched requirement.",
                        )
                    )
            if (
                requirement is not None
                and requirement.requirement_type is RequirementType.IMPLICIT
                and match.match_score_component is not None
            ):
                issues.append(
                    self._issue(
                        "IMPLICIT_REQUIREMENT_SCORE_COMPONENT",
                        match.match_id,
                        "Implicit requirements cannot carry a score component.",
                    )
                )
        return issues

    def _validate_advisory_references(
        self,
        bundle: JobFitDomainBundle,
        evidence_by_id: dict[str, object],
        requirement_by_id: dict[str, object],
        citation_by_id: dict[str, object],
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        for action in bundle.actions:
            issues.extend(
                self._unknown_refs(
                    action.related_requirement_ids,
                    requirement_by_id,
                    "DANGLING_ACTION_REQUIREMENT_REFERENCE",
                    action.action_id,
                )
            )
            issues.extend(
                self._unknown_refs(
                    [*action.related_evidence_ids, *action.supported_by_evidence_ids],
                    evidence_by_id,
                    "DANGLING_ACTION_EVIDENCE_REFERENCE",
                    action.action_id,
                )
            )
        for question in bundle.interview_questions:
            issues.extend(
                self._unknown_refs(
                    question.related_requirement_ids,
                    requirement_by_id,
                    "DANGLING_INTERVIEW_REQUIREMENT_REFERENCE",
                    question.question_id,
                )
            )
            issues.extend(
                self._unknown_refs(
                    question.related_evidence_ids,
                    evidence_by_id,
                    "DANGLING_INTERVIEW_EVIDENCE_REFERENCE",
                    question.question_id,
                )
            )
            issues.extend(
                self._unknown_refs(
                    question.knowledge_citation_ids,
                    citation_by_id,
                    "DANGLING_INTERVIEW_CITATION_REFERENCE",
                    question.question_id,
                )
            )
        for requirement in bundle.requirements:
            issues.extend(
                self._unknown_refs(
                    requirement.knowledge_citation_ids,
                    citation_by_id,
                    "DANGLING_REQUIREMENT_CITATION_REFERENCE",
                    requirement.requirement_id,
                )
            )
        return issues

    def _validate_clarifications(
        self,
        bundle: JobFitDomainBundle,
        evidence_by_id: dict[str, object],
        requirement_by_id: dict[str, object],
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        analysis_id = bundle.analysis_core.analysis_id if bundle.analysis_core else None
        for clarification in bundle.user_clarifications:
            if analysis_id is not None and clarification.analysis_id != analysis_id:
                issues.append(
                    self._issue(
                        "CLARIFICATION_ANALYSIS_ID_MISMATCH",
                        clarification.clarification_id,
                        "Clarification belongs to another analysis.",
                    )
                )
            issues.extend(
                self._unknown_refs(
                    clarification.affected_requirement_ids,
                    requirement_by_id,
                    "DANGLING_CLARIFICATION_REQUIREMENT_REFERENCE",
                    clarification.clarification_id,
                )
            )
            issues.extend(
                self._unknown_refs(
                    clarification.affected_evidence_ids,
                    evidence_by_id,
                    "DANGLING_CLARIFICATION_EVIDENCE_REFERENCE",
                    clarification.clarification_id,
                )
            )
            for evidence_id in clarification.created_evidence_ids:
                evidence = evidence_by_id.get(evidence_id)
                if evidence is None:
                    issues.append(
                        self._issue(
                            "DANGLING_CLARIFICATION_CREATED_EVIDENCE_REFERENCE",
                            clarification.clarification_id,
                            "Clarification-created evidence does not exist.",
                        )
                    )
                elif (
                    evidence.source_origin
                    is not EvidenceSourceOrigin.USER_CLARIFICATION
                    or evidence.source_record_id != clarification.clarification_id
                ):
                    issues.append(
                        self._issue(
                            "CLARIFICATION_EVIDENCE_SOURCE_MISMATCH",
                            clarification.clarification_id,
                            "Clarification evidence has an invalid source identity.",
                        )
                    )
        return issues

    def _validate_decision_and_versions(
        self,
        bundle: JobFitDomainBundle,
        requirement_by_id: dict[str, object],
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        core = bundle.analysis_core
        if core is not None:
            if (
                bundle.resume_profile is not None
                and core.resume_version_id != bundle.resume_profile.resume_version_id
            ):
                issues.append(
                    self._issue(
                        "ANALYSIS_RESUME_VERSION_MISMATCH",
                        core.analysis_id,
                        "Analysis references another resume version.",
                    )
                )
            if (
                bundle.job_profile is not None
                and core.jd_snapshot_id != bundle.job_profile.jd_snapshot_id
            ):
                issues.append(
                    self._issue(
                        "ANALYSIS_JD_VERSION_MISMATCH",
                        core.analysis_id,
                        "Analysis references another JD snapshot.",
                    )
                )
            guarded_ids = {
                *core.critical_gap_requirement_ids,
                *core.hard_blocker_ids,
                *core.hard_pending_ids,
            }
            for requirement_id in sorted(guarded_ids):
                requirement = requirement_by_id.get(requirement_id)
                if requirement is None:
                    issues.append(
                        self._issue(
                            "DANGLING_ANALYSIS_REQUIREMENT_REFERENCE",
                            core.analysis_id,
                            "Analysis decision references an unknown requirement.",
                        )
                    )
                elif (
                    requirement.requirement_type is RequirementType.IMPLICIT
                    or requirement.source is RequirementSource.KNOWLEDGE
                ):
                    issues.append(
                        self._issue(
                            "IMPLICIT_REQUIREMENT_DECISION_GUARD",
                            requirement_id,
                            "Implicit knowledge cannot enter core decision guards.",
                        )
                    )
            for requirement_id in sorted(
                {*core.hard_blocker_ids, *core.hard_pending_ids}
            ):
                requirement = requirement_by_id.get(requirement_id)
                if requirement is not None and (
                    requirement.requirement_type is not RequirementType.HARD
                    or requirement.source is not RequirementSource.JD
                ):
                    issues.append(
                        self._issue(
                            "HARD_GUARD_REQUIREMENT_TYPE_INVALID",
                            requirement_id,
                            "Hard guards must reference explicit JD hard requirements.",
                        )
                    )
            for requirement_id in sorted(core.critical_gap_requirement_ids):
                requirement = requirement_by_id.get(requirement_id)
                if requirement is not None and (
                    requirement.requirement_type is not RequirementType.CORE
                    or requirement.importance is not Importance.CRITICAL
                    or requirement.critical_status is not CriticalStatus.CONFIRMED
                ):
                    issues.append(
                        self._issue(
                            "CRITICAL_GAP_REQUIREMENT_INVALID",
                            requirement_id,
                            "Critical gaps must reference confirmed critical core requirements.",
                        )
                    )
        if (
            bundle.report is not None
            and core is not None
            and bundle.report.analysis_id != core.analysis_id
        ):
            issues.append(
                self._issue(
                    "REPORT_ANALYSIS_ID_MISMATCH",
                    bundle.report.report_id,
                    "Report belongs to another analysis.",
                )
            )
        if (
            bundle.analysis_lifecycle is not None
            and core is not None
            and bundle.analysis_lifecycle.analysis_id != core.analysis_id
        ):
            issues.append(
                self._issue(
                    "LIFECYCLE_ANALYSIS_ID_MISMATCH",
                    bundle.analysis_lifecycle.analysis_id,
                    "Lifecycle belongs to another analysis.",
                )
            )
        if bundle.versions is not None:
            for citation in bundle.knowledge_citations:
                if citation.knowledge_version != bundle.versions.knowledge_version:
                    issues.append(
                        self._issue(
                            "KNOWLEDGE_VERSION_MISMATCH",
                            citation.citation_id,
                            "Citation belongs to another knowledge version.",
                        )
                    )
        return issues

    def _validate_knowledge_boundary(
        self,
        bundle: JobFitDomainBundle,
        evidence_by_id: dict[str, object],
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        evidence_ids = set(evidence_by_id)
        for citation in bundle.knowledge_citations:
            if citation.citation_id in evidence_ids:
                issues.append(
                    self._issue(
                        "KNOWLEDGE_CANDIDATE_EVIDENCE_COLLISION",
                        citation.citation_id,
                        "Knowledge citation cannot share candidate evidence identity.",
                    )
                )
            if (
                citation.role_family is not None
                and bundle.job_profile is not None
                and citation.role_family != bundle.job_profile.job_family
            ):
                issues.append(
                    self._issue(
                        "KNOWLEDGE_ROLE_FAMILY_MISMATCH",
                        citation.citation_id,
                        "Citation belongs to another role family.",
                    )
                )
        return issues

    @staticmethod
    def _first_by_id(items: Iterable[object], field_name: str) -> dict[str, object]:
        result: dict[str, object] = {}
        for item in items:
            result.setdefault(getattr(item, field_name), item)
        return result

    def _unknown_refs(
        self,
        references: Iterable[str],
        registry: dict[str, object],
        code: str,
        object_ref: str,
    ) -> list[ValidationIssue]:
        return [
            self._issue(code, object_ref, "Object references an unknown identity.")
            for reference in references
            if reference not in registry
        ]

    @staticmethod
    def _issue(code: str, object_ref: str, message: str) -> ValidationIssue:
        return ValidationIssue(
            code=code,
            severity=ValidationSeverity.ERROR,
            message=message,
            object_ref=object_ref,
        )
