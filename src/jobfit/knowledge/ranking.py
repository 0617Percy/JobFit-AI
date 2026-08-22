"""Versioned Decimal ranking shared by every knowledge recall backend."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from jobfit.knowledge.normalization import (
    normalize_query_terms,
    normalize_search_text,
)
from jobfit.knowledge.query import (
    KnowledgeSearchQuery,
    RoleProfileQuery,
    validate_knowledge_limit,
)
from jobfit.models import Importance

RETRIEVAL_STRATEGY_VERSION = "1.0"
ROLE_RELEVANCE_THRESHOLD = Decimal("0.4500")
REQUIREMENT_RELEVANCE_THRESHOLD = Decimal("0.3500")
_FOUR_PLACES = Decimal("0.0001")
_IMPORTANCE = {
    Importance.CRITICAL: Decimal("1"),
    Importance.HIGH: Decimal("0.75"),
    Importance.MEDIUM: Decimal("0.50"),
    Importance.LOW: Decimal("0.25"),
}
_IMPORTANCE_ORDER = {
    Importance.CRITICAL: 0,
    Importance.HIGH: 1,
    Importance.MEDIUM: 2,
    Importance.LOW: 3,
    None: 4,
}
_ENTITY_ORDER = {
    "role_profile": 0,
    "role_requirement": 1,
    "evidence_pattern": 2,
    "knowledge_chunk": 3,
    "interview_question": 4,
}


@dataclass(frozen=True, slots=True)
class RoleRankCandidate:
    entity_id: str
    code: str
    name: str
    aliases: tuple[str, ...]
    keywords: tuple[str, ...]
    description: str
    seniority: str
    industry: str | None


@dataclass(frozen=True, slots=True)
class RequirementRankCandidate:
    entity_id: str
    role_profile_id: str
    title: str
    keywords: tuple[str, ...]
    description: str
    expected_evidence: tuple[str, ...]
    importance: Importance


@dataclass(frozen=True, slots=True)
class KnowledgeRankScore:
    relevance: Decimal
    matched_fields: tuple[str, ...]
    matched_terms: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RankedKnowledgeCandidate:
    entity_type: str
    entity_id: str
    relevance: Decimal
    importance: Importance | None
    matched_fields: tuple[str, ...]
    matched_terms: tuple[str, ...]


def _quantize(value: Decimal) -> Decimal:
    return min(Decimal("1"), max(Decimal("0"), value)).quantize(
        _FOUR_PLACES,
        rounding=ROUND_HALF_UP,
    )


def _coverage(query_tokens: tuple[str, ...], candidate_values: tuple[str, ...]) -> Decimal:
    candidate_tokens = normalize_query_terms(candidate_values)
    if not candidate_tokens:
        return Decimal("0")
    query_set = set(query_tokens)
    return Decimal(len(query_set.intersection(candidate_tokens))) / Decimal(
        len(candidate_tokens)
    )


def _matched_terms(
    query_tokens: tuple[str, ...],
    candidate_values: tuple[str, ...],
) -> tuple[str, ...]:
    known = set(normalize_query_terms(candidate_values))
    return tuple(token for token in query_tokens if token in known)


def score_role_candidate(
    query: RoleProfileQuery,
    candidate: RoleRankCandidate,
) -> KnowledgeRankScore:
    query_titles = tuple(
        normalize_search_text(value) for value in (query.title, *query.aliases)
    )
    normalized_name = normalize_search_text(candidate.name)
    normalized_code = normalize_search_text(candidate.code.replace("_", " "))
    normalized_aliases = {
        normalize_search_text(value) for value in candidate.aliases
    }
    query_tokens = normalize_query_terms(
        (query.title, *query.aliases, *query.keywords)
    )
    exact_name = normalized_name in query_titles
    code_match = normalized_code in query_titles
    exact_title = exact_name or code_match
    exact_alias = not exact_title and bool(
        normalized_aliases.intersection(query_titles)
    )
    name_coverage = _coverage(query_tokens, (candidate.name,))
    keyword_coverage = _coverage(query_tokens, candidate.keywords)
    industry_match = bool(
        query.industry
        and candidate.industry
        and normalize_search_text(query.industry)
        == normalize_search_text(candidate.industry)
    )
    seniority_match = bool(
        query.seniority
        and normalize_search_text(query.seniority)
        == normalize_search_text(candidate.seniority)
    )
    score = (
        Decimal("0.45") * Decimal(exact_title)
        + Decimal("0.35") * Decimal(exact_alias)
        + Decimal("0.25") * name_coverage
        + Decimal("0.20") * keyword_coverage
        + Decimal("0.10") * Decimal(industry_match)
        + Decimal("0.05") * Decimal(seniority_match)
    )
    fields: list[str] = []
    if code_match:
        fields.append("code")
    if exact_title:
        if exact_name:
            fields.append("name")
        fields.append("phrase")
    elif exact_alias:
        fields.append("alias")
        if name_coverage:
            fields.append("name")
    elif name_coverage:
        fields.append("name")
    if keyword_coverage:
        fields.append("keywords")
    if industry_match:
        fields.append("industry")
    if seniority_match:
        fields.append("seniority")
    return KnowledgeRankScore(
        relevance=_quantize(score),
        matched_fields=tuple(fields),
        matched_terms=_matched_terms(
            query_tokens,
            (candidate.code, candidate.name, *candidate.aliases, *candidate.keywords),
        ),
    )


def score_requirement_candidate(
    query: KnowledgeSearchQuery,
    candidate: RequirementRankCandidate,
    *,
    role_relevance: Decimal,
) -> KnowledgeRankScore:
    query_tokens = normalize_query_terms(query.terms)
    title_coverage = _coverage(query_tokens, (candidate.title,))
    keyword_coverage = _coverage(query_tokens, candidate.keywords)
    description_coverage = _coverage(query_tokens, (candidate.description,))
    evidence_coverage = _coverage(query_tokens, candidate.expected_evidence)
    if query_tokens and not any(
        (
            title_coverage,
            keyword_coverage,
            description_coverage,
            evidence_coverage,
        )
    ):
        return KnowledgeRankScore(
            relevance=Decimal("0.0000"),
            matched_fields=(),
            matched_terms=(),
        )
    score = (
        Decimal("0.35") * role_relevance
        + Decimal("0.25") * title_coverage
        + Decimal("0.20") * keyword_coverage
        + Decimal("0.10") * description_coverage
        + Decimal("0.10") * _IMPORTANCE[candidate.importance]
    )
    fields: list[str] = []
    if title_coverage:
        fields.append("title")
    if keyword_coverage:
        fields.append("keywords")
    if description_coverage:
        fields.append("description")
    if evidence_coverage:
        fields.append("expected_evidence")
    fields.append("importance")
    return KnowledgeRankScore(
        relevance=_quantize(score),
        matched_fields=tuple(fields),
        matched_terms=_matched_terms(
            query_tokens,
            (
                candidate.title,
                *candidate.keywords,
                candidate.description,
                *candidate.expected_evidence,
            ),
        ),
    )


def score_text_candidate(
    terms: tuple[str, ...],
    *,
    primary: str,
    keywords: tuple[str, ...] = (),
    description: str = "",
) -> KnowledgeRankScore:
    query_tokens = normalize_query_terms(terms)
    primary_coverage = _coverage(query_tokens, (primary,))
    keyword_coverage = _coverage(query_tokens, keywords)
    description_coverage = _coverage(query_tokens, (description,))
    score = (
        Decimal("0.60") * primary_coverage
        + Decimal("0.25") * keyword_coverage
        + Decimal("0.15") * description_coverage
    )
    fields = tuple(
        name
        for name, coverage in (
            ("primary", primary_coverage),
            ("keywords", keyword_coverage),
            ("description", description_coverage),
        )
        if coverage
    )
    return KnowledgeRankScore(
        relevance=_quantize(score),
        matched_fields=fields,
        matched_terms=_matched_terms(
            query_tokens,
            (primary, *keywords, description),
        ),
    )


def rank_knowledge_candidates(
    values: tuple[RankedKnowledgeCandidate, ...] | list[RankedKnowledgeCandidate],
    *,
    limit: int,
) -> list[RankedKnowledgeCandidate]:
    safe_limit = validate_knowledge_limit(limit)
    return sorted(
        values,
        key=lambda item: (
            -item.relevance,
            _ENTITY_ORDER.get(item.entity_type, 99),
            _IMPORTANCE_ORDER[item.importance],
            item.entity_id,
        ),
    )[:safe_limit]


__all__ = [
    "REQUIREMENT_RELEVANCE_THRESHOLD",
    "RETRIEVAL_STRATEGY_VERSION",
    "ROLE_RELEVANCE_THRESHOLD",
    "KnowledgeRankScore",
    "RankedKnowledgeCandidate",
    "RequirementRankCandidate",
    "RoleRankCandidate",
    "rank_knowledge_candidates",
    "score_requirement_candidate",
    "score_role_candidate",
    "score_text_candidate",
]
