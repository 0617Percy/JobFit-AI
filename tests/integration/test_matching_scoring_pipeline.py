"""Offline Mock matching followed by deterministic scoring."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from jobfit.llm import LLMSettings, LLMTask, MockLLMClient, MockLLMProvider
from jobfit.llm.prompt_registry import PromptRegistry
from jobfit.matching import EvidenceMatcher
from jobfit.models import MatchStatus
from jobfit.scoring import ScoringEngine


def test_mock_matching_results_feed_deterministic_scoring(matching_case) -> None:
    drafts = [
        matching_case.draft(
            "req-python",
            MatchStatus.MATCHED,
            ("ev-python",),
            reasoning="简历明确写明使用Python完成数据处理。",
        ),
        matching_case.draft(
            "req-production",
            MatchStatus.PARTIAL_MATCH,
            ("ev-course",),
            reasoning="课程项目相关，但没有生产部署证据。",
        ),
        matching_case.draft(
            "req-java",
            MatchStatus.NOT_MATCHED,
            ("ev-no-java",),
            reasoning="简历明确写明没有Java经验。",
            missing_note="存在明确否定表述。",
        ),
        matching_case.draft(
            "req-sql",
            MatchStatus.UNKNOWN,
            reasoning="当前简历没有足够证据确认SQL能力。",
            missing_note="当前简历未提供足够证据确认该能力。",
        ),
    ]
    provider = MockLLMProvider(
        {
            LLMTask.MATCH_EVIDENCE: [
                json.dumps(
                    {
                        "matches": [
                            item.model_dump(mode="json") for item in drafts
                        ]
                    },
                    ensure_ascii=False,
                )
            ]
        }
    )
    matcher = EvidenceMatcher(
        client=MockLLMClient(provider),
        prompt_registry=PromptRegistry(
            Path(__file__).parents[2] / "src" / "jobfit" / "prompts"
        ),
        settings=LLMSettings(
            model="mock-model",
            max_retries=0,
            request_id="integration-default",
            prompt_version="1.0",
        ),
    )

    matches = matcher.match(
        matching_case.resume,
        matching_case.job,
        matching_case.document,
        matching_case.registry,
        request_id="integration-score",
    )
    first = ScoringEngine().score(
        matching_case.job.requirements.items,
        matches,
    )
    second = ScoringEngine().score(
        matching_case.job.requirements.items,
        matches,
    )

    assert first == second
    assert sum(
        (
            item.weight
            for item in matching_case.job.requirements.items
        ),
        Decimal("0"),
    ) == Decimal("100.00")
    assert first.final_score <= first.raw_score
    assert provider.call_count == 1
