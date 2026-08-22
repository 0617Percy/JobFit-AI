"""LLM-backed semantic matching with deterministic local assembly."""

from __future__ import annotations

import json
from collections.abc import Sequence

from pydantic import Field, ValidationError

from jobfit.errors import ErrorCode, JobFitError, SchemaValidationError
from jobfit.llm import (
    LLMClient,
    LLMMessage,
    LLMSettings,
    LLMTask,
    PromptRegistry,
)
from jobfit.models import (
    DocumentContent,
    EvidenceRegistry,
    JobProfile,
    RequirementMatch,
    RequirementMatchDraft,
    ResumeProfile,
    StrictModel,
)
from jobfit.validators.evidence import STATUS_VALUES, EvidenceValidator


class RequirementMatchBatchDraft(StrictModel):
    """One LLM response containing one draft for every job requirement."""

    matches: list[RequirementMatchDraft] = Field(min_length=1)


def assemble_match(
    draft: RequirementMatchDraft,
    registry: EvidenceRegistry,
) -> RequirementMatch:
    """Resolve model-submitted evidence to canonical items and write local score."""

    canonical_items = []
    try:
        for submitted in draft.evidence_items:
            canonical = registry.get(submitted.evidence_id)
            if submitted != canonical:
                raise ValueError("submitted evidence differs from registry")
            canonical_items.append(canonical)
        return RequirementMatch(
            **draft.model_dump(exclude={"evidence_items"}),
            evidence_items=canonical_items,
            match_score=STATUS_VALUES[draft.match_status],
        )
    except (KeyError, ValueError, ValidationError) as exc:
        raise SchemaValidationError(
            code=ErrorCode.EVIDENCE_INVALID,
            user_message="模型返回的岗位匹配证据无效，请重试。",
            recoverable=True,
            cause=exc,
        ) from exc


class EvidenceMatcher:
    """Match every requirement once and reject ungrounded model output."""

    def __init__(
        self,
        *,
        client: LLMClient,
        prompt_registry: PromptRegistry,
        settings: LLMSettings,
        prompt_version: str = "1.0",
        validator: EvidenceValidator | None = None,
    ) -> None:
        self._client = client
        self._prompt_registry = prompt_registry
        self._settings = settings
        self._prompt_version = prompt_version
        self._validator = validator or EvidenceValidator()

    def match(
        self,
        resume: ResumeProfile,
        job: JobProfile,
        document: DocumentContent,
        registry: EvidenceRegistry,
        *,
        request_id: str,
    ) -> list[RequirementMatch]:
        if resume.document_id != document.document_id:
            raise SchemaValidationError(
                code=ErrorCode.EVIDENCE_INVALID,
                user_message="简历档案与证据文档不一致。",
                recoverable=False,
            )
        template = self._prompt_registry.load(
            LLMTask.MATCH_EVIDENCE.value,
            self._prompt_version,
        )
        expected_ids = [
            item.requirement_id for item in job.requirements.items
        ]
        messages = self._build_messages(
            template.system_text,
            template.user_template,
            resume,
            job,
            registry,
        )
        settings = self._settings.model_copy(
            update={
                "request_id": request_id,
                "prompt_version": template.version,
            }
        )

        last_error: JobFitError | None = None
        for attempt in range(2):
            batch = self._client.generate_structured(
                task=LLMTask.MATCH_EVIDENCE,
                response_model=RequirementMatchBatchDraft,
                messages=messages,
                settings=settings,
            )
            try:
                matches = [
                    assemble_match(draft, registry) for draft in batch.matches
                ]
                self._validator.validate_or_raise(
                    document,
                    registry,
                    job.requirements.items,
                    matches,
                )
                by_id = {item.requirement_id: item for item in matches}
                return [by_id[requirement_id] for requirement_id in expected_ids]
            except JobFitError as exc:
                last_error = exc
                if attempt == 0:
                    messages = (*messages, self._repair_message(expected_ids))

        raise SchemaValidationError(
            code=ErrorCode.EVIDENCE_INVALID,
            user_message="岗位匹配结果在有限修复后仍未通过证据校验。",
            recoverable=True,
            cause=last_error,
        )

    @staticmethod
    def _build_messages(
        system_text: str,
        user_template: str,
        resume: ResumeProfile,
        job: JobProfile,
        registry: EvidenceRegistry,
    ) -> tuple[LLMMessage, LLMMessage]:
        payload = {
            "requirements": [
                item.model_dump(
                    mode="json",
                    exclude={"priority_factor", "weight"},
                )
                for item in job.requirements.items
            ],
            "resume_profile": resume.model_dump(
                mode="json",
                exclude={"basic_info": {"email", "phone"}},
            ),
            "evidence_catalog": [
                registry.get(evidence_id).model_dump(mode="json")
                for evidence_id in registry.ids
            ],
        }
        token = "{validated_requirements_and_resume_facts}"
        if token not in user_template:
            raise ValueError("match_evidence prompt placeholder is missing")
        user_text = user_template.replace(
            token,
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        )
        return (
            LLMMessage(role="system", content=system_text),
            LLMMessage(role="user", content=user_text),
        )

    @staticmethod
    def _repair_message(expected_ids: Sequence[str]) -> LLMMessage:
        payload = {
            "instruction": (
                "上一次结果未通过本地覆盖或证据校验。仅修复结构与引用；"
                "不得新增事实、证据、分数、权重或岗位要求。"
            ),
            "required_requirement_ids": list(expected_ids),
            "required_count": len(expected_ids),
        }
        return LLMMessage(
            role="user",
            content=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        )
