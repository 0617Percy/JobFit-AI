"""Anonymous SQLite fixtures for the job-knowledge persistence tests."""

from __future__ import annotations

import importlib
from datetime import UTC, datetime

import pytest


@pytest.fixture
def knowledge_modules():
    return {
        "db": importlib.import_module("jobfit.knowledge.db"),
        "orm": importlib.import_module("jobfit.knowledge.orm"),
        "repository": importlib.import_module("jobfit.knowledge.repository"),
        "schema": importlib.import_module("jobfit.knowledge.schema"),
    }


@pytest.fixture
def knowledge_database(tmp_path, knowledge_modules):
    db_module = knowledge_modules["db"]
    database = db_module.KnowledgeDatabase(tmp_path / "nested" / "knowledge.sqlite3")
    db_module.initialize_knowledge_schema(database)
    yield database
    database.dispose()


@pytest.fixture
def seeded_database(knowledge_database, knowledge_modules):
    orm = knowledge_modules["orm"]
    now = datetime(2026, 7, 25, 8, 0, tzinfo=UTC)
    with knowledge_database._session_scope() as session:
        session.add(
            orm.KnowledgeBaseVersionRecord(
                id="kbv-2026-07-1",
                version="2026.07.1",
                name="Anonymous reviewed knowledge",
                description="Offline persistence fixture",
                status="published",
                published_at=now,
                created_at=now,
                content_hash="a" * 64,
            )
        )
        session.add(
            orm.KnowledgeSourceRecord(
                id="ks-public-ai-role",
                title="Anonymous public role guide",
                source_type="official_job_description",
                publisher="Anonymous publisher",
                source_url="https://example.com/jobs/ai-intern",
                published_at=now,
                collected_at=now,
                license_note="Short reviewed summary used for tests.",
                reliability_level="primary",
                review_status="approved",
                checksum="b" * 64,
            )
        )
        session.flush()
        session.add(
            orm.JobFamilyRecord(
                id="jf-ai-application",
                code="ai_application",
                name="AI application",
                description="Anonymous AI application family",
                aliases_json='["ai application"]',
                knowledge_version_id="kbv-2026-07-1",
                is_active=True,
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            orm.CompetencyDimensionRecord(
                id="cd-application-engineering",
                code="application_engineering",
                name="Application engineering",
                description="Build and validate bounded AI applications.",
                scoring_category_hint=None,
                display_order=1,
                knowledge_version_id="kbv-2026-07-1",
                review_status="approved",
                is_active=True,
            )
        )
        session.flush()
        session.add(
            orm.RoleProfileRecord(
                id="rp-ai-application-intern",
                job_family_id="jf-ai-application",
                code="ai_application_intern",
                name="AI application intern",
                seniority="intern",
                industry=None,
                description="Anonymous entry-level application role.",
                aliases_json='["ai intern"]',
                keywords_json='["python","llm"]',
                knowledge_version_id="kbv-2026-07-1",
                review_status="approved",
                is_active=True,
                created_at=now,
                updated_at=now,
            )
        )
        session.flush()
        session.add(
            orm.RoleRequirementRecord(
                id="kr-python-application",
                role_profile_id="rp-ai-application-intern",
                competency_dimension_id="cd-application-engineering",
                title="Python application development",
                description="Use Python to implement and validate application logic.",
                requirement_type="must_have",
                importance="high",
                is_common_hard_blocker=True,
                expected_evidence_json='["implemented a Python project"]',
                weak_evidence_json='["listed Python only"]',
                negative_signals_json='["explicitly no Python experience"]',
                keywords_json='["python"]',
                source_id="ks-public-ai-role",
                knowledge_version_id="kbv-2026-07-1",
                review_status="approved",
                is_active=True,
            )
        )
        session.add(
            orm.KnowledgeChunkRecord(
                id="kc-ai-role-summary",
                source_id="ks-public-ai-role",
                role_profile_id="rp-ai-application-intern",
                section="requirements",
                chunk_text="Python is commonly used for application implementation.",
                start_offset=0,
                end_offset=55,
                keywords_json='["python"]',
                knowledge_version_id="kbv-2026-07-1",
                review_status="approved",
                content_hash="c" * 64,
            )
        )
        session.add(
            orm.SourceRoleLinkRecord(
                source_id="ks-public-ai-role",
                role_profile_id="rp-ai-application-intern",
                knowledge_version_id="kbv-2026-07-1",
                relation_type="supports",
                created_at=now,
            )
        )
        session.flush()
        session.add(
            orm.EvidencePatternRecord(
                id="ep-python-project",
                role_requirement_id="kr-python-application",
                evidence_type="project",
                description="A project states a concrete Python implementation action.",
                strength="strong",
                positive_example="Implemented data processing in Python.",
                weak_example="Familiar with Python.",
                negative_example=None,
                source_id="ks-public-ai-role",
                knowledge_version_id="kbv-2026-07-1",
                review_status="approved",
                is_active=True,
            )
        )
        session.add(
            orm.InterviewQuestionRecord(
                id="iq-ai-project",
                role_profile_id="rp-ai-application-intern",
                competency_dimension_id="cd-application-engineering",
                question="Describe an AI application project you implemented.",
                question_type="project_deep_dive",
                expected_points_json='["context","action","validation"]',
                follow_up_questions_json='["How did you validate the output?"]',
                difficulty="medium",
                source_id="ks-public-ai-role",
                knowledge_version_id="kbv-2026-07-1",
                review_status="approved",
                is_active=True,
            )
        )
    return knowledge_database
