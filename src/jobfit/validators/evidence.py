"""Pure local validation for requirement coverage and resume evidence grounding."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from typing import Any

from jobfit.errors import ErrorCode, SchemaValidationError
from jobfit.models import (
    DocumentContent,
    EvidenceKind,
    EvidenceRegistry,
    EvidenceSourceType,
    JobRequirement,
    MatchStatus,
    RequirementMatch,
    ValidationIssue,
    ValidationResult,
    ValidationSeverity,
)
from jobfit.scoring.policy import STATUS_VALUES

_UNKNOWN_DEFINITIVE_PATTERNS = (
    "用户不会",
    "用户不具备",
    "候选人不会",
    "候选人不具备",
    "does not have",
    "cannot",
)
_NEGATION_PATTERN = re.compile(
    r"(没有|无|未曾|不具备|不熟悉|不会|no\b|not\b|without\b)",
    re.IGNORECASE,
)
_PRODUCTION_MARKERS = ("生产", "上线", "部署", "production", "deployed")
_LEARNING_MARKERS = ("课程", "学习", "实验", "course", "tutorial", "class")
_AFFIRMATIVE_UNSUPPORTED_TERMS = ("主导", "负责", "独立完成")
_NUMBER_PATTERN = re.compile(r"\d+(?:\.\d+)?")
_ASCII_SKILL_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9.+#-]{1,}")


class EvidenceValidator:
    """Validate matches without mutating model judgments or guessing repairs."""

    checked_rules = [
        "requirement_id_coverage",
        "status_score_mapping",
        "evidence_registry_reference",
        "resume_document_source",
        "evidence_character_range",
        "status_evidence_minimum",
        "reasoning_source_boundary",
        "unknown_semantic_boundary",
    ]

    def validate_matches(
        self,
        document: DocumentContent,
        registry: EvidenceRegistry,
        requirements: Sequence[JobRequirement],
        matches: Sequence[RequirementMatch],
    ) -> ValidationResult:
        issues: list[ValidationIssue] = []
        expected_ids = [item.requirement_id for item in requirements]
        actual_ids = [item.requirement_id for item in matches]
        counts = Counter(actual_ids)

        for requirement_id, count in sorted(counts.items()):
            if count > 1:
                issues.append(
                    self._issue(
                        "REQUIREMENT_DUPLICATE",
                        requirement_id,
                        "同一岗位要求出现了多个匹配结果。",
                    )
                )
        for requirement_id in sorted(set(actual_ids) - set(expected_ids)):
            issues.append(
                self._issue(
                    "REQUIREMENT_UNKNOWN",
                    requirement_id,
                    "匹配结果引用了未知岗位要求。",
                )
            )
        for requirement_id in sorted(set(expected_ids) - set(actual_ids)):
            issues.append(
                self._issue(
                    "REQUIREMENT_MISSING",
                    requirement_id,
                    "岗位要求缺少匹配结果。",
                )
            )

        requirement_by_id = {item.requirement_id: item for item in requirements}
        for match in matches:
            requirement = requirement_by_id.get(match.requirement_id)
            if requirement is None:
                continue
            issues.extend(
                self._validate_match(
                    document,
                    registry,
                    requirement,
                    match,
                )
            )

        return ValidationResult(
            valid=not issues,
            issues=issues,
            checked_rules=self.checked_rules,
        )

    def validate_or_raise(
        self,
        document: DocumentContent,
        registry: EvidenceRegistry,
        requirements: Sequence[JobRequirement],
        matches: Sequence[RequirementMatch],
    ) -> ValidationResult:
        result = self.validate_matches(document, registry, requirements, matches)
        if not result.valid:
            raise SchemaValidationError(
                code=ErrorCode.EVIDENCE_INVALID,
                user_message="岗位匹配结果未通过本地证据校验，请重试。",
                recoverable=True,
            )
        return result

    def _validate_match(
        self,
        document: DocumentContent,
        registry: EvidenceRegistry,
        requirement: JobRequirement,
        match: RequirementMatch,
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        if match.match_score != STATUS_VALUES[match.match_status]:
            issues.append(
                self._issue(
                    "MATCH_SCORE_INVALID",
                    match.requirement_id,
                    "匹配状态分值不符合本地固定映射。",
                )
            )

        valid_evidence = []
        for evidence in match.evidence_items:
            evidence_issues = self._validate_evidence(document, registry, evidence)
            issues.extend(
                self._issue(code, match.requirement_id, message)
                for code, message in evidence_issues
            )
            if not evidence_issues:
                valid_evidence.append(evidence)

        if match.match_status is MatchStatus.MATCHED and not any(
            item.evidence_kind is EvidenceKind.DIRECT for item in valid_evidence
        ):
            issues.append(
                self._issue(
                    "EVIDENCE_REQUIRED",
                    match.requirement_id,
                    "完全匹配必须包含至少一条直接简历证据。",
                )
            )
        if match.match_status is MatchStatus.PARTIAL_MATCH and not valid_evidence:
            issues.append(
                self._issue(
                    "EVIDENCE_REQUIRED",
                    match.requirement_id,
                    "部分匹配必须包含至少一条有效简历证据。",
                )
            )
        if (
            match.match_status in {MatchStatus.UNKNOWN, MatchStatus.NOT_MATCHED}
            and not match.missing_evidence_note
        ):
            issues.append(
                self._issue(
                    "MISSING_EVIDENCE_NOTE_REQUIRED",
                    match.requirement_id,
                    "未知或不匹配状态必须说明证据缺失或明确冲突。",
                )
            )

        evidence_text = "\n".join(item.quote for item in valid_evidence)
        issues.extend(self._validate_reasoning(requirement, match, evidence_text))
        return issues

    @staticmethod
    def _validate_evidence(
        document: DocumentContent,
        registry: EvidenceRegistry,
        evidence: Any,
    ) -> list[tuple[str, str]]:
        issues: list[tuple[str, str]] = []
        try:
            canonical = registry.get(evidence.evidence_id)
        except KeyError:
            return [("EVIDENCE_ID_UNKNOWN", "引用的简历证据ID不存在。")]
        if evidence != canonical:
            issues.append(("EVIDENCE_MUTATED", "引用证据与证据注册表不一致。"))
        if evidence.source_type is not EvidenceSourceType.RESUME:
            issues.append(("EVIDENCE_SOURCE_INVALID", "岗位JD不能作为简历证据。"))
        if (
            evidence.document_id != document.document_id
            or canonical.document_id != document.document_id
        ):
            issues.append(("EVIDENCE_DOCUMENT_INVALID", "证据不属于当前简历文档。"))
        if evidence.end_char > len(document.normalized_text):
            issues.append(("EVIDENCE_RANGE_INVALID", "证据字符区间超出简历文本。"))
            return issues
        if document.normalized_text[evidence.start_char : evidence.end_char] != evidence.quote:
            issues.append(("EVIDENCE_RANGE_INVALID", "证据引文与字符区间不一致。"))

        segment = next(
            (
                item
                for item in document.segments
                if item.segment_id == evidence.segment_id
            ),
            None,
        )
        if segment is None:
            issues.append(("EVIDENCE_SEGMENT_INVALID", "证据片段ID不存在。"))
        elif not (
            segment.start_char <= evidence.start_char
            and evidence.end_char <= segment.end_char
            and evidence.source_reference == segment.segment_id
        ):
            issues.append(("EVIDENCE_SEGMENT_INVALID", "证据区间不属于引用片段。"))
        return issues

    def _validate_reasoning(
        self,
        requirement: JobRequirement,
        match: RequirementMatch,
        evidence_text: str,
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        combined_reasoning = "\n".join(
            item for item in (match.reasoning, match.missing_evidence_note) if item
        )
        allowed_claim_source = f"{requirement.requirement_text}\n{evidence_text}"
        unsupported_numbers = set(_NUMBER_PATTERN.findall(combined_reasoning)) - set(
            _NUMBER_PATTERN.findall(allowed_claim_source)
        )
        if unsupported_numbers:
            issues.append(
                self._issue(
                    "UNSUPPORTED_REASONING_CLAIM",
                    match.requirement_id,
                    "判断理由包含证据和岗位要求中不存在的数字。",
                )
            )
        if any(
            term in combined_reasoning and term not in evidence_text
            for term in _AFFIRMATIVE_UNSUPPORTED_TERMS
        ):
            issues.append(
                self._issue(
                    "UNSUPPORTED_REASONING_CLAIM",
                    match.requirement_id,
                    "判断理由包含简历证据未支持的强化表述。",
                )
            )
        if match.match_status is MatchStatus.UNKNOWN and any(
            pattern.casefold() in combined_reasoning.casefold()
            for pattern in _UNKNOWN_DEFINITIVE_PATTERNS
        ):
            issues.append(
                self._issue(
                    "UNKNOWN_SEMANTICS_INVALID",
                    match.requirement_id,
                    "未知状态不能表述为用户确定不具备该能力。",
                )
            )
        if match.match_status in {MatchStatus.MATCHED, MatchStatus.PARTIAL_MATCH}:
            technical_tokens = {
                token.casefold()
                for token in _ASCII_SKILL_PATTERN.findall(
                    requirement.requirement_text
                )
            }
            if technical_tokens and not any(
                token in evidence_text.casefold() for token in technical_tokens
            ):
                issues.append(
                    self._issue(
                        "EVIDENCE_RELEVANCE_INVALID",
                        match.requirement_id,
                        "技术要求的证据未包含对应技术关键词。",
                    )
                )
        if match.match_status is MatchStatus.MATCHED:
            requirement_lower = requirement.requirement_text.casefold()
            evidence_lower = evidence_text.casefold()
            if (
                any(marker in requirement_lower for marker in _PRODUCTION_MARKERS)
                and any(marker in evidence_lower for marker in _LEARNING_MARKERS)
                and not any(marker in evidence_lower for marker in _PRODUCTION_MARKERS)
            ):
                issues.append(
                    self._issue(
                        "EXPERIENCE_LEVEL_UNSUPPORTED",
                        match.requirement_id,
                        "课程或学习证据不能直接证明生产级经验。",
                    )
                )
            skill_tokens = {
                token.casefold()
                for token in _ASCII_SKILL_PATTERN.findall(
                    requirement.requirement_text
                )
            }
            if (
                skill_tokens
                and _NEGATION_PATTERN.search(evidence_text)
                and any(token in evidence_lower for token in skill_tokens)
            ):
                issues.append(
                    self._issue(
                        "NEGATED_EVIDENCE_INVALID",
                        match.requirement_id,
                        "否定证据不能支持完全匹配状态。",
                    )
                )
        return issues

    @staticmethod
    def _issue(
        code: str,
        object_ref: str,
        message: str,
    ) -> ValidationIssue:
        return ValidationIssue(
            code=code,
            severity=ValidationSeverity.ERROR,
            message=message,
            object_ref=object_ref,
        )
