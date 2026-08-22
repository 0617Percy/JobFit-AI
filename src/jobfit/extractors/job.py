"""Source-grounded job requirement extraction without scoring."""

from __future__ import annotations

from decimal import Decimal

from pydantic import ValidationError

from jobfit.errors import ErrorCode, SchemaValidationError
from jobfit.extractors.common import (
    build_prompt_messages,
    require_text_limit,
    settings_for_prompt,
    stable_id,
)
from jobfit.extractors.validators import (
    require_source_supported,
    validate_job_requirement,
)
from jobfit.llm import LLMClient, LLMSettings, LLMTask, PromptRegistry
from jobfit.models import (
    DocumentContent,
    JobExtractionDraft,
    JobProfile,
    JobRequirement,
    JobRequirementCollection,
)

_UNSCORED = Decimal("0")


class JobRequirementExtractor:
    """Convert a JD document into deduplicated, unscored requirements."""

    def __init__(
        self,
        *,
        client: LLMClient,
        prompt_registry: PromptRegistry,
        settings: LLMSettings,
        prompt_version: str = "1.0",
        max_characters: int = 30_000,
    ) -> None:
        self._client = client
        self._prompt_registry = prompt_registry
        self._settings = settings
        self._prompt_version = prompt_version
        self._max_characters = max_characters

    def extract(
        self,
        document: DocumentContent,
        *,
        title: str | None = None,
        company: str | None = None,
    ) -> JobProfile:
        require_text_limit(
            document,
            max_characters=self._max_characters,
            label="岗位描述",
        )
        template = self._prompt_registry.load(
            LLMTask.EXTRACT_JOB.value,
            self._prompt_version,
        )
        draft = self._client.generate_structured(
            task=LLMTask.EXTRACT_JOB,
            response_model=JobExtractionDraft,
            messages=build_prompt_messages(
                template,
                placeholder="job_description_text",
                source_text=document.normalized_text,
            ),
            settings=settings_for_prompt(self._settings, template),
        )
        return self._assemble(
            document,
            draft,
            title=title,
            company=company,
        )

    @staticmethod
    def _assemble(
        document: DocumentContent,
        draft: JobExtractionDraft,
        *,
        title: str | None,
        company: str | None,
    ) -> JobProfile:
        if title is None:
            require_source_supported(draft.title, document.normalized_text, "岗位名称")
        if company is None:
            require_source_supported(draft.company, document.normalized_text, "公司名称")
        for keyword in draft.keywords:
            require_source_supported(keyword, document.normalized_text, "岗位关键词")

        ordered = sorted(
            draft.requirements,
            key=lambda item: (
                item.source_start_char,
                item.source_end_char,
                item.normalized_key,
            ),
        )
        unique = []
        seen_keys: set[str] = set()
        notes: list[str] = []
        for requirement in ordered:
            validate_job_requirement(document, requirement)
            if requirement.normalized_key in seen_keys:
                notes.append(
                    f"已按 normalized_key 去重：{requirement.normalized_key}"
                )
                continue
            seen_keys.add(requirement.normalized_key)
            unique.append(requirement)

        try:
            items = [
                JobRequirement(
                    **requirement.model_dump(),
                    requirement_id=stable_id(
                        "req",
                        document.document_id,
                        requirement.normalized_key,
                        requirement.source_start_char,
                        requirement.source_end_char,
                    ),
                    priority_factor=_UNSCORED,
                    weight=_UNSCORED,
                )
                for requirement in unique
            ]
            resolved_title = _clean_override(title) if title is not None else draft.title
            resolved_company = (
                _clean_override(company) if company is not None else draft.company
            )
            return JobProfile(
                job_id=stable_id("job", document.document_id),
                title=resolved_title,
                company=resolved_company,
                language=draft.language,
                jd_text=document.normalized_text,
                summary=_build_summary(
                    title=resolved_title,
                    company=resolved_company,
                    requirement_count=len(items),
                ),
                requirements=JobRequirementCollection(
                    items=items,
                    deduplication_notes=notes,
                    source_coverage_ratio=_source_coverage_ratio(
                        document.normalized_text,
                        [(item.source_start_char, item.source_end_char) for item in unique],
                    ),
                ),
                keywords=draft.keywords,
                extraction_warnings=draft.extraction_warnings,
            )
        except (TypeError, ValueError, ValidationError) as exc:
            raise SchemaValidationError(
                code=ErrorCode.SCHEMA_VALIDATION_FAILED,
                user_message="岗位结构化结果无法映射到领域模型。",
                recoverable=True,
                cause=exc,
            ) from exc


def _clean_override(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise SchemaValidationError(
            code=ErrorCode.SCHEMA_VALIDATION_FAILED,
            user_message="岗位名称或公司名称不能只包含空白字符。",
            recoverable=True,
        )
    return cleaned


def _build_summary(
    *,
    title: str | None,
    company: str | None,
    requirement_count: int,
) -> str:
    subject = title or "该岗位"
    if company:
        subject = f"{company}的{subject}"
    return f"{subject}已从原始JD中提取 {requirement_count} 项要求。"


def _source_coverage_ratio(
    source_text: str,
    ranges: list[tuple[int, int]],
) -> Decimal:
    source_positions = {
        position
        for position, character in enumerate(source_text)
        if not character.isspace()
    }
    covered = {
        position
        for start_char, end_char in ranges
        for position in range(start_char, end_char)
        if position in source_positions
    }
    if not source_positions:
        return Decimal("0")
    return (Decimal(len(covered)) / Decimal(len(source_positions))).quantize(
        Decimal("0.0001")
    )
