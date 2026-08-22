"""Tests for deterministic diagnosis and recommendation assembly."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from jobfit.errors import ErrorCode, JobFitError
from jobfit.generators.diagnosis import finalize_diagnosis
from jobfit.llm import PromptRegistry
from jobfit.models import (
    AdviceBundleDraft,
    EvidenceRegistry,
    GapItem,
    GapRemediability,
    HardConditionKind,
    Importance,
    InterviewQuestionDraft,
    RecommendationLevel,
    RewriteSuggestionDraft,
    StrengthItem,
)


def test_advice_draft_uses_id_free_transport_models() -> None:
    draft = AdviceBundleDraft(
        strengths=[],
        gaps=[],
        recommendation_reasoning=["[req-python] 建议先核验证据。"],
        rewrite_suggestions=[
            RewriteSuggestionDraft(
                original_text="参与模型测试",
                rewritten_text="参与模型测试并记录结果",
                reason="提高动作清晰度。",
                requirement_ids=["req-python"],
                evidence_ids=["ev-python"],
            )
        ],
        interview_questions=[
            InterviewQuestionDraft(
                question=f"问题{index}",
                intent="验证已提供信息。",
                answer_framework=["按事实回答。"],
                requirement_ids=["req-python"],
            )
            for index in range(1, 6)
        ],
    )

    assert not hasattr(draft.rewrite_suggestions[0], "suggestion_id")
    assert not hasattr(draft.interview_questions[0], "question_id")


def test_advice_draft_rejects_model_generated_score_or_level() -> None:
    payload = _draft().model_dump(mode="json")
    payload["final_score"] = "99"
    payload["recommendation_level"] = "priority_apply"

    with pytest.raises(ValidationError):
        AdviceBundleDraft.model_validate(payload)


def test_prompt_v12_is_explicit_and_prior_versions_remain_traceable() -> None:
    prompt_root = Path(__file__).parents[2] / "src" / "jobfit" / "prompts"
    registry = PromptRegistry(prompt_root)

    current = registry.load("generate_advice_bundle", "1.2")
    archived_v11 = registry.load("generate_advice_bundle", "1.1")
    archived_v10 = registry.load("generate_advice_bundle", "1.0")
    current_text = f"{current.system_text}\n{current.user_template}"

    assert current.version == "1.2"
    assert archived_v11.version == "1.1"
    assert archived_v10.version == "1.0"
    assert "REFERENCE_KNOWLEDGE" in current_text
    assert "{reference_knowledge}" in current.user_template
    assert "unknown" in current_text and "not_matched" in current_text
    assert "introduced_claims" in current_text
    assert "恰好五道" in current_text
    assert "不得输出、替换、升级或降级推荐等级" in current_text


def test_llm_cannot_upgrade_recommendation(advice_case) -> None:
    draft = _draft(
        recommendation_reasoning=[
            "[req-python] 文案建议优先投递，但等级必须由评分结果决定。"
        ]
    )
    original_level = advice_case.score.recommendation_level

    _, _, recommendation = finalize_diagnosis(
        draft,
        advice_case.job,
        advice_case.matches,
        advice_case.score,
        advice_case.registry,
    )

    assert recommendation.level is original_level
    assert recommendation.level is not RecommendationLevel.PRIORITY_APPLY


def test_strengths_are_grounded_deduplicated_and_limited(advice_case) -> None:
    duplicate = _strength(
        "Python能力",
        ["req-python"],
        ["ev-python"],
    )
    draft = _draft(
        strengths=[
            duplicate,
            duplicate.model_copy(
                update={"summary": "重复表达同一能力。"},
            ),
            _strength(
                "项目相关基础",
                ["req-production"],
                ["ev-course"],
                summary="课程项目提供了相关基础，但不等同于生产经验。",
            ),
        ]
    )

    strengths, _, _ = finalize_diagnosis(
        draft,
        advice_case.job,
        advice_case.matches,
        advice_case.score,
        advice_case.registry,
    )

    assert len(strengths) == 2
    assert all(item.requirement_ids and item.evidence_ids for item in strengths)
    assert strengths[0].requirement_ids == ["req-production"]


def test_strength_with_unknown_or_unrelated_evidence_is_rejected(
    advice_case,
) -> None:
    draft = _draft(
        strengths=[
            _strength(
                "虚假SQL优势",
                ["req-sql"],
                ["ev-python"],
            )
        ]
    )

    with pytest.raises(JobFitError) as exc_info:
        finalize_diagnosis(
            draft,
            advice_case.job,
            advice_case.matches,
            advice_case.score,
            advice_case.registry,
        )

    assert exc_info.value.code is ErrorCode.ADVICE_VALIDATION_FAILED


def test_low_confidence_evidence_cannot_be_written_as_certain_strength(
    advice_case,
) -> None:
    low_confidence = advice_case.registry.get("ev-python").model_copy(
        update={"confidence": Decimal("0.50")}
    )
    registry = EvidenceRegistry(
        [
            low_confidence
            if evidence_id == "ev-python"
            else advice_case.registry.get(evidence_id)
            for evidence_id in advice_case.registry.ids
        ]
    )
    matches = [
        match.model_copy(update={"evidence_items": [low_confidence]})
        if match.requirement_id == "req-python"
        else match
        for match in advice_case.matches
    ]
    draft = _draft(
        strengths=[
            _strength(
                "明确的Python优势",
                ["req-python"],
                ["ev-python"],
                summary="证据充分证明用户确定具备该能力。",
            )
        ]
    )

    with pytest.raises(JobFitError) as exc_info:
        finalize_diagnosis(
            draft,
            advice_case.job,
            matches,
            advice_case.score,
            registry,
        )

    assert exc_info.value.code is ErrorCode.ADVICE_VALIDATION_FAILED


def test_gap_semantics_and_remediability_are_constrained(advice_case) -> None:
    draft = _draft(
        gaps=[
            _gap(
                "SQL证据不足",
                "当前简历未提供足够证据确认SQL能力。",
                ["req-sql"],
                GapRemediability.EVIDENCE_NEEDED,
                confirmation=True,
            ),
            _gap(
                "Java明确缺口",
                "简历明确写明没有Java经验。",
                ["req-java"],
                GapRemediability.LEARNING_PRACTICE,
            ),
            _gap(
                "生产经验不足",
                "课程项目不能证明生产级部署经验。",
                ["req-production"],
                GapRemediability.LEARNING_PRACTICE,
            ),
        ]
    )

    _, gaps, _ = finalize_diagnosis(
        draft,
        advice_case.job,
        advice_case.matches,
        advice_case.score,
        advice_case.registry,
    )

    by_requirement = {item.requirement_ids[0]: item for item in gaps}
    assert by_requirement["req-sql"].remediability is GapRemediability.EVIDENCE_NEEDED
    assert by_requirement["req-sql"].user_confirmation_needed is True
    assert by_requirement["req-java"].remediability is GapRemediability.LEARNING_PRACTICE
    assert len(gaps) == 3


def test_wording_gap_remains_wording_when_fact_is_already_grounded(
    advice_case,
) -> None:
    draft = _draft(
        gaps=[
            _gap(
                "Python表达偏弱",
                "已有Python事实，但当前表述可以更清晰。",
                ["req-python"],
                GapRemediability.WORDING,
            )
        ]
    )

    _, gaps, _ = finalize_diagnosis(
        draft,
        advice_case.job,
        advice_case.matches,
        advice_case.score,
        advice_case.registry,
    )

    assert gaps[0].remediability is GapRemediability.WORDING


def test_hard_condition_gap_is_hard_to_fix_short_term(advice_case) -> None:
    hard_requirement = advice_case.job.requirements.items[3].model_copy(
        update={
            "importance": Importance.CRITICAL,
            "hard_condition_kind": HardConditionKind.WORK_AUTHORIZATION,
        }
    )
    job = advice_case.job.model_copy(
        update={
            "requirements": advice_case.job.requirements.model_copy(
                update={
                    "items": [
                        *advice_case.job.requirements.items[:3],
                        hard_requirement,
                    ]
                }
            )
        }
    )
    draft = _draft(
        gaps=[
            _gap(
                "工作许可待确认",
                "当前简历未提供足够证据确认工作许可。",
                ["req-sql"],
                GapRemediability.EVIDENCE_NEEDED,
            )
        ]
    )

    _, gaps, _ = finalize_diagnosis(
        draft,
        job,
        advice_case.matches,
        advice_case.score,
        advice_case.registry,
    )

    assert gaps[0].remediability is GapRemediability.HARD_TO_FIX_SHORT_TERM
    assert gaps[0].user_confirmation_needed is True


def test_unknown_gap_cannot_claim_user_lacks_ability(advice_case) -> None:
    draft = _draft(
        gaps=[
            _gap(
                "SQL能力缺失",
                "用户一定不会SQL，完全不具备该能力。",
                ["req-sql"],
                GapRemediability.EVIDENCE_NEEDED,
            )
        ]
    )

    with pytest.raises(JobFitError) as exc_info:
        finalize_diagnosis(
            draft,
            advice_case.job,
            advice_case.matches,
            advice_case.score,
            advice_case.registry,
        )

    assert exc_info.value.code is ErrorCode.ADVICE_VALIDATION_FAILED


def test_blockers_and_unknown_confirmation_actions_come_from_score(
    advice_case,
) -> None:
    score = advice_case.score.model_copy(
        update={
            "confirmed_hard_blockers": ["req-java"],
            "unverified_hard_blockers": ["req-sql"],
            "score_cap": Decimal("49"),
            "final_score": min(advice_case.score.raw_score, Decimal("49")),
            "recommendation_level": RecommendationLevel.NOT_PRIORITY,
        }
    )
    draft = _draft(
        recommendation_reasoning=[
            "[req-java] 存在明确不满足项。",
            "[req-sql] 硬性条件仍需确认。",
        ],
        gaps=[
            _gap(
                "SQL待确认",
                "当前简历未提供足够证据确认SQL能力。",
                ["req-sql"],
                GapRemediability.EVIDENCE_NEEDED,
                confirmation=True,
            )
        ],
    )

    _, _, recommendation = finalize_diagnosis(
        draft,
        advice_case.job,
        advice_case.matches,
        score,
        advice_case.registry,
    )

    assert recommendation.level is RecommendationLevel.NOT_PRIORITY
    assert recommendation.blocking_requirement_ids == ["req-java", "req-sql"]
    assert any(
        "req-sql" in action and "确认" in action
        for action in recommendation.before_applying_actions
    )


def test_recommendation_reasoning_must_reference_known_requirement(
    advice_case,
) -> None:
    draft = _draft(
        recommendation_reasoning=["[req-invented] 建议投递。"],
    )

    with pytest.raises(JobFitError):
        finalize_diagnosis(
            draft,
            advice_case.job,
            advice_case.matches,
            advice_case.score,
            advice_case.registry,
        )


def _strength(
    title: str,
    requirement_ids: list[str],
    evidence_ids: list[str],
    *,
    summary: str = "简历包含直接、明确的相关证据。",
) -> StrengthItem:
    return StrengthItem(
        title=title,
        summary=summary,
        requirement_ids=requirement_ids,
        evidence_ids=evidence_ids,
        why_it_matters="该能力对应目标岗位的高权重要求。",
    )


def _gap(
    title: str,
    summary: str,
    requirement_ids: list[str],
    remediability: GapRemediability,
    *,
    confirmation: bool = False,
) -> GapItem:
    return GapItem(
        title=title,
        summary=summary,
        requirement_ids=requirement_ids,
        remediability=remediability,
        risk_level=Importance.HIGH,
        recommended_action="基于真实情况补充证据或完成实践。",
        user_confirmation_needed=confirmation,
    )


def _draft(
    *,
    strengths: list[StrengthItem] | None = None,
    gaps: list[GapItem] | None = None,
    recommendation_reasoning: list[str] | None = None,
) -> AdviceBundleDraft:
    return AdviceBundleDraft(
        strengths=strengths or [],
        gaps=gaps or [],
        recommendation_reasoning=recommendation_reasoning
        or ["[req-python] 已有明确Python证据。"],
        rewrite_suggestions=[],
        interview_questions=[
            InterviewQuestionDraft(
                question=f"占位问题{index}",
                intent="仅用于诊断单元测试。",
                answer_framework=["基于事实回答。"],
                requirement_ids=["req-python"],
            )
            for index in range(1, 6)
        ],
    )
