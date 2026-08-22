"""Diagnosis and content generation package."""

from jobfit.generators.advice_bundle import (
    KNOWLEDGE_ADVICE_STRATEGY_VERSION as KNOWLEDGE_ADVICE_STRATEGY_VERSION,
)
from jobfit.generators.advice_bundle import AdviceBundleGenerator as AdviceBundleGenerator
from jobfit.generators.advice_bundle import GeneratedAdvice as GeneratedAdvice
from jobfit.generators.advice_bundle import (
    KnowledgeGenerationResult as KnowledgeGenerationResult,
)

__all__ = [
    "AdviceBundleGenerator",
    "GeneratedAdvice",
    "KNOWLEDGE_ADVICE_STRATEGY_VERSION",
    "KnowledgeGenerationResult",
]
