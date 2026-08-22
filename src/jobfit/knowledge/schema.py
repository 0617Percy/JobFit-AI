"""Knowledge database schema revision constants."""

KNOWLEDGE_SCHEMA_VERSION = 1
KNOWLEDGE_TABLE_NAMES = frozenset(
    {
        "knowledge_base_versions",
        "job_families",
        "role_profiles",
        "competency_dimensions",
        "role_requirements",
        "evidence_patterns",
        "knowledge_sources",
        "knowledge_chunks",
        "interview_questions",
        "source_role_links",
    }
)

__all__ = ["KNOWLEDGE_SCHEMA_VERSION", "KNOWLEDGE_TABLE_NAMES"]
