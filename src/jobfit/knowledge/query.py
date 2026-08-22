"""Validated, persistence-agnostic knowledge search queries."""

from __future__ import annotations

from dataclasses import dataclass

from jobfit.models import Importance, RequirementType

DEFAULT_KNOWLEDGE_LIMIT = 12
MAX_KNOWLEDGE_LIMIT = 20


def _normalize_required(value: str, *, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    return normalized


def _normalize_optional(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _normalize_terms(values: tuple[str, ...], *, field_name: str) -> tuple[str, ...]:
    normalized = tuple(
        _normalize_required(value, field_name=field_name) for value in values
    )
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{field_name} must not contain duplicates")
    return normalized


def validate_knowledge_limit(limit: int) -> int:
    """Return a bounded result limit or reject unsafe and ambiguous values."""
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ValueError("limit must be an integer")
    if not 1 <= limit <= MAX_KNOWLEDGE_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_KNOWLEDGE_LIMIT}")
    return limit


@dataclass(frozen=True, slots=True)
class RoleProfileQuery:
    title: str
    aliases: tuple[str, ...] = ()
    seniority: str | None = None
    industry: str | None = None
    keywords: tuple[str, ...] = ()
    job_family_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "title",
            _normalize_required(self.title, field_name="title"),
        )
        object.__setattr__(
            self,
            "aliases",
            _normalize_terms(self.aliases, field_name="aliases"),
        )
        object.__setattr__(self, "seniority", _normalize_optional(self.seniority))
        object.__setattr__(self, "industry", _normalize_optional(self.industry))
        object.__setattr__(
            self,
            "keywords",
            _normalize_terms(self.keywords, field_name="keywords"),
        )
        object.__setattr__(
            self,
            "job_family_codes",
            _normalize_terms(
                self.job_family_codes,
                field_name="job_family_codes",
            ),
        )


@dataclass(frozen=True, slots=True)
class KnowledgeSearchQuery:
    role_profile_ids: tuple[str, ...]
    terms: tuple[str, ...] = ()
    requirement_types: tuple[RequirementType, ...] = ()
    importance_levels: tuple[Importance, ...] = ()
    source_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        role_ids = _normalize_terms(
            self.role_profile_ids,
            field_name="role_profile_ids",
        )
        if not role_ids:
            raise ValueError("role_profile_ids must not be empty")
        if any(not role_id.startswith("rp-") for role_id in role_ids):
            raise ValueError("role_profile_ids contain an invalid role ID")
        object.__setattr__(self, "role_profile_ids", role_ids)
        object.__setattr__(
            self,
            "terms",
            _normalize_terms(self.terms, field_name="terms"),
        )
        if len(self.requirement_types) != len(set(self.requirement_types)):
            raise ValueError("requirement_types must not contain duplicates")
        if len(self.importance_levels) != len(set(self.importance_levels)):
            raise ValueError("importance_levels must not contain duplicates")
        source_ids = _normalize_terms(self.source_ids, field_name="source_ids")
        if any(not source_id.startswith("ks-") for source_id in source_ids):
            raise ValueError("source_ids contain an invalid source ID")
        object.__setattr__(self, "source_ids", source_ids)


__all__ = [
    "DEFAULT_KNOWLEDGE_LIMIT",
    "KnowledgeSearchQuery",
    "MAX_KNOWLEDGE_LIMIT",
    "RoleProfileQuery",
    "validate_knowledge_limit",
]
