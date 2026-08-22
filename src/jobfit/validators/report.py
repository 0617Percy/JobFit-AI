"""Cross-module validation and immutable AnalysisReport assembly."""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal

from jobfit.errors import ErrorCode, JobFitError, ReportGenerationError
from jobfit.generators import GeneratedAdvice
from jobfit.generators.common import normalized_phrase
from jobfit.generators.interview import finalize_questions
from jobfit.models import (
    AnalysisReport,
    BasicInfo,
    DocumentContent,
    EvidenceRegistry,
    GapRemediability,
    HardConditionKind,
    Importance,
    InterviewQuestionDraft,
    JobProfile,
    KnowledgeAdviceTrace,
    KnowledgeContext,
    MatchScoreSummary,
    MatchStatus,
    RecommendationLevel,
    RequirementMatch,
    ResumeProfile,
    ValidationIssue,
    ValidationResult,
    ValidationSeverity,
)
from jobfit.reporting.knowledge import build_report_knowledge_section
from jobfit.scoring import ScoringEngine
from jobfit.validators.evidence import EvidenceValidator
from jobfit.validators.report_knowledge import KnowledgeReportValidator
from jobfit.validators.rewrite import RewriteValidator

_UNKNOWN_DEFINITIVE = (
    "一定不会",
    "确定不会",
    "不具备",
    "没有能力",
    "无法胜任",
    "明确不满足",
)
_UPGRADE_LANGUAGE = (
    "强烈建议优先投递",
    "建议优先投递",
    "应当优先投递",
)
_SPECIFIC_RESULT = re.compile(
    r"(?:\d+(?:\.\d+)?%?|[$¥￥]\s*\d+|\d+\s*(?:元|万元|用户|人))"
)
_SENSITIVE_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._-]{16,}", re.IGNORECASE),
    re.compile(r"[A-Za-z]:\\(?:Users|Documents|Desktop)\\", re.IGNORECASE),
    re.compile(r"/(?:Users|home)/[^/\s]+/"),
    re.compile(r"##\s*(?:System|User)\b", re.IGNORECASE),
)
_DEFAULT_LIMITATIONS = [
    "匹配分数由确定性规则计算，不代表真实录用概率。",
    "unknown仅表示当前简历未提供足够证据，不代表用户一定不具备该能力。",
    "所有需确认的改写必须由用户核实后才能写入简历。",
]


class ReportValidator:
    """Recompute evidence and scoring invariants before report creation."""

    checked_rules = [
        "evidence_grounding",
        "deterministic_score_recomputation",
        "recommendation_consistency",
        "strength_and_gap_consistency",
        "rewrite_anti_fabrication",
        "interview_set_consistency",
        "report_safety_and_limitations",
    ]

    def __init__(
        self,
        *,
        evidence_validator: EvidenceValidator | None = None,
        scoring_engine: ScoringEngine | None = None,
        rewrite_validator: RewriteValidator | None = None,
        knowledge_report_validator: KnowledgeReportValidator | None = None,
    ) -> None:
        self._evidence = evidence_validator or EvidenceValidator()
        self._scoring = scoring_engine or ScoringEngine()
        self._rewrite = rewrite_validator or RewriteValidator()
        self._knowledge_report = (
            knowledge_report_validator or KnowledgeReportValidator()
        )

    def validate_components(
        self,
        *,
        document: DocumentContent,
        resume: ResumeProfile,
        job: JobProfile,
        matches: Sequence[RequirementMatch],
        score: MatchScoreSummary,
        advice: GeneratedAdvice,
        registry: EvidenceRegistry,
        limitations: Sequence[str],
    ) -> ValidationResult:
        issues: list[ValidationIssue] = []
        evidence_result = self._evidence.validate_matches(
            document,
            registry,
            job.requirements.items,
            matches,
        )
        issues.extend(evidence_result.issues)
        issues.extend(self._validate_score(job, matches, score))
        issues.extend(self._validate_recommendation(job, score, advice))
        issues.extend(self._validate_strengths(job, matches, advice, registry))
        issues.extend(self._validate_gaps(job, matches, advice))
        issues.extend(self._validate_rewrites(job, advice, registry))
        issues.extend(self._validate_interviews(job, advice, registry))
        if resume.document_id != document.document_id:
            issues.append(
                self._error(
                    "REPORT_DOCUMENT_MISMATCH",
                    "resume_profile",
                    "简历档案与证据文档不一致。",
                )
            )
        if not limitations or not all(item.strip() for item in limitations):
            issues.append(
                self._error(
                    "LIMITATIONS_REQUIRED",
                    "limitations",
                    "最终报告必须包含非空分析限制。",
                )
            )
        if self._contains_sensitive_content(job, advice, limitations):
            issues.append(
                self._error(
                    "REPORT_SENSITIVE_CONTENT",
                    "report",
                    "报告展示字段包含密钥、Prompt或本地路径特征。",
                )
            )
        issues.append(
            ValidationIssue(
                code="REPORT_VALIDATION_COMPLETED",
                severity=ValidationSeverity.INFO,
                message="已执行最终证据、评分、建议和安全一致性校验。",
                object_ref="report",
            )
        )
        return ValidationResult(
            valid=not any(
                issue.severity is ValidationSeverity.ERROR for issue in issues
            ),
            issues=issues,
            checked_rules=[
                *EvidenceValidator.checked_rules,
                *self.checked_rules,
            ],
        )

    def validate(
        self,
        report: AnalysisReport,
        document: DocumentContent,
        registry: EvidenceRegistry,
    ) -> ValidationResult:
        direct = [
            item
            for item in report.rewrite_suggestions
            if not item.introduced_claims and not item.user_confirmation_needed
        ]
        confirmation = [
            item
            for item in report.rewrite_suggestions
            if item.introduced_claims or item.user_confirmation_needed
        ]
        advice = GeneratedAdvice(
            strengths=report.strengths,
            gaps=report.gaps,
            recommendation=report.recommendation,
            direct_rewrites=direct,
            confirmation_required_rewrites=confirmation,
            interview_questions=report.interview_questions,
        )
        base = self.validate_components(
            document=document,
            resume=report.resume_profile,
            job=report.job_profile,
            matches=report.matches,
            score=report.score_summary,
            advice=advice,
            registry=registry,
            limitations=report.limitations,
        )
        issues = [*base.issues, *self._knowledge_report.validate(report)]
        return ValidationResult(
            valid=not any(
                issue.severity is ValidationSeverity.ERROR for issue in issues
            ),
            issues=issues,
            checked_rules=[
                *base.checked_rules,
                *KnowledgeReportValidator.checked_rules,
            ],
        )

    def validate_knowledge_report(
        self,
        report: AnalysisReport,
    ) -> list[ValidationIssue]:
        return self._knowledge_report.validate(report)

    def _validate_score(
        self,
        job: JobProfile,
        matches: Sequence[RequirementMatch],
        score: MatchScoreSummary,
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        cloned_requirements = [
            item.model_copy(deep=True) for item in job.requirements.items
        ]
        try:
            recomputed = self._scoring.score(cloned_requirements, matches)
        except JobFitError:
            return [
                self._error(
                    "SCORING_RECOMPUTE_FAILED",
                    "score_summary",
                    "匹配结果无法通过确定性评分引擎重新计算。",
                )
            ]

        original_by_id = {
            item.requirement_id: item for item in job.requirements.items
        }
        for item in cloned_requirements:
            original = original_by_id[item.requirement_id]
            if original.priority_factor != item.priority_factor:
                issues.append(
                    self._error(
                        "REQUIREMENT_PRIORITY_FACTOR_MISMATCH",
                        item.requirement_id,
                        "岗位要求优先级因子与确定性重算结果不一致。",
                    )
                )
            if original.weight != item.weight:
                issues.append(
                    self._error(
                        "REQUIREMENT_WEIGHT_MISMATCH",
                        item.requirement_id,
                        "岗位要求权重与确定性重算结果不一致。",
                    )
                )

        comparisons = [
            ("raw_score", "SCORE_RAW_MISMATCH"),
            ("score_cap", "SCORE_CAP_MISMATCH"),
            ("final_score", "SCORE_FINAL_MISMATCH"),
            ("dimension_scores", "SCORE_DIMENSIONS_MISMATCH"),
            (
                "mandatory_coverage_ratio",
                "SCORE_MANDATORY_COVERAGE_MISMATCH",
            ),
            (
                "strong_evidence_coverage_ratio",
                "SCORE_STRONG_EVIDENCE_MISMATCH",
            ),
            ("cap_reasons", "SCORE_CAP_REASONS_MISMATCH"),
            ("recommendation_level", "RECOMMENDATION_LEVEL_MISMATCH"),
        ]
        for field, code in comparisons:
            if getattr(score, field) != getattr(recomputed, field):
                issues.append(
                    self._error(
                        code,
                        f"score_summary.{field}",
                        "评分摘要字段与确定性重算结果不一致。",
                    )
                )
        if (
            score.confirmed_hard_blockers
            != recomputed.confirmed_hard_blockers
            or score.unverified_hard_blockers
            != recomputed.unverified_hard_blockers
        ):
            issues.append(
                self._error(
                    "SCORE_BLOCKERS_MISMATCH",
                    "score_summary.blockers",
                    "评分摘要中的硬门槛列表与重算结果不一致。",
                )
            )
        return issues

    def _validate_recommendation(
        self,
        job: JobProfile,
        score: MatchScoreSummary,
        advice: GeneratedAdvice,
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        recommendation = advice.recommendation
        requirement_ids = {
            item.requirement_id for item in job.requirements.items
        }
        if recommendation.level is not score.recommendation_level:
            issues.append(
                self._error(
                    "REPORT_RECOMMENDATION_LEVEL_MISMATCH",
                    "recommendation.level",
                    "投递建议等级与确定性评分摘要不一致。",
                )
            )
        expected_blockers = list(
            dict.fromkeys(
                [
                    *score.confirmed_hard_blockers,
                    *score.unverified_hard_blockers,
                ]
            )
        )
        if (
            recommendation.blocking_requirement_ids != expected_blockers
            or not set(recommendation.blocking_requirement_ids).issubset(
                requirement_ids
            )
        ):
            issues.append(
                self._error(
                    "REPORT_BLOCKERS_MISMATCH",
                    "recommendation.blocking_requirement_ids",
                    "投递建议阻塞项与评分结果不一致。",
                )
            )
        for requirement_id in score.unverified_hard_blockers:
            if not any(
                requirement_id in action and "确认" in action
                for action in recommendation.before_applying_actions
            ):
                issues.append(
                    self._error(
                        "HARD_CONDITION_CONFIRMATION_MISSING",
                        requirement_id,
                        "待确认硬门槛缺少投递前确认行动。",
                    )
                )
        if (
            score.recommendation_level is not RecommendationLevel.PRIORITY_APPLY
            and any(
                term in statement
                for statement in recommendation.reasoning
                for term in _UPGRADE_LANGUAGE
            )
        ):
            issues.append(
                self._error(
                    "RECOMMENDATION_LANGUAGE_CONFLICT",
                    "recommendation.reasoning",
                    "推荐文案隐含升级了确定性投递等级。",
                )
            )
        return issues

    def _validate_strengths(
        self,
        job: JobProfile,
        matches: Sequence[RequirementMatch],
        advice: GeneratedAdvice,
        registry: EvidenceRegistry,
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        if len(advice.strengths) > 3:
            issues.append(
                self._error(
                    "STRENGTH_LIMIT_EXCEEDED",
                    "strengths",
                    "核心优势不得超过三项。",
                )
            )
        requirement_ids = {
            item.requirement_id for item in job.requirements.items
        }
        match_by_id = {item.requirement_id: item for item in matches}
        signatures: set[tuple[str, tuple[str, ...]]] = set()
        for item in advice.strengths:
            if not set(item.requirement_ids).issubset(requirement_ids):
                issues.append(
                    self._error(
                        "STRENGTH_REQUIREMENT_INVALID",
                        item.title,
                        "优势引用了不存在的岗位要求。",
                    )
                )
                continue
            try:
                registry.require_many(item.evidence_ids)
            except KeyError:
                issues.append(
                    self._error(
                        "STRENGTH_EVIDENCE_INVALID",
                        item.title,
                        "优势引用了不存在的简历证据。",
                    )
                )
                continue
            linked_matches = [
                match_by_id[requirement_id]
                for requirement_id in item.requirement_ids
                if requirement_id in match_by_id
            ]
            if any(
                match.match_status
                not in {MatchStatus.MATCHED, MatchStatus.PARTIAL_MATCH}
                or (
                    match.match_status is MatchStatus.PARTIAL_MATCH
                    and (
                        match.confidence < Decimal("0.70")
                        or not match.evidence_items
                    )
                )
                for match in linked_matches
            ):
                issues.append(
                    self._error(
                        "STRENGTH_STATUS_INVALID",
                        item.title,
                        "优势不是来自充分证据支持的匹配结果。",
                    )
                )
            allowed_evidence = {
                evidence.evidence_id
                for match in linked_matches
                for evidence in match.evidence_items
            }
            if not set(item.evidence_ids).issubset(allowed_evidence):
                issues.append(
                    self._error(
                        "STRENGTH_EVIDENCE_INVALID",
                        item.title,
                        "优势证据不属于对应岗位匹配结果。",
                    )
                )
            signature = (
                normalized_phrase(item.title),
                tuple(sorted(item.evidence_ids)),
            )
            if signature in signatures:
                issues.append(
                    self._error(
                        "STRENGTH_DUPLICATE",
                        item.title,
                        "优势列表重复表达同一能力和证据。",
                    )
                )
            signatures.add(signature)
        return issues

    def _validate_gaps(
        self,
        job: JobProfile,
        matches: Sequence[RequirementMatch],
        advice: GeneratedAdvice,
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        if len(advice.gaps) > 3:
            issues.append(
                self._error(
                    "GAP_LIMIT_EXCEEDED",
                    "gaps",
                    "主要缺口不得超过三项。",
                )
            )
        requirement_by_id = {
            item.requirement_id: item for item in job.requirements.items
        }
        match_by_id = {item.requirement_id: item for item in matches}
        for item in advice.gaps:
            if not set(item.requirement_ids).issubset(requirement_by_id):
                issues.append(
                    self._error(
                        "GAP_REQUIREMENT_INVALID",
                        item.title,
                        "缺口引用了不存在的岗位要求。",
                    )
                )
                continue
            statuses = {
                match_by_id[requirement_id].match_status
                for requirement_id in item.requirement_ids
                if requirement_id in match_by_id
            }
            if MatchStatus.UNKNOWN in statuses and any(
                term in f"{item.title}{item.summary}"
                for term in _UNKNOWN_DEFINITIVE
            ):
                issues.append(
                    self._error(
                        "GAP_UNKNOWN_SEMANTICS_INVALID",
                        item.title,
                        "unknown缺口不能描述为用户确定不具备该能力。",
                    )
                )
            has_hard_condition = any(
                requirement_by_id[requirement_id].hard_condition_kind
                is not HardConditionKind.NONE
                for requirement_id in item.requirement_ids
            )
            if has_hard_condition and (
                item.remediability
                is not GapRemediability.HARD_TO_FIX_SHORT_TERM
                or item.risk_level is not Importance.CRITICAL
            ):
                issues.append(
                    self._error(
                        "GAP_HARD_CONDITION_INCONSISTENT",
                        item.title,
                        "硬门槛缺口必须标记为短期难修复且风险为critical。",
                    )
                )
        return issues

    def _validate_rewrites(
        self,
        job: JobProfile,
        advice: GeneratedAdvice,
        registry: EvidenceRegistry,
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        seen_ids: set[str] = set()
        for direct, items in (
            (True, advice.direct_rewrites),
            (False, advice.confirmation_required_rewrites),
        ):
            for item in items:
                if item.suggestion_id in seen_ids:
                    issues.append(
                        self._error(
                            "REWRITE_ID_DUPLICATE",
                            item.suggestion_id,
                            "改写建议ID重复。",
                        )
                    )
                seen_ids.add(item.suggestion_id)
                result = self._rewrite.validate(
                    item,
                    registry,
                    job.requirements.items,
                    direct=direct,
                )
                issues.extend(result.issues)
        return issues

    def _validate_interviews(
        self,
        job: JobProfile,
        advice: GeneratedAdvice,
        registry: EvidenceRegistry,
    ) -> list[ValidationIssue]:
        try:
            drafts = [
                InterviewQuestionDraft.model_validate(
                    item.model_dump(exclude={"question_id"})
                )
                for item in advice.interview_questions
            ]
            rebuilt = finalize_questions(
                drafts,
                job.requirements.items,
                registry,
                advice.gaps,
            )
            if rebuilt != advice.interview_questions:
                raise ValueError("question IDs or ordering changed")
        except (JobFitError, KeyError, ValueError):
            return [
                self._error(
                    "INTERVIEW_SET_INVALID",
                    "interview_questions",
                    "面试题数量、引用、类型覆盖或稳定ID无效。",
                )
            ]

        issues: list[ValidationIssue] = []
        for question in advice.interview_questions:
            evidence_text = "\n".join(
                registry.get(evidence_id).quote
                for evidence_id in question.resume_evidence_ids
            )
            framework = "\n".join(question.answer_framework)
            unsupported = set(_SPECIFIC_RESULT.findall(framework)) - set(
                _SPECIFIC_RESULT.findall(evidence_text)
            )
            if unsupported:
                issues.append(
                    self._error(
                        "INTERVIEW_ANSWER_UNGROUNDED",
                        question.question_id,
                        "回答框架包含简历证据未支持的具体成果。",
                    )
                )
        return issues

    @staticmethod
    def _contains_sensitive_content(
        job: JobProfile,
        advice: GeneratedAdvice,
        limitations: Sequence[str],
    ) -> bool:
        display_payload = {
            "job": {
                "title": job.title,
                "company": job.company,
                "summary": job.summary,
            },
            "strengths": advice.strengths,
            "gaps": advice.gaps,
            "recommendation": advice.recommendation,
            "rewrites": advice.rewrite_suggestions,
            "questions": advice.interview_questions,
            "limitations": list(limitations),
        }
        text = json.dumps(
            display_payload,
            ensure_ascii=False,
            default=lambda value: value.model_dump(mode="json"),
        )
        unescaped_text = text.replace("\\\\", "\\")
        return any(pattern.search(unescaped_text) for pattern in _SENSITIVE_PATTERNS)

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


def build_analysis_report(
    *,
    document: DocumentContent,
    resume: ResumeProfile,
    job: JobProfile,
    matches: Sequence[RequirementMatch],
    score: MatchScoreSummary,
    advice: GeneratedAdvice,
    registry: EvidenceRegistry,
    limitations: Sequence[str] | None = None,
    report_id: str | None = None,
    generated_at: datetime | None = None,
    validator: ReportValidator | None = None,
    knowledge_context: KnowledgeContext | None = None,
    knowledge_advice_trace: KnowledgeAdviceTrace | None = None,
) -> AnalysisReport:
    """Validate all inputs and build the frozen final report aggregate."""

    final_limitations = (
        list(_DEFAULT_LIMITATIONS)
        if limitations is None
        else list(limitations)
    )
    report_validator = validator or ReportValidator()
    validation = report_validator.validate_components(
        document=document,
        resume=resume,
        job=job,
        matches=matches,
        score=score,
        advice=advice,
        registry=registry,
        limitations=final_limitations,
    )
    if not validation.valid:
        raise ReportGenerationError(
            code=ErrorCode.REPORT_VALIDATION_FAILED,
            user_message="最终报告未通过一致性校验，已禁止生成和下载。",
            recoverable=True,
        )

    safe_job = job.model_copy(
        deep=True,
        update={"jd_text": "[完整JD原文已从最终报告中省略]"},
    )
    safe_resume = resume.model_copy(
        deep=True,
        update={
            "basic_info": BasicInfo(
                target_title=resume.basic_info.target_title,
                evidence_ids=resume.basic_info.evidence_ids,
            )
        },
    )
    timestamp = generated_at or datetime.now(UTC)
    knowledge = build_report_knowledge_section(
        knowledge_context,
        knowledge_advice_trace,
        advice,
    )
    report = AnalysisReport(
        schema_version="1.1",
        report_id=report_id or f"report-{uuid.uuid4().hex}",
        generated_at=timestamp,
        job_profile=safe_job,
        resume_profile=safe_resume,
        matches=list(matches),
        score_summary=score,
        strengths=advice.strengths,
        gaps=advice.gaps,
        recommendation=advice.recommendation,
        rewrite_suggestions=advice.rewrite_suggestions,
        interview_questions=advice.interview_questions,
        limitations=final_limitations,
        validation=validation,
        knowledge=knowledge,
    )
    knowledge_issues = report_validator.validate_knowledge_report(report)
    if any(
        issue.severity is ValidationSeverity.ERROR for issue in knowledge_issues
    ):
        raise ReportGenerationError(
            code=ErrorCode.REPORT_VALIDATION_FAILED,
            user_message="岗位知识报告未通过一致性校验，已禁止生成和下载。",
            recoverable=True,
        )
    combined_validation = ValidationResult(
        valid=True,
        issues=[*validation.issues, *knowledge_issues],
        checked_rules=[
            *validation.checked_rules,
            *KnowledgeReportValidator.checked_rules,
        ],
    )
    return report.model_copy(update={"validation": combined_validation})
