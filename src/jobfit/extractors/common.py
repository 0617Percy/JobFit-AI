"""Shared deterministic utilities for structured extractors."""

from __future__ import annotations

from hashlib import sha256

from jobfit.errors import ErrorCode, InputError
from jobfit.llm import LLMMessage, LLMSettings, PromptTemplate
from jobfit.models import DocumentContent


def stable_id(prefix: str, *parts: object) -> str:
    """Build a compact deterministic ID from source-controlled values."""

    payload = "\x1f".join(str(part) for part in parts)
    digest = sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def require_text_limit(
    document: DocumentContent,
    *,
    max_characters: int,
    label: str,
) -> None:
    if len(document.normalized_text) > max_characters:
        raise InputError(
            code=ErrorCode.INPUT_TOO_LARGE,
            user_message=f"{label}文本超过 {max_characters} 字符限制，请精简后重试。",
            recoverable=True,
        )


def build_prompt_messages(
    template: PromptTemplate,
    *,
    placeholder: str,
    source_text: str,
) -> tuple[LLMMessage, LLMMessage]:
    token = "{" + placeholder + "}"
    if token not in template.user_template:
        raise ValueError(f"Prompt template is missing placeholder: {placeholder}")
    user_text = template.user_template.replace(token, source_text)
    return (
        LLMMessage(role="system", content=template.system_text),
        LLMMessage(role="user", content=user_text),
    )


def settings_for_prompt(
    settings: LLMSettings,
    template: PromptTemplate,
) -> LLMSettings:
    return settings.model_copy(update={"prompt_version": template.version})
