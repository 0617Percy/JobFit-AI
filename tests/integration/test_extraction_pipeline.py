"""Offline document-to-domain extraction integration tests."""

from __future__ import annotations

import json
from pathlib import Path

from jobfit.extractors import JobRequirementExtractor, ResumeExtractor
from jobfit.llm import LLMSettings, LLMTask, MockLLMClient, MockLLMProvider
from jobfit.llm.prompt_registry import PromptRegistry
from jobfit.parsers.text import TextDocumentParser


def test_mock_llm_extracts_resume_and_job_documents() -> None:
    resume_text = "匿名候选人\n技能：Python"
    skill_start = resume_text.index("技能：Python")
    job_text = "AI应用开发实习生\n要求：必须熟悉 Python。"
    requirement_source = "必须熟悉 Python"
    requirement_start = job_text.index(requirement_source)
    provider = MockLLMProvider(
        {
            LLMTask.EXTRACT_RESUME: [
                json.dumps(
                    {
                        "language": "zh",
                        "basic_info": {"name": "匿名候选人"},
                        "facts": [
                            {
                                "fact_type": "skill",
                                "raw_text": "技能：Python",
                                "structured_fields": {"name": "Python"},
                                "evidence_candidates": [
                                    {
                                        "quote": "技能：Python",
                                        "start_char": skill_start,
                                        "end_char": skill_start + len("技能：Python"),
                                        "page_number": None,
                                        "evidence_kind": "direct",
                                        "confidence": "0.95",
                                    }
                                ],
                            }
                        ],
                        "extraction_warnings": [],
                    },
                    ensure_ascii=False,
                )
            ],
            LLMTask.EXTRACT_JOB: [
                json.dumps(
                    {
                        "title": "AI应用开发实习生",
                        "company": None,
                        "language": "zh",
                        "summary": "岗位摘要仅作为草稿。",
                        "requirements": [
                            {
                                "requirement_text": "熟悉 Python",
                                "source_text": requirement_source,
                                "source_start_char": requirement_start,
                                "source_end_char": requirement_start
                                + len(requirement_source),
                                "requirement_type": "must_have",
                                "category": "technical_skill",
                                "importance": "high",
                                "mandatory": True,
                                "hard_condition_kind": "none",
                                "normalized_key": "python",
                            }
                        ],
                        "keywords": ["Python"],
                        "extraction_warnings": [],
                    },
                    ensure_ascii=False,
                )
            ],
        }
    )
    client = MockLLMClient(provider)
    registry = PromptRegistry(
        Path(__file__).parents[2] / "src" / "jobfit" / "prompts"
    )
    settings = LLMSettings(
        model="mock-model",
        max_retries=0,
        request_id="integration-extraction",
        prompt_version="1.0",
    )
    parser = TextDocumentParser()

    resume, evidence = ResumeExtractor(
        client=client,
        prompt_registry=registry,
        settings=settings,
    ).extract(parser.parse_text(resume_text))
    job = JobRequirementExtractor(
        client=client,
        prompt_registry=registry,
        settings=settings,
    ).extract(parser.parse_text(job_text))

    assert resume.basic_info.name == "匿名候选人"
    assert resume.skills[0].name == "Python"
    assert evidence.require_many(resume.skills[0].evidence_ids)
    assert job.requirements.items[0].requirement_text == "熟悉 Python"
    assert job.requirements.items[0].weight == 0
    assert provider.call_count == 2
