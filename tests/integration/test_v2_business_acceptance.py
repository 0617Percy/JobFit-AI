"""Frozen acceptance registry for all forty-two approved business cases."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "v2" / "business_cases.json"
EXPECTED_CATEGORY_COUNTS = {
    "core_fit": 12,
    "hard": 6,
    "evidence": 6,
    "seniority": 4,
    "jd_quality": 4,
    "knowledge": 4,
    "safety": 3,
    "failure": 3,
}


def _cases() -> list[dict[str, object]]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_business_case_registry_is_complete_unique_and_frozen() -> None:
    cases = _cases()
    case_ids = [str(item["case_id"]) for item in cases]
    expected_ids = [
        *(f"A{index:02d}" for index in range(1, 13)),
        *(f"B{index:02d}" for index in range(1, 7)),
        *(f"C{index:02d}" for index in range(1, 7)),
        *(f"D{index:02d}" for index in range(1, 5)),
        *(f"E{index:02d}" for index in range(1, 5)),
        *(f"F{index:02d}" for index in range(1, 5)),
        *(f"G{index:02d}" for index in range(1, 4)),
        *(f"H{index:02d}" for index in range(1, 4)),
    ]

    assert case_ids == expected_ids
    assert len(case_ids) == len(set(case_ids)) == 42
    assert Counter(str(item["category"]) for item in cases) == EXPECTED_CATEGORY_COUNTS
    assert {str(item["outcome"]) for item in cases} == {"PASS"}
    assert all(item["required_concepts"] for item in cases)
    assert all(item["forbidden_claims"] for item in cases)


@pytest.mark.parametrize("case", _cases(), ids=lambda item: str(item["case_id"]))
def test_each_business_case_has_an_explicit_approved_outcome(
    case: dict[str, object],
) -> None:
    assert case["outcome"] == "PASS"
    assert case["expected_hard"]
    assert case["expected_critical"]
    assert case["score_range"]
    assert case["expected_recommendation"]
    assert case["expected_confidence"]


def test_only_approved_golden_overlay_cases_change_workbook_expectations() -> None:
    overlaid = {
        str(item["case_id"])
        for item in _cases()
        if "authority_override" in item
    }

    assert overlaid == {"A02", "A03", "A07"}

    by_id = {str(item["case_id"]): item for item in _cases()}
    assert by_id["A02"]["score_range"] == "0-75"
    assert by_id["A02"]["expected_recommendation"] == "suggested_or_lower"
    assert by_id["A03"]["score_range"] == "0-54.99"
    assert by_id["A03"]["expected_recommendation"] == "not_recommended"
    assert by_id["A07"]["score_range"] == "0-54.99"
    assert by_id["A07"]["expected_recommendation"] == "not_recommended"


def test_workflow_local_recovery_cases_are_no_longer_deferred() -> None:
    by_id = {str(item["case_id"]): item for item in _cases()}

    assert by_id["H02"]["required_concepts"] == ["retry interview only"]
    assert by_id["H02"]["expected_recommendation"] == "unchanged"
    assert by_id["H03"]["required_concepts"] == ["regenerate report only"]
    assert by_id["H03"]["expected_recommendation"] == "unchanged"
