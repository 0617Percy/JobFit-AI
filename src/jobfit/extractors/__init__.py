"""Structured, source-grounded extraction package."""

from jobfit.extractors.job import JobRequirementExtractor as JobRequirementExtractor
from jobfit.extractors.resume import ResumeExtractor as ResumeExtractor

__all__ = ["JobRequirementExtractor", "ResumeExtractor"]
