"""Exact Decimal ranking shared by FTS and keyword candidate recall."""

from __future__ import annotations

from decimal import Decimal

from jobfit.knowledge.query import KnowledgeSearchQuery, RoleProfileQuery
from jobfit.knowledge.ranking import (
    RETRIEVAL_STRATEGY_VERSION,
    RankedKnowledgeCandidate,
    RequirementRankCandidate,
    RoleRankCandidate,
    rank_knowledge_candidates,
    score_requirement_candidate,
    score_role_candidate,
)
from jobfit.models import Importance


def test_role_exact_title_uses_documented_decimal_formula() -> None:
    result = score_role_candidate(
        RoleProfileQuery(
            title="Synthetic AI Assistant",
            seniority="intern",
            industry="technology",
            keywords=("python", "assistant"),
        ),
        RoleRankCandidate(
            entity_id="rp-synthetic-ai",
            code="synthetic_ai_assistant",
            name="Synthetic AI Assistant",
            aliases=("sample assistant",),
            keywords=("python", "assistant"),
            description="Build a bounded assistant.",
            seniority="intern",
            industry="technology",
        ),
    )

    assert result.relevance == Decimal("1.0000")
    assert result.matched_fields == (
        "code",
        "name",
        "phrase",
        "keywords",
        "industry",
        "seniority",
    )
    assert RETRIEVAL_STRATEGY_VERSION == "1.0"


def test_role_alias_match_is_ranked_without_becoming_candidate_score() -> None:
    result = score_role_candidate(
        RoleProfileQuery(title="sample assistant"),
        RoleRankCandidate(
            entity_id="rp-synthetic-ai",
            code="synthetic_ai_assistant",
            name="Sample AI Assistant",
            aliases=("sample assistant",),
            keywords=("python",),
            description="Build a bounded assistant.",
            seniority="intern",
            industry=None,
        ),
    )

    assert result.relevance == Decimal("0.5167")
    assert result.matched_fields == ("alias", "name")
    assert not hasattr(result, "candidate_score")


def test_role_code_exact_match_receives_title_level_relevance() -> None:
    result = score_role_candidate(
        RoleProfileQuery(title="synthetic role code"),
        RoleRankCandidate(
            entity_id="rp-synthetic-code",
            code="synthetic_role_code",
            name="Unrelated display name",
            aliases=(),
            keywords=(),
            description="Synthetic description.",
            seniority="intern",
            industry=None,
        ),
    )

    assert result.relevance == Decimal("0.4500")
    assert result.matched_fields == ("code", "phrase")


def test_requirement_score_uses_role_title_keyword_description_and_importance() -> None:
    result = score_requirement_candidate(
        KnowledgeSearchQuery(
            role_profile_ids=("rp-synthetic-ai",),
            terms=("python", "validation"),
        ),
        RequirementRankCandidate(
            entity_id="kr-python-validation",
            role_profile_id="rp-synthetic-ai",
            title="Python validation",
            keywords=("python",),
            description="Use Python validation method.",
            expected_evidence=("validated a Python project",),
            importance=Importance.HIGH,
        ),
        role_relevance=Decimal("1.0000"),
    )

    assert result.relevance == Decimal("0.9250")
    assert result.matched_fields == (
        "title",
        "keywords",
        "description",
        "expected_evidence",
        "importance",
    )


def test_ranking_uses_relevance_entity_priority_importance_and_stable_id() -> None:
    candidates = (
        RankedKnowledgeCandidate(
            entity_type="interview_question",
            entity_id="iq-a",
            relevance=Decimal("0.8000"),
            importance=Importance.LOW,
            matched_fields=("question",),
            matched_terms=("python",),
        ),
        RankedKnowledgeCandidate(
            entity_type="role_requirement",
            entity_id="kr-b",
            relevance=Decimal("0.8000"),
            importance=Importance.HIGH,
            matched_fields=("title",),
            matched_terms=("python",),
        ),
        RankedKnowledgeCandidate(
            entity_type="role_requirement",
            entity_id="kr-a",
            relevance=Decimal("0.8000"),
            importance=Importance.HIGH,
            matched_fields=("title",),
            matched_terms=("python",),
        ),
        RankedKnowledgeCandidate(
            entity_type="role_profile",
            entity_id="rp-a",
            relevance=Decimal("0.8000"),
            importance=None,
            matched_fields=("name",),
            matched_terms=("python",),
        ),
    )

    ranked = rank_knowledge_candidates(candidates, limit=4)

    assert [item.entity_id for item in ranked] == ["rp-a", "kr-a", "kr-b", "iq-a"]
    assert all(Decimal("0") <= item.relevance <= Decimal("1") for item in ranked)
