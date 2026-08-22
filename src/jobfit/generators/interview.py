"""Deterministic validation for a five-question interview set."""

from __future__ import annotations

import re
from collections.abc import Sequence

from jobfit.generators.common import (
    advice_error,
    normalized_phrase,
    require_requirement_ids,
    require_resume_evidence,
    requirement_index,
    stable_generated_id,
)
from jobfit.models import (
    EvidenceRegistry,
    GapItem,
    InterviewQuestion,
    InterviewQuestionDraft,
    JobRequirement,
    RequirementCategory,
)

_ASSUMED_EXPERIENCE = re.compile(
    r"(你曾经|你曾|你主导|你负责|你独立完成|你在.{0,12}(?:上线|生产部署|商业化))"
)
_PROJECT_TERMS = ("项目", "project")
_TECHNICAL_TERMS = ("技术", "方法", "算法", "python", "模型")
_BUSINESS_TERMS = ("业务", "场景", "需求", "方案", "交付")
_GAP_TERMS = ("缺口", "不足", "没有", "未提供", "补足", "风险")
_BEHAVIOR_TERMS = ("协作", "复盘", "动机", "沟通", "团队", "分歧", "合作")


def finalize_questions(
    items: Sequence[InterviewQuestionDraft],
    requirements: Sequence[JobRequirement],
    registry: EvidenceRegistry,
    gaps: Sequence[GapItem],
) -> list[InterviewQuestion]:
    if len(items) != 5:
        raise advice_error("面试问题必须恰好为五道。")
    requirement_by_id = requirement_index(requirements)
    gap_requirement_ids = {
        requirement_id
        for gap in gaps
        for requirement_id in gap.requirement_ids
    }
    normalized_questions = [normalized_phrase(item.question) for item in items]
    if len(set(normalized_questions)) != len(normalized_questions):
        raise advice_error("面试问题不得重复。")

    finalized: list[InterviewQuestion] = []
    purposes = {
        "project": False,
        "technical": False,
        "business": False,
        "gap": False,
        "behavior": False,
    }
    referenced_requirements: set[str] = set()
    for item in items:
        linked_requirements = require_requirement_ids(
            item.requirement_ids,
            requirement_by_id,
        )
        evidence = require_resume_evidence(
            item.resume_evidence_ids,
            registry,
            allow_empty=True,
        )
        text = f"{item.question} {item.intent}".casefold()
        if _ASSUMED_EXPERIENCE.search(item.question):
            raise advice_error("面试问题假定了简历中未证明的经历。")
        purposes["project"] |= bool(evidence) and _contains(text, _PROJECT_TERMS)
        purposes["technical"] |= (
            any(
                requirement.category is RequirementCategory.TECHNICAL_SKILL
                for requirement in linked_requirements
            )
            or _contains(text, _TECHNICAL_TERMS)
        )
        purposes["business"] |= _contains(text, _BUSINESS_TERMS)
        purposes["gap"] |= (
            bool(set(item.requirement_ids) & gap_requirement_ids)
            and _contains(text, _GAP_TERMS)
        )
        purposes["behavior"] |= _contains(text, _BEHAVIOR_TERMS)
        referenced_requirements.update(item.requirement_ids)
        finalized.append(
            InterviewQuestion(
                **item.model_dump(),
                question_id=stable_generated_id(
                    "question",
                    item.question,
                    *sorted(item.requirement_ids),
                ),
            )
        )

    if not all(purposes.values()):
        missing = ",".join(name for name, covered in purposes.items() if not covered)
        raise advice_error(f"五道面试题未覆盖全部必要类型：{missing}。")
    max_weight = max(item.weight for item in requirements)
    if not any(
        requirement_by_id[requirement_id].weight == max_weight
        for requirement_id in referenced_requirements
    ):
        raise advice_error("面试题未覆盖最高权重岗位要求。")
    return finalized


def _contains(text: str, terms: Sequence[str]) -> bool:
    return any(term in text for term in terms)
