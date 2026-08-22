"""P06-P07 advisory services for the v2 architecture."""

from jobfit.advisory.v2.actions import P06ActionGenerator as P06ActionGenerator
from jobfit.advisory.v2.actions import P06ActionResult as P06ActionResult
from jobfit.advisory.v2.interview import (
    P07InterviewGenerator as P07InterviewGenerator,
)
from jobfit.advisory.v2.interview import P07InterviewResult as P07InterviewResult
from jobfit.advisory.v2.pipeline import AdvisoryReportPipeline as AdvisoryReportPipeline
from jobfit.advisory.v2.pipeline import AdvisoryReportResult as AdvisoryReportResult
from jobfit.advisory.v2.selectors import select_top_actions as select_top_actions

__all__ = [
    "P06ActionGenerator",
    "P06ActionResult",
    "P07InterviewGenerator",
    "P07InterviewResult",
    "AdvisoryReportPipeline",
    "AdvisoryReportResult",
    "select_top_actions",
]
