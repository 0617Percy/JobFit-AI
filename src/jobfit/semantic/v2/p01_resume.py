"""P01 source-grounded resume parsing and local identity assembly."""

from __future__ import annotations

from dataclasses import dataclass

from jobfit.extractors.common import stable_id
from jobfit.models import DocumentContent
from jobfit.models.v2 import CandidateProfile, ResumeProfile
from jobfit.semantic.v2.contracts import PromptExecutionRecord
from jobfit.semantic.v2.executor import (
    SemanticPromptError,
    SemanticPromptExecutor,
    SemanticValidationIssueError,
)
from jobfit.semantic.v2.severity import SemanticValidationIssue, validation_issue
from jobfit.semantic.v2.source_anchoring import exact_text_spans
from jobfit.semantic.v2.stage_contracts import (
    CandidateEvidence,
    P01EvidenceDraft,
    P01ResumeInput,
    P01ResumeLLMOutput,
    P01ResumeOutput,
    ResumeCollectionItemDraft,
    SemanticAmbiguity,
)


@dataclass(frozen=True, slots=True)
class P01ResumeResult:
    analysis_id: str
    profile: ResumeProfile
    candidate_evidence: tuple[CandidateEvidence, ...]
    ambiguities: tuple[SemanticAmbiguity, ...]
    execution: PromptExecutionRecord


class P01ResumeParser:
    """Parse only resume source; final evidence strength remains local code."""

    def __init__(self, executor: SemanticPromptExecutor) -> None:
        self._executor = executor

    def parse(
        self,
        *,
        analysis_id: str,
        resume_version_id: str,
        document: DocumentContent,
    ) -> P01ResumeResult:
        prompt_input = P01ResumeInput.model_validate(
            {
                "analysis_id": analysis_id,
                "resume_version_id": resume_version_id,
                "document": {
                    "document_id": document.document_id,
                    "language": document.language.value,
                    "normalized_text": document.normalized_text,
                    "segments": [
                        segment.model_dump(mode="json") for segment in document.segments
                    ],
                },
            }
        )
        anchored_output: P01ResumeOutput | None = None

        def validate_and_anchor(output: P01ResumeLLMOutput) -> None:
            nonlocal anchored_output
            candidate = _anchor_output(output, document)
            _validate_business(candidate, document)
            _validate_references(candidate)
            anchored_output = candidate

        result = self._executor.execute_prompt(
            prompt_id="P01",
            input_payload=prompt_input,
            input_object_ids=(analysis_id, resume_version_id, document.document_id),
            response_model=P01ResumeLLMOutput,
            business_validator=validate_and_anchor,
            quality_validator=_quality_issues,
        )
        if anchored_output is None:
            raise SemanticPromptError("P01", "EVIDENCE_ANCHORING_FAILED")
        output = anchored_output
        evidence_by_local = _build_evidence(
            output,
            resume_version_id=resume_version_id,
        )
        evidence = tuple(
            evidence_by_local[item.local_id]
            for item in sorted(
                output.evidence_items,
                key=lambda item: (item.start_char, item.end_char, item.local_id),
            )
        )
        profile = ResumeProfile(
            resume_version_id=resume_version_id,
            candidate_profile=CandidateProfile.model_validate(
                output.candidate_profile.model_dump()
            ),
            education=_collection(output.education, evidence_by_local),
            skills=_collection(output.skills, evidence_by_local),
            projects=_collection(output.projects, evidence_by_local),
            internships=_collection(output.internships, evidence_by_local),
            work_experience=_collection(
                output.work_experience, evidence_by_local
            ),
            research=_collection(output.research, evidence_by_local),
            competitions=_collection(output.competitions, evidence_by_local),
            campus_experience=_collection(
                output.campus_experience, evidence_by_local
            ),
            achievements=_collection(output.achievements, evidence_by_local),
            evidence_ids=[item.evidence_id for item in evidence],
            ambiguity_ids=[item.ambiguity_id for item in output.ambiguities],
            parse_completeness=output.parse_completeness,
        )
        execution = result.record.model_copy(
            update={"output_object_ids": tuple(profile.evidence_ids)}
        )
        return P01ResumeResult(
            analysis_id=analysis_id,
            profile=profile,
            candidate_evidence=evidence,
            ambiguities=tuple(output.ambiguities),
            execution=execution,
        )


def _anchor_output(
    output: P01ResumeLLMOutput,
    document: DocumentContent,
) -> P01ResumeOutput:
    segment_by_id = {segment.segment_id: segment for segment in document.segments}
    anchored: list[P01EvidenceDraft] = []
    validation_paths: list[str] = []
    validation_categories: list[str] = []

    for index, item in enumerate(output.evidence_items):
        if item.document_id != document.document_id:
            _fail(
                "EVIDENCE_IDENTITY_INVALID",
                f"evidence_items[{index}].document_id",
                "EVIDENCE_DOCUMENT_MISMATCH",
            )
        segment = segment_by_id.get(item.segment_id)
        if segment is None:
            _fail(
                "EVIDENCE_IDENTITY_INVALID",
                f"evidence_items[{index}].segment_id",
                "EVIDENCE_SEGMENT_UNKNOWN",
            )
        spans = exact_text_spans(
            segment.text,
            item.quote,
            base_offset=segment.start_char,
        )
        if len(spans) != 1:
            validation_paths.append(f"evidence_items[{index}]")
            validation_categories.append(
                "EVIDENCE_QUOTE_NOT_FOUND"
                if not spans
                else "EVIDENCE_QUOTE_AMBIGUOUS"
            )
            continue
        start_char, end_char = spans[0]
        anchored.append(
            P01EvidenceDraft.model_validate(
                {
                    **item.model_dump(mode="json"),
                    "start_char": start_char,
                    "end_char": end_char,
                }
            )
        )

    if validation_paths:
        raise SemanticValidationIssueError(
            "EVIDENCE_ANCHORING_FAILED",
            validation_paths=validation_paths,
            validation_categories=validation_categories,
        )

    return P01ResumeOutput.model_validate(
        {
            **output.model_dump(mode="json", exclude={"evidence_items"}),
            "evidence_items": [item.model_dump(mode="json") for item in anchored],
        }
    )

def _validate_business(output: P01ResumeOutput, document: DocumentContent) -> None:
    if not output.evidence_items:
        _fail("BUSINESS_VALIDATION_FAILED", "evidence_items", "P01_EVIDENCE_REQUIRED")
    local_ids: set[str] = set()
    segment_by_id = {segment.segment_id: segment for segment in document.segments}
    for item in output.evidence_items:
        if item.local_id in local_ids:
            _fail(
                "BUSINESS_VALIDATION_FAILED",
                "evidence_items",
                "P01_DUPLICATE_EVIDENCE_ID",
            )
        local_ids.add(item.local_id)
        if item.document_id != document.document_id:
            _fail(
                "EVIDENCE_IDENTITY_INVALID",
                "evidence_items.document_id",
                "EVIDENCE_DOCUMENT_MISMATCH",
            )
        segment = segment_by_id.get(item.segment_id)
        if segment is None:
            _fail(
                "EVIDENCE_IDENTITY_INVALID",
                "evidence_items.segment_id",
                "EVIDENCE_SEGMENT_UNKNOWN",
            )
        if not (
            segment.start_char <= item.start_char
            and item.end_char <= segment.end_char
        ):
            _fail(
                "EVIDENCE_ANCHORING_FAILED",
                "evidence_items",
                "EVIDENCE_OFFSET_OUT_OF_RANGE",
            )
        if document.normalized_text[item.start_char : item.end_char] != item.quote:
            _fail(
                "EVIDENCE_ANCHORING_FAILED",
                "evidence_items",
                "EVIDENCE_QUOTE_MISMATCH",
            )


def _validate_references(output: P01ResumeOutput) -> None:
    evidence_ids = {item.local_id for item in output.evidence_items}
    for item in _all_collection_items(output):
        if any(reference not in evidence_ids for reference in item.evidence_local_ids):
            _fail(
                "CROSS_OBJECT_VALIDATION_FAILED",
                "collections.evidence_local_ids",
                "UNKNOWN_EVIDENCE_REFERENCE",
            )


def _quality_issues(output: P01ResumeLLMOutput) -> tuple[SemanticValidationIssue, ...]:
    issues: list[SemanticValidationIssue] = []
    if not output.education:
        issues.append(
            validation_issue(
                stage="P01",
                category="P01_EDUCATION_NOT_EXTRACTED",
                safe_path="education",
            )
        )
    if not (output.projects or output.internships or output.work_experience):
        issues.append(
            validation_issue(
                stage="P01",
                category="P01_EXPERIENCE_NOT_EXTRACTED",
                safe_path="projects",
            )
        )
    return tuple(issues)


def _fail(code: str, path: str, category: str) -> None:
    raise SemanticValidationIssueError(
        code,
        validation_paths=(path,),
        validation_categories=(category,),
    )


def _build_evidence(
    output: P01ResumeOutput,
    *,
    resume_version_id: str,
) -> dict[str, CandidateEvidence]:
    return {
        item.local_id: CandidateEvidence(
            evidence_id=stable_id(
                "evidence",
                resume_version_id,
                item.document_id,
                item.segment_id,
                item.start_char,
                item.end_char,
                item.quote,
            ),
            resume_version_id=resume_version_id,
            source_type=item.source_type,
            quote=item.quote,
            document_id=item.document_id,
            segment_id=item.segment_id,
            start_char=item.start_char,
            end_char=item.end_char,
        )
        for item in output.evidence_items
    }


def _collection(
    items: list[ResumeCollectionItemDraft],
    evidence_by_local: dict[str, CandidateEvidence],
) -> list[dict[str, object]]:
    return [
        {
            "item_id": item.item_id,
            "label": item.label,
            "details": item.details,
            "evidence_ids": [
                evidence_by_local[reference].evidence_id
                for reference in item.evidence_local_ids
            ],
        }
        for item in items
    ]


def _all_collection_items(
    output: P01ResumeOutput,
) -> tuple[ResumeCollectionItemDraft, ...]:
    return tuple(
        item
        for collection in (
            output.education,
            output.skills,
            output.projects,
            output.internships,
            output.work_experience,
            output.research,
            output.competitions,
            output.campus_experience,
            output.achievements,
        )
        for item in collection
    )
