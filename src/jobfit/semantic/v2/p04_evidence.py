"""P04 evidence feature normalization with deterministic B2 levels."""

from __future__ import annotations

from dataclasses import dataclass

from jobfit.models.v2 import Evidence, EvidenceLevel, EvidenceSourceOrigin
from jobfit.scoring.v2 import determine_evidence_level, validate_evidence_level
from jobfit.semantic.v2.contracts import PromptExecutionRecord
from jobfit.semantic.v2.executor import (
    SemanticPromptExecutor,
    SemanticValidationIssueError,
)
from jobfit.semantic.v2.p01_resume import P01ResumeResult
from jobfit.semantic.v2.stage_contracts import (
    CandidateEvidence,
    P04EvidenceFeatureDraft,
    P04EvidenceInput,
    P04EvidenceOutput,
)


@dataclass(frozen=True, slots=True)
class P04EvidenceResult:
    analysis_id: str
    resume_version_id: str
    evidence: tuple[Evidence, ...]
    warnings: tuple[str, ...]
    execution: PromptExecutionRecord


class P04EvidenceNormalizer:
    """Normalize semantic features; frozen code alone derives L1-L4."""

    def __init__(self, executor: SemanticPromptExecutor) -> None:
        self._executor = executor

    def normalize(self, parsed_resume: P01ResumeResult) -> P04EvidenceResult:
        prompt_input = P04EvidenceInput(
            analysis_id=parsed_resume.analysis_id,
            resume_version_id=parsed_resume.profile.resume_version_id,
            candidate_evidence=list(parsed_resume.candidate_evidence),
        )
        result = self._executor.execute_prompt(
            prompt_id="P04",
            input_payload=prompt_input,
            input_object_ids=(
                parsed_resume.analysis_id,
                parsed_resume.profile.resume_version_id,
                *(item.evidence_id for item in parsed_resume.candidate_evidence),
            ),
            response_model=P04EvidenceOutput,
            business_validator=_validate_business,
            cross_object_validator=lambda output: _validate_references(
                output,
                parsed_resume,
            ),
        )
        feature_by_id = {
            item.evidence_id: item for item in result.output.evidence
        }
        # Coverage stays strict (exact ID set); ordering ownership is
        # deterministic code: re-emit features in the authoritative P01
        # input evidence order regardless of provider output order.
        evidence = tuple(
            _assemble_evidence(feature_by_id[candidate.evidence_id], candidate)
            for candidate in parsed_resume.candidate_evidence
        )
        execution = result.record.model_copy(
            update={
                "output_object_ids": tuple(item.evidence_id for item in evidence)
            }
        )
        return P04EvidenceResult(
            analysis_id=parsed_resume.analysis_id,
            resume_version_id=parsed_resume.profile.resume_version_id,
            evidence=evidence,
            warnings=tuple(result.output.warnings),
            execution=execution,
        )


def _validate_business(output: P04EvidenceOutput) -> None:
    evidence_ids = [item.evidence_id for item in output.evidence]
    if len(evidence_ids) != len(set(evidence_ids)):
        _fail(
            "BUSINESS_VALIDATION_FAILED",
            "evidence",
            "P04_EVIDENCE_ID_DUPLICATE",
        )


def _validate_references(
    output: P04EvidenceOutput,
    parsed_resume: P01ResumeResult,
) -> None:
    # Exact set coverage: every P01 evidence_id exactly once, no missing,
    # no unknown, no duplicate (duplicates also fail the business validator).
    # Order equality is deliberately NOT part of the contract: deterministic
    # code restores the canonical P01 input order after validation.
    expected = [item.evidence_id for item in parsed_resume.candidate_evidence]
    actual = [item.evidence_id for item in output.evidence]
    if sorted(actual) != sorted(expected):
        _fail(
            "CROSS_OBJECT_VALIDATION_FAILED",
            "evidence.evidence_id",
            "P04_NORMALIZATION_INCOMPLETE",
        )


def _fail(code: str, path: str, category: str) -> None:
    raise SemanticValidationIssueError(
        code,
        validation_paths=(path,),
        validation_categories=(category,),
    )


def _assemble_evidence(
    feature: P04EvidenceFeatureDraft,
    candidate: CandidateEvidence,
) -> Evidence:
    provisional = Evidence(
        evidence_id=candidate.evidence_id,
        resume_version_id=candidate.resume_version_id,
        source_origin=EvidenceSourceOrigin.RESUME,
        source_type=candidate.source_type,
        source_text=candidate.quote,
        normalized_capabilities=feature.normalized_capabilities,
        personal_contribution=feature.personal_contribution,
        task_clarity=feature.task_clarity,
        method_tool_clarity=feature.method_tool_clarity,
        result_clarity=feature.result_clarity,
        verification_strength=feature.verification_strength,
        practical_use=feature.practical_use,
        evidence_level=EvidenceLevel.L1,
        ambiguity=feature.ambiguity,
        document_id=candidate.document_id,
        segment_id=candidate.segment_id,
        start_char=candidate.start_char,
        end_char=candidate.end_char,
    )
    resolved = provisional.model_copy(
        update={"evidence_level": determine_evidence_level(provisional)}
    )
    return validate_evidence_level(resolved)
