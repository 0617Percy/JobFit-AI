"""Single-call advice generation with deterministic local assembly."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from jobfit.generators.common import advice_error, require_resume_evidence
from jobfit.generators.diagnosis import finalize_diagnosis
from jobfit.generators.interview import finalize_questions
from jobfit.generators.knowledge_reference import (
    KnowledgeReferenceBlock,
    build_knowledge_reference_block,
)
from jobfit.generators.rewrite import partition_rewrites
from jobfit.llm import (
    LLMClient,
    LLMMessage,
    LLMSettings,
    LLMTask,
    PromptRegistry,
)
from jobfit.models import (
    AdviceBundleDraft,
    ApplicationRecommendation,
    EvidenceRegistry,
    GapItem,
    InterviewQuestion,
    JobProfile,
    KnowledgeCitationUseDraft,
    KnowledgeContext,
    MatchScoreSummary,
    RecommendationLevel,
    RequirementMatch,
    ResumeProfile,
    RewriteSuggestion,
    StrengthItem,
)
from jobfit.scoring.policy import STATUS_VALUES

KNOWLEDGE_ADVICE_STRATEGY_VERSION = "1.0"


@dataclass(frozen=True, slots=True)
class GeneratedAdvice:
    strengths: list[StrengthItem]
    gaps: list[GapItem]
    recommendation: ApplicationRecommendation
    direct_rewrites: list[RewriteSuggestion]
    confirmation_required_rewrites: list[RewriteSuggestion]
    interview_questions: list[InterviewQuestion]

    @property
    def rewrite_suggestions(self) -> list[RewriteSuggestion]:
        return [
            *self.direct_rewrites,
            *self.confirmation_required_rewrites,
        ]


@dataclass(frozen=True, slots=True)
class KnowledgeGenerationResult:
    advice: GeneratedAdvice
    citation_uses: tuple[KnowledgeCitationUseDraft, ...]
    provided_citation_ids: tuple[str, ...]


class AdviceBundleGenerator:
    """Generate one structured draft and enforce every local invariant."""

    def __init__(
        self,
        *,
        client: LLMClient,
        prompt_registry: PromptRegistry,
        settings: LLMSettings,
        prompt_version: str = "1.1",
        knowledge_prompt_char_limit: int = 8_000,
    ) -> None:
        self._client = client
        self._prompt_registry = prompt_registry
        self._settings = settings
        self._prompt_version = prompt_version
        self._knowledge_prompt_char_limit = knowledge_prompt_char_limit

    def generate(
        self,
        resume: ResumeProfile,
        job: JobProfile,
        matches: Sequence[RequirementMatch],
        score: MatchScoreSummary,
        registry: EvidenceRegistry,
        *,
        request_id: str,
    ) -> GeneratedAdvice:
        draft = self._generate_draft(
            resume,
            job,
            matches,
            score,
            registry,
            request_id=request_id,
            knowledge_reference=None,
        )
        return _finalize_advice(draft, job, matches, score, registry)

    def generate_with_knowledge(
        self,
        resume: ResumeProfile,
        job: JobProfile,
        matches: Sequence[RequirementMatch],
        score: MatchScoreSummary,
        registry: EvidenceRegistry,
        *,
        knowledge_context: KnowledgeContext,
        request_id: str,
    ) -> KnowledgeGenerationResult:
        reference = build_knowledge_reference_block(
            knowledge_context,
            max_characters=self._knowledge_prompt_char_limit,
        )
        if reference is None:
            raise advice_error(
                "岗位知识参考无法在安全字符预算内组装，已停止使用该增强结果。"
            )
        draft = self._generate_draft(
            resume,
            job,
            matches,
            score,
            registry,
            request_id=request_id,
            knowledge_reference=reference,
        )
        return KnowledgeGenerationResult(
            advice=_finalize_advice(draft, job, matches, score, registry),
            citation_uses=tuple(draft.knowledge_citation_uses),
            provided_citation_ids=reference.citation_ids,
        )

    def _generate_draft(
        self,
        resume: ResumeProfile,
        job: JobProfile,
        matches: Sequence[RequirementMatch],
        score: MatchScoreSummary,
        registry: EvidenceRegistry,
        *,
        request_id: str,
        knowledge_reference: KnowledgeReferenceBlock | None,
    ) -> AdviceBundleDraft:
        _validate_inputs(job, matches, score, registry)
        template = self._prompt_registry.load(
            LLMTask.GENERATE_ADVICE_BUNDLE.value,
            self._prompt_version,
        )
        draft = self._client.generate_structured(
            task=LLMTask.GENERATE_ADVICE_BUNDLE,
            response_model=AdviceBundleDraft,
            messages=_build_messages(
                template.system_text,
                template.user_template,
                resume,
                job,
                matches,
                score,
                registry,
                knowledge_reference,
            ),
            settings=self._settings.model_copy(
                update={
                    "request_id": request_id,
                    "prompt_version": template.version,
                }
            ),
        )
        return draft


def _finalize_advice(
    draft: AdviceBundleDraft,
    job: JobProfile,
    matches: Sequence[RequirementMatch],
    score: MatchScoreSummary,
    registry: EvidenceRegistry,
) -> GeneratedAdvice:
    strengths, gaps, recommendation = finalize_diagnosis(
        draft,
        job,
        matches,
        score,
        registry,
    )
    direct, confirmation = partition_rewrites(
        draft.rewrite_suggestions,
        job.requirements.items,
        registry,
    )
    questions = finalize_questions(
        draft.interview_questions,
        job.requirements.items,
        registry,
        gaps,
    )
    return GeneratedAdvice(
        strengths=strengths,
        gaps=gaps,
        recommendation=recommendation,
        direct_rewrites=direct,
        confirmation_required_rewrites=confirmation,
        interview_questions=questions,
    )


def _validate_inputs(
    job: JobProfile,
    matches: Sequence[RequirementMatch],
    score: MatchScoreSummary,
    registry: EvidenceRegistry,
) -> None:
    requirements = job.requirements.items
    requirement_ids = [item.requirement_id for item in requirements]
    match_ids = [item.requirement_id for item in matches]
    if (
        len(requirement_ids) != len(set(requirement_ids))
        or len(match_ids) != len(set(match_ids))
        or set(requirement_ids) != set(match_ids)
    ):
        raise advice_error("生成建议前，岗位要求与匹配结果必须严格一一对应。")
    if sum((item.weight for item in requirements), Decimal("0")) != Decimal("100.00"):
        raise advice_error("生成建议前，岗位要求权重必须已由评分引擎归一化。")
    if score.final_score != min(score.raw_score, score.score_cap):
        raise advice_error("Score Summary的最终分数与原始分数或上限不一致。")
    if sum(
        (item.effective_points for item in score.dimension_scores),
        Decimal("0"),
    ) != Decimal("100.00"):
        raise advice_error("Score Summary的有效维度分未严格合计100.00。")
    if sum(
        (item.earned_points for item in score.dimension_scores),
        Decimal("0"),
    ) != score.raw_score:
        raise advice_error("Score Summary的维度得分与原始总分不一致。")

    for match in matches:
        if match.match_score != STATUS_VALUES[match.match_status]:
            raise advice_error("生成建议前，匹配状态分值必须通过固定映射校验。")
        canonical = require_resume_evidence(
            (item.evidence_id for item in match.evidence_items),
            registry,
            allow_empty=True,
        )
        if canonical != match.evidence_items:
            raise advice_error("生成建议前，匹配证据必须与Evidence Registry一致。")

    active_dimension_ids = [
        requirement_id
        for dimension in score.dimension_scores
        if dimension.active
        for requirement_id in dimension.requirement_ids
    ]
    if (
        len(active_dimension_ids) != len(set(active_dimension_ids))
        or set(active_dimension_ids) != set(requirement_ids)
    ):
        raise advice_error("Score Summary未完整覆盖全部岗位要求。")
    blockers = {
        *score.confirmed_hard_blockers,
        *score.unverified_hard_blockers,
    }
    if not blockers.issubset(requirement_ids):
        raise advice_error("Score Summary包含未知的阻塞要求。")
    if score.confirmed_hard_blockers and (
        score.score_cap > Decimal("49")
        or score.recommendation_level is not RecommendationLevel.NOT_PRIORITY
    ):
        raise advice_error("Score Summary的明确硬门槛与分数或推荐等级不一致。")
    if score.unverified_hard_blockers and (
        score.score_cap > Decimal("69")
        or score.recommendation_level
        in {
            RecommendationLevel.PRIORITY_APPLY,
            RecommendationLevel.OPTIMIZE_THEN_APPLY,
        }
    ):
        raise advice_error("Score Summary的待确认硬门槛与推荐等级不一致。")


def _build_messages(
    system_text: str,
    user_template: str,
    resume: ResumeProfile,
    job: JobProfile,
    matches: Sequence[RequirementMatch],
    score: MatchScoreSummary,
    registry: EvidenceRegistry,
    knowledge_reference: KnowledgeReferenceBlock | None,
) -> tuple[LLMMessage, LLMMessage]:
    token = "{validated_matches_and_scores}"
    if token not in user_template:
        raise advice_error("generate_advice_bundle Prompt缺少输入占位符。")
    knowledge_token = "{reference_knowledge}"
    if knowledge_reference is not None and knowledge_token not in user_template:
        raise advice_error("generate_advice_bundle Prompt缺少知识参考占位符。")
    payload = {
        "resume_profile": resume.model_dump(
            mode="json",
            exclude={"basic_info": {"email", "phone"}},
        ),
        "job": {
            "job_id": job.job_id,
            "title": job.title,
            "company": job.company,
            "summary": job.summary,
            "requirements": [
                item.model_dump(mode="json")
                for item in job.requirements.items
            ],
            "keywords": job.keywords,
        },
        "validated_matches": [
            item.model_dump(mode="json") for item in matches
        ],
        "score_summary": score.model_dump(mode="json"),
        "evidence_catalog": [
            registry.get(evidence_id).model_dump(mode="json")
            for evidence_id in registry.ids
        ],
    }
    return (
        LLMMessage(role="system", content=system_text),
        LLMMessage(
            role="user",
            content=user_template.replace(
                token,
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            ).replace(
                knowledge_token,
                knowledge_reference.text if knowledge_reference is not None else "",
            ),
        ),
    )
