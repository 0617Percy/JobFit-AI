"""P02 explicit-requirement extraction contract regression tests.

Protects the corrected P02 contract: raw_requirements must include every
explicit source-grounded hiring expectation (including cue-free explicit
duties/expectations), lexical markers are NOT required, and P02 must not
decide Hard/Core/Supporting/Preferred (that is exclusively P03's job).
"""

from __future__ import annotations

from pathlib import Path

PROMPT_ROOT = Path(__file__).parents[2] / "src" / "jobfit" / "prompts" / "v2"
P02_PROMPT = (PROMPT_ROOT / "p02_jd_parser.md").read_text(encoding="utf-8")
_FOLDED = P02_PROMPT.casefold()


def test_p02_prompt_defines_raw_requirements_broadly() -> None:
    # raw_requirements must cover every explicit hiring expectation...
    assert (
        "raw_requirements must include every explicit source-grounded "
        "hiring expectation" in P02_PROMPT
    )
    # ...including explicit duties/expectations and qualifications
    assert "dut" in _FOLDED
    assert "expectation" in _FOLDED
    assert "qualification" in _FOLDED


def test_p02_prompt_does_not_require_lexical_cues() -> None:
    assert "does not need lexical markers" in _FOLDED
    assert "required" in _FOLDED
    assert "preferred" in _FOLDED


def test_p02_prompt_forbids_type_based_filtering() -> None:
    # P02 must not decide Hard/Core/Supporting/Preferred
    assert "hard" in _FOLDED
    assert "core" in _FOLDED
    assert "supporting" in _FOLDED
    assert "preferred" in _FOLDED
    # classification belongs exclusively to P03
    assert "p03" in _FOLDED
    assert "type-filter" in _FOLDED or "type based filtering" in _FOLDED


def test_p02_prompt_keeps_grounding_constraints() -> None:
    assert "verbatim" in _FOLDED
    assert "do not invent" in _FOLDED
    assert "do not paraphrase" in _FOLDED
    assert "uniquely identifiable" in _FOLDED


def test_p02_prompt_explains_duplicate_span_disambiguation() -> None:
    # The prompt must tell the model how to disambiguate a repeated phrase:
    # use the SHORTEST unique verbatim span and extend it with surrounding
    # context only until it is unique.
    assert "shortest" in _FOLDED
    assert "more than once" in _FOLDED
    assert "unique" in _FOLDED
    assert "context" in _FOLDED
