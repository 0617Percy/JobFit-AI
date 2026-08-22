"""Professional Markdown rendering from one validated AnalysisReport."""

from __future__ import annotations

import html
from collections.abc import Iterable
from decimal import Decimal

from jobfit.models import (
    AnalysisReport,
    KnowledgeRetrievalStatus,
    MatchStatus,
    RecommendationLevel,
    RequirementCategory,
)
from jobfit.reporting._guards import ensure_exportable

_RECOMMENDATION_LABELS = {
    RecommendationLevel.PRIORITY_APPLY: "建议优先投递",
    RecommendationLevel.OPTIMIZE_THEN_APPLY: "可以投递，但应先优化简历",
    RecommendationLevel.TRY_APPLY: "可以尝试投递，整体匹配一般",
    RecommendationLevel.NOT_PRIORITY: "不建议作为当前优先岗位",
}
_STATUS_LABELS = {
    MatchStatus.MATCHED: "已匹配",
    MatchStatus.PARTIAL_MATCH: "部分匹配",
    MatchStatus.NOT_MATCHED: "未匹配（存在明确冲突）",
    MatchStatus.UNKNOWN: "无法判断（简历证据不足）",
}
_CATEGORY_LABELS = {
    RequirementCategory.ELIGIBILITY: "硬性条件与基本资格",
    RequirementCategory.TECHNICAL_SKILL: "技术技能",
    RequirementCategory.EXPERIENCE_PROJECT: "项目或经历相关性",
    RequirementCategory.DOMAIN_BUSINESS: "行业与业务能力",
    RequirementCategory.EDUCATION_LANGUAGE: "教育、专业与语言",
    RequirementCategory.COMMUNICATION_KEYWORD: "表达与关键词",
}


def render_markdown(report: AnalysisReport) -> str:
    """Render display-only Markdown without recalculating business results."""

    ensure_exportable(report)
    score = report.score_summary
    recommendation_label = _RECOMMENDATION_LABELS[report.recommendation.level]
    lines = [
        "# JobFit Agent 岗位匹配与简历诊断报告",
        "",
        "## 1. 报告信息与使用说明",
        "",
        f"- 报告 ID：{_inline(report.report_id)}",
        f"- Schema 版本：{_inline(report.schema_version)}",
        f"- 生成时间：{_inline(report.generated_at.isoformat())}",
        "- 本报告基于简历中可追溯证据与目标岗位要求生成。",
        "- 匹配分不是录用概率；总分由确定性规则计算。",
        "- unknown表示简历证据不足，不代表用户一定不具备该能力。",
        "",
        "## 2. 岗位基本信息",
        "",
        f"- 岗位名称：{_inline(report.job_profile.title)}",
        f"- 公司名称：{_inline(report.job_profile.company)}",
        f"- 岗位语言：{_inline(report.job_profile.language.value)}",
        f"- 岗位摘要：{_inline(report.job_profile.summary)}",
        "",
        "## 3. 综合结论",
        "",
        f"- 推荐等级：{recommendation_label}"
        f"（`{report.recommendation.level.value}`）",
        *[
            f"- {_inline(reason)}"
            for reason in report.recommendation.reasoning
        ],
        "",
        "## 4. 综合评分",
        "",
        f"- 最终匹配分：{_points(score.final_score)} / 100",
        f"- 原始匹配分：{_points(score.raw_score)} / 100",
        f"- 分数上限：{_points(score.score_cap)} / 100",
        f"- 必须项覆盖率：{_percent(score.mandatory_coverage_ratio)}",
        f"- 强证据覆盖率：{_percent(score.strong_evidence_coverage_ratio)}",
        "- 上限原因：",
        *_bullets(score.cap_reasons, empty="无额外分数上限原因。"),
        "",
        "## 5. 分维度评分",
        "",
        "| 维度 | 状态 | 基础分 | 有效分 | 得分 | 覆盖率 |",
        "|---|---:|---:|---:|---:|---:|",
        *[
            "| "
            + " | ".join(
                [
                    _table(_CATEGORY_LABELS[item.category]),
                    "启用" if item.active else "未启用",
                    _points(item.base_points),
                    _points(item.effective_points),
                    _points(item.earned_points),
                    _percent(item.coverage_ratio),
                ]
            )
            + " |"
            for item in score.dimension_scores
        ],
        "",
        "## 6. 岗位要求逐项匹配",
        "",
        "| ID | 岗位要求 | 类型 | Mandatory | 权重 | 状态 | "
        "Evidence 摘要 | 判断理由 | 改进建议 |",
        "|---|---|---|---:|---:|---|---|---|---|",
        *_match_rows(report),
        "",
        "## 7. 核心优势",
        "",
        *_strength_lines(report),
        "",
        "## 8. 主要缺口",
        "",
        *_gap_lines(report),
        "",
        "## 9. 投递建议与投递前行动",
        "",
        f"- 确定性建议：{recommendation_label}"
        f"（`{report.recommendation.level.value}`）",
        "- 阻塞要求：",
        *_bullets(
            report.recommendation.blocking_requirement_ids,
            empty="无已记录阻塞要求。",
        ),
        "- 投递前行动：",
        *_bullets(
            report.recommendation.before_applying_actions,
            empty="无需额外行动；仍建议人工核对全部事实。",
        ),
        "",
        "## 10. 简历内容策略",
        "",
        "- 保留：保留已通过证据校验且与岗位要求直接相关的经历。",
        "- 强化：优先采用下方“可直接采用”的措辞优化。",
        "- 弱化或删除：本报告不凭空删除真实经历；请人工核对低相关内容。",
        "- 顺序：优先展示对应高权重岗位要求且证据充分的经历。",
        "",
        "## 11. 可直接采用的改写",
        "",
        *_rewrite_lines(report, confirmation_required=False),
        "",
        "## 12. 需要用户确认的改写",
        "",
        *_rewrite_lines(report, confirmation_required=True),
        "",
        "## 13. 面试准备",
        "",
        *_interview_lines(report),
        "",
        "## 14. 岗位知识参考",
        "",
        *_knowledge_lines(report),
        "",
        "## 15. 分析限制与核对提醒",
        "",
        *_bullets(report.limitations, empty="未提供分析限制。"),
        "- 采用任何改写前，请逐项确认其与真实经历完全一致。",
        "- 本系统不能代替招聘人员的综合判断。",
        "",
    ]
    return "\n".join(lines)


def _match_rows(report: AnalysisReport) -> list[str]:
    requirement_by_id = {
        item.requirement_id: item
        for item in report.job_profile.requirements.items
    }
    rows: list[str] = []
    for match in report.matches:
        requirement = requirement_by_id[match.requirement_id]
        evidence_summary = "；".join(
            _excerpt(item.quote) for item in match.evidence_items
        )
        if not evidence_summary:
            evidence_summary = match.missing_evidence_note or "未找到简历证据"
        rows.append(
            "| "
            + " | ".join(
                [
                    _table(requirement.requirement_id),
                    _table(requirement.requirement_text),
                    _table(requirement.requirement_type.value),
                    "是" if requirement.mandatory else "否",
                    _points(requirement.weight),
                    _table(_STATUS_LABELS[match.match_status]),
                    _table(evidence_summary),
                    _table(match.reasoning),
                    _table(match.improvement_suggestion),
                ]
            )
            + " |"
        )
    return rows


def _strength_lines(report: AnalysisReport) -> list[str]:
    if not report.strengths:
        return ["- 未找到足够强、可证据化的核心优势。"]
    lines: list[str] = []
    for index, item in enumerate(report.strengths, start=1):
        lines.extend(
            [
                f"### 优势 {index}：{_inline(item.title)}",
                "",
                f"- 说明：{_inline(item.summary)}",
                f"- 对应要求：{_inline(', '.join(item.requirement_ids))}",
                f"- 证据 ID：{_inline(', '.join(item.evidence_ids))}",
                f"- 岗位价值：{_inline(item.why_it_matters)}",
                "",
            ]
        )
    return lines


def _gap_lines(report: AnalysisReport) -> list[str]:
    if not report.gaps:
        return ["- 未识别到需要优先处理的主要缺口。"]
    lines: list[str] = []
    for index, item in enumerate(report.gaps, start=1):
        lines.extend(
            [
                f"### 缺口 {index}：{_inline(item.title)}",
                "",
                f"- 说明：{_inline(item.summary)}",
                f"- 对应要求：{_inline(', '.join(item.requirement_ids))}",
                f"- 修复类型：`{item.remediability.value}`",
                f"- 风险等级：`{item.risk_level.value}`",
                f"- 建议行动：{_inline(item.recommended_action)}",
                "- 需要用户确认："
                + ("是" if item.user_confirmation_needed else "否"),
                "",
            ]
        )
    return lines


def _rewrite_lines(
    report: AnalysisReport,
    *,
    confirmation_required: bool,
) -> list[str]:
    selected = [
        item
        for item in report.rewrite_suggestions
        if bool(item.introduced_claims or item.user_confirmation_needed)
        is confirmation_required
    ]
    if not selected:
        return ["- 无。"]
    lines: list[str] = []
    for index, item in enumerate(selected, start=1):
        lines.extend(
            [
                f"### 改写 {index}",
                "",
                f"- 原始表述：{_inline(item.original_text)}",
                f"- 优化表述：{_inline(item.rewritten_text)}",
                f"- 修改原因：{_inline(item.reason)}",
                f"- 对应要求：{_inline(', '.join(item.requirement_ids))}",
                f"- Evidence ID：{_inline(', '.join(item.evidence_ids))}",
            ]
        )
        if confirmation_required:
            lines.extend(
                [
                    "- 新增主张：",
                    *_bullets(item.introduced_claims, empty="无已列明主张。"),
                    "- 用户确认事项：",
                    *_bullets(
                        item.user_confirmation_needed,
                        empty="无已列明确认事项。",
                    ),
                ]
            )
        lines.append("")
    return lines


def _interview_lines(report: AnalysisReport) -> list[str]:
    lines: list[str] = []
    for index, item in enumerate(report.interview_questions, start=1):
        lines.extend(
            [
                f"### 面试题 {index}",
                "",
                f"**问题：** {_inline(item.question)}",
                "",
                f"- 考察意图：{_inline(item.intent)}",
                f"- 对应要求：{_inline(', '.join(item.requirement_ids))}",
                "- 回答框架：",
                *_numbered(item.answer_framework),
                f"- 可引用 Evidence："
                f"{_inline(', '.join(item.resume_evidence_ids) or '无')}",
                "- 建议强调：",
                *_bullets(item.emphasis, empty="无额外强调项。"),
                "- 需要避免：",
                *_bullets(item.risks_to_avoid, empty="无额外风险提示。"),
                "",
            ]
        )
    return lines


def _knowledge_lines(report: AnalysisReport) -> list[str]:
    section = report.knowledge
    if section is None:
        return ["- 此Schema 1.0历史报告未记录岗位知识增强信息。"]
    status_messages = {
        KnowledgeRetrievalStatus.DISABLED: "本次未启用岗位知识增强。",
        KnowledgeRetrievalStatus.UNAVAILABLE: (
            "知识库暂不可用，本次报告仍基于简历和JD完成。"
        ),
        KnowledgeRetrievalStatus.NO_MATCH: (
            "未识别到足够明确的岗位画像，未注入专属岗位知识。"
        ),
        KnowledgeRetrievalStatus.AMBIGUOUS: (
            "岗位画像存在歧义，为避免跨岗位污染未注入专属知识。"
        ),
    }
    if section.status is not KnowledgeRetrievalStatus.AVAILABLE:
        lines = [f"- {status_messages[section.status]}"]
        if section.status is KnowledgeRetrievalStatus.AMBIGUOUS:
            lines.extend(
                f"- 候选画像：{_inline(item.name)}"
                f"（相关度 `{item.relevance_score}`）"
                for item in section.role_candidates
            )
        lines.extend(
            f"- 提示：{_inline(item.message)}" for item in section.warnings
        )
        return lines

    lines = [
        (
            "> 以下内容用于解释岗位要求，不代表候选人已具备相关能力，"
            "也不参与本次匹配评分。"
        ),
        "",
        f"- 知识库版本：{_inline(section.knowledge_version)}",
        f"- 检索方式：`{section.retrieval_mode.value}`",
        f"- 检索策略版本：`{section.retrieval_strategy_version}`",
        f"- 推断岗位画像：{_inline(section.selected_role_profile.name)}",
        "- 岗位要求参考：",
        *[
            f"  - {_inline(item.title)}：{_inline(item.description)}"
            for item in section.requirements
        ],
        "- 可接受证据观察角度：",
        *[
            f"  - {_inline(item.description)}"
            for item in section.evidence_patterns
        ],
        "- 面试准备维度：",
        *[
            f"  - {_inline(item.competency_dimension_code)}："
            f"{_inline(item.question)}"
            for item in section.interview_references
        ],
        "- 知识来源：",
        *[
            f"  - `{_inline(item.citation_id)}` — "
            f"{_inline(item.source_title)} — {_inline(item.source_url)}"
            for item in section.citations
        ],
    ]
    used = [item for item in section.citations if item.used_by]
    if used:
        lines.extend(
            [
                "- 已验证的Advice知识引用：",
                *[
                    f"  - `{_inline(item.citation_id)}` → "
                    f"{_inline(', '.join(item.used_by))}"
                    for item in used
                ],
            ]
        )
    if section.fallback_used:
        lines.append("- 知识增强Advice未通过引用校验，已使用无知识回退结果。")
    lines.extend(
        f"- 提示：{_inline(item.message)}" for item in section.warnings
    )
    return lines


def _bullets(values: Iterable[str], *, empty: str) -> list[str]:
    items = [value for value in values if value]
    if not items:
        return [f"  - {_inline(empty)}"]
    return [f"  - {_inline(item)}" for item in items]


def _numbered(values: Iterable[str]) -> list[str]:
    return [
        f"  {index}. {_inline(item)}"
        for index, item in enumerate(values, start=1)
    ]


def _points(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'))}"


def _percent(value: Decimal) -> str:
    return f"{(value * Decimal('100')).quantize(Decimal('0.01'))}%"


def _excerpt(value: str, limit: int = 120) -> str:
    compact = " ".join(value.split())
    if len(compact) <= limit:
        return compact
    return f"{compact[: limit - 1]}…"


def _inline(value: object | None) -> str:
    if value is None or value == "":
        return "未提供"
    escaped = html.escape(str(value), quote=False)
    for character in ("\\", "`", "*", "_", "[", "]", "#"):
        escaped = escaped.replace(character, f"\\{character}")
    return escaped.replace("\r\n", "<br>").replace("\r", "<br>").replace(
        "\n", "<br>"
    )


def _table(value: object | None) -> str:
    return _inline(value).replace("|", "\\|")
