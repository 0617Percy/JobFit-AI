"""Frozen governance contracts for the side-by-side P01-P08 prompt pack."""

from __future__ import annotations

from pathlib import Path

import pytest

from jobfit.semantic.v2.governance import (
    GLOBAL_RULES_VERSION,
    PROMPT_PACK_VERSION,
    KnowledgeTier,
    PromptChangeClass,
    PromptCriticality,
    PromptLifecycleStatus,
    load_global_rules,
    load_prompt_manifest,
    validate_prompt_pack,
)

PROMPT_ROOT = Path(__file__).parents[2] / "src" / "jobfit" / "prompts" / "v2"


def test_global_rules_are_complete_versioned_and_stably_ordered() -> None:
    rules = load_global_rules(PROMPT_ROOT)

    assert GLOBAL_RULES_VERSION == "1.0.0"
    assert [rule.rule_id for rule in rules] == [f"G{index:02d}" for index in range(1, 11)]
    assert "candidate evidence" in rules[0].text.casefold()
    assert "missing evidence" in rules[2].text.casefold()
    assert "knowledge" in rules[3].text.casefold()
    assert "embedded instructions" in rules[8].text.casefold()


def test_manifest_freezes_p01_through_p08_as_candidate_prompts() -> None:
    manifest = load_prompt_manifest(PROMPT_ROOT)

    assert PROMPT_PACK_VERSION == "1.0.0"
    assert manifest.lifecycle_status is PromptLifecycleStatus.CANDIDATE
    assert [item.prompt_id for item in manifest.prompts] == [
        "P01",
        "P02",
        "P03",
        "P04",
        "P05",
        "P06",
        "P07",
        "P08",
    ]
    assert {item.prompt_version for item in manifest.prompts} == {"1.0.0"}
    assert {item.global_rules_version for item in manifest.prompts} == {"1.0.0"}
    assert {item.prompt_pack_version for item in manifest.prompts} == {
        "1.0.0"
    }
    assert {item.lifecycle_status for item in manifest.prompts} == {
        PromptLifecycleStatus.CANDIDATE
    }
    assert [item.change_class for item in manifest.prompts] == [
        PromptChangeClass.SEMANTIC_ANALYSIS,
        PromptChangeClass.SEMANTIC_ANALYSIS,
        PromptChangeClass.SEMANTIC_ANALYSIS,
        PromptChangeClass.SEMANTIC_ANALYSIS,
        PromptChangeClass.SEMANTIC_ANALYSIS,
        PromptChangeClass.ADVISORY,
        PromptChangeClass.ADVISORY,
        PromptChangeClass.PRESENTATION,
    ]
    assert [item.knowledge_access for item in manifest.prompts] == [
        False,
        False,
        False,
        False,
        False,
        [KnowledgeTier.BUILD],
        [KnowledgeTier.INTERVIEW],
        [KnowledgeTier.JOB_EXPLANATION, KnowledgeTier.IMPLICIT],
    ]
    assert [item.criticality for item in manifest.prompts] == [
        PromptCriticality.CRITICAL,
        PromptCriticality.CRITICAL,
        PromptCriticality.CRITICAL,
        PromptCriticality.HIGH,
        PromptCriticality.CRITICAL,
        PromptCriticality.HIGH,
        PromptCriticality.HIGH,
        PromptCriticality.CRITICAL,
    ]


def test_prompt_pack_content_hashes_are_verified_fail_closed(tmp_path: Path) -> None:
    validate_prompt_pack(PROMPT_ROOT)
    for source in PROMPT_ROOT.iterdir():
        if source.is_file():
            (tmp_path / source.name).write_bytes(source.read_bytes())
    prompt_path = tmp_path / "p03_requirement_classifier.md"
    prompt_path.write_text(
        prompt_path.read_text(encoding="utf-8") + "\nunauthorized change\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="content hash"):
        validate_prompt_pack(tmp_path)
