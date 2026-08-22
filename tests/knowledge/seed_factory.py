"""Anonymous, deterministic seed payloads used only by knowledge tests."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

SEED_FILES = (
    "knowledge_base_version.json",
    "job_families.json",
    "role_profiles.json",
    "competency_dimensions.json",
    "role_requirements.json",
    "evidence_patterns.json",
    "knowledge_sources.json",
    "knowledge_chunks.json",
    "interview_questions.json",
    "source_role_links.json",
)


def valid_seed_payload() -> dict[str, Any]:
    chunk_text = "A synthetic project description can demonstrate a method."
    return {
        "schema_version": "1.0",
        "knowledge_base_version": {
            "id": "kbv-synthetic-2099-01-1",
            "version": "2099.01.1",
            "name": "Synthetic reviewed knowledge",
            "description": "Anonymous offline lifecycle fixture.",
            "status": "draft",
        },
        "job_families": [
            {
                "id": "jf-synthetic-analysis",
                "code": "synthetic_analysis",
                "name": "Synthetic analysis",
                "description": "A fictional role family used only for tests.",
                "aliases": ["sample analysis"],
                "knowledge_version_id": "kbv-synthetic-2099-01-1",
                "is_active": True,
            }
        ],
        "role_profiles": [
            {
                "id": "rp-synthetic-analysis-intern",
                "job_family_id": "jf-synthetic-analysis",
                "code": "synthetic_analysis_intern",
                "name": "Synthetic analysis intern",
                "seniority": "intern",
                "industry": None,
                "description": "A fictional entry-level analysis profile.",
                "aliases": ["sample intern"],
                "keywords": ["analysis", "method"],
                "knowledge_version_id": "kbv-synthetic-2099-01-1",
                "review_status": "approved",
                "is_active": True,
            }
        ],
        "competency_dimensions": [
            {
                "id": "cd-synthetic-method",
                "code": "synthetic_method",
                "name": "Synthetic method",
                "description": "Explain and validate a bounded method.",
                "scoring_category_hint": None,
                "display_order": 1,
                "knowledge_version_id": "kbv-synthetic-2099-01-1",
                "review_status": "approved",
                "is_active": True,
            }
        ],
        "role_requirements": [
            {
                "id": "kr-synthetic-method",
                "role_profile_id": "rp-synthetic-analysis-intern",
                "competency_dimension_id": "cd-synthetic-method",
                "title": "Explain a method",
                "description": "Describe a method and how it was validated.",
                "requirement_type": "must_have",
                "importance": "high",
                "is_common_hard_blocker": False,
                "expected_evidence": ["a concrete project action"],
                "weak_evidence": ["a skill name without context"],
                "negative_signals": ["an explicit contradiction"],
                "keywords": ["method"],
                "source_id": "ks-synthetic-guide",
                "knowledge_version_id": "kbv-synthetic-2099-01-1",
                "review_status": "approved",
                "is_active": True,
            }
        ],
        "evidence_patterns": [
            {
                "id": "ep-synthetic-project",
                "role_requirement_id": "kr-synthetic-method",
                "evidence_type": "project",
                "description": "A project describes an action and validation.",
                "strength": "strong",
                "positive_example": "Applied a method and checked the output.",
                "weak_example": "Aware of the method.",
                "negative_example": None,
                "source_id": "ks-synthetic-guide",
                "knowledge_version_id": "kbv-synthetic-2099-01-1",
                "review_status": "approved",
                "is_active": True,
            }
        ],
        "knowledge_sources": [
            {
                "id": "ks-synthetic-guide",
                "title": "Synthetic role guide",
                "source_type": "internal_template",
                "publisher": "JobFit test fixture",
                "source_url": "https://example.test/knowledge/synthetic-guide",
                "published_at": "2099-01-01T00:00:00Z",
                "collected_at": "2099-01-02T00:00:00Z",
                "license_note": "Original synthetic content for offline tests.",
                "reliability_level": "medium",
                "review_status": "approved",
                "checksum": "b" * 64,
            }
        ],
        "knowledge_chunks": [
            {
                "id": "kc-synthetic-summary",
                "source_id": "ks-synthetic-guide",
                "role_profile_id": "rp-synthetic-analysis-intern",
                "section": "requirements",
                "chunk_text": chunk_text,
                "start_offset": 0,
                "end_offset": len(chunk_text),
                "keywords": ["method", "project"],
                "knowledge_version_id": "kbv-synthetic-2099-01-1",
                "review_status": "approved",
                "content_hash": hashlib.sha256(chunk_text.encode()).hexdigest(),
            }
        ],
        "interview_questions": [
            {
                "id": "iq-synthetic-project",
                "role_profile_id": "rp-synthetic-analysis-intern",
                "competency_dimension_id": "cd-synthetic-method",
                "question": "How did you validate a method in a project?",
                "question_type": "project_deep_dive",
                "expected_points": ["context", "action", "validation"],
                "follow_up_questions": ["What would you change next time?"],
                "difficulty": "medium",
                "source_id": "ks-synthetic-guide",
                "knowledge_version_id": "kbv-synthetic-2099-01-1",
                "review_status": "approved",
                "is_active": True,
            }
        ],
        "source_role_links": [
            {
                "source_id": "ks-synthetic-guide",
                "role_profile_id": "rp-synthetic-analysis-intern",
                "knowledge_version_id": "kbv-synthetic-2099-01-1",
                "relation_type": "supports",
            }
        ],
    }


def synthetic_workflow_seed_payload() -> dict[str, Any]:
    """A richer anonymous package used only by workflow integration tests."""

    payload = copy.deepcopy(valid_seed_payload())
    family = payload["job_families"][0]
    family.update(
        code="synthetic_ai_application",
        name="Synthetic AI application",
        aliases=["sample ai application"],
    )
    role = payload["role_profiles"][0]
    role.update(
        code="synthetic_ai_assistant",
        name="Synthetic AI Assistant",
        description="A fictional AI application profile for offline tests.",
        aliases=["AI应用开发实习生", "sample ai assistant"],
        keywords=["python", "machine learning", "sql", "ai application"],
    )
    requirement = payload["role_requirements"][0]
    requirement.update(
        title="Synthetic Python application practice",
        description="Use Python in a bounded application and validate the result.",
        expected_evidence=["a concrete Python implementation action"],
        keywords=["python", "application"],
    )
    for requirement_id, role_id, title, keywords in (
        (
            "kr-synthetic-research",
            "rp-synthetic-ai-research",
            "Synthetic research practice",
            ["research", "paper"],
        ),
        (
            "kr-synthetic-strategy",
            "rp-synthetic-strategy",
            "Synthetic strategy practice",
            ["strategy", "planning"],
        ),
    ):
        extra_requirement = copy.deepcopy(requirement)
        extra_requirement.update(
            id=requirement_id,
            role_profile_id=role_id,
            title=title,
            description=f"Describe and validate {title.casefold()}.",
            expected_evidence=["a concrete synthetic project action"],
            keywords=keywords,
        )
        payload["role_requirements"].append(extra_requirement)
    payload["job_families"].append(
        {
            "id": "jf-synthetic-strategy",
            "code": "synthetic_strategy",
            "name": "Synthetic strategy",
            "description": "A second fictional family used for isolation tests.",
            "aliases": ["sample strategy"],
            "knowledge_version_id": "kbv-synthetic-2099-01-1",
            "is_active": True,
        }
    )
    payload["role_profiles"].extend(
        [
            {
                "id": "rp-synthetic-ai-research",
                "job_family_id": family["id"],
                "code": "synthetic_ai_research",
                "name": "Synthetic AI Research Assistant",
                "seniority": "intern",
                "industry": None,
                "description": "A nearby fictional research-oriented profile.",
                "aliases": ["sample ai research"],
                "keywords": ["research", "paper", "model"],
                "knowledge_version_id": "kbv-synthetic-2099-01-1",
                "review_status": "approved",
                "is_active": True,
            },
            {
                "id": "rp-synthetic-strategy",
                "job_family_id": "jf-synthetic-strategy",
                "code": "synthetic_strategy_profile",
                "name": "Sample Strategy Profile",
                "seniority": "intern",
                "industry": None,
                "description": "A separate fictional strategy profile.",
                "aliases": ["sample strategy intern"],
                "keywords": ["strategy", "market", "planning"],
                "knowledge_version_id": "kbv-synthetic-2099-01-1",
                "review_status": "approved",
                "is_active": True,
            },
        ]
    )
    payload["source_role_links"].extend(
        [
            {
                "source_id": "ks-synthetic-guide",
                "role_profile_id": "rp-synthetic-ai-research",
                "knowledge_version_id": "kbv-synthetic-2099-01-1",
                "relation_type": "supports",
            },
            {
                "source_id": "ks-synthetic-guide",
                "role_profile_id": "rp-synthetic-strategy",
                "knowledge_version_id": "kbv-synthetic-2099-01-1",
                "relation_type": "supports",
            },
        ]
    )
    return payload


def write_seed_package(
    root: Path,
    payload: dict[str, Any] | None = None,
) -> Path:
    data = payload or valid_seed_payload()
    root.mkdir(parents=True)
    manifest = {"schema_version": "1.0", "files": list(SEED_FILES)}
    (root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    for filename in SEED_FILES:
        key = filename.removesuffix(".json")
        value = data[key]
        (root / filename).write_text(
            json.dumps(value, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return root
