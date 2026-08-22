"""Final anti-fabrication validation for resume rewrite suggestions."""

from __future__ import annotations

import re
from collections.abc import Sequence

from jobfit.models import (
    EvidenceRegistry,
    EvidenceSourceType,
    JobRequirement,
    RewriteSuggestion,
    ValidationIssue,
    ValidationResult,
    ValidationSeverity,
)

_NUMBER = re.compile(r"(?<![A-Za-z])\d+(?:\.\d+)?%?")
_DATE = re.compile(
    r"(?:19|20)\d{2}(?:[-/.年](?:0?[1-9]|1[0-2])"
    r"(?:[-/.月](?:0?[1-9]|[12]\d|3[01])日?)?)?"
)
_MONEY = re.compile(
    r"(?:[$¥￥]\s*\d+(?:\.\d+)?(?:万|百万|亿)?"
    r"|\d+(?:\.\d+)?\s*(?:元|万元|美元|人民币))",
    re.IGNORECASE,
)
_ORGANIZATION = re.compile(
    r"[A-Za-z\u4e00-\u9fff]{2,24}(?:公司|大学|学院|实验室|研究院|客户)"
)
_TEAM_SIZE = re.compile(r"\d+\s*(?:人|名成员|人团队)")
_TECH_TERMS = {
    "aws",
    "azure",
    "django",
    "docker",
    "excel",
    "fastapi",
    "flask",
    "gcp",
    "git",
    "hadoop",
    "java",
    "kubernetes",
    "langchain",
    "linux",
    "llamaindex",
    "mongodb",
    "mysql",
    "numpy",
    "pandas",
    "postgres",
    "powerbi",
    "pytorch",
    "react",
    "redis",
    "scikit-learn",
    "sklearn",
    "spark",
    "sql",
    "streamlit",
    "tableau",
    "tensorflow",
    "vue",
}
_ROLE_ESCALATION = ("主导", "负责", "独立完成", "管理", "带领", "领导")
_DELIVERY_ESCALATION = (
    "上线",
    "部署",
    "生产环境",
    "商业化",
    "商业项目",
    "客户落地",
)
_METRIC_TERMS = (
    "准确率",
    "效率提升",
    "效率提高",
    "增长",
    "降低",
    "转化率",
    "收入",
    "用户量",
)
_AWARD_CERTIFICATE_TERMS = (
    "获奖",
    "一等奖",
    "二等奖",
    "三等奖",
    "证书",
    "认证",
)
_SKILL_ESCALATION = ("熟练掌握", "精通", "专家")


class RewriteValidator:
    """Validate one final rewrite without changing its content."""

    checked_rules = [
        "rewrite_requirement_reference",
        "rewrite_evidence_reference",
        "rewrite_original_traceability",
        "rewrite_claim_detection",
        "rewrite_confirmation_consistency",
        "rewrite_direct_collection_boundary",
    ]

    def validate(
        self,
        suggestion: RewriteSuggestion,
        registry: EvidenceRegistry,
        requirements: Sequence[JobRequirement],
        *,
        direct: bool = False,
    ) -> ValidationResult:
        issues: list[ValidationIssue] = []
        requirement_ids = {item.requirement_id for item in requirements}
        unknown_requirements = sorted(
            set(suggestion.requirement_ids) - requirement_ids
        )
        if unknown_requirements:
            issues.append(
                self._error(
                    "REWRITE_REQUIREMENT_UNKNOWN",
                    suggestion.suggestion_id,
                    "改写建议引用了不存在的岗位要求。",
                )
            )

        evidence = []
        for evidence_id in suggestion.evidence_ids:
            try:
                item = registry.get(evidence_id)
            except KeyError:
                issues.append(
                    self._error(
                        "REWRITE_EVIDENCE_UNKNOWN",
                        suggestion.suggestion_id,
                        "改写建议引用了不存在的简历证据。",
                    )
                )
                continue
            if item.source_type is not EvidenceSourceType.RESUME:
                issues.append(
                    self._error(
                        "REWRITE_EVIDENCE_SOURCE_INVALID",
                        suggestion.suggestion_id,
                        "改写建议只能引用简历证据。",
                    )
                )
                continue
            evidence.append(item)

        if evidence and not any(
            suggestion.original_text == item.quote for item in evidence
        ):
            issues.append(
                self._error(
                    "REWRITE_ORIGINAL_UNTRACEABLE",
                    suggestion.suggestion_id,
                    "改写原文无法由引用证据精确回溯。",
                )
            )

        evidence_text = "\n".join(item.quote for item in evidence)
        detected_claims = detect_new_claims(
            suggestion.original_text,
            evidence_text,
            suggestion.rewritten_text,
        )
        declared = suggestion.introduced_claims
        confirmations = suggestion.user_confirmation_needed
        if detected_claims and not declared:
            issues.append(
                self._error(
                    "REWRITE_CLAIMS_UNDECLARED",
                    suggestion.suggestion_id,
                    "改写包含未写入introduced_claims的新增事实。",
                )
            )
        if declared and not confirmations:
            issues.append(
                self._error(
                    "REWRITE_CONFIRMATION_MISSING",
                    suggestion.suggestion_id,
                    "新增主张缺少对应的用户确认事项。",
                )
            )
        if confirmations and not declared:
            issues.append(
                self._error(
                    "REWRITE_CONFIRMATION_WITHOUT_CLAIM",
                    suggestion.suggestion_id,
                    "用户确认事项没有对应的新增主张。",
                )
            )
        has_risk = bool(detected_claims or declared or confirmations)
        if direct and has_risk:
            issues.append(
                self._error(
                    "REWRITE_DIRECT_HIGH_RISK",
                    suggestion.suggestion_id,
                    "含新增主张的改写不能进入可直接采用集合。",
                )
            )
        elif has_risk and declared and confirmations:
            issues.append(
                ValidationIssue(
                    code="REWRITE_CONFIRMATION_REQUIRED",
                    severity=ValidationSeverity.WARNING,
                    message="该改写仅可在用户确认新增主张后采用。",
                    object_ref=suggestion.suggestion_id,
                )
            )

        return self._result(issues)

    def _result(self, issues: list[ValidationIssue]) -> ValidationResult:
        return ValidationResult(
            valid=not any(
                issue.severity is ValidationSeverity.ERROR for issue in issues
            ),
            issues=issues,
            checked_rules=self.checked_rules,
        )

    @staticmethod
    def _error(
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


def detect_new_claims(
    original_text: str,
    evidence_text: str,
    rewritten_text: str,
) -> list[str]:
    """Return normalized claim descriptions absent from the evidence source."""

    source = f"{original_text}\n{evidence_text}"
    source_lower = source.casefold()
    rewritten_lower = rewritten_text.casefold()
    claims: list[str] = []

    source_dates = set(_DATE.findall(source))
    source_money = set(_MONEY.findall(source))
    source_team_sizes = set(_TEAM_SIZE.findall(source))
    for value in _DATE.findall(rewritten_text):
        if value not in source_dates:
            claims.append(f"新增日期：{value}")
    for value in _MONEY.findall(rewritten_text):
        if value not in source_money:
            claims.append(f"新增金额：{value}")
    for value in _TEAM_SIZE.findall(rewritten_text):
        if value not in source_team_sizes:
            claims.append(f"新增团队规模：{value}")

    protected_values = {
        *source_dates,
        *source_money,
        *source_team_sizes,
    }
    source_numbers = set(_NUMBER.findall(source))
    for value in _NUMBER.findall(rewritten_text):
        if value not in source_numbers and not any(
            value in protected for protected in protected_values
        ):
            claims.append(f"新增数字或量化指标：{value}")

    source_tech = {term for term in _TECH_TERMS if term in source_lower}
    for term in sorted(_TECH_TERMS):
        if term in rewritten_lower and term not in source_tech:
            claims.append(f"新增技术或框架：{term}")

    for value in _ORGANIZATION.findall(rewritten_text):
        if value not in source:
            claims.append(f"新增组织或客户：{value}")
    for term in _ROLE_ESCALATION:
        if term in rewritten_text and term not in source:
            claims.append(f"职责级别强化：{term}")
    for term in _DELIVERY_ESCALATION:
        if term in rewritten_text and term not in source:
            claims.append(f"新增落地状态：{term}")
    for term in _METRIC_TERMS:
        if term in rewritten_text and term not in source:
            claims.append(f"新增成果指标：{term}")
    for term in _AWARD_CERTIFICATE_TERMS:
        if term in rewritten_text and term not in source:
            claims.append(f"新增获奖或证书：{term}")
    for term in _SKILL_ESCALATION:
        if term in rewritten_text and term not in source:
            claims.append(f"能力等级强化：{term}")
    return list(dict.fromkeys(claims))
