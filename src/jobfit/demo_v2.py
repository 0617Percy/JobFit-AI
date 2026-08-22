"""Deterministic, offline-only runtime for the side-by-side v2 RC UI."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from jobfit.advisory.v2 import AdvisoryReportPipeline
from jobfit.extractors.common import stable_id
from jobfit.llm import LLMSettings, MockLLMProvider
from jobfit.models import DocumentContent
from jobfit.models.v2 import JobFamily, VersionManifest
from jobfit.semantic.v2 import SemanticLLMTask, SemanticPipeline, SemanticPromptExecutor
from jobfit.workflow.v2 import AnalysisRepository, V2AnalysisApplication

DEMO_RESUME_TEXT = """Education: BSc Computer Science.
Project: Built and tested a Python model API with structured JSON validation.
Collaboration: Documented trade-offs and reviewed failures with teammates."""

DEMO_JD_TEXT = """AI Application Intern
Build and test Python model API workflows.
Python application delivery with structured output validation is required."""

_PROMPT_ROOT = Path(__file__).parent / "prompts" / "v2"


@dataclass(frozen=True, slots=True)
class V2DemoRuntime:
    application: V2AnalysisApplication
    provider: MockLLMProvider


@dataclass(frozen=True, slots=True)
class _ContentSlice:
    segment_id: str
    start_char: int
    end_char: int
    text: str


def build_demo_runtime(
    *,
    resume_document: DocumentContent,
    jd_document: DocumentContent,
    history: AnalysisRepository | None = None,
    resume_version_id: str = "demo-resume-1",
    jd_snapshot_id: str = "demo-jd-1",
) -> V2DemoRuntime:
    """Build an input-bound mock runtime; it never opens a network connection."""
    provider = MockLLMProvider(
        _build_scripts(
            resume_document=resume_document,
            jd_document=jd_document,
            resume_version_id=resume_version_id,
            jd_snapshot_id=jd_snapshot_id,
        )
    )
    executor = SemanticPromptExecutor(
        provider=provider,
        prompt_root=_PROMPT_ROOT,
        settings=LLMSettings(model="jobfit-v2-rc-mock", max_retries=0),
    )
    versions = VersionManifest(
        software_version="1.1.0",
        prompt_pack_version="1.0.0",
        schema_version="2.0.0",
        scoring_rule_version="1.0.0",
        knowledge_version="2026.08.1",
        analysis_engine_version="1.0.0",
        business_test_set_version="1.0.0",
        golden_set_version="1.0.0",
    )
    application = V2AnalysisApplication(
        semantic_pipeline=SemanticPipeline(executor),
        advisory_pipeline=AdvisoryReportPipeline(executor),
        versions=versions,
        history=history,
    )
    return V2DemoRuntime(application=application, provider=provider)


def _build_scripts(
    *,
    resume_document: DocumentContent,
    jd_document: DocumentContent,
    resume_version_id: str,
    jd_snapshot_id: str,
) -> dict[SemanticLLMTask, list[str]]:
    resume_segment = _content_segment(resume_document, prefer="Project:")
    jd_title_segment = _content_segment(jd_document, prefer="Intern")
    jd_requirement_segment = _content_segment(jd_document, prefer="required")
    jd_responsibility_segment = _content_segment(jd_document, prefer="Build")
    evidence_id = stable_id(
        "evidence",
        resume_version_id,
        resume_document.document_id,
        resume_segment.segment_id,
        resume_segment.start_char,
        resume_segment.end_char,
        resume_segment.text,
    )
    raw_requirement_id = stable_id(
        "raw-requirement",
        jd_snapshot_id,
        jd_document.document_id,
        jd_requirement_segment.segment_id,
        jd_requirement_segment.start_char,
        jd_requirement_segment.end_char,
        jd_requirement_segment.text,
    )
    role_family = _role_family(jd_title_segment.text)
    capability = _role_capability(role_family)
    action_copy = _role_action_copy(role_family, capability)
    requirement_id = stable_id(
        "requirement",
        jd_snapshot_id,
        raw_requirement_id,
        capability,
    )
    scripts: dict[SemanticLLMTask, list[str]] = {
        SemanticLLMTask.P01_RESUME_PARSER: [
            _json(
                {
                    "candidate_profile": {
                        "name": None,
                        "education_level": "bachelor",
                        "current_status": "student",
                        "graduation_date": None,
                        "years_of_full_time_experience": "0",
                    },
                    "education": [
                        {
                            "item_id": "demo-education",
                            "label": "Bachelor-level study",
                            "details": {},
                            "evidence_local_ids": ["demo-evidence"],
                        }
                    ],
                    "skills": [],
                    "projects": [
                        {
                            "item_id": "demo-project",
                            "label": "Application project",
                            "details": {"source": resume_segment.text},
                            "evidence_local_ids": ["demo-evidence"],
                        }
                    ],
                    "internships": [],
                    "work_experience": [],
                    "research": [],
                    "competitions": [],
                    "campus_experience": [],
                    "achievements": [],
                    "evidence_items": [
                        {
                            "local_id": "demo-evidence",
                            "source_type": "project",
                            "quote": resume_segment.text,
                            "document_id": resume_document.document_id,
                            "segment_id": resume_segment.segment_id,
                        }
                    ],
                    "ambiguities": [],
                    "parse_completeness": "complete",
                }
            )
        ],
        SemanticLLMTask.P02_JD_PARSER: [
            _json(
                {
                    "job_title": jd_title_segment.text,
                    "company": None,
                    "location": None,
                    "employment_type": "internship",
                    "job_family": role_family.value,
                    "responsibilities": [
                        _source_item(
                            "demo-responsibility",
                            jd_document,
                            jd_responsibility_segment,
                        )
                    ],
                    "raw_requirements": [
                        _source_item(
                            "demo-requirement",
                            jd_document,
                            jd_requirement_segment,
                        )
                    ],
                    "explicit_constraints": [],
                    "seniority_signals": [],
                    "ambiguities": [],
                    "parse_completeness": "complete",
                }
            )
        ],
        SemanticLLMTask.P03_REQUIREMENT_CLASSIFIER: [
            _json(
                {
                    "requirements": [
                        {
                            "local_id": "demo-classified-requirement",
                            "raw_requirement_ids": [raw_requirement_id],
                            "normalized_capability": capability,
                            "requirement_type": "core",
                            "importance": "high",
                            "critical_status": "not_critical",
                            "classification_reason": (
                                "The source explicitly asks for application delivery."
                            ),
                        }
                    ],
                    "warnings": [],
                }
            )
        ],
        SemanticLLMTask.P04_EVIDENCE_NORMALIZER: [
            _json(
                {
                    "evidence": [
                        {
                            "evidence_id": evidence_id,
                            "normalized_capabilities": [capability],
                            "personal_contribution": "clear",
                            "task_clarity": "high",
                            "method_tool_clarity": "high",
                            "result_clarity": "high",
                            "verification_strength": "medium",
                            "practical_use": "high",
                            "ambiguity": False,
                        }
                    ],
                    "warnings": [],
                }
            )
        ],
        SemanticLLMTask.P05_SEMANTIC_MATCHER: [
            _json(
                {
                    "matches": [
                        {
                            "requirement_id": requirement_id,
                            "matched_evidence": [
                                {
                                    "evidence_id": evidence_id,
                                    "relevance": "high",
                                    "support_type": "direct",
                                }
                            ],
                            "coverage": "full",
                            "evidence_status": "present",
                            "ability_status": "confirmed",
                            "reason": "The cited project directly supports the requirement.",
                        }
                    ],
                    "warnings": [],
                }
            )
        ],
        SemanticLLMTask.P06_ACTIONS: [
            _json(
                {
                    "actions": [
                        {
                            "action_type": "rewrite",
                            "priority": "p0",
                            "related_requirement_ids": [requirement_id],
                            "related_evidence_ids": [evidence_id],
                            "supported_by_evidence_ids": [evidence_id],
                            "source_clarification_ids": [],
                            "knowledge_citation_ids": [],
                            "title": action_copy["rewrite_title"],
                            "why_it_matters": action_copy["rewrite_why"],
                            "recommended_action": resume_segment.text,
                            "completion_criteria": action_copy["rewrite_completion"],
                            "effort": "low",
                            "time_to_complete": "30-45 minutes",
                            "timing": "before_apply",
                            "introduced_claims": [],
                        }
                    ],
                    "warnings": [],
                }
            ),
            _json(
                {
                    "actions": [
                        {
                            "priority": "p1",
                            "related_requirement_ids": [requirement_id],
                            "knowledge_citation_ids": [],
                            "title": action_copy["build_title"],
                            "why_it_matters": action_copy["build_why"],
                            "recommended_action": action_copy["build_action"],
                            "completion_criteria": action_copy["build_completion"],
                            "effort": "medium",
                            "time_to_complete": action_copy["build_time"],
                            "timing": "parallel_with_applications",
                        }
                    ],
                    "warnings": [],
                }
            ),
        ],
        SemanticLLMTask.P07_INTERVIEW: [
            _json(
                {
                    "questions": [
                        {
                            "question_id": "demo-question",
                            "question_type": "resume_deep_dive",
                            "priority": "p0",
                            "question": action_copy["question"],
                            "why_likely": action_copy["question_why"],
                            "related_requirement_ids": [requirement_id],
                            "related_evidence_ids": [evidence_id],
                            "critical_gap_requirement_ids": [],
                            "hard_concern_requirement_ids": [],
                            "related_action_ids": ["p06-candidate-001"],
                            "preparation_points": action_copy["preparation_points"],
                            "knowledge_citation_ids": [],
                        }
                    ],
                    "warnings": [],
                }
            )
        ],
        SemanticLLMTask.P08_REPORT: [
            _json(
                {
                    "job_explanations": [],
                    "implicit_explanations": [],
                    "application_strategy_notes": [
                        "Use the frozen recommendation and current evidence boundary."
                    ],
                    "boundary_notes": [
                        "Missing evidence does not prove missing ability."
                    ],
                    "warnings": [],
                }
            )
        ],
    }
    return scripts


def _content_segment(document: DocumentContent, *, prefer: str) -> _ContentSlice:
    lines = [line for line in document.normalized_text.splitlines() if line.strip()]
    chosen = next(
        (line for line in lines if prefer.casefold() in line.casefold()),
        max(lines, key=len),
    )
    start = document.normalized_text.index(chosen)
    end = start + len(chosen)
    segment = next(
        item
        for item in document.segments
        if item.start_char <= start and end <= item.end_char
    )
    return _ContentSlice(
        segment_id=segment.segment_id,
        start_char=start,
        end_char=end,
        text=chosen,
    )


def _role_action_copy(
    role_family: JobFamily,
    capability: str,
) -> dict[str, str | list[str]]:
    common = {
        "rewrite_title": f"Strengthen the existing project bullet for {capability}",
        "rewrite_why": (
            f"The cited project supports {capability}; make its existing task, "
            "method, validation, and result easier to verify before applying."
        ),
        "rewrite_completion": (
            "The revised bullet preserves the original facts and adds no metric, "
            "result, tool, or ownership not already present in the resume."
        ),
    }
    role_specific: dict[JobFamily, dict[str, str | list[str]]] = {
        JobFamily.AI_APPLICATION: {
            "build_title": "Add reproducible evaluation evidence to the AI application",
            "build_why": (
                "Evaluation is the missing proof needed to explain whether the model "
                "API behaves reliably, not just whether it can be called."
            ),
            "build_action": (
                "Extend the existing model API project with a repeatable evaluation "
                "script, fixed inputs, structured-output checks, and failure logs; "
                "document how another person can rerun the checks."
            ),
            "build_completion": (
                "The repository contains a runnable evaluation script, a result table, "
                "failure examples, and a README; only observed results may be added to "
                "a future resume."
            ),
            "build_time": "4-6 focused hours",
            "question": (
                "How did you validate the model API's structured output, and what "
                "failure cases did you observe?"
            ),
            "question_why": (
                "The role requires reliable AI application delivery, so the interviewer "
                "is likely to test whether validation went beyond a successful API call."
            ),
            "preparation_points": [
                "Validation target: explain how structured-output correctness was defined.",
                "Evidence to recall: use only the model API and JSON validation work "
                "stated in the resume.",
                "Answer structure: task, method, checks, observed result, and limitation.",
                "Follow-up risk: be ready to explain malformed output and retry handling "
                "only if actually tested.",
                "Evidence boundary: do not invent accuracy metrics, production users, "
                "or ownership.",
            ],
        },
        JobFamily.DATA_ANALYTICS: {
            "build_title": "Create verifiable SQL-to-dashboard analysis evidence",
            "build_why": (
                "The role needs proof that SQL results can answer a business question "
                "and survive a basic validation check."
            ),
            "build_action": (
                "Use a synthetic dataset to answer one defined business question with "
                "SQL, validate the aggregates in Python, and present the result in a "
                "small dashboard with documented assumptions."
            ),
            "build_completion": (
                "The repository contains SQL queries, a validation notebook or script, "
                "a dashboard export, and a README linking each metric to its definition."
            ),
            "build_time": "6-8 focused hours",
            "question": (
                "How would you use SQL to answer the dashboard's business question, "
                "validate the metric, and explain an unexpected result?"
            ),
            "question_why": (
                "The role combines SQL, metric reasoning, and communication rather than "
                "judging tool names in isolation."
            ),
            "preparation_points": [
                "Validation target: show how the SQL query maps to the business metric.",
                "Evidence to recall: use only the documented project and dashboard material.",
                "Answer structure: question, data checks, SQL logic, validation, and "
                "interpretation.",
                "Follow-up risk: be ready to discuss nulls, duplicates, and "
                "metric-definition changes.",
                "Evidence boundary: do not invent business impact or stakeholder adoption.",
            ],
        },
        JobFamily.TECHNOLOGY_STRATEGY: {
            "build_title": "Produce a sourced technology-and-commercial research brief",
            "build_why": (
                "The role needs evidence that technical research can support a structured "
                "commercial decision, not only summarize technology."
            ),
            "build_action": (
                "Create a research brief that compares two synthetic technology "
                "alternatives using cited sources, an industry assumption table, "
                "commercial trade-offs, and a one-page executive recommendation with "
                "explicit uncertainty."
            ),
            "build_completion": (
                "The research brief contains traceable sources, a comparison table, "
                "commercial assumptions, an executive summary, and a limitations section."
            ),
            "build_time": "6-10 focused hours",
            "question": (
                "How would you turn technical research into a commercial recommendation "
                "when the industry evidence is incomplete?"
            ),
            "question_why": (
                "The role tests whether research can connect technology, industry context, "
                "commercial reasoning, and structured communication."
            ),
            "preparation_points": [
                "Validation target: explain the decision criteria and treatment of uncertainty.",
                "Evidence to recall: use only the cited research and report work in the resume.",
                "Answer structure: question, sources, comparison, commercial trade-off, "
                "and recommendation.",
                "Follow-up risk: be ready to separate evidence, assumption, and personal judgment.",
                "Evidence boundary: do not invent market data, executive adoption, "
                "or client impact.",
            ],
        },
    }
    return {**common, **role_specific[role_family]}


def _source_item(
    local_id: str,
    document: DocumentContent,
    segment: _ContentSlice,
) -> dict[str, object]:
    return {
        "local_id": local_id,
        "text": segment.text,
        "document_id": document.document_id,
        "segment_id": segment.segment_id,
    }


def _role_family(title: str) -> JobFamily:
    normalized = title.casefold()
    if "data" in normalized or "数据" in normalized:
        return JobFamily.DATA_ANALYTICS
    if "strategy" in normalized or "战略" in normalized:
        return JobFamily.TECHNOLOGY_STRATEGY
    return JobFamily.AI_APPLICATION


def _role_capability(role_family: JobFamily) -> str:
    return {
        JobFamily.AI_APPLICATION: "Python application delivery",
        JobFamily.DATA_ANALYTICS: "SQL business analysis",
        JobFamily.TECHNOLOGY_STRATEGY: (
            "technology research and structured analysis"
        ),
    }.get(role_family, "role-specific application delivery")


def _json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False)
