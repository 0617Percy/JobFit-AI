"""Continuous contract checks for the official approved multi-role knowledge seed."""

from __future__ import annotations

from pathlib import Path

import pytest

from jobfit.errors import ErrorCode, KnowledgeSeedError
from jobfit.knowledge.db import KnowledgeDatabase, initialize_knowledge_schema
from jobfit.knowledge.importer import KnowledgeSeedImporter
from jobfit.knowledge.seed_loader import (
    calculate_seed_content_hash,
    load_knowledge_seed,
)
from jobfit.knowledge.versioning import KnowledgeVersionPublisher

SEED_ROOT = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "knowledge"
    / "versions"
    / "2026.08.1"
)
EXPECTED_CONTENT_HASH = "346542eb0c405643a08ebc4bffdab9b5bce22a1b7227f5ad2b27f12e3d1ef7f4"


def _official_bundle():
    return load_knowledge_seed(SEED_ROOT)


def test_official_seed_has_expected_draft_scope() -> None:
    bundle = _official_bundle()

    assert bundle.schema_version == "1.0"
    assert bundle.knowledge_base_version.id == "kbv-2026-08-1"
    assert bundle.knowledge_base_version.version == "2026.08.1"
    assert bundle.knowledge_base_version.status.value == "draft"
    assert {item.id for item in bundle.job_families} == {
        "jf-ai-application",
        "jf-data-analysis",
        "jf-technology-strategy",
    }
    assert {item.id for item in bundle.role_profiles} == {
        "rp-ai-application-intern",
        "rp-data-analyst-intern",
        "rp-technology-strategy-intern",
    }
    assert len(bundle.competency_dimensions) == 31
    assert len(bundle.knowledge_sources) == 21
    assert len(bundle.role_requirements) == 45
    assert len(bundle.evidence_patterns) == 52
    assert len(bundle.interview_questions) == 30
    assert bundle.knowledge_chunks == []
    assert len(bundle.source_role_links) == 21


def test_official_seed_is_publisher_approved_and_non_scoring() -> None:
    bundle = _official_bundle()
    reviewed = (
        *bundle.role_profiles,
        *bundle.competency_dimensions,
        *bundle.knowledge_sources,
        *bundle.role_requirements,
        *bundle.evidence_patterns,
        *bundle.interview_questions,
    )

    assert len(reviewed) == 182
    assert {item.review_status.value for item in reviewed} == {"approved"}
    assert not any(item.is_common_hard_blocker for item in bundle.role_requirements)
    assert all(
        dimension.scoring_category_hint is None
        for dimension in bundle.competency_dimensions
    )


def test_official_seed_sources_are_used_and_licensed() -> None:
    bundle = _official_bundle()
    source_ids = {source.id for source in bundle.knowledge_sources}
    linked_ids = {link.source_id for link in bundle.source_role_links}
    content_source_ids = {
        item.source_id
        for collection in (
            bundle.role_requirements,
            bundle.evidence_patterns,
            bundle.interview_questions,
        )
        for item in collection
    }

    assert source_ids == linked_ids
    assert source_ids <= content_source_ids
    assert all(source.license_note for source in bundle.knowledge_sources)
    assert all(source.source_url is not None for source in bundle.knowledge_sources)


def test_official_ai_seed_reflects_b1f_user_decisions() -> None:
    bundle = _official_bundle()
    requirements = {item.id: item for item in bundle.role_requirements}
    questions = {item.id: item for item in bundle.interview_questions}
    sources = {item.id: item for item in bundle.knowledge_sources}
    ai_requirements = [
        item
        for item in bundle.role_requirements
        if item.role_profile_id == "rp-ai-application-intern"
    ]

    assert requirements["kr-ai-python-implementation"].title == (
        "使用Python或等价语言实现可运行的AI应用组件"
    )
    assert {
        requirements[item_id].requirement_type.value
        for item_id in (
            "kr-ai-model-api-integration",
            "kr-ai-output-debugging",
            "kr-ai-privacy-security",
        )
    } == {"responsibility"}
    assert {
        requirements[item_id].importance.value
        for item_id in (
            "kr-ai-agent-workflow",
            "kr-ai-project-communication",
            "kr-ai-prompt-design",
        )
    } == {"medium"}
    assert sum(item.requirement_type.value == "must_have" for item in ai_requirements) == 1
    assert sum(item.requirement_type.value == "responsibility" for item in ai_requirements) == 11
    assert sum(item.importance.value == "high" for item in ai_requirements) == 9
    assert sum(item.importance.value == "medium" for item in ai_requirements) == 6
    assert questions["iq-ai-evaluation"].difficulty.value == "medium"
    assert questions["iq-ai-tradeoff"].difficulty.value == "medium"
    assert sources["ks-ai-google-managing-ml-projects"].published_at is None


def test_official_data_analyst_seed_reflects_b2f_user_decisions() -> None:
    bundle = _official_bundle()
    data_role_id = "rp-data-analyst-intern"
    role = next(item for item in bundle.role_profiles if item.id == data_role_id)
    requirement_by_id = {item.id: item for item in bundle.role_requirements}
    question_by_id = {item.id: item for item in bundle.interview_questions}
    requirements = [
        item for item in bundle.role_requirements if item.role_profile_id == data_role_id
    ]
    questions = [
        item for item in bundle.interview_questions if item.role_profile_id == data_role_id
    ]
    patterns = [
        item
        for item in bundle.evidence_patterns
        if item.role_requirement_id.startswith("kr-da-")
    ]
    links = [
        item for item in bundle.source_role_links if item.role_profile_id == data_role_id
    ]

    assert len(requirements) == 15
    assert len(patterns) == 18
    assert len(questions) == 10
    assert len(links) == 7
    assert sum(item.requirement_type.value == "must_have" for item in requirements) == 1
    assert sum(item.requirement_type.value == "responsibility" for item in requirements) == 11
    assert sum(item.requirement_type.value == "preferred" for item in requirements) == 2
    assert sum(item.requirement_type.value == "implicit" for item in requirements) == 1
    assert sum(item.importance.value == "high" for item in requirements) == 9
    assert sum(item.importance.value == "medium" for item in requirements) == 6
    assert role.aliases == [
        "Analytics Intern",
        "Business Data Analyst Intern",
        "Business Intelligence Intern (analysis focus)",
        "Operations Analytics Intern",
        "Reporting Analyst Intern (analysis focus)",
    ]
    assert (
        requirement_by_id["kr-da-stakeholder-collaboration"].importance.value
        == "medium"
    )
    assert requirement_by_id["kr-da-visualization-dashboard"].title == (
        "制作适合受众的可视化、报告或Dashboard"
    )
    assert question_by_id["iq-da-scope-boundary"].difficulty.value == "medium"
    assert not any(item.is_common_hard_blocker for item in requirements)
    assert {item.source_id for item in links} == {
        "ks-da-amazon-bi-intern-3149400",
        "ks-da-apple-japan-data-analyst-intern",
        "ks-da-bls-operations-research",
        "ks-da-google-data-analytics-certificate",
        "ks-da-microsoft-pl-300",
        "ks-da-onet-bi-analysts",
        "ks-da-skills-england-st0118",
    }
    assert {
        item.relation_type.value
        for item in links
        if item.source_id == "ks-da-bls-operations-research"
    } == {"contrasts"}
    continuous_improvement_patterns = [
        item
        for item in patterns
        if item.role_requirement_id == "kr-da-continuous-improvement"
    ]
    assert len(continuous_improvement_patterns) == 1
    pattern = continuous_improvement_patterns[0]
    assert pattern.id == "ep-da-continuous-improvement-medium"
    assert pattern.evidence_type == "analysis_improvement_record"
    assert pattern.strength.value == "medium"
    assert pattern.source_id == "ks-da-amazon-bi-intern-3149400"


def test_official_active_requirements_have_active_evidence_patterns() -> None:
    bundle = _official_bundle()
    active_requirement_ids = {
        item.id for item in bundle.role_requirements if item.is_active
    }
    covered_requirement_ids = {
        item.role_requirement_id
        for item in bundle.evidence_patterns
        if item.is_active
        and item.knowledge_version_id == bundle.knowledge_base_version.id
    }

    assert active_requirement_ids <= covered_requirement_ids


def test_official_technology_strategy_seed_reflects_b3f_user_decisions() -> None:
    bundle = _official_bundle()
    role_id = "rp-technology-strategy-intern"
    role = next(item for item in bundle.role_profiles if item.id == role_id)
    requirement_by_id = {item.id: item for item in bundle.role_requirements}
    question_by_id = {item.id: item for item in bundle.interview_questions}
    requirements = [
        item for item in bundle.role_requirements if item.role_profile_id == role_id
    ]
    questions = [
        item for item in bundle.interview_questions if item.role_profile_id == role_id
    ]
    patterns = [
        item
        for item in bundle.evidence_patterns
        if item.role_requirement_id.startswith("kr-ts-")
    ]
    links = [
        item for item in bundle.source_role_links if item.role_profile_id == role_id
    ]

    assert role.code == "technology_strategy_intern"
    assert role.seniority == "intern"
    assert role.aliases == [
        "Digital Strategy Intern (technology focus)",
        "Innovation Strategy Intern (technology focus)",
        "Strategic Technology Research Intern",
        "Tech Strategy Intern",
        "Technology Intelligence Intern",
        "Technology Strategy Analyst Intern",
    ]
    assert len(requirements) == 15
    assert len(patterns) == 17
    assert len(questions) == 10
    assert len(links) == 7
    assert sum(item.requirement_type.value == "must_have" for item in requirements) == 1
    assert sum(item.requirement_type.value == "responsibility" for item in requirements) == 11
    assert sum(item.requirement_type.value == "preferred" for item in requirements) == 2
    assert sum(item.requirement_type.value == "implicit" for item in requirements) == 1
    assert sum(item.importance.value == "high" for item in requirements) == 8
    assert sum(item.importance.value == "medium" for item in requirements) == 7
    assert requirement_by_id["kr-ts-source-grounded-research"].requirement_type.value == (
        "must_have"
    )
    assert requirement_by_id["kr-ts-source-grounded-research"].importance.value == (
        "high"
    )
    assert requirement_by_id["kr-ts-scenario-roadmapping"].importance.value == (
        "medium"
    )
    assert requirement_by_id["kr-ts-executive-synthesis"].title == (
        "形成面向决策的技术战略分析摘要"
    )
    assert question_by_id["iq-ts-scenario-roadmap"].difficulty.value == "medium"
    assert not any(item.is_common_hard_blocker for item in requirements)
    assert {item.source_id for item in links} == {
        "ks-ts-amazon-wwtd-strategy-2990306",
        "ks-ts-bcg-digital-consultant",
        "ks-ts-jrc-technology-foresight-2023",
        "ks-ts-oecd-sti-outlook-2025",
        "ks-ts-openai-competitive-intelligence",
        "ks-ts-uk-futures-toolkit-2024",
        "ks-ts-wef-future-jobs-2025",
    }
    assert {
        item.relation_type.value
        for item in links
        if item.source_id in {
            "ks-ts-bcg-digital-consultant",
            "ks-ts-wef-future-jobs-2025",
        }
    } == {"background"}


def test_official_seed_canonical_hash_is_stable() -> None:
    bundle = _official_bundle()

    assert calculate_seed_content_hash(bundle) == EXPECTED_CONTENT_HASH


def test_official_seed_import_is_idempotent_and_publish_is_immutable(
    tmp_path: Path,
) -> None:
    bundle = _official_bundle()
    database_path = tmp_path / "official-approved.sqlite3"
    database = KnowledgeDatabase(database_path)
    initialize_knowledge_schema(database)
    importer = KnowledgeSeedImporter(database)

    try:
        first = importer.import_seed(bundle)
        second = importer.import_seed(bundle)
        published = KnowledgeVersionPublisher(database).publish(first.version_id)

        assert first.created is True
        assert first.idempotent is False
        assert second.created is False
        assert second.idempotent is True
        assert second.content_hash == first.content_hash == EXPECTED_CONTENT_HASH
        assert published.status == "published"
        assert published.content_hash == EXPECTED_CONTENT_HASH
        assert first.counts.job_families == 3
        assert first.counts.role_profiles == 3
        assert first.counts.competency_dimensions == 31
        assert first.counts.role_requirements == 45
        assert first.counts.evidence_patterns == 52
        assert first.counts.knowledge_sources == 21
        assert first.counts.interview_questions == 30
        assert first.counts.knowledge_chunks == 0
        assert first.counts.source_role_links == 21

        with pytest.raises(KnowledgeSeedError) as exc_info:
            KnowledgeVersionPublisher(database).publish(first.version_id)

        assert exc_info.value.code is ErrorCode.KNOWLEDGE_PUBLISHED_IMMUTABLE
    finally:
        database.dispose()
        for database_file in tmp_path.glob("official-approved.sqlite3*"):
            database_file.unlink()
