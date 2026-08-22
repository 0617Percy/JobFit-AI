"""Private SQLAlchemy mappings for the reviewed knowledge store."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _enum_check(column: str, values: tuple[str, ...], name: str) -> CheckConstraint:
    allowed = ", ".join(f"'{value}'" for value in values)
    return CheckConstraint(f"{column} IN ({allowed})", name=name)


def _sha256_check(column: str, name: str) -> CheckConstraint:
    return CheckConstraint(
        f"length({column}) = 64 AND lower({column}) = {column} "
        f"AND {column} NOT GLOB '*[^0-9a-f]*'",
        name=name,
    )


class Base(DeclarativeBase):
    """Private declarative registry; never exported from the public package API."""


class KnowledgeBaseVersionRecord(Base):
    __tablename__ = "knowledge_base_versions"
    __table_args__ = (
        UniqueConstraint("version", name="uq_knowledge_version"),
        UniqueConstraint("content_hash", name="uq_knowledge_version_hash"),
        _enum_check(
            "status",
            ("draft", "published", "retired"),
            "ck_knowledge_version_status",
        ),
        _sha256_check("content_hash", "ck_knowledge_version_hash"),
        CheckConstraint(
            "status = 'draft' OR published_at IS NOT NULL",
            name="ck_knowledge_version_publication_time",
        ),
    )

    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    version: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class JobFamilyRecord(Base):
    __tablename__ = "job_families"
    __table_args__ = (
        UniqueConstraint(
            "knowledge_version_id",
            "code",
            name="uq_job_family_version_code",
        ),
    )

    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    code: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    aliases_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    knowledge_version_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_base_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("1"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
    )


class RoleProfileRecord(Base):
    __tablename__ = "role_profiles"
    __table_args__ = (
        UniqueConstraint(
            "knowledge_version_id",
            "code",
            name="uq_role_profile_version_code",
        ),
        _enum_check(
            "review_status",
            ("pending", "approved", "rejected"),
            "ck_role_profile_review_status",
        ),
        Index(
            "ix_role_profiles_version_status_active_code",
            "knowledge_version_id",
            "review_status",
            "is_active",
            "code",
        ),
    )

    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    job_family_id: Mapped[str] = mapped_column(
        ForeignKey("job_families.id", ondelete="RESTRICT"),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    seniority: Mapped[str] = mapped_column(String(80), nullable=False)
    industry: Mapped[str | None] = mapped_column(String(120), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    aliases_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    keywords_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    knowledge_version_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_base_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    review_status: Mapped[str] = mapped_column(String(20), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("1"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
    )


class CompetencyDimensionRecord(Base):
    __tablename__ = "competency_dimensions"
    __table_args__ = (
        UniqueConstraint(
            "knowledge_version_id",
            "code",
            name="uq_competency_dimension_version_code",
        ),
        _enum_check(
            "review_status",
            ("pending", "approved", "rejected"),
            "ck_competency_dimension_review_status",
        ),
        CheckConstraint("display_order >= 0", name="ck_competency_display_order"),
    )

    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    code: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    scoring_category_hint: Mapped[str | None] = mapped_column(
        String(80),
        nullable=True,
    )
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)
    knowledge_version_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_base_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    review_status: Mapped[str] = mapped_column(String(20), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("1"),
    )


class KnowledgeSourceRecord(Base):
    __tablename__ = "knowledge_sources"
    __table_args__ = (
        UniqueConstraint("checksum", name="uq_knowledge_source_checksum"),
        _enum_check(
            "source_type",
            (
                "official_job_description",
                "public_recruitment_page",
                "expert_definition",
                "internal_template",
                "research_report",
            ),
            "ck_knowledge_source_type",
        ),
        _enum_check(
            "reliability_level",
            ("primary", "high", "medium", "low"),
            "ck_knowledge_source_reliability",
        ),
        _enum_check(
            "review_status",
            ("pending", "approved", "rejected"),
            "ck_knowledge_source_review_status",
        ),
        CheckConstraint(
            "source_url IS NULL OR lower(source_url) LIKE 'http://%' "
            "OR lower(source_url) LIKE 'https://%'",
            name="ck_knowledge_source_http_url",
        ),
        _sha256_check("checksum", "ck_knowledge_source_checksum"),
    )

    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    publisher: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
    )
    license_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reliability_level: Mapped[str] = mapped_column(String(20), nullable=False)
    review_status: Mapped[str] = mapped_column(String(20), nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)


class RoleRequirementRecord(Base):
    __tablename__ = "role_requirements"
    __table_args__ = (
        UniqueConstraint(
            "knowledge_version_id",
            "role_profile_id",
            "title",
            name="uq_role_requirement_version_role_title",
        ),
        _enum_check(
            "requirement_type",
            ("responsibility", "must_have", "preferred", "implicit"),
            "ck_role_requirement_type",
        ),
        _enum_check(
            "importance",
            ("low", "medium", "high", "critical"),
            "ck_role_requirement_importance",
        ),
        _enum_check(
            "review_status",
            ("pending", "approved", "rejected"),
            "ck_role_requirement_review_status",
        ),
        Index(
            "ix_role_requirements_version_role_status_active",
            "knowledge_version_id",
            "role_profile_id",
            "review_status",
            "is_active",
        ),
    )

    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    role_profile_id: Mapped[str] = mapped_column(
        ForeignKey("role_profiles.id", ondelete="RESTRICT"),
        nullable=False,
    )
    competency_dimension_id: Mapped[str] = mapped_column(
        ForeignKey("competency_dimensions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    requirement_type: Mapped[str] = mapped_column(String(30), nullable=False)
    importance: Mapped[str] = mapped_column(String(20), nullable=False)
    is_common_hard_blocker: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("0"),
    )
    expected_evidence_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="[]",
    )
    weak_evidence_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="[]",
    )
    negative_signals_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="[]",
    )
    keywords_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    source_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_sources.id", ondelete="RESTRICT"),
        nullable=False,
    )
    knowledge_version_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_base_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    review_status: Mapped[str] = mapped_column(String(20), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("1"),
    )


class EvidencePatternRecord(Base):
    __tablename__ = "evidence_patterns"
    __table_args__ = (
        _enum_check(
            "strength",
            ("strong", "medium", "weak"),
            "ck_evidence_pattern_strength",
        ),
        _enum_check(
            "review_status",
            ("pending", "approved", "rejected"),
            "ck_evidence_pattern_review_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    role_requirement_id: Mapped[str] = mapped_column(
        ForeignKey("role_requirements.id", ondelete="RESTRICT"),
        nullable=False,
    )
    evidence_type: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    strength: Mapped[str] = mapped_column(String(20), nullable=False)
    positive_example: Mapped[str | None] = mapped_column(Text, nullable=True)
    weak_example: Mapped[str | None] = mapped_column(Text, nullable=True)
    negative_example: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_sources.id", ondelete="RESTRICT"),
        nullable=False,
    )
    knowledge_version_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_base_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    review_status: Mapped[str] = mapped_column(String(20), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("1"),
    )


class KnowledgeChunkRecord(Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        _enum_check(
            "review_status",
            ("pending", "approved", "rejected"),
            "ck_knowledge_chunk_review_status",
        ),
        _sha256_check("content_hash", "ck_knowledge_chunk_hash"),
        CheckConstraint(
            "(start_offset IS NULL AND end_offset IS NULL) OR "
            "(start_offset IS NOT NULL AND end_offset IS NOT NULL "
            "AND start_offset >= 0 AND end_offset >= start_offset)",
            name="ck_knowledge_chunk_offset_pair",
        ),
        UniqueConstraint("content_hash", name="uq_knowledge_chunk_hash"),
    )

    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    source_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_sources.id", ondelete="RESTRICT"),
        nullable=False,
    )
    role_profile_id: Mapped[str | None] = mapped_column(
        ForeignKey("role_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    section: Mapped[str | None] = mapped_column(String(120), nullable=True)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    start_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    keywords_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    knowledge_version_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_base_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    review_status: Mapped[str] = mapped_column(String(20), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class InterviewQuestionRecord(Base):
    __tablename__ = "interview_questions"
    __table_args__ = (
        _enum_check(
            "question_type",
            (
                "project_deep_dive",
                "technical",
                "business_scenario",
                "gap_validation",
                "collaboration_motivation",
            ),
            "ck_interview_question_type",
        ),
        _enum_check(
            "difficulty",
            ("basic", "medium", "advanced"),
            "ck_interview_question_difficulty",
        ),
        _enum_check(
            "review_status",
            ("pending", "approved", "rejected"),
            "ck_interview_question_review_status",
        ),
        Index(
            "ix_interview_questions_version_role_status_active",
            "knowledge_version_id",
            "role_profile_id",
            "review_status",
            "is_active",
        ),
    )

    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    role_profile_id: Mapped[str] = mapped_column(
        ForeignKey("role_profiles.id", ondelete="RESTRICT"),
        nullable=False,
    )
    competency_dimension_id: Mapped[str] = mapped_column(
        ForeignKey("competency_dimensions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    question_type: Mapped[str] = mapped_column(String(40), nullable=False)
    expected_points_json: Mapped[str] = mapped_column(Text, nullable=False)
    follow_up_questions_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="[]",
    )
    difficulty: Mapped[str] = mapped_column(String(20), nullable=False)
    source_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_sources.id", ondelete="RESTRICT"),
        nullable=False,
    )
    knowledge_version_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_base_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    review_status: Mapped[str] = mapped_column(String(20), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("1"),
    )


class SourceRoleLinkRecord(Base):
    __tablename__ = "source_role_links"
    __table_args__ = (
        _enum_check(
            "relation_type",
            ("supports", "contrasts", "background"),
            "ck_source_role_link_relation_type",
        ),
    )

    source_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_sources.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    role_profile_id: Mapped[str] = mapped_column(
        ForeignKey("role_profiles.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    knowledge_version_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_base_versions.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    relation_type: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
    )
