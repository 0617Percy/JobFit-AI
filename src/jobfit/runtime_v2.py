"""Production v2 runtime assembly for DeepSeek BYOK analysis."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jobfit.advisory.v2 import AdvisoryReportPipeline
from jobfit.llm.deepseek_provider import DEEPSEEK_MODELS, DeepSeekProvider
from jobfit.llm.protocol import LLMSettings
from jobfit.models.v2 import VersionManifest
from jobfit.semantic.v2 import SemanticPipeline, SemanticPromptExecutor
from jobfit.workflow.v2 import AnalysisRepository, V2AnalysisApplication

_PROMPT_ROOT = Path(__file__).parent / "prompts" / "v2"


@dataclass(frozen=True, slots=True)
class V2DeepSeekRuntime:
    application: V2AnalysisApplication
    provider: DeepSeekProvider


def build_deepseek_runtime(
    *,
    api_key: str,
    model: str,
    thinking_enabled: bool,
    history: AnalysisRepository | None = None,
    client: Any | None = None,
) -> V2DeepSeekRuntime:
    """Wire DeepSeek into the governed P01-P08 pipeline without demo scripts."""

    if model not in DEEPSEEK_MODELS:
        raise ValueError("A supported DeepSeek model is required.")
    provider = DeepSeekProvider(
        api_key=api_key,
        thinking_enabled=thinking_enabled,
        client=client,
    )
    executor = SemanticPromptExecutor(
        provider=provider,
        prompt_root=_PROMPT_ROOT,
        settings=LLMSettings(model=model, max_retries=0),
    )
    application = V2AnalysisApplication(
        semantic_pipeline=SemanticPipeline(executor),
        advisory_pipeline=AdvisoryReportPipeline(executor),
        versions=_version_manifest(),
        history=history,
    )
    return V2DeepSeekRuntime(application=application, provider=provider)


def _version_manifest() -> VersionManifest:
    return VersionManifest(
        software_version="1.1.0",
        prompt_pack_version="1.0.0",
        schema_version="2.0.0",
        scoring_rule_version="1.0.0",
        knowledge_version="2026.08.1",
        analysis_engine_version="1.0.0",
        business_test_set_version="1.0.0",
        golden_set_version="1.0.0",
    )


__all__ = ["V2DeepSeekRuntime", "build_deepseek_runtime"]
