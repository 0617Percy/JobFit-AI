"""Anonymous, deterministic, fully offline demonstration runtime."""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal

from jobfit.config import Settings
from jobfit.extractors.common import stable_id
from jobfit.llm import LLMTask, MockLLMClient, MockLLMProvider
from jobfit.models import (
    EvidenceItem,
    EvidenceKind,
    EvidenceSourceType,
    MatchStatus,
    RequirementMatchDraft,
)
from jobfit.parsers.text import TextDocumentParser
from jobfit.workflow import WorkflowCache, WorkflowOrchestrator
from jobfit.workflow.factory import build_workflow_orchestrator

DEMO_RESUME_TEXT = "\n".join(
    [
        "匿名候选人",
        "技能：Python",
        "项目：机器学习课程项目",
        "说明：没有Java经验",
    ]
)
DEMO_JOB_TEXT = "\n".join(
    [
        "AI应用开发实习生",
        "岗位要求：",
        "1. 必须熟悉Python。",
        "2. 具有生产级机器学习部署经验。",
        "3. 熟悉Java。",
        "4. 熟悉SQL。",
    ]
)
DEMO_JOB_TITLE = "AI应用开发实习生"
DEMO_COMPANY_NAME = "匿名公司"


@dataclass(frozen=True, slots=True)
class DemoRuntime:
    orchestrator: WorkflowOrchestrator
    provider: MockLLMProvider


def build_demo_runtime(
    *,
    cache: WorkflowCache | None = None,
) -> DemoRuntime:
    """Create a session-local demo with four fixed structured responses."""

    provider = MockLLMProvider(_build_scripts())
    client = MockLLMClient(provider)
    settings = Settings(
        app_env="test",
        llm_provider="mock",
        llm_model="mock-model",
        llm_api_key=None,
        llm_base_url=None,
        demo_mode=True,
    )
    return DemoRuntime(
        orchestrator=build_workflow_orchestrator(
            settings,
            client=client,
            cache=cache,
        ),
        provider=provider,
    )


def _build_scripts() -> dict[LLMTask, list[str]]:
    parser = TextDocumentParser()
    resume_document = parser.parse_text(DEMO_RESUME_TEXT)
    job_document = parser.parse_text(DEMO_JOB_TEXT)
    evidence = _evidence_catalog(resume_document)
    requirements = _requirement_catalog(job_document)
    resume_payload = _resume_payload()
    job_payload = _job_payload()
    match_payload = _match_payload(requirements, evidence)
    advice_payload = _advice_payload(requirements, evidence)
    return {
        LLMTask.EXTRACT_RESUME: [_json(resume_payload)],
        LLMTask.EXTRACT_JOB: [_json(job_payload)],
        LLMTask.MATCH_EVIDENCE: [_json(match_payload)],
        LLMTask.GENERATE_ADVICE_BUNDLE: [_json(advice_payload)],
    }


def _evidence_catalog(document) -> dict[str, EvidenceItem]:
    definitions = {
        "技能：Python": EvidenceKind.DIRECT,
        "项目：机器学习课程项目": EvidenceKind.CONTEXTUAL,
        "说明：没有Java经验": EvidenceKind.DIRECT,
    }
    items: dict[str, EvidenceItem] = {}
    for quote, kind in definitions.items():
        start = document.normalized_text.index(quote)
        end = start + len(quote)
        segment = next(
            item
            for item in document.segments
            if item.start_char <= start and end <= item.end_char
        )
        items[quote] = EvidenceItem(
            evidence_id=stable_id(
                "ev",
                document.document_id,
                start,
                end,
                kind.value,
            ),
            document_id=document.document_id,
            segment_id=segment.segment_id,
            source_type=EvidenceSourceType.RESUME,
            source_reference=segment.segment_id,
            quote=quote,
            start_char=start,
            end_char=end,
            page_number=segment.page_number,
            evidence_kind=kind,
            confidence=Decimal("0.95"),
        )
    return items


def _requirement_catalog(document) -> dict[str, str]:
    values = {
        "python": "必须熟悉Python",
        "production_deployment": "具有生产级机器学习部署经验",
        "java": "熟悉Java",
        "sql": "熟悉SQL",
    }
    return {
        key: stable_id(
            "req",
            document.document_id,
            key,
            document.normalized_text.index(source),
            document.normalized_text.index(source) + len(source),
        )
        for key, source in values.items()
    }


def _resume_payload() -> dict[str, object]:
    facts = []
    for fact_type, quote, structured_fields, evidence_kind in (
        (
            "skill",
            "技能：Python",
            {"name": "Python", "skill_type": "language"},
            EvidenceKind.DIRECT,
        ),
        (
            "project",
            "项目：机器学习课程项目",
            {"name": "机器学习课程项目", "bullets": []},
            EvidenceKind.CONTEXTUAL,
        ),
        (
            "additional_information",
            "说明：没有Java经验",
            {"text": "说明：没有Java经验"},
            EvidenceKind.DIRECT,
        ),
    ):
        start = DEMO_RESUME_TEXT.index(quote)
        facts.append(
            {
                "fact_type": fact_type,
                "raw_text": quote,
                "structured_fields": structured_fields,
                "evidence_candidates": [
                    {
                        "quote": quote,
                        "start_char": start,
                        "end_char": start + len(quote),
                        "page_number": None,
                        "evidence_kind": evidence_kind.value,
                        "confidence": "0.95",
                    }
                ],
            }
        )
    return {
        "language": "zh",
        "basic_info": {"name": "匿名候选人"},
        "facts": facts,
        "extraction_warnings": [],
    }


def _job_payload() -> dict[str, object]:
    definitions = (
        ("必须熟悉Python", "熟悉Python", "technical_skill", "python"),
        (
            "具有生产级机器学习部署经验",
            "具有生产级机器学习部署经验",
            "experience_project",
            "production_deployment",
        ),
        ("熟悉Java", "熟悉Java", "technical_skill", "java"),
        ("熟悉SQL", "熟悉SQL", "technical_skill", "sql"),
    )
    requirements = []
    for source, text, category, key in definitions:
        start = DEMO_JOB_TEXT.index(source)
        requirements.append(
            {
                "requirement_text": text,
                "source_text": source,
                "source_start_char": start,
                "source_end_char": start + len(source),
                "requirement_type": "must_have",
                "category": category,
                "importance": "high",
                "mandatory": True,
                "hard_condition_kind": "none",
                "normalized_key": key,
            }
        )
    return {
        "title": DEMO_JOB_TITLE,
        "company": None,
        "language": "zh",
        "summary": "匿名演示岗位。",
        "requirements": requirements,
        "keywords": ["Python", "Java", "SQL"],
        "extraction_warnings": [],
    }


def _match_payload(
    requirements: dict[str, str],
    evidence: dict[str, EvidenceItem],
) -> dict[str, object]:
    drafts = [
        RequirementMatchDraft(
            requirement_id=requirements["python"],
            match_status=MatchStatus.MATCHED,
            evidence_items=[evidence["技能：Python"]],
            reasoning="简历明确写明Python技能。",
            confidence=Decimal("0.95"),
            improvement_suggestion="补充真实项目中的Python应用深度。",
        ),
        RequirementMatchDraft(
            requirement_id=requirements["production_deployment"],
            match_status=MatchStatus.PARTIAL_MATCH,
            evidence_items=[evidence["项目：机器学习课程项目"]],
            reasoning="课程项目相关，但没有生产部署证据。",
            confidence=Decimal("0.80"),
            improvement_suggestion="通过真实部署实践补充可验证证据。",
        ),
        RequirementMatchDraft(
            requirement_id=requirements["java"],
            match_status=MatchStatus.NOT_MATCHED,
            evidence_items=[evidence["说明：没有Java经验"]],
            reasoning="简历明确写明没有Java经验。",
            confidence=Decimal("0.95"),
            missing_evidence_note="存在明确否定表述。",
            improvement_suggestion="仅在岗位确有需要时安排真实学习。",
        ),
        RequirementMatchDraft(
            requirement_id=requirements["sql"],
            match_status=MatchStatus.UNKNOWN,
            evidence_items=[],
            reasoning="当前简历未提供足够证据确认SQL能力。",
            confidence=Decimal("0.70"),
            missing_evidence_note="当前简历未提供足够证据确认该能力。",
            improvement_suggestion="确认是否已有SQL经历并补充真实证据。",
        ),
    ]
    return {"matches": [item.model_dump(mode="json") for item in drafts]}


def _advice_payload(
    requirements: dict[str, str],
    evidence: dict[str, EvidenceItem],
) -> dict[str, object]:
    python_req = requirements["python"]
    production_req = requirements["production_deployment"]
    java_req = requirements["java"]
    sql_req = requirements["sql"]
    python_ev = evidence["技能：Python"].evidence_id
    project_ev = evidence["项目：机器学习课程项目"].evidence_id
    return {
        "strengths": [
            {
                "title": "Python技能证据",
                "summary": "简历明确写明Python技能。",
                "requirement_ids": [python_req],
                "evidence_ids": [python_ev],
                "why_it_matters": "对应岗位的核心技术要求。",
            },
            {
                "title": "机器学习课程项目基础",
                "summary": "课程项目提供相关基础，但不等同生产部署经验。",
                "requirement_ids": [production_req],
                "evidence_ids": [project_ev],
                "why_it_matters": "可作为继续补充真实工程实践的起点。",
            },
        ],
        "gaps": [
            {
                "title": "生产级部署证据不足",
                "summary": "课程项目不能证明生产级部署经验。",
                "requirement_ids": [production_req],
                "remediability": "learning_practice",
                "risk_level": "high",
                "recommended_action": "通过真实部署练习补充证据。",
                "user_confirmation_needed": False,
            },
            {
                "title": "Java明确缺口",
                "summary": "简历明确写明没有Java经验。",
                "requirement_ids": [java_req],
                "remediability": "learning_practice",
                "risk_level": "high",
                "recommended_action": "按岗位需要安排真实学习。",
                "user_confirmation_needed": False,
            },
            {
                "title": "SQL证据待确认",
                "summary": "当前简历未提供足够证据确认SQL能力。",
                "requirement_ids": [sql_req],
                "remediability": "evidence_needed",
                "risk_level": "high",
                "recommended_action": "确认已有经历并补充真实证据。",
                "user_confirmation_needed": True,
            },
        ],
        "recommendation_reasoning": [
            f"[{python_req}] 已有明确Python证据。",
            f"[{production_req}] 生产经验仍需真实实践。",
            f"[{sql_req}] 当前只能判断为证据不足。",
        ],
        "rewrite_suggestions": [
            {
                "original_text": "技能：Python",
                "rewritten_text": "技能：Python（按原文保留）",
                "reason": "保持事实不变并改善可读性。",
                "requirement_ids": [python_req],
                "evidence_ids": [python_ev],
                "introduced_claims": [],
                "user_confirmation_needed": [],
            }
        ],
        "interview_questions": [
            _question(
                "请介绍机器学习课程项目及个人行动。",
                "核心项目深挖并核对真实参与范围。",
                production_req,
                evidence_id=project_ev,
                risk="不要表述为生产部署",
            ),
            _question(
                "Python相关技术方法如何选择？",
                "考察核心技术和方法理解。",
                python_req,
                evidence_id=python_ev,
            ),
            _question(
                "面对业务场景时如何设计机器学习交付方案？",
                "考察业务需求和方案设计。",
                production_req,
                risk="不要虚构生产经验",
            ),
            _question(
                "当前SQL证据不足，你会如何补足这一缺口？",
                "核验主要缺口与学习计划。",
                sql_req,
                risk="不要把未证明描述为不会",
            ),
            _question(
                "团队协作中如何沟通、复盘并处理分歧？",
                "考察协作、复盘和求职动机。",
                python_req,
                risk="没有真实案例时使用假设式回答",
            ),
        ],
    }


def _question(
    question: str,
    intent: str,
    requirement_id: str,
    *,
    evidence_id: str | None = None,
    risk: str | None = None,
) -> dict[str, object]:
    return {
        "question": question,
        "intent": intent,
        "answer_framework": ["说明背景", "说明行动", "说明验证与风险"],
        "resume_evidence_ids": [evidence_id] if evidence_id else [],
        "requirement_ids": [requirement_id],
        "emphasis": [],
        "risks_to_avoid": [risk] if risk else [],
    }


def _json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False)
