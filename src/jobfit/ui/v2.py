"""Safe presentation helpers for the validated v2 report contract."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import streamlit as st

from jobfit.models.v2 import JobFitReport
from jobfit.ui.presentation_translation import (
    PresentationTranslationItem,
    needs_chinese_translation,
)

_RECOMMENDATIONS = {
    "priority": "优先投递",
    "suggested": "建议投递",
    "challenge": "挑战投递",
    "not_recommended": "暂不建议投递",
}
_COVERAGE = {
    "full": "充分匹配",
    "substantial": "大部分匹配",
    "partial": "部分匹配",
    "weak": "匹配较弱",
    "none": "暂无匹配证据",
}
_EVIDENCE_STATUS = {
    "present": "已有证据",
    "weak": "证据较弱",
    "missing": "缺少证据",
    "conflict": "证据存在冲突",
}
_ABILITY_STATUS = {
    "confirmed": "已确认",
    "confirmed_gap": "已确认缺口",
    "unknown": "待确认",
    "conflict": "待核对",
}
_CONFIDENCE = {"high": "高", "medium": "中", "low": "低"}
_SENIORITY = {
    "aligned": "岗位级别匹配",
    "borderline": "岗位级别基本匹配",
    "misaligned": "岗位级别存在偏差",
}
_PRIORITY = {"p0": "高优先级", "p1": "中优先级", "p2": "补充准备"}
_EFFORT = {"low": "低", "medium": "中", "high": "高"}
_TIMING = {
    "before_apply": "投递前",
    "parallel_with_applications": "与投递同步进行",
    "long_term": "长期补强",
}
_FIXED_SYSTEM_COPY = {
    "Current evidence is insufficient; ability remains unknown.": (
        "当前证据不足，相关能力仍待确认。"
    ),
    "Absence of evidence does not establish a confirmed gap.": (
        "当前未发现相关证据，但这并不代表已确认存在能力缺口。"
    ),
    "This is a confirmed gap.": "该项已确认存在能力缺口，需要重点补强。",
}
_COMMON_UNKNOWN_GAP_NOTES = {
    "Current evidence is insufficient; ability remains unknown.",
    "当前证据不足，相关能力仍待确认。",
}
_UNKNOWN_GAP_SUMMARY = (
    "部分岗位要求目前缺少充分证据，相关能力仍处于待确认状态。"
    "这并不代表你不具备这些能力，只表示当前简历材料不足以完成确认。"
)
_INTERNAL_ID_TOKEN = re.compile(
    r"(?<![\w-])(?:"
    r"raw-requirement|requirement|evidence|match|clarification|question|cite|"
    r"responsibility|constraint|seniority"
    r")-[0-9a-f]{16}(?![\w-])"
    r"|(?<![\w-])p06-(?:candidate|build)-\d{3}(?![\w-])",
    re.IGNORECASE,
)
_HIDDEN_REFERENCE = "（内部引用已隐藏）"


def render_v2_report(
    report: JobFitReport,
    *,
    translations: Mapping[str, str] | None = None,
) -> None:
    """Render only validated P08 fields; no decision is recomputed here."""
    replacements, internal_ids = _public_reference_context(report)
    display_translations = translations or {}

    def public(key: str, value: object) -> str:
        sanitized = _sanitize_public_prose(value, replacements, internal_ids)
        localized = _localize_fixed_system_copy(sanitized)
        translated = display_translations.get(key, localized)
        return _localize_fixed_system_copy(
            _sanitize_public_prose(translated, replacements, internal_ids)
        )

    summary = report.summary
    score = report.score_explanation or {}
    job_profile = report.job_profile or {}
    requirements = _records(job_profile.get("explicit_requirements"))
    requirements_by_id = {
        str(item.get("requirement_id")): public(
            f"job_profile.explicit_requirements.{index}.normalized_capability",
            item.get("normalized_capability", "未命名要求"),
        )
        for index, item in enumerate(requirements)
        if item.get("requirement_id")
    }
    evidence_profile = report.resume_evidence_profile or {}
    evidence_by_id = {
        str(item.get("evidence_id")): str(item.get("source_text", ""))
        for item in _records(evidence_profile.get("candidate_evidence"))
        if item.get("evidence_id")
    }

    st.markdown(
        f"### {public('job_profile.job_title', job_profile.get('job_title', '目标岗位'))}"
    )
    st.subheader("总体结论")
    st.markdown("#### 投递建议")
    recommendation = str(summary.get("recommendation", "unknown"))
    st.success(_RECOMMENDATIONS.get(recommendation, "待确认"))
    if recommendation == "challenge":
        st.caption("存在一定匹配基础，但仍有重要条件需要确认或补强。")

    hard = report.hard_check or {}
    st.markdown("#### 关键门槛状态")
    blocker_ids = list(hard.get("hard_blocker_ids", []))
    pending_ids = list(hard.get("hard_pending_ids", []))
    if blocker_ids:
        st.error("关键门槛：存在已确认阻断项")
    elif pending_ids:
        st.warning("关键门槛：仍有资格信息待确认")
    else:
        st.info("关键门槛：未发现已确认阻断项")
    metrics = st.columns(3)
    metrics[0].metric("匹配分", str(score.get("final_fit_score", "—")))
    confidence = str(summary.get("confidence", "unknown"))
    metrics[1].metric("置信度", _CONFIDENCE.get(confidence, "待确认"))
    seniority = str(summary.get("seniority_alignment", "unknown"))
    metrics[2].metric("岗位级别适配", _SENIORITY.get(seniority, "待确认"))
    for index, item in enumerate(_records(job_profile.get("job_explanations"))):
        if item.get("text"):
            st.write(public(f"job_profile.job_explanations.{index}.text", item["text"]))

    st.subheader("岗位优势")
    strengths = report.strengths_and_gaps or {}
    strength_names = [
        requirements_by_id[item]
        for item in _strings(strengths.get("strength_requirement_ids"))
        if item in requirements_by_id
    ]
    if strength_names:
        for name in strength_names:
            st.markdown(f"- {name}")
    else:
        st.caption("当前尚未识别到可明确确认的优势项。")

    st.subheader("需要确认或补强的地方")
    gaps = _records(strengths.get("gaps"))
    if not gaps:
        st.caption("当前没有已确认缺口；未确认信息仍按待确认处理。")
    if any(_is_unknown_gap(gap) for gap in gaps):
        st.warning(_UNKNOWN_GAP_SUMMARY)
    for index, gap in enumerate(gaps):
        requirement_name = requirements_by_id.get(str(gap.get("requirement_id")), "岗位要求")
        st.markdown(f"**{requirement_name}**")
        st.caption(f"状态：{_gap_status_label(gap)}")
        safe_note = str(gap.get("safe_note", "")).strip()
        if safe_note and safe_note not in _COMMON_UNKNOWN_GAP_NOTES:
            st.caption(public(f"strengths_and_gaps.gaps.{index}.safe_note", safe_note))

    st.subheader("岗位要求逐项匹配")
    for index, item in enumerate(_records(report.requirement_match)):
        requirement_name = requirements_by_id.get(
            str(item.get("requirement_id")), "岗位要求"
        )
        with st.expander(requirement_name):
            coverage = str(item.get("coverage", "none"))
            evidence_status = str(item.get("evidence_status", "unknown"))
            ability_status = str(item.get("ability_status", "unknown"))
            st.markdown(f"**匹配程度：** {_COVERAGE.get(coverage, '待确认')}")
            st.markdown(
                f"**证据状态：** {_EVIDENCE_STATUS.get(evidence_status, '待确认')}"
            )
            st.markdown(
                f"**能力状态：** {_ABILITY_STATUS.get(ability_status, '待确认')}"
            )
            support = [
                evidence_by_id.get(str(ref.get("evidence_id")), "")
                for ref in _records(item.get("matched_evidence"))
            ]
            support = [value for value in support if value]
            st.markdown("**现有支撑：**")
            if support:
                for value in support:
                    st.write(value)
            else:
                st.caption("当前材料中暂未发现直接支撑；这不等于候选人不具备该能力。")
            if item.get("reason"):
                st.markdown("**分析说明：**")
                st.write(public(f"requirement_match.{index}.reason", item["reason"]))

    optimization = report.resume_optimization or {}
    st.subheader("简历优化建议")
    st.markdown("#### 简历可以立即优化")
    _render_actions(
        _records(optimization.get("rewrite")),
        empty="暂无可立即优化的表达建议。",
        public=public,
        key_prefix="resume_optimization.rewrite",
    )
    st.markdown("#### 可以补充的真实经历")
    _render_actions(
        _records(optimization.get("recover")),
        empty="暂无已确认但尚未写入简历的经历。",
        public=public,
        key_prefix="resume_optimization.recover",
    )
    st.markdown("#### 建议后续补强的能力 / 证明")
    st.caption("以下属于未来补强，完成前不能写成当前能力，也不计入当前匹配分。")
    _render_actions(
        _records(report.build_recommendations)[:3],
        empty="暂无需要列出的长期补强建议。",
        public=public,
        key_prefix="build_recommendations",
    )

    st.subheader("下一步行动建议")
    strategy = report.application_strategy
    for index, note in enumerate(_strings(strategy.get("notes"))):
        st.markdown(f"- {public(f'application_strategy.notes.{index}', note)}")

    st.subheader("面试准备")
    for index, item in enumerate(_records(report.interview_preparation)):
        prefix = f"interview_preparation.{index}"
        st.markdown(f"**{public(f'{prefix}.question', item.get('question', '参考问题'))}**")
        if item.get("why_likely"):
            st.caption(
                f"为什么可能被问：{public(f'{prefix}.why_likely', item['why_likely'])}"
            )
        priority = str(item.get("priority", "p2"))
        st.caption(f"优先级：{_PRIORITY.get(priority, '补充准备')}")
        st.caption("回答准备要点：以下内容只能基于已验证的真实经历。")
        for point_index, point in enumerate(_strings(item.get("preparation_points"))):
            st.caption(
                f"准备角度：{public(f'{prefix}.preparation_points.{point_index}', point)}"
            )
        st.caption("回答边界：不得编造项目结果、指标或个人职责。")

    st.subheader("分析依据与边界")
    basis = report.analysis_basis_and_limits or {}
    for index, boundary in enumerate(_strings(basis.get("boundaries"))):
        st.caption(
            public(
                f"analysis_basis_and_limits.boundaries.{index}",
                _friendly_boundary(boundary),
            )
        )
    st.caption("匹配分只是辅助信息，不代表录用概率；待确认不等于不具备。")


def build_presentation_translation_items(
    report: JobFitReport,
) -> tuple[PresentationTranslationItem, ...]:
    """Collect only English/mixed generated prose after public-ID sanitization."""
    replacements, internal_ids = _public_reference_context(report)
    items: list[PresentationTranslationItem] = []

    def add(key: str, value: object) -> None:
        text = _localize_fixed_system_copy(
            _sanitize_public_prose(value, replacements, internal_ids)
        ).strip()
        if text and needs_chinese_translation(text):
            items.append(PresentationTranslationItem(key=key, text=text))

    job_profile = report.job_profile or {}
    add("job_profile.job_title", job_profile.get("job_title", ""))
    for index, item in enumerate(_records(job_profile.get("explicit_requirements"))):
        add(
            f"job_profile.explicit_requirements.{index}.normalized_capability",
            item.get("normalized_capability", ""),
        )
    for index, item in enumerate(_records(job_profile.get("job_explanations"))):
        add(f"job_profile.job_explanations.{index}.text", item.get("text", ""))

    strengths = report.strengths_and_gaps or {}
    for index, gap in enumerate(_records(strengths.get("gaps"))):
        safe_note = str(gap.get("safe_note", "")).strip()
        if safe_note and safe_note not in _COMMON_UNKNOWN_GAP_NOTES:
            add(f"strengths_and_gaps.gaps.{index}.safe_note", safe_note)

    for index, item in enumerate(_records(report.requirement_match)):
        add(f"requirement_match.{index}.reason", item.get("reason", ""))

    optimization = report.resume_optimization or {}
    for prefix, actions in (
        ("resume_optimization.rewrite", _records(optimization.get("rewrite"))),
        ("resume_optimization.recover", _records(optimization.get("recover"))),
        ("build_recommendations", _records(report.build_recommendations)[:3]),
    ):
        for index, action in enumerate(actions):
            for field in (
                "title",
                "why_it_matters",
                "recommended_action",
                "completion_criteria",
                "time_to_complete",
            ):
                add(f"{prefix}.{index}.{field}", action.get(field, ""))

    strategy = report.application_strategy or {}
    for index, note in enumerate(_strings(strategy.get("notes"))):
        add(f"application_strategy.notes.{index}", note)

    for index, item in enumerate(_records(report.interview_preparation)):
        prefix = f"interview_preparation.{index}"
        add(f"{prefix}.question", item.get("question", ""))
        add(f"{prefix}.why_likely", item.get("why_likely", ""))
        for point_index, point in enumerate(
            _strings(item.get("preparation_points"))
        ):
            add(f"{prefix}.preparation_points.{point_index}", point)

    basis = report.analysis_basis_and_limits or {}
    for index, boundary in enumerate(_strings(basis.get("boundaries"))):
        add(
            f"analysis_basis_and_limits.boundaries.{index}",
            _friendly_boundary(boundary),
        )
    return tuple(items)


def _render_actions(
    actions: Sequence[Mapping[str, Any]],
    *,
    empty: str,
    public: Callable[[str, object], str],
    key_prefix: str,
) -> None:
    if not actions:
        st.caption(empty)
        return
    for index, action in enumerate(actions):
        prefix = f"{key_prefix}.{index}"
        st.markdown(f"**{public(f'{prefix}.title', action.get('title', '行动建议'))}**")
        if action.get("why_it_matters"):
            st.caption(
                f"为什么现在做：{public(f'{prefix}.why_it_matters', action['why_it_matters'])}"
            )
        st.write(
            "建议执行："
            f"{public(f'{prefix}.recommended_action', action.get('recommended_action', ''))}"
        )
        st.caption(
            "完成标准："
            f"{public(f'{prefix}.completion_criteria', action.get('completion_criteria', ''))}"
        )
        st.caption(
            "预计投入："
            f"{public(f'{prefix}.time_to_complete', action.get('time_to_complete', '未提供'))}；"
            f"投入程度：{_EFFORT.get(str(action.get('effort', '')), '待确认')}；"
            f"安排建议：{_TIMING.get(str(action.get('timing', '')), '待确认')}"
        )
        action_type = str(action.get("action_type", ""))
        boundary = {
            "rewrite": "只改善已有事实的表达，不增加未提供的结果、数字或职责。",
            "recover": "只补充已经确认真实存在的经历。",
            "build": "这是未来补强；完成前不能写成当前能力，也不计入当前匹配分。",
        }.get(action_type, "不得编造候选人事实。")
        st.caption(f"事实边界：{boundary}")


def _public_reference_context(
    report: JobFitReport,
) -> tuple[dict[str, str], set[str]]:
    """Build display-only labels without changing the validated report."""
    payload = report.model_dump(mode="python")
    job_profile = report.job_profile or {}
    evidence_profile = report.resume_evidence_profile or {}
    replacements: dict[str, str] = {}
    for item in _records(job_profile.get("explicit_requirements")):
        _add_public_label(
            replacements,
            item.get("requirement_id"),
            item.get("normalized_capability"),
        )
    for item in _records(evidence_profile.get("candidate_evidence")):
        _add_public_label(
            replacements,
            item.get("evidence_id"),
            item.get("source_text"),
        )
    optimization = report.resume_optimization or {}
    actions = [
        *_records(optimization.get("rewrite")),
        *_records(optimization.get("recover")),
        *_records(report.build_recommendations),
    ]
    for item in actions:
        _add_public_label(replacements, item.get("action_id"), item.get("title"))
    for item in _records(report.interview_preparation):
        _add_public_label(replacements, item.get("question_id"), item.get("question"))
    return replacements, _collect_structured_ids(payload)


def _add_public_label(
    replacements: dict[str, str],
    internal_id: object,
    label: object,
) -> None:
    if isinstance(internal_id, str) and isinstance(label, str) and label.strip():
        replacements[internal_id] = label.strip()


def _collect_structured_ids(value: object) -> set[str]:
    collected: set[str] = set()
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key.endswith("_id") and isinstance(item, str):
                collected.add(item)
            elif key.endswith("_ids") and isinstance(item, Sequence) and not isinstance(
                item, (str, bytes)
            ):
                collected.update(entry for entry in item if isinstance(entry, str))
            collected.update(_collect_structured_ids(item))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            collected.update(_collect_structured_ids(item))
    return collected


def _sanitize_public_prose(
    value: object,
    replacements: Mapping[str, str],
    internal_ids: set[str],
) -> str:
    """Replace only exact project IDs in display text; never mutate source data."""
    text = str(value)
    for internal_id in sorted(internal_ids, key=len, reverse=True):
        replacement = replacements.get(internal_id, _HIDDEN_REFERENCE)
        text = re.sub(
            rf"(?<![\w-]){re.escape(internal_id)}(?![\w-])",
            lambda _match, replacement=replacement: replacement,
            text,
        )
    return _INTERNAL_ID_TOKEN.sub(_HIDDEN_REFERENCE, text)


def _localize_fixed_system_copy(value: str) -> str:
    localized = value
    for source, target in _FIXED_SYSTEM_COPY.items():
        localized = localized.replace(source, target)
    return localized


def _is_unknown_gap(gap: Mapping[str, Any]) -> bool:
    return (
        str(gap.get("ability_status", "")) == "unknown"
        or str(gap.get("safe_note", "")).strip() in _COMMON_UNKNOWN_GAP_NOTES
    )


def _gap_status_label(gap: Mapping[str, Any]) -> str:
    ability_status = str(gap.get("ability_status", ""))
    gap_kind = str(gap.get("gap_kind", ""))
    if ability_status == "confirmed_gap" or gap_kind == "confirmed_gap":
        return "需要补强"
    if ability_status == "unknown":
        return "待确认"
    if gap_kind == "missing_evidence":
        return "缺少证据"
    return _ABILITY_STATUS.get(ability_status, "待确认")


def _friendly_boundary(value: str) -> str:
    return {
        "Candidate evidence comes only from validated candidate sources.": (
            "候选人证据只来自已验证的候选人材料。"
        ),
        "Knowledge is explanatory and never candidate evidence.": (
            "岗位知识只用于解释要求，不代表候选人已具备相关能力。"
        ),
        "Missing evidence keeps ability unknown unless explicitly confirmed.": (
            "缺少材料时能力保持待确认，除非用户明确确认。"
        ),
        "Missing evidence is not proof of missing ability.": (
            "当前材料未体现，不等于候选人不具备。"
        ),
    }.get(value, value)


def _records(value: object) -> list[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _strings(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [str(item) for item in value]
