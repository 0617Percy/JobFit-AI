"""Offline tests for source-grounded resume and job extractors."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from jobfit.errors import ErrorCode, SchemaValidationError
from jobfit.extractors import JobRequirementExtractor, ResumeExtractor
from jobfit.llm import LLMSettings, LLMTask, MockLLMClient, MockLLMProvider
from jobfit.llm.prompt_registry import PromptRegistry
from jobfit.models import DocumentContent, EvidenceRegistry, ResumeProfile
from jobfit.parsers.text import TextDocumentParser


@pytest.fixture
def prompt_registry() -> PromptRegistry:
    prompt_root = Path(__file__).parents[2] / "src" / "jobfit" / "prompts"
    return PromptRegistry(prompt_root)


@pytest.fixture
def llm_settings() -> LLMSettings:
    return LLMSettings(
        model="mock-model",
        timeout_seconds=2,
        max_retries=0,
        request_id="request-extractor-test",
        prompt_version="1.0",
    )


def make_document(text: str) -> DocumentContent:
    return TextDocumentParser().parse_text(text)


def candidate(source: str, quote: str) -> dict[str, Any]:
    start = source.index(quote)
    return {
        "quote": quote,
        "start_char": start,
        "end_char": start + len(quote),
        "page_number": None,
        "evidence_kind": "direct",
        "confidence": "0.95",
    }


def resume_fact(
    source: str,
    fact_type: str,
    raw_text: str,
    structured_fields: dict[str, Any],
    *,
    quote: str | None = None,
) -> dict[str, Any]:
    return {
        "fact_type": fact_type,
        "raw_text": raw_text,
        "structured_fields": structured_fields,
        "evidence_candidates": [candidate(source, quote or raw_text)],
    }


def resume_payload(
    source: str,
    facts: list[dict[str, Any]],
    *,
    language: str = "zh",
    basic_info: dict[str, Any] | None = None,
) -> str:
    return json.dumps(
        {
            "language": language,
            "basic_info": basic_info or {},
            "facts": facts,
            "extraction_warnings": [],
        },
        ensure_ascii=False,
    )


def job_requirement(
    source: str,
    source_text: str,
    *,
    requirement_text: str | None = None,
    requirement_type: str = "must_have",
    category: str = "technical_skill",
    importance: str = "high",
    mandatory: bool = True,
    normalized_key: str | None = None,
) -> dict[str, Any]:
    start = source.index(source_text)
    return {
        "requirement_text": requirement_text or source_text,
        "source_text": source_text,
        "source_start_char": start,
        "source_end_char": start + len(source_text),
        "requirement_type": requirement_type,
        "category": category,
        "importance": importance,
        "mandatory": mandatory,
        "hard_condition_kind": "none",
        "normalized_key": normalized_key or source_text.casefold(),
    }


def job_payload(
    requirements: list[dict[str, Any]],
    *,
    title: str | None = "AI应用开发实习生",
    company: str | None = None,
    language: str = "zh",
    keywords: list[str] | None = None,
) -> str:
    return json.dumps(
        {
            "title": title,
            "company": company,
            "language": language,
            "summary": "面向AI应用开发的实习岗位。",
            "requirements": requirements,
            "keywords": keywords or [],
            "extraction_warnings": [],
        },
        ensure_ascii=False,
    )


def make_resume_extractor(
    response: str,
    prompt_registry: PromptRegistry,
    llm_settings: LLMSettings,
) -> tuple[ResumeExtractor, MockLLMProvider]:
    provider = MockLLMProvider({LLMTask.EXTRACT_RESUME: [response]})
    extractor = ResumeExtractor(
        client=MockLLMClient(provider),
        prompt_registry=prompt_registry,
        settings=llm_settings,
    )
    return extractor, provider


def make_job_extractor(
    response: str,
    prompt_registry: PromptRegistry,
    llm_settings: LLMSettings,
) -> tuple[JobRequirementExtractor, MockLLMProvider]:
    provider = MockLLMProvider({LLMTask.EXTRACT_JOB: [response]})
    extractor = JobRequirementExtractor(
        client=MockLLMClient(provider),
        prompt_registry=prompt_registry,
        settings=llm_settings,
    )
    return extractor, provider


def test_resume_extractor_builds_full_grounded_profile(
    prompt_registry: PromptRegistry,
    llm_settings: LLMSettings,
) -> None:
    source = "\n".join(
        [
            "王明",
            "教育：示例大学 计算机科学 本科",
            "实习：示例实验室 数据分析实习生",
            "项目：推荐系统",
            "使用 Python 完成数据清洗",
            "技能：Python",
            "证书：大学英语六级",
            "语言：英语 CET-6",
            "成果：校级一等奖",
        ]
    )
    project_text = "项目：推荐系统\n使用 Python 完成数据清洗"
    facts = [
        resume_fact(source, "basic_info", "王明", {"name": "王明"}),
        resume_fact(
            source,
            "education",
            "教育：示例大学 计算机科学 本科",
            {"institution": "示例大学", "major": "计算机科学", "degree": "本科"},
        ),
        resume_fact(
            source,
            "experience",
            "实习：示例实验室 数据分析实习生",
            {"organization": "示例实验室", "role": "数据分析实习生"},
        ),
        resume_fact(
            source,
            "project",
            project_text,
            {
                "name": "推荐系统",
                "technologies": ["Python"],
                "bullets": ["使用 Python 完成数据清洗"],
            },
        ),
        resume_fact(
            source,
            "skill",
            "技能：Python",
            {"name": "Python", "skill_type": "language"},
        ),
        resume_fact(
            source,
            "certificate",
            "证书：大学英语六级",
            {"name": "大学英语六级"},
        ),
        resume_fact(
            source,
            "language",
            "语言：英语 CET-6",
            {"language": "英语", "proficiency_text": "CET-6"},
        ),
        resume_fact(
            source,
            "achievement",
            "成果：校级一等奖",
            {"name": "校级一等奖"},
        ),
    ]
    extractor, provider = make_resume_extractor(
        resume_payload(source, facts),
        prompt_registry,
        llm_settings,
    )

    profile, evidence = extractor.extract(make_document(source))

    assert isinstance(profile, ResumeProfile)
    assert isinstance(evidence, EvidenceRegistry)
    assert profile.basic_info.name == "王明"
    assert len(profile.education) == 1
    assert len(profile.experiences) == 1
    assert len(profile.projects) == 1
    assert len(profile.skills) == 1
    assert len(profile.certificates) == 1
    assert len(profile.languages) == 1
    assert len(profile.achievements) == 1
    assert profile.projects[0].technologies == ["Python"]
    assert provider.calls[0].task is LLMTask.EXTRACT_RESUME
    assert source in provider.calls[0].messages[1].content


@pytest.mark.parametrize(
    ("source", "facts", "expected_language"),
    [
        (
            "李华\n技能：SQL",
            [resume_fact("李华\n技能：SQL", "skill", "技能：SQL", {"name": "SQL"})],
            "zh",
        ),
        (
            "Alex Chen\nSkills: SQL",
            [
                resume_fact(
                    "Alex Chen\nSkills: SQL",
                    "skill",
                    "Skills: SQL",
                    {"name": "SQL"},
                )
            ],
            "en",
        ),
    ],
)
def test_resume_extractor_supports_chinese_and_english(
    source: str,
    facts: list[dict[str, Any]],
    expected_language: str,
    prompt_registry: PromptRegistry,
    llm_settings: LLMSettings,
) -> None:
    extractor, _ = make_resume_extractor(
        resume_payload(source, facts, language=expected_language),
        prompt_registry,
        llm_settings,
    )

    profile, _ = extractor.extract(make_document(source))

    assert profile.language.value == expected_language
    assert profile.skills[0].name == "SQL"


def test_resume_extractor_allows_missing_education_and_projects(
    prompt_registry: PromptRegistry,
    llm_settings: LLMSettings,
) -> None:
    source = "技能：Python"
    facts = [resume_fact(source, "skill", source, {"name": "Python"})]
    extractor, _ = make_resume_extractor(
        resume_payload(source, facts),
        prompt_registry,
        llm_settings,
    )

    profile, _ = extractor.extract(make_document(source))

    assert profile.education == []
    assert profile.projects == []


def test_resume_extractor_grounds_top_level_basic_info(
    prompt_registry: PromptRegistry,
    llm_settings: LLMSettings,
) -> None:
    source = "Alex Chen\nalex@example.test"
    extractor, _ = make_resume_extractor(
        resume_payload(
            source,
            [],
            language="en",
            basic_info={"name": "Alex Chen", "email": "alex@example.test"},
        ),
        prompt_registry,
        llm_settings,
    )

    profile, evidence = extractor.extract(make_document(source))

    assert profile.basic_info.name == "Alex Chen"
    assert profile.basic_info.email == "alex@example.test"
    assert len(profile.basic_info.evidence_ids) == 2
    assert all(
        evidence.get(evidence_id).quote in source
        for evidence_id in profile.basic_info.evidence_ids
    )


def test_resume_evidence_ids_resolve_to_exact_document_ranges(
    prompt_registry: PromptRegistry,
    llm_settings: LLMSettings,
) -> None:
    source = "技能：Python"
    facts = [resume_fact(source, "skill", source, {"name": "Python"})]
    extractor, _ = make_resume_extractor(
        resume_payload(source, facts),
        prompt_registry,
        llm_settings,
    )
    document = make_document(source)

    profile, evidence = extractor.extract(document)
    evidence_item = evidence.get(profile.skills[0].evidence_ids[0])

    assert evidence_item.document_id == document.document_id
    assert evidence_item.quote == source[evidence_item.start_char : evidence_item.end_char]
    assert evidence_item.segment_id in {segment.segment_id for segment in document.segments}


def test_resume_extractor_assigns_stable_ids(
    prompt_registry: PromptRegistry,
    llm_settings: LLMSettings,
) -> None:
    source = "技能：Python"
    response = resume_payload(
        source,
        [resume_fact(source, "skill", source, {"name": "Python"})],
    )
    first, _ = make_resume_extractor(response, prompt_registry, llm_settings)
    second, _ = make_resume_extractor(response, prompt_registry, llm_settings)
    document = make_document(source)

    first_profile, first_evidence = first.extract(document)
    second_profile, second_evidence = second.extract(document)

    assert first_profile == second_profile
    assert first_evidence.ids == second_evidence.ids


def test_resume_extractor_rejects_hallucinated_positive_claim(
    prompt_registry: PromptRegistry,
    llm_settings: LLMSettings,
) -> None:
    source = "没有Python经验"
    facts = [
        resume_fact(
            source,
            "skill",
            source,
            {"name": "Python", "proficiency_text": "Python开发经验"},
        )
    ]
    extractor, _ = make_resume_extractor(
        resume_payload(source, facts),
        prompt_registry,
        llm_settings,
    )

    with pytest.raises(SchemaValidationError) as exc_info:
        extractor.extract(make_document(source))

    assert exc_info.value.code is ErrorCode.SCHEMA_VALIDATION_FAILED


def test_resume_extractor_rejects_mismatched_evidence_range(
    prompt_registry: PromptRegistry,
    llm_settings: LLMSettings,
) -> None:
    source = "技能：Python"
    fact = resume_fact(source, "skill", source, {"name": "Python"})
    fact["evidence_candidates"][0]["start_char"] = 0
    fact["evidence_candidates"][0]["end_char"] = len("技能：SQL")
    fact["evidence_candidates"][0]["quote"] = "技能：SQL"
    extractor, _ = make_resume_extractor(
        resume_payload(source, [fact]),
        prompt_registry,
        llm_settings,
    )

    with pytest.raises(SchemaValidationError):
        extractor.extract(make_document(source))


def test_job_extractor_builds_requirements_without_scoring(
    prompt_registry: PromptRegistry,
    llm_settings: LLMSettings,
) -> None:
    source = "\n".join(
        [
            "AI应用开发实习生",
            "职责：使用 Python 开发AI应用。",
            "要求：必须熟悉 Python 和 SQL。",
            "加分项：有 Streamlit 使用经验优先。",
        ]
    )
    requirements = [
        job_requirement(
            source,
            "使用 Python 开发AI应用",
            requirement_type="responsibility",
            category="experience_project",
            importance="medium",
            mandatory=False,
            normalized_key="develop-ai-apps",
        ),
        job_requirement(
            source,
            "必须熟悉 Python 和 SQL",
            requirement_text="熟悉 Python",
            normalized_key="python",
        ),
        job_requirement(
            source,
            "必须熟悉 Python 和 SQL",
            requirement_text="熟悉 SQL",
            normalized_key="sql",
        ),
        job_requirement(
            source,
            "有 Streamlit 使用经验优先",
            requirement_type="preferred",
            importance="medium",
            mandatory=False,
            normalized_key="streamlit",
        ),
    ]
    extractor, provider = make_job_extractor(
        job_payload(requirements, keywords=["Python", "SQL", "Streamlit"]),
        prompt_registry,
        llm_settings,
    )

    profile = extractor.extract(make_document(source))

    assert profile.title == "AI应用开发实习生"
    assert profile.company is None
    assert len(profile.requirements.items) == 4
    assert all(item.priority_factor == 0 for item in profile.requirements.items)
    assert all(item.weight == 0 for item in profile.requirements.items)
    assert 0 < profile.requirements.source_coverage_ratio <= 1
    assert provider.calls[0].task is LLMTask.EXTRACT_JOB
    assert source in provider.calls[0].messages[1].content


def test_job_extractor_supports_missing_company_and_education(
    prompt_registry: PromptRegistry,
    llm_settings: LLMSettings,
) -> None:
    source = "数据分析实习生\n要求：熟悉 SQL。"
    requirements = [job_requirement(source, "熟悉 SQL", normalized_key="sql")]
    extractor, _ = make_job_extractor(
        job_payload(requirements, title="数据分析实习生", company=None, keywords=["SQL"]),
        prompt_registry,
        llm_settings,
    )

    profile = extractor.extract(make_document(source))

    assert profile.company is None
    assert all(item.category.value != "education_language" for item in profile.requirements.items)


def test_job_extractor_distinguishes_mandatory_and_preferred(
    prompt_registry: PromptRegistry,
    llm_settings: LLMSettings,
) -> None:
    source = "要求：必须熟悉 Python。\n加分项：了解 Docker 优先。"
    requirements = [
        job_requirement(source, "必须熟悉 Python", normalized_key="python"),
        job_requirement(
            source,
            "了解 Docker 优先",
            requirement_type="preferred",
            importance="medium",
            mandatory=False,
            normalized_key="docker",
        ),
    ]
    extractor, _ = make_job_extractor(
        job_payload(requirements, title=None, keywords=["Python", "Docker"]),
        prompt_registry,
        llm_settings,
    )

    profile = extractor.extract(make_document(source))

    assert profile.requirements.items[0].mandatory is True
    assert profile.requirements.items[1].mandatory is False
    assert profile.requirements.items[1].requirement_type.value == "preferred"


def test_job_extractor_deduplicates_normalized_requirements(
    prompt_registry: PromptRegistry,
    llm_settings: LLMSettings,
) -> None:
    source = "要求：熟悉 Python。"
    duplicate = job_requirement(source, "熟悉 Python", normalized_key="python")
    extractor, _ = make_job_extractor(
        job_payload([duplicate, duplicate], title=None, keywords=["Python"]),
        prompt_registry,
        llm_settings,
    )

    profile = extractor.extract(make_document(source))

    assert len(profile.requirements.items) == 1
    assert profile.requirements.deduplication_notes


def test_job_extractor_accepts_user_title_and_company_overrides(
    prompt_registry: PromptRegistry,
    llm_settings: LLMSettings,
) -> None:
    source = "要求：熟悉 Python。"
    requirements = [job_requirement(source, "熟悉 Python", normalized_key="python")]
    extractor, _ = make_job_extractor(
        job_payload(requirements, title=None, company=None, keywords=["Python"]),
        prompt_registry,
        llm_settings,
    )

    profile = extractor.extract(
        make_document(source),
        title="用户输入岗位",
        company="用户输入公司",
    )

    assert profile.title == "用户输入岗位"
    assert profile.company == "用户输入公司"


def test_job_extractor_rejects_mismatched_source_reference(
    prompt_registry: PromptRegistry,
    llm_settings: LLMSettings,
) -> None:
    source = "要求：熟悉 Python。"
    requirement = job_requirement(source, "熟悉 Python", normalized_key="python")
    requirement["source_text"] = "熟悉 Java"
    extractor, _ = make_job_extractor(
        job_payload([requirement], title=None),
        prompt_registry,
        llm_settings,
    )

    with pytest.raises(SchemaValidationError) as exc_info:
        extractor.extract(make_document(source))

    assert exc_info.value.code is ErrorCode.SCHEMA_VALIDATION_FAILED
