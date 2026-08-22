"""Evidence matching package."""

from jobfit.matching.evidence_matcher import EvidenceMatcher as EvidenceMatcher
from jobfit.matching.evidence_matcher import (
    RequirementMatchBatchDraft as RequirementMatchBatchDraft,
)
from jobfit.matching.evidence_matcher import assemble_match as assemble_match

__all__ = [
    "EvidenceMatcher",
    "RequirementMatchBatchDraft",
    "assemble_match",
]
