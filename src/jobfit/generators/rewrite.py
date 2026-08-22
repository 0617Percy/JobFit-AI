"""Evidence-bound rewrite validation and confirmation partitioning."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from jobfit.generators.common import (
    advice_error,
    require_requirement_ids,
    require_resume_evidence,
    requirement_index,
    stable_generated_id,
)
from jobfit.models import (
    EvidenceRegistry,
    JobRequirement,
    RewriteSuggestion,
    RewriteSuggestionDraft,
)

_NUMBER = re.compile(
    r"(?<![A-Za-z])(?:\d+(?:\.\d+)?%?|[一二三四五六七八九十百千万]+(?:倍|项|人|次))"
)

# D2.18: the old detector treated every novel English lexical token as a new
# tool/technology claim, so benign paraphrasing and language-preserving
# translation were hard-blocked. The repaired detector replaces lexical
# novelty with per-dimension deterministic claim-family rules:
#
# - marker families only fire when the corresponding factual dimension is
#   absent from the source evidence (marker presence in source keeps the
#   family legal, which also makes translation legal);
# - the new-tool guard only considers technical token shapes (acronyms,
#   mixed case, proper-case words away from sentence starts, letter-digit
#   tokens, and punctuated technical names) and only when the token is not
#   supported by the source text or authoritative structured capabilities.
#   Ordinary lowercase novel wording is never treated as technology.

_WORD = re.compile(r"[A-Za-z0-9+.#_-]+")
_ACRONYM = re.compile(r"[A-Z]{2,8}")
_MIXED_CASE = re.compile(r"(?=.*[a-z])(?=.*[A-Z])[A-Za-z0-9+.#_-]+")
_PROPER_CASE = re.compile(r"[A-Z][a-z]+")
_LETTER_DIGIT = re.compile(r"(?=.*[A-Za-z])(?=.*[0-9])[A-Za-z0-9+.#_-]+")
_PUNCTUATED = re.compile(r"[+.#_]")
_SINGLE_LETTER_NUMBER = re.compile(r"[A-Za-z][0-9]{1,3}")
_SENTENCE_BREAK_CHARS = frozenset(".!?。！？\n")


@dataclass(frozen=True, slots=True)
class _MarkerFamily:
    """One frozen factual-strength dimension with closed marker vocabulary."""

    name: str
    english: re.Pattern[str] | None
    chinese: tuple[str, ...]

    def present(self, text: str) -> bool:
        if self.english is not None and self.english.search(text):
            return True
        return any(marker in text for marker in self.chinese)


_MARKER_FAMILIES: tuple[_MarkerFamily, ...] = (
    _MarkerFamily(
        "RESPONSIBILITY_ESCALATION",
        re.compile(
            r"\b(?:led|owned|managed|directed|spearheaded|headed|orchestrated|"
            r"championed|independently|responsible for)\b",
            re.IGNORECASE,
        ),
        ("主导", "负责", "独立完成", "领导", "管理", "牵头", "带领", "独立"),
    ),
    _MarkerFamily(
        "RESULT_INVENTION",
        re.compile(
            r"\b(?:improved|increased|decreased|reduced|achieved|boosted|"
            r"accelerated|drove|grew|lowered|shortened|resulted)\b",
            re.IGNORECASE,
        ),
        ("提升", "提高", "降低", "减少", "增长", "改善", "节省", "翻倍"),
    ),
    _MarkerFamily(
        "DEPLOYMENT_ESCALATION",
        re.compile(
            r"\b(?:deployed|deployment|production|productionized|"
            r"production-ready|released|launched|went live|rolled out)\b",
            re.IGNORECASE,
        ),
        ("上线", "生产部署", "部署上线", "商业化", "客户落地", "生产环境", "部署", "发布"),
    ),
    _MarkerFamily(
        "USER_IMPACT_ESCALATION",
        re.compile(
            r"\b(?:customers?|clients?|adoption|adopted|end users?|"
            r"user base|stakeholders?|enterprise)\b",
            re.IGNORECASE,
        ),
        ("公司", "客户", "实验室", "研究院", "业务效果", "采用"),
    ),
    _MarkerFamily(
        "COMPLETION_ESCALATION",
        re.compile(
            r"\b(?:completed|delivered|finalized|finished|shipped)\b",
            re.IGNORECASE,
        ),
        ("已完成", "成功完成", "已交付", "按期完成"),
    ),
    _MarkerFamily(
        "QUALITY_ESCALATION",
        re.compile(
            r"\b(?:robust|reliable|high-performance|high performance|scalable|"
            r"optimized|fault-tolerant|production-grade|reusable|maintainable)\b",
            re.IGNORECASE,
        ),
        ("高性能", "稳定", "可靠", "高可用", "可扩展", "鲁棒", "优化"),
    ),
    _MarkerFamily(
        "ABILITY_ESCALATION",
        re.compile(
            r"\b(?:proficient|proficiency|expertise|adept|skilled)\b",
            re.IGNORECASE,
        ),
        ("精通", "擅长", "熟练"),
    ),
)

_FAMILY_CLAIM_TEXT = {
    "RESPONSIBILITY_ESCALATION": "职责强化",
    "RESULT_INVENTION": "新增结果或量化主张",
    "DEPLOYMENT_ESCALATION": "新增落地范围",
    "USER_IMPACT_ESCALATION": "新增组织或客户主张",
    "COMPLETION_ESCALATION": "新增完成状态主张",
    "QUALITY_ESCALATION": "新增质量主张",
    "ABILITY_ESCALATION": "新增能力主张",
    "NEW_TOOL_OR_TECHNOLOGY": "新增技术或工具",
}

_FAMILY_ORDER: tuple[str, ...] = (
    "RESPONSIBILITY_ESCALATION",
    "RESULT_INVENTION",
    "DEPLOYMENT_ESCALATION",
    "USER_IMPACT_ESCALATION",
    "COMPLETION_ESCALATION",
    "QUALITY_ESCALATION",
    "ABILITY_ESCALATION",
    "NEW_TOOL_OR_TECHNOLOGY",
)


def partition_rewrites(
    items: Sequence[RewriteSuggestionDraft],
    requirements: Sequence[JobRequirement],
    registry: EvidenceRegistry,
) -> tuple[list[RewriteSuggestion], list[RewriteSuggestion]]:
    requirement_by_id = requirement_index(requirements)
    direct: list[tuple[int, RewriteSuggestion]] = []
    confirmation: list[tuple[int, RewriteSuggestion]] = []

    for item in items:
        require_requirement_ids(item.requirement_ids, requirement_by_id)
        evidence = require_resume_evidence(item.evidence_ids, registry)
        if not any(
            item.original_text == evidence_item.quote
            or item.original_text in evidence_item.quote
            for evidence_item in evidence
        ):
            raise advice_error("改写原始表述无法通过Evidence回溯到简历原文。")

        claims = list(dict.fromkeys([
            *item.introduced_claims,
            *_detect_new_claims(item, evidence_text=" ".join(
                evidence_item.quote for evidence_item in evidence
            )),
        ]))
        confirmations = list(item.user_confirmation_needed)
        if claims and not confirmations:
            confirmations = [
                f"请确认后再采用：{claim}" for claim in claims
            ]
        suggestion = RewriteSuggestion(
            **item.model_dump(
                exclude={"introduced_claims", "user_confirmation_needed"}
            ),
            suggestion_id=stable_generated_id(
                "rewrite",
                item.original_text,
                item.rewritten_text,
                *sorted(item.evidence_ids),
            ),
            introduced_claims=claims,
            user_confirmation_needed=confirmations,
        )
        start = min(evidence_item.start_char for evidence_item in evidence)
        target = confirmation if claims or confirmations else direct
        target.append((start, suggestion))

    direct.sort(key=lambda entry: (entry[0], entry[1].suggestion_id))
    confirmation.sort(key=lambda entry: (entry[0], entry[1].suggestion_id))
    return (
        [item for _, item in direct],
        [item for _, item in confirmation],
    )


def _detect_new_claims(
    item: RewriteSuggestionDraft,
    *,
    evidence_text: str,
    allowed_terms: Sequence[str] = (),
) -> list[str]:
    """Return token-free claim descriptions for unsupported strengthening.

    ``allowed_terms`` may carry authoritative structured capability names
    (for example P04 normalized capabilities) that a rewrite may reuse even
    when they are absent from the raw evidence text.
    """
    families = _detected_strength_families(
        item,
        evidence_text=evidence_text,
        allowed_terms=allowed_terms,
    )
    claims = [_FAMILY_CLAIM_TEXT[name] for name in _FAMILY_ORDER if name in families]
    source = f"{item.original_text} {evidence_text}"
    source_numbers = set(_NUMBER.findall(source))
    if any(value not in source_numbers for value in _NUMBER.findall(item.rewritten_text)):
        claims.append("新增数字或量化结果")
    return claims


def _detected_strength_families(
    item: object,
    *,
    evidence_text: str,
    allowed_terms: Sequence[str] = (),
) -> frozenset[str]:
    """Deterministic semantic-strength families violated by the rewrite.

    A marker family fires only when its dimension is present in the rewrite
    and absent from the combined original/evidence text. Language change
    alone never fires: ordinary novel wording carries no claim, and a
    dimension already present in the source remains legal in translation.
    """
    source = f"{item.original_text} {evidence_text}"
    rewritten = item.rewritten_text
    families: set[str] = set()

    source_numbers = set(_NUMBER.findall(source))
    if any(value not in source_numbers for value in _NUMBER.findall(rewritten)):
        families.add("RESULT_INVENTION")

    for family in _MARKER_FAMILIES:
        if family.present(rewritten) and not family.present(source):
            families.add(family.name)

    if _novel_technical_tokens(rewritten, source, allowed_terms):
        families.add("NEW_TOOL_OR_TECHNOLOGY")
    return frozenset(families)


def _novel_technical_tokens(
    rewritten: str,
    source: str,
    allowed_terms: Sequence[str],
) -> list[str]:
    """Technical-shaped rewrite tokens unsupported by source evidence."""
    allowed = {token.rstrip(".").casefold() for token in _WORD.findall(source)}
    for term in allowed_terms:
        allowed.update(token.rstrip(".").casefold() for token in _WORD.findall(str(term)))
    return [
        token for token in _technical_token_candidates(rewritten) if token.casefold() not in allowed
    ]


def _technical_token_candidates(text: str) -> set[str]:
    """Tokens whose shape suggests a tool/technology name.

    Proper-case words at sentence starts are excluded because sentence
    capitalization is an ordinary writing pattern, not a tool signal;
    acronyms, mixed-case, letter-digit, and punctuated technical shapes are
    position-independent.
    """
    candidates: set[str] = set()
    for match in _WORD.finditer(text):
        token = match.group(0).rstrip(".")
        if not any(character.isalpha() for character in token):
            continue
        is_candidate = (
            _ACRONYM.fullmatch(token)
            or (_MIXED_CASE.fullmatch(token) and not _PROPER_CASE.fullmatch(token))
            or (_LETTER_DIGIT.fullmatch(token) and not _SINGLE_LETTER_NUMBER.fullmatch(token))
            or (
                _PUNCTUATED.search(token)
                and (
                    any(character.isupper() for character in token)
                    or any(character.isdigit() for character in token)
                )
            )
            or (_PROPER_CASE.fullmatch(token) and not _is_sentence_start(text, match.start()))
        )
        if is_candidate:
            candidates.add(token)
    return candidates


def _is_sentence_start(text: str, start: int) -> bool:
    boundary = text[:start].rstrip()
    if not boundary:
        return True
    return boundary[-1] in _SENTENCE_BREAK_CHARS
