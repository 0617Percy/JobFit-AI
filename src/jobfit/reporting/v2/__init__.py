"""Side-by-side P08 report assembly for the v2 architecture."""

from jobfit.reporting.v2.assembler import P08ReportAssembler as P08ReportAssembler
from jobfit.reporting.v2.assembler import P08ReportResult as P08ReportResult
from jobfit.reporting.v2.validation import (
    B5ReportValidationError as B5ReportValidationError,
)
from jobfit.reporting.v2.validation import P08ReportValidator as P08ReportValidator

__all__ = [
    "B5ReportValidationError",
    "P08ReportAssembler",
    "P08ReportResult",
    "P08ReportValidator",
]
