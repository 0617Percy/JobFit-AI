"""P05 relation-only semantic matching for validated requirements and evidence."""

from __future__ import annotations

from dataclasses import dataclass

from jobfit.extractors.common import stable_id
from jobfit.models.v2 import (
    AbilityStatus,
    EvidenceStatus,
    MatchCoverage,
    MatchedEvidence,
    RequirementMatch,
)
from jobfit.semantic.v2.contracts import PromptExecutionRecord
from jobfit.semantic.v2.executor import (
    SemanticPromptError,
    SemanticPromptExecutor,
    SemanticValidationIssueError,
)
from jobfit.semantic.v2.p03_requirements import P03RequirementResult
from jobfit.semantic.v2.p04_evidence import P04EvidenceResult
from jobfit.semantic.v2.stage_contracts import (
    P05MatchInput,
    P05MatchOutput,
    P05RequirementMatchDraft,
)


@dataclass(frozen=True, slots=True)
class P05MatchResult:
    analysis_id: str
    resume_version_id: str
    jd_snapshot_id: str
    matches: tuple[RequirementMatch, ...]
    warnings: tuple[str, ...]
    execution: PromptExecutionRecord


class P05SemanticMatcher:
    """Describe semantic relations; frozen B2 code owns numeric decisions."""

    def __init__(self, executor: SemanticPromptExecutor) -> None:
        self._executor = executor

    def match(
        self,
        classified_job: P03RequirementResult,
        normalized_evidence: P04EvidenceResult,
    ) -> P05MatchResult:
        if classified_job.analysis_id != normalized_evidence.analysis_id:
            raise SemanticPromptError("P05", "CROSS_ANALYSIS_INPUT")
        prompt_input = P05MatchInput.model_validate(
            {
                "analysis_id": classified_job.analysis_id,
                "jd_snapshot_id": classified_job.job_profile.jd_snapshot_id,
                "resume_version_id": normalized_evidence.resume_version_id,
                "requirements": [
                    item.model_dump(
                        mode="json",
                        exclude={"knowledge_citation_ids"},
                    )
                    for item in classified_job.requirements
                ],
                "candidate_evidence": [
                    item.model_dump(
                        mode="json",
                        exclude={"evidence_level"},
                    )
                    for item in normalized_evidence.evidence
                ],
            }
        )
        result = self._executor.execute_prompt(
            prompt_id="P05",
            input_payload=prompt_input,
            input_object_ids=(
                classified_job.analysis_id,
                classified_job.job_profile.jd_snapshot_id,
                normalized_evidence.resume_version_id,
                *(item.requirement_id for item in classified_job.requirements),
                *(item.evidence_id for item in normalized_evidence.evidence),
            ),
            response_model=P05MatchOutput,
            business_validator=_validate_business,
            cross_object_validator=lambda output: _validate_references(
                output,
                classified_job,
                normalized_evidence,
            ),
        )
        draft_by_requirement = {
            item.requirement_id: item for item in result.output.matches
        }
        matches = tuple(
            _assemble_match(draft_by_requirement[requirement.requirement_id])
            for requirement in classified_job.requirements
        )
        execution = result.record.model_copy(
            update={"output_object_ids": tuple(item.match_id for item in matches)}
        )
        return P05MatchResult(
            analysis_id=classified_job.analysis_id,
            resume_version_id=normalized_evidence.resume_version_id,
            jd_snapshot_id=classified_job.job_profile.jd_snapshot_id,
            matches=matches,
            warnings=tuple(result.output.warnings),
            execution=execution,
        )


def _validate_business(output: P05MatchOutput) -> None:
    requirement_ids = [item.requirement_id for item in output.matches]
    if len(requirement_ids) != len(set(requirement_ids)):
        _fail("BUSINESS_VALIDATION_FAILED", "matches", "P05_MATCH_ID_DUPLICATE")
    for item in output.matches:
        if item.ability_status is AbilityStatus.CONFIRMED_GAP:
            _fail(
                "BUSINESS_VALIDATION_FAILED",
                "matches.ability_status",
                "FORBIDDEN_ABILITY_GAP_AUTHORITY",
            )
        if item.evidence_status is EvidenceStatus.MISSING:
            if item.matched_evidence:
                _fail(
                    "BUSINESS_VALIDATION_FAILED",
                    "matches.matched_evidence",
                    "P05_MISSING_EVIDENCE_RELATION_INVALID",
                )
            if item.coverage is not MatchCoverage.NONE:
                _fail(
                    "BUSINESS_VALIDATION_FAILED",
                    "matches.coverage",
                    "P05_MISSING_EVIDENCE_COVERAGE_INVALID",
                )
            if item.ability_status is not AbilityStatus.UNKNOWN:
                _fail(
                    "BUSINESS_VALIDATION_FAILED",
                    "matches.ability_status",
                    "P05_MISSING_EVIDENCE_ABILITY_INVALID",
                )
        elif not item.matched_evidence:
            _fail(
                "BUSINESS_VALIDATION_FAILED",
                "matches.matched_evidence",
                "P05_PRESENT_EVIDENCE_RELATION_REQUIRED",
            )


def _validate_references(
    output: P05MatchOutput,
    classified_job: P03RequirementResult,
    normalized_evidence: P04EvidenceResult,
) -> None:
    expected_requirements = [
        item.requirement_id for item in classified_job.requirements
    ]
    actual_requirements = [item.requirement_id for item in output.matches]
    if sorted(actual_requirements) != sorted(expected_requirements):
        _fail(
            "CROSS_OBJECT_VALIDATION_FAILED",
            "matches.requirement_id",
            "P05_MATCH_COUNT_INVALID",
        )
    evidence_ids = {item.evidence_id for item in normalized_evidence.evidence}
    for match in output.matches:
        for relation in match.matched_evidence:
            if relation.evidence_id not in evidence_ids:
                _fail(
                    "CROSS_OBJECT_VALIDATION_FAILED",
                    "matches.matched_evidence.evidence_id",
                    "UNKNOWN_EVIDENCE_REFERENCE",
                )


def _fail(code: str, path: str, category: str) -> None:
    raise SemanticValidationIssueError(
        code,
        validation_paths=(path,),
        validation_categories=(category,),
    )


def _assemble_match(item: P05RequirementMatchDraft) -> RequirementMatch:
    requirement_id = item.requirement_id
    return RequirementMatch(
        match_id=stable_id("match", requirement_id),
        requirement_id=requirement_id,
        matched_evidence=[
            MatchedEvidence(
                evidence_id=relation.evidence_id,
                relevance=relation.relevance,
                support_type=relation.support_type,
            )
            for relation in item.matched_evidence
        ],
        coverage=item.coverage,
        evidence_status=item.evidence_status,
        ability_status=item.ability_status,
        best_evidence_level=None,
        match_score_component=None,
        reason=item.reason,
    )
