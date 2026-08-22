"""Report-level invariants for compact job-knowledge metadata."""

from __future__ import annotations

import json
import re

from jobfit.models import (
    AnalysisReport,
    KnowledgeRetrievalStatus,
    ReportCitationStatus,
    ValidationIssue,
    ValidationSeverity,
)

_SENSITIVE = (
    re.compile(r"[A-Za-z]:\\(?:Users|Documents|Desktop)\\", re.IGNORECASE),
    re.compile(r"/(?:Users|home)/[^/\s]+/"),
    re.compile(r"\b(?:select\s+.+\s+from|insert\s+into|delete\s+from)\b", re.I),
    re.compile(r"##\s*(?:System|User)\b", re.I),
)


class KnowledgeReportValidator:
    """Validate knowledge provenance without treating it as resume evidence."""

    checked_rules = ["knowledge_report_consistency"]

    def validate(self, report: AnalysisReport) -> list[ValidationIssue]:
        section = report.knowledge
        issues: list[ValidationIssue] = []
        if report.schema_version == "1.0":
            if section is not None:
                issues.append(self._error("KNOWLEDGE_SCHEMA_VERSION_INVALID"))
            return issues
        if section is None:
            return [self._error("KNOWLEDGE_SECTION_REQUIRED")]

        status = section.status
        if status is KnowledgeRetrievalStatus.AVAILABLE:
            if (
                not section.enabled
                or section.knowledge_version_id is None
                or section.knowledge_version is None
                or section.knowledge_content_hash is None
                or section.selected_role_profile is None
            ):
                issues.append(self._error("KNOWLEDGE_REPORT_IDENTITY_INVALID"))
        elif status is KnowledgeRetrievalStatus.DISABLED:
            if section.enabled or self._has_role_content(section):
                issues.append(self._error("KNOWLEDGE_DISABLED_PAYLOAD_INVALID"))
        elif status is KnowledgeRetrievalStatus.AMBIGUOUS:
            if len(section.role_candidates) < 2 or self._has_role_content(section):
                issues.append(self._error("KNOWLEDGE_AMBIGUOUS_PAYLOAD_INVALID"))
        elif status is KnowledgeRetrievalStatus.NO_MATCH:
            if self._has_role_content(section):
                issues.append(self._error("KNOWLEDGE_NO_MATCH_PAYLOAD_INVALID"))
        elif status is KnowledgeRetrievalStatus.UNAVAILABLE and (
            self._has_role_content(section)
            or any(
                (
                    section.knowledge_version_id,
                    section.knowledge_version,
                    section.knowledge_content_hash,
                )
            )
        ):
            issues.append(self._error("KNOWLEDGE_UNAVAILABLE_PAYLOAD_INVALID"))

        citation_ids = [item.citation_id for item in section.citations]
        if len(citation_ids) != len(set(citation_ids)):
            issues.append(self._error("KNOWLEDGE_CITATION_DUPLICATE"))
        known = set(citation_ids)
        selected_id = (
            section.selected_role_profile.role_profile_id
            if section.selected_role_profile
            else None
        )
        for citation in section.citations:
            if citation.knowledge_version_id != section.knowledge_version_id:
                issues.append(self._error("KNOWLEDGE_CITATION_VERSION_MISMATCH"))
            if citation.role_profile_id != selected_id:
                issues.append(self._error("KNOWLEDGE_CITATION_ROLE_MISMATCH"))
            if citation.validation_status is ReportCitationStatus.VALIDATED_ADVICE:
                if not citation.used_by:
                    issues.append(self._error("KNOWLEDGE_CITATION_USAGE_INVALID"))
                for target in citation.used_by:
                    if not self._target_exists(target, report):
                        issues.append(self._error("KNOWLEDGE_CITATION_TARGET_INVALID"))
            elif citation.used_by:
                issues.append(self._error("KNOWLEDGE_CITATION_USAGE_INVALID"))

        referenced = {
            citation_id
            for item in (
                *section.requirements,
                *section.evidence_patterns,
                *section.interview_references,
            )
            for citation_id in item.citation_ids
        }
        if not referenced.issubset(known):
            issues.append(self._error("KNOWLEDGE_CITATION_UNKNOWN"))
        if section.advice_trace is not None:
            if section.advice_trace.used_citation_ids != sorted(
                set(section.advice_trace.used_citation_ids)
            ):
                issues.append(self._error("KNOWLEDGE_CITATION_DUPLICATE"))
            if not set(section.advice_trace.used_citation_ids).issubset(known):
                issues.append(self._error("KNOWLEDGE_CITATION_UNKNOWN"))
            validated_citation_ids = {
                item.citation_id
                for item in section.citations
                if item.validation_status is ReportCitationStatus.VALIDATED_ADVICE
            }
            if set(section.advice_trace.used_citation_ids) != validated_citation_ids:
                issues.append(self._error("KNOWLEDGE_CITATION_USAGE_INVALID"))
            if section.fallback_used != section.advice_trace.fallback_used:
                issues.append(self._error("KNOWLEDGE_FALLBACK_STATE_INVALID"))
            if section.advice_trace.fallback_used and (
                section.advice_trace.validated
                or section.advice_trace.used_citation_ids
            ):
                issues.append(self._error("KNOWLEDGE_FALLBACK_CITATION_INVALID"))
            if (
                not section.advice_trace.fallback_used
                and not section.advice_trace.validated
            ):
                issues.append(self._error("KNOWLEDGE_ADVICE_TRACE_INVALID"))

        resume_evidence_ids = {
            item.evidence_id
            for match in report.matches
            for item in match.evidence_items
        }
        resume_evidence_ids.update(
            evidence_id
            for item in report.strengths
            for evidence_id in item.evidence_ids
        )
        resume_evidence_ids.update(
            evidence_id
            for item in report.rewrite_suggestions
            for evidence_id in item.evidence_ids
        )
        resume_evidence_ids.update(
            evidence_id
            for item in report.interview_questions
            for evidence_id in item.resume_evidence_ids
        )
        if known.intersection(resume_evidence_ids):
            issues.append(self._error("KNOWLEDGE_CITATION_AS_RESUME_EVIDENCE"))
        scored_ids = {item.requirement_id for item in report.job_profile.requirements.items}
        knowledge_ids = {
            item.knowledge_requirement_id for item in section.requirements
        }
        if scored_ids.intersection(knowledge_ids):
            issues.append(self._error("KNOWLEDGE_REQUIREMENT_SCORING_COLLISION"))

        payload = json.dumps(section.model_dump(mode="json"), ensure_ascii=False)
        if any(pattern.search(payload.replace("\\\\", "\\")) for pattern in _SENSITIVE):
            issues.append(self._error("KNOWLEDGE_REPORT_SENSITIVE_CONTENT"))
        return issues

    @staticmethod
    def _has_role_content(section) -> bool:
        return any(
            (
                section.selected_role_profile,
                section.requirements,
                section.evidence_patterns,
                section.interview_references,
                section.citations,
                section.advice_trace,
            )
        )

    @staticmethod
    def _target_exists(reference: str, report: AnalysisReport) -> bool:
        kind, _, raw_index = reference.partition(":")
        if not raw_index.isdigit():
            return False
        index = int(raw_index)
        limits = {
            "gap": len(report.gaps),
            "recommendation": 1,
            "rewrite": len(report.rewrite_suggestions),
            "interview_question": len(report.interview_questions),
        }
        return kind in limits and index < limits[kind]

    @staticmethod
    def _error(code: str) -> ValidationIssue:
        return ValidationIssue(
            code=code,
            severity=ValidationSeverity.ERROR,
            message="岗位知识报告元数据未通过一致性校验。",
            object_ref="knowledge",
        )


__all__ = ["KnowledgeReportValidator"]
