"""Full offline parser-to-export workflow using the real Mock LLM client."""

from __future__ import annotations

import json
from pathlib import Path

from jobfit.config import Settings
from jobfit.extractors import JobRequirementExtractor, ResumeExtractor
from jobfit.generators import AdviceBundleGenerator
from jobfit.llm import (
    LLMSettings,
    LLMTask,
    MockLLMClient,
    MockLLMProvider,
    PromptRegistry,
)
from jobfit.matching import EvidenceMatcher
from jobfit.models import (
    AnalysisRequest,
    EvidenceKind,
    GapRemediability,
    Importance,
    KnowledgeContext,
    MatchStatus,
    RequirementMatchDraft,
    WorkflowStage,
)
from jobfit.parsers import DocumentParserService
from jobfit.parsers.text import TextDocumentParser
from jobfit.scoring import ScoringEngine
from jobfit.validators import EvidenceValidator
from jobfit.workflow import WorkflowFingerprintContext, WorkflowOrchestrator

_RESUME_TEXT = "\n".join(
    [
        "匿名候选人",
        "技能：Python",
        "项目：机器学习课程项目",
        "说明：没有Java经验",
    ]
)
_JOB_TEXT = "\n".join(
    [
        "AI应用开发实习生",
        "岗位要求：",
        "1. 必须熟悉Python。",
        "2. 具有生产级机器学习部署经验。",
        "3. 熟悉Java。",
        "4. 熟悉SQL。",
    ]
)


class _StaticKnowledgeRetriever:
    def __init__(self, context: KnowledgeContext) -> None:
        self.context = context
        self.call_count = 0

    def retrieve_for_job(self, job_profile, *, limit: int = 12) -> KnowledgeContext:
        del job_profile, limit
        self.call_count += 1
        return self.context


def test_real_mock_workflow_is_offline_grounded_and_exportable(
    monkeypatch,
) -> None:
    monkeypatch.delenv("JOBFIT_LLM_API_KEY", raising=False)
    provider, orchestrator = _build_real_mock_orchestrator()
    request = AnalysisRequest(
        request_id="request-full-mock",
        pasted_resume_text=_RESUME_TEXT,
        job_description_text=_JOB_TEXT,
        job_title="AI应用开发实习生",
        company_name="匿名公司",
        llm_mode="mock",
    )

    result = orchestrator.run(request, selected_source="text")

    assert result.success is True
    assert result.stage is WorkflowStage.COMPLETED
    assert result.report is not None
    assert result.report.validation.valid is True
    assert len(result.report.matches) == 4
    assert len(result.report.interview_questions) == 5
    assert result.markdown is not None
    assert "匹配分不是录用概率" in result.markdown
    assert result.json_text is not None
    assert json.loads(result.json_text)["report_id"] == result.report.report_id
    assert provider.call_count == 4
    assert WorkflowStage.RETRIEVING_KNOWLEDGE in {
        event.stage for event in result.events
    }
    assert "knowledge_context" not in json.loads(result.json_text)
    assert [call.task for call in provider.calls] == [
        LLMTask.EXTRACT_RESUME,
        LLMTask.EXTRACT_JOB,
        LLMTask.MATCH_EVIDENCE,
        LLMTask.GENERATE_ADVICE_BUNDLE,
    ]


def test_real_mock_workflow_reuses_same_request_without_model_calls() -> None:
    provider, orchestrator = _build_real_mock_orchestrator()
    request = AnalysisRequest(
        request_id="request-cache-one",
        pasted_resume_text=_RESUME_TEXT,
        job_description_text=_JOB_TEXT,
        job_title="AI应用开发实习生",
        company_name="匿名公司",
        llm_mode="mock",
    )

    first = orchestrator.run(request, selected_source="text")
    second = orchestrator.run(
        request.model_copy(update={"request_id": "request-cache-two"}),
        selected_source="text",
    )

    assert first.success is True
    assert second.success is True
    assert second.cache_hit is True
    assert second.report is first.report
    assert second.markdown == first.markdown
    assert second.json_text == first.json_text
    assert provider.call_count == 4


def test_grounded_knowledge_advice_keeps_the_four_call_baseline(
    available_knowledge_context,
) -> None:
    provider, orchestrator = _build_real_mock_orchestrator(
        knowledge_context=available_knowledge_context,
    )

    result = orchestrator.run(
        AnalysisRequest(
            request_id="request-grounded-knowledge",
            pasted_resume_text=_RESUME_TEXT,
            job_description_text=_JOB_TEXT,
            job_title="AI搴旂敤寮€鍙戝疄涔犵敓",
            company_name="鍖垮悕鍏徃",
            llm_mode="mock",
        ),
        selected_source="text",
    )

    assert result.success is True
    assert provider.call_count == 4
    assert result.report is not None
    assert result.report.schema_version == "1.1"
    assert result.report.knowledge.status.value == "available"
    assert result.report.knowledge.citations[0].used_by == ["recommendation:0"]
    assert not hasattr(result.report, "knowledge_citations")
    assert "knowledge_citation_uses" not in json.loads(result.json_text or "{}")


def test_invalid_knowledge_citation_has_exactly_one_plain_fallback_call(
    available_knowledge_context,
) -> None:
    provider, orchestrator = _build_real_mock_orchestrator(
        knowledge_context=available_knowledge_context,
        invalid_knowledge_citation=True,
    )

    result = orchestrator.run(
        AnalysisRequest(
            request_id="request-invalid-knowledge-citation",
            pasted_resume_text=_RESUME_TEXT,
            job_description_text=_JOB_TEXT,
            job_title="AI搴旂敤寮€鍙戝疄涔犵敓",
            company_name="鍖垮悕鍏徃",
            llm_mode="mock",
        ),
        selected_source="text",
    )

    assert result.success is True
    assert provider.call_count == 5
    assert [
        call.task for call in provider.calls
    ].count(LLMTask.GENERATE_ADVICE_BUNDLE) == 2
    advice_calls = [
        call
        for call in provider.calls
        if call.task is LLMTask.GENERATE_ADVICE_BUNDLE
    ]
    assert "<REFERENCE_KNOWLEDGE" in advice_calls[0].messages[1].content
    assert "<REFERENCE_KNOWLEDGE" not in advice_calls[1].messages[1].content
    assert result.report is not None
    assert result.report.validation.valid is True
    assert result.report.knowledge.fallback_used is True
    assert all(not item.used_by for item in result.report.knowledge.citations)
    assert "cite-ffffffffffffffff" not in result.json_text


def _build_real_mock_orchestrator(
    *,
    knowledge_context: KnowledgeContext | None = None,
    invalid_knowledge_citation: bool = False,
) -> tuple[MockLLMProvider, WorkflowOrchestrator]:
    prompt_registry = PromptRegistry(
        Path(__file__).parents[2] / "src" / "jobfit" / "prompts"
    )
    llm_settings = LLMSettings(
        model="mock-model",
        max_retries=0,
        request_id="workflow-fixture-bootstrap",
        prompt_version="1.0",
    )
    resume_payload = _resume_payload()
    job_payload = _job_payload()
    bootstrap_provider = MockLLMProvider(
        {
            LLMTask.EXTRACT_RESUME: [
                json.dumps(resume_payload, ensure_ascii=False)
            ],
            LLMTask.EXTRACT_JOB: [
                json.dumps(job_payload, ensure_ascii=False)
            ],
        }
    )
    bootstrap_client = MockLLMClient(bootstrap_provider)
    parser = TextDocumentParser()
    resume, registry = ResumeExtractor(
        client=bootstrap_client,
        prompt_registry=prompt_registry,
        settings=llm_settings,
    ).extract(parser.parse_text(_RESUME_TEXT))
    job = JobRequirementExtractor(
        client=bootstrap_client,
        prompt_registry=prompt_registry,
        settings=llm_settings,
    ).extract(
        parser.parse_text(_JOB_TEXT),
        title="AI应用开发实习生",
        company="匿名公司",
    )
    requirement_ids = {
        item.normalized_key: item.requirement_id
        for item in job.requirements.items
    }
    evidence_by_quote = {
        registry.get(evidence_id).quote: registry.get(evidence_id)
        for evidence_id in registry.ids
    }
    match_payload = {
        "matches": [
            RequirementMatchDraft(
                requirement_id=requirement_ids["python"],
                match_status=MatchStatus.MATCHED,
                evidence_items=[evidence_by_quote["技能：Python"]],
                reasoning="简历明确写明Python技能。",
                confidence="0.95",
                improvement_suggestion="补充真实项目中的Python应用深度。",
            ).model_dump(mode="json"),
            RequirementMatchDraft(
                requirement_id=requirement_ids["production_deployment"],
                match_status=MatchStatus.PARTIAL_MATCH,
                evidence_items=[
                    evidence_by_quote["项目：机器学习课程项目"]
                ],
                reasoning="课程项目相关，但没有生产部署证据。",
                confidence="0.80",
                improvement_suggestion="通过真实部署实践补充可验证证据。",
            ).model_dump(mode="json"),
            RequirementMatchDraft(
                requirement_id=requirement_ids["java"],
                match_status=MatchStatus.NOT_MATCHED,
                evidence_items=[evidence_by_quote["说明：没有Java经验"]],
                reasoning="简历明确写明没有Java经验。",
                confidence="0.95",
                missing_evidence_note="存在明确否定表述。",
                improvement_suggestion="仅在岗位确有需要时安排真实学习。",
            ).model_dump(mode="json"),
            RequirementMatchDraft(
                requirement_id=requirement_ids["sql"],
                match_status=MatchStatus.UNKNOWN,
                evidence_items=[],
                reasoning="当前简历未提供足够证据确认SQL能力。",
                confidence="0.70",
                missing_evidence_note="当前简历未提供足够证据确认该能力。",
                improvement_suggestion="确认是否已有SQL经历并补充真实证据。",
            ).model_dump(mode="json"),
        ]
    }
    advice_payload = _advice_payload(
        requirement_ids=requirement_ids,
        evidence_ids={
            quote: item.evidence_id
            for quote, item in evidence_by_quote.items()
        },
    )
    advice_responses = [advice_payload]
    if knowledge_context is not None:
        grounded_payload = dict(advice_payload)
        grounded_payload["knowledge_citation_uses"] = [
            {
                "citation_id": (
                    "cite-ffffffffffffffff"
                    if invalid_knowledge_citation
                    else knowledge_context.citations[0].citation_id
                ),
                "target_type": "recommendation",
                "target_index": 0,
                "purpose": "role_requirement_context",
            }
        ]
        advice_responses = [grounded_payload]
        if invalid_knowledge_citation:
            advice_responses.append(advice_payload)
    provider = MockLLMProvider(
        {
            LLMTask.EXTRACT_RESUME: [
                json.dumps(resume_payload, ensure_ascii=False)
            ],
            LLMTask.EXTRACT_JOB: [
                json.dumps(job_payload, ensure_ascii=False)
            ],
            LLMTask.MATCH_EVIDENCE: [
                json.dumps(match_payload, ensure_ascii=False)
            ],
            LLMTask.GENERATE_ADVICE_BUNDLE: [
                json.dumps(item, ensure_ascii=False)
                for item in advice_responses
            ],
        }
    )
    client = MockLLMClient(provider)
    settings = Settings(
        app_env="test",
        llm_provider="mock",
        llm_model="mock-model",
        demo_mode=True,
    )
    shared_llm_settings = LLMSettings.from_app_settings(settings)
    advice_generator = AdviceBundleGenerator(
        client=client,
        prompt_registry=prompt_registry,
        settings=shared_llm_settings,
        prompt_version="1.2",
    )
    knowledge_retriever = (
        _StaticKnowledgeRetriever(knowledge_context)
        if knowledge_context is not None
        else None
    )
    return provider, WorkflowOrchestrator(
        parser_service=DocumentParserService(settings=settings),
        jd_parser=parser,
        resume_extractor=ResumeExtractor(
            client=client,
            prompt_registry=prompt_registry,
            settings=shared_llm_settings,
        ),
        job_extractor=JobRequirementExtractor(
            client=client,
            prompt_registry=prompt_registry,
            settings=shared_llm_settings,
        ),
        matcher=EvidenceMatcher(
            client=client,
            prompt_registry=prompt_registry,
            settings=shared_llm_settings,
        ),
        evidence_validator=EvidenceValidator(),
        scoring_engine=ScoringEngine(),
        advice_generator=advice_generator,
        knowledge_advice_generator=advice_generator,
        knowledge_retriever=knowledge_retriever,
        fingerprint_context=WorkflowFingerprintContext(
            provider="mock",
            model="mock-model",
            prompt_versions={
                "extract_resume": "1.0",
                "extract_job": "1.0",
                "match_evidence": "1.0",
                "generate_advice_bundle": "1.2",
            },
        ),
    )


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
            {
                "name": "机器学习课程项目",
                "bullets": [],
            },
            EvidenceKind.CONTEXTUAL,
        ),
        (
            "additional_information",
            "说明：没有Java经验",
            {"text": "说明：没有Java经验"},
            EvidenceKind.DIRECT,
        ),
    ):
        start = _RESUME_TEXT.index(quote)
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
    requirements = []
    for (
        source_text,
        requirement_text,
        category,
        normalized_key,
    ) in (
        (
            "必须熟悉Python",
            "熟悉Python",
            "technical_skill",
            "python",
        ),
        (
            "具有生产级机器学习部署经验",
            "具有生产级机器学习部署经验",
            "experience_project",
            "production_deployment",
        ),
        ("熟悉Java", "熟悉Java", "technical_skill", "java"),
        ("熟悉SQL", "熟悉SQL", "technical_skill", "sql"),
    ):
        start = _JOB_TEXT.index(source_text)
        requirements.append(
            {
                "requirement_text": requirement_text,
                "source_text": source_text,
                "source_start_char": start,
                "source_end_char": start + len(source_text),
                "requirement_type": "must_have",
                "category": category,
                "importance": "high",
                "mandatory": True,
                "hard_condition_kind": "none",
                "normalized_key": normalized_key,
            }
        )
    return {
        "title": "AI应用开发实习生",
        "company": None,
        "language": "zh",
        "summary": "匿名演示岗位。",
        "requirements": requirements,
        "keywords": ["Python", "Java", "SQL"],
        "extraction_warnings": [],
    }


def _advice_payload(
    *,
    requirement_ids: dict[str, str],
    evidence_ids: dict[str, str],
) -> dict[str, object]:
    python_req = requirement_ids["python"]
    production_req = requirement_ids["production_deployment"]
    java_req = requirement_ids["java"]
    sql_req = requirement_ids["sql"]
    python_ev = evidence_ids["技能：Python"]
    project_ev = evidence_ids["项目：机器学习课程项目"]
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
                "remediability": GapRemediability.LEARNING_PRACTICE.value,
                "risk_level": Importance.HIGH.value,
                "recommended_action": "通过真实部署练习补充证据。",
                "user_confirmation_needed": False,
            },
            {
                "title": "Java明确缺口",
                "summary": "简历明确写明没有Java经验。",
                "requirement_ids": [java_req],
                "remediability": GapRemediability.LEARNING_PRACTICE.value,
                "risk_level": Importance.HIGH.value,
                "recommended_action": "按岗位需要安排真实学习。",
                "user_confirmation_needed": False,
            },
            {
                "title": "SQL证据待确认",
                "summary": "当前简历未提供足够证据确认SQL能力。",
                "requirement_ids": [sql_req],
                "remediability": GapRemediability.EVIDENCE_NEEDED.value,
                "risk_level": Importance.HIGH.value,
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
            {
                "question": "请介绍机器学习课程项目及个人行动。",
                "intent": "核心项目深挖并核对真实参与范围。",
                "answer_framework": ["说明背景", "说明个人行动", "说明验证方式"],
                "resume_evidence_ids": [project_ev],
                "requirement_ids": [production_req],
                "emphasis": ["只引用课程项目事实"],
                "risks_to_avoid": ["不要表述为生产部署"],
            },
            {
                "question": "Python相关技术方法如何选择？",
                "intent": "考察核心技术和方法理解。",
                "answer_framework": ["说明输入", "说明方法", "说明验证"],
                "resume_evidence_ids": [python_ev],
                "requirement_ids": [python_req],
                "emphasis": [],
                "risks_to_avoid": [],
            },
            {
                "question": "面对业务场景时如何设计机器学习交付方案？",
                "intent": "考察业务需求和方案设计。",
                "answer_framework": ["澄清需求", "提出方案", "说明风险"],
                "resume_evidence_ids": [],
                "requirement_ids": [production_req],
                "emphasis": [],
                "risks_to_avoid": ["不要虚构生产经验"],
            },
            {
                "question": "当前SQL证据不足，你会如何补足这一缺口？",
                "intent": "核验主要缺口与学习计划。",
                "answer_framework": ["说明现状", "说明验证", "说明计划"],
                "resume_evidence_ids": [],
                "requirement_ids": [sql_req],
                "emphasis": [],
                "risks_to_avoid": ["不要把未证明描述为不会"],
            },
            {
                "question": "团队协作中如何沟通、复盘并处理分歧？",
                "intent": "考察协作、复盘和求职动机。",
                "answer_framework": ["说明原则", "说明复盘", "说明假设边界"],
                "resume_evidence_ids": [],
                "requirement_ids": [python_req],
                "emphasis": [],
                "risks_to_avoid": ["没有真实案例时使用假设式回答"],
            },
        ],
    }
