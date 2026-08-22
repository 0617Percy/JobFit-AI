"""P02 source-grounded JD parsing without candidate or knowledge access."""

from __future__ import annotations

from dataclasses import dataclass

from jobfit.extractors.common import stable_id
from jobfit.models import DocumentContent
from jobfit.models.v2 import JobFamily, ParseCompleteness
from jobfit.semantic.v2.contracts import PromptExecutionRecord
from jobfit.semantic.v2.executor import (
    SemanticPromptError,
    SemanticPromptExecutor,
    SemanticValidationIssueError,
)
from jobfit.semantic.v2.source_anchoring import exact_text_spans
from jobfit.semantic.v2.stage_contracts import (
    JDSourceItem,
    JDSourceItemDraft,
    P02JobInput,
    P02JobLLMOutput,
    P02JobOutput,
    SemanticAmbiguity,
)


@dataclass(frozen=True, slots=True)
class P02JobResult:
    analysis_id: str
    jd_snapshot_id: str
    job_title: str
    company: str | None
    location: str | None
    employment_type: str | None
    job_family: JobFamily
    responsibilities: tuple[JDSourceItem, ...]
    raw_requirements: tuple[JDSourceItem, ...]
    explicit_constraints: tuple[JDSourceItem, ...]
    seniority_signals: tuple[JDSourceItem, ...]
    ambiguities: tuple[SemanticAmbiguity, ...]
    parse_completeness: ParseCompleteness
    role_scope_valid: bool
    execution: PromptExecutionRecord


class P02JobParser:
    """Extract JD-only facts and preserve ambiguity instead of guessing."""

    def __init__(self, executor: SemanticPromptExecutor) -> None:
        self._executor = executor

    def parse(
        self,
        *,
        analysis_id: str,
        jd_snapshot_id: str,
        document: DocumentContent,
    ) -> P02JobResult:
        prompt_input = P02JobInput.model_validate(
            {
                "analysis_id": analysis_id,
                "jd_snapshot_id": jd_snapshot_id,
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
        anchored_output: P02JobOutput | None = None

        def validate_and_anchor(output: P02JobLLMOutput) -> None:
            nonlocal anchored_output
            candidate = _anchor_output(output, document)
            _validate_business(candidate, document)
            anchored_output = candidate

        result = self._executor.execute_prompt(
            prompt_id="P02",
            input_payload=prompt_input,
            input_object_ids=(analysis_id, jd_snapshot_id, document.document_id),
            response_model=P02JobLLMOutput,
            business_validator=validate_and_anchor,
        )
        if anchored_output is None:
            raise SemanticPromptError("P02", "JD_SOURCE_ANCHORING_FAILED")
        output = anchored_output
        responsibilities = _assemble_items(
            output.responsibilities,
            prefix="responsibility",
            jd_snapshot_id=jd_snapshot_id,
        )
        raw_requirements = _assemble_items(
            output.raw_requirements,
            prefix="raw-requirement",
            jd_snapshot_id=jd_snapshot_id,
        )
        constraints = _assemble_items(
            output.explicit_constraints,
            prefix="constraint",
            jd_snapshot_id=jd_snapshot_id,
        )
        seniority = _assemble_items(
            output.seniority_signals,
            prefix="seniority",
            jd_snapshot_id=jd_snapshot_id,
        )
        output_ids = tuple(
            item.object_id
            for collection in (
                responsibilities,
                raw_requirements,
                constraints,
                seniority,
            )
            for item in collection
        )
        execution = result.record.model_copy(
            update={"output_object_ids": output_ids}
        )
        return P02JobResult(
            analysis_id=analysis_id,
            jd_snapshot_id=jd_snapshot_id,
            job_title=output.job_title,
            company=output.company,
            location=output.location,
            employment_type=output.employment_type,
            job_family=output.job_family,
            responsibilities=responsibilities,
            raw_requirements=raw_requirements,
            explicit_constraints=constraints,
            seniority_signals=seniority,
            ambiguities=tuple(output.ambiguities),
            parse_completeness=output.parse_completeness,
            role_scope_valid=(
                output.job_family not in {JobFamily.UNKNOWN, JobFamily.OTHER}
                and not output.ambiguities
            ),
            execution=execution,
        )


def _anchor_output(
    output: P02JobLLMOutput,
    document: DocumentContent,
) -> P02JobOutput:
    segment_by_id = {segment.segment_id: segment for segment in document.segments}
    anchored_collections: dict[str, list[dict[str, object]]] = {}
    validation_paths: list[str] = []
    validation_categories: list[str] = []

    for field_name in (
        "responsibilities",
        "raw_requirements",
        "explicit_constraints",
        "seniority_signals",
    ):
        anchored: list[dict[str, object]] = []
        for index, item in enumerate(getattr(output, field_name)):
            if item.document_id != document.document_id:
                _fail(
                    "JD_SOURCE_IDENTITY_INVALID",
                    f"{field_name}[{index}].document_id",
                    "JD_SOURCE_DOCUMENT_MISMATCH",
                )
            segment = segment_by_id.get(item.segment_id)
            if segment is None:
                _fail(
                    "JD_SOURCE_IDENTITY_INVALID",
                    f"{field_name}[{index}].segment_id",
                    "JD_SOURCE_SEGMENT_UNKNOWN",
                )
            spans = exact_text_spans(
                segment.text,
                item.text,
                base_offset=segment.start_char,
            )
            if len(spans) != 1:
                validation_paths.append(f"{field_name}[{index}]")
                validation_categories.append(
                    "JD_SOURCE_TEXT_NOT_FOUND"
                    if not spans
                    else "JD_SOURCE_TEXT_AMBIGUOUS"
                )
                continue
            start_char, end_char = spans[0]
            anchored.append(
                {
                    **item.model_dump(mode="json"),
                    "start_char": start_char,
                    "end_char": end_char,
                }
            )
        anchored_collections[field_name] = anchored

    if validation_paths:
        raise SemanticValidationIssueError(
            "JD_SOURCE_ANCHORING_FAILED",
            validation_paths=validation_paths,
            validation_categories=validation_categories,
        )

    return P02JobOutput.model_validate(
        {
            **output.model_dump(
                mode="json",
                exclude=set(anchored_collections),
            ),
            **anchored_collections,
        }
    )


def _validate_business(output: P02JobOutput, document: DocumentContent) -> None:
    if not output.responsibilities:
        _fail(
            "BUSINESS_VALIDATION_FAILED",
            "responsibilities",
            "P02_RESPONSIBILITY_REQUIRED",
        )
    if not output.raw_requirements:
        _fail(
            "BUSINESS_VALIDATION_FAILED",
            "raw_requirements",
            "P02_MEANINGFUL_REQUIREMENT_REQUIRED",
        )
    seen: set[str] = set()
    segment_by_id = {segment.segment_id: segment for segment in document.segments}
    for item in _all_items(output):
        if item.local_id in seen:
            _fail(
                "BUSINESS_VALIDATION_FAILED",
                "source_items",
                "P02_SOURCE_ID_DUPLICATE",
            )
        seen.add(item.local_id)
        if item.document_id != document.document_id:
            _fail(
                "JD_SOURCE_IDENTITY_INVALID",
                "source_items.document_id",
                "JD_SOURCE_DOCUMENT_MISMATCH",
            )
        segment = segment_by_id.get(item.segment_id)
        if segment is None:
            _fail(
                "JD_SOURCE_IDENTITY_INVALID",
                "source_items.segment_id",
                "JD_SOURCE_SEGMENT_UNKNOWN",
            )
        if not (
            segment.start_char <= item.start_char
            and item.end_char <= segment.end_char
        ):
            _fail(
                "JD_SOURCE_ANCHORING_FAILED",
                "source_items",
                "JD_SOURCE_OFFSET_OUT_OF_RANGE",
            )
        if document.normalized_text[item.start_char : item.end_char] != item.text:
            _fail(
                "JD_SOURCE_ANCHORING_FAILED",
                "source_items",
                "JD_SOURCE_TEXT_MISMATCH",
            )


def _fail(code: str, path: str, category: str) -> None:
    raise SemanticValidationIssueError(
        code,
        validation_paths=(path,),
        validation_categories=(category,),
    )


def _assemble_items(
    items: list[JDSourceItemDraft],
    *,
    prefix: str,
    jd_snapshot_id: str,
) -> tuple[JDSourceItem, ...]:
    return tuple(
        JDSourceItem(
            object_id=stable_id(
                prefix,
                jd_snapshot_id,
                item.document_id,
                item.segment_id,
                item.start_char,
                item.end_char,
                item.text,
            ),
            text=item.text,
            document_id=item.document_id,
            segment_id=item.segment_id,
            start_char=item.start_char,
            end_char=item.end_char,
        )
        for item in sorted(
            items,
            key=lambda item: (item.start_char, item.end_char, item.local_id),
        )
    )


def _all_items(output: P02JobOutput) -> tuple[JDSourceItemDraft, ...]:
    return tuple(
        item
        for collection in (
            output.responsibilities,
            output.raw_requirements,
            output.explicit_constraints,
            output.seniority_signals,
        )
        for item in collection
    )
