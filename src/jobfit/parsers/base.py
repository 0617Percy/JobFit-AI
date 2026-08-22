"""Shared document parser interface and safe model assembly."""

from __future__ import annotations

from abc import ABC, abstractmethod
from hashlib import sha256
from pathlib import Path
from typing import Protocol, runtime_checkable

from jobfit.errors import DocumentParseError, ErrorCode, InputError
from jobfit.models import (
    DocumentContent,
    DocumentSourceKind,
    LanguageCode,
    TextSegment,
)


@runtime_checkable
class DocumentParser(Protocol):
    """Format-independent parser contract consumed by the router and service."""

    def parse(
        self,
        content: bytes,
        filename: str,
        *,
        media_type: str | None = None,
    ) -> DocumentContent: ...

    def parse_path(
        self,
        path: str | Path,
        *,
        media_type: str | None = None,
    ) -> DocumentContent: ...


class BaseDocumentParser(ABC):
    """Base implementation for byte loading and deterministic document identity."""

    source_kind: DocumentSourceKind
    default_media_type: str
    parser_name: str

    @abstractmethod
    def parse(
        self,
        content: bytes,
        filename: str,
        *,
        media_type: str | None = None,
    ) -> DocumentContent:
        """Parse file bytes into an evidence-ready document."""

    def parse_path(
        self,
        path: str | Path,
        *,
        media_type: str | None = None,
    ) -> DocumentContent:
        source_path = Path(path)
        try:
            content = source_path.read_bytes()
        except OSError as exc:
            raise DocumentParseError(
                code=ErrorCode.DOCUMENT_PARSE_FAILED,
                user_message="无法读取所选文件，请重新选择文件或粘贴简历文本。",
                recoverable=True,
                cause=exc,
            ) from exc
        return self.parse(
            content,
            source_path.name,
            media_type=media_type,
        )

    @staticmethod
    def require_non_empty_bytes(content: bytes) -> None:
        if not content:
            raise InputError(
                code=ErrorCode.INPUT_EMPTY,
                user_message="上传文件为空，请选择有效文件或粘贴简历文本。",
                recoverable=True,
            )

    def build_document(
        self,
        *,
        content: bytes,
        filename: str | None,
        raw_text: str,
        normalized_text: str,
        segments: list[TextSegment],
        media_type: str | None,
        source_kind: DocumentSourceKind | None = None,
        source: str | None = None,
        metadata: dict[str, str | int | float | bool | None] | None = None,
        warnings: list[str] | None = None,
    ) -> DocumentContent:
        digest = sha256(content).hexdigest()
        safe_filename = Path(filename).name if filename else None
        resolved_source_kind = source_kind or self.source_kind
        return DocumentContent(
            document_id=f"doc-{digest[:16]}",
            source_kind=resolved_source_kind,
            original_filename=safe_filename,
            media_type=media_type or self.default_media_type,
            byte_size=len(content),
            source=source or safe_filename or resolved_source_kind.value,
            raw_text=raw_text,
            normalized_text=normalized_text,
            language=LanguageCode.UNKNOWN,
            segments=segments,
            content_sha256=digest,
            metadata={"parser": self.parser_name, **(metadata or {})},
            warnings=warnings or [],
        )
