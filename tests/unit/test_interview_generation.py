"""Tests for the deterministic five-question interview boundary."""

from __future__ import annotations

import pytest

from jobfit.errors import ErrorCode, JobFitError
from jobfit.generators.interview import finalize_questions
from jobfit.models import GapItem, GapRemediability, Importance, InterviewQuestionDraft


def test_questions_are_exactly_five_unique_grounded_and_stable(
    advice_case,
) -> None:
    drafts = _valid_questions()
    gaps = [_sql_gap()]

    first = finalize_questions(
        drafts,
        advice_case.job.requirements.items,
        advice_case.registry,
        gaps,
    )
    second = finalize_questions(
        drafts,
        advice_case.job.requirements.items,
        advice_case.registry,
        gaps,
    )

    assert len(first) == 5
    assert len({item.question_id for item in first}) == 5
    assert first == second
    assert any("SQL" in item.question for item in first)
    assert first[3].resume_evidence_ids == []


@pytest.mark.parametrize("count", [4, 6])
def test_question_count_must_be_exactly_five(advice_case, count: int) -> None:
    with pytest.raises(JobFitError) as exc_info:
        finalize_questions(
            _valid_questions()[:count]
            if count < 5
            else [*_valid_questions(), _valid_questions()[0].model_copy(
                update={"question": "第六个重复结构问题"}
            )],
            advice_case.job.requirements.items,
            advice_case.registry,
            [_sql_gap()],
        )

    assert exc_info.value.code is ErrorCode.ADVICE_VALIDATION_FAILED


def test_duplicate_question_is_rejected(advice_case) -> None:
    drafts = _valid_questions()
    drafts[4] = drafts[0].model_copy()

    with pytest.raises(JobFitError):
        finalize_questions(
            drafts,
            advice_case.job.requirements.items,
            advice_case.registry,
            [_sql_gap()],
        )


def test_unknown_requirement_or_evidence_is_rejected(advice_case) -> None:
    drafts = _valid_questions()
    drafts[0] = drafts[0].model_copy(
        update={"requirement_ids": ["req-invented"]},
    )

    with pytest.raises(JobFitError):
        finalize_questions(
            drafts,
            advice_case.job.requirements.items,
            advice_case.registry,
            [_sql_gap()],
        )

    drafts = _valid_questions()
    drafts[0] = drafts[0].model_copy(
        update={"resume_evidence_ids": ["ev-invented"]},
    )
    with pytest.raises(JobFitError):
        finalize_questions(
            drafts,
            advice_case.job.requirements.items,
            advice_case.registry,
            [_sql_gap()],
        )


def test_question_set_must_cover_all_five_interview_purposes(advice_case) -> None:
    drafts = _valid_questions()
    drafts[4] = drafts[4].model_copy(
        update={
            "question": "请再介绍一次Python技术细节。",
            "intent": "考察技术理解。",
        }
    )

    with pytest.raises(JobFitError):
        finalize_questions(
            drafts,
            advice_case.job.requirements.items,
            advice_case.registry,
            [_sql_gap()],
        )


def test_question_cannot_assume_unproven_experience(advice_case) -> None:
    drafts = _valid_questions()
    drafts[2] = drafts[2].model_copy(
        update={
            "question": "你主导Docker生产部署时取得了什么商业成果？",
            "resume_evidence_ids": [],
        }
    )

    with pytest.raises(JobFitError):
        finalize_questions(
            drafts,
            advice_case.job.requirements.items,
            advice_case.registry,
            [_sql_gap()],
        )


def _valid_questions() -> list[InterviewQuestionDraft]:
    return [
        InterviewQuestionDraft(
            question="请深入介绍课程项目中的机器学习方法与个人行动。",
            intent="核心项目深挖，核对真实参与范围。",
            answer_framework=["说明背景", "说明个人行动", "说明已验证结果"],
            resume_evidence_ids=["ev-course"],
            requirement_ids=["req-production"],
            emphasis=["只引用课程项目事实"],
            risks_to_avoid=["不要表述为生产部署"],
        ),
        InterviewQuestionDraft(
            question="Python数据处理采用了什么技术方法？",
            intent="考察核心技术与方法理解。",
            answer_framework=["说明输入", "说明处理步骤", "说明验证方式"],
            resume_evidence_ids=["ev-python"],
            requirement_ids=["req-python"],
        ),
        InterviewQuestionDraft(
            question="如果面向真实业务场景，你会如何设计机器学习交付方案？",
            intent="考察岗位场景和业务理解，不假定已有生产经验。",
            answer_framework=["澄清需求", "提出方案", "说明风险"],
            resume_evidence_ids=[],
            requirement_ids=["req-production"],
        ),
        InterviewQuestionDraft(
            question="当前简历没有SQL证据，你准备如何验证或补足这一缺口？",
            intent="核验主要缺口与学习计划。",
            answer_framework=["诚实说明现状", "给出验证方式", "给出实践计划"],
            resume_evidence_ids=[],
            requirement_ids=["req-sql"],
        ),
        InterviewQuestionDraft(
            question="如果与团队协作推进项目，你会如何沟通、复盘并处理分歧？",
            intent="考察协作、复盘和求职动机。",
            answer_framework=["说明协作原则", "说明复盘结构", "避免虚构案例"],
            resume_evidence_ids=[],
            requirement_ids=["req-python"],
        ),
    ]


def _sql_gap() -> GapItem:
    return GapItem(
        title="SQL证据不足",
        summary="当前简历未提供足够证据确认SQL能力。",
        requirement_ids=["req-sql"],
        remediability=GapRemediability.EVIDENCE_NEEDED,
        risk_level=Importance.HIGH,
        recommended_action="补充真实SQL练习或项目证据。",
        user_confirmation_needed=True,
    )
