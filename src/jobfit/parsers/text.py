"""UTF-8 TXT and pasted-text parser."""

from __future__ import annotations

from jobfit.errors import DocumentParseError, ErrorCode, InputError
from jobfit.models import DocumentContent, DocumentSourceKind
from jobfit.parsers.base import BaseDocumentParser
from jobfit.parsers.normalizer import normalize_text


class TextDocumentParser(BaseDocumentParser):
    source_kind = DocumentSourceKind.TXT
    default_media_type = "text/plain"
    parser_name = "txt"

    def parse(
        self,
        content: bytes,
        filename: str,
        *,
        media_type: str | None = None,
    ) -> DocumentContent:
        self.require_non_empty_bytes(content)
        try:
            raw_text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise DocumentParseError(
                code=ErrorCode.DOCUMENT_PARSE_FAILED,
                user_message=("TXT 文件不是有效的 UTF-8 文本，请另存为 UTF-8 或直接粘贴简历内容。"),
                recoverable=True,
                cause=exc,
            ) from exc
        return self._build_text_document(
            content=content,
            filename=filename,
            raw_text=raw_text,
            media_type=media_type,
            source_kind=DocumentSourceKind.TXT,
            source=None,
            parser_name="txt",
        )

    def parse_text(self, text: str) -> DocumentContent:
        if not text or not text.strip():
            raise InputError(
                code=ErrorCode.INPUT_EMPTY,
                user_message="粘贴的简历文本为空，请输入有效内容。",
                recoverable=True,
            )
        content = text.encode("utf-8")
        return self._build_text_document(
            content=content,
            filename=None,
            raw_text=text,
            media_type="text/plain; charset=utf-8",
            source_kind=DocumentSourceKind.PASTED_TEXT,
            source="pasted_text",
            parser_name="pasted_text",
        )

    def _build_text_document(
        self,
        *,
        content: bytes,
        filename: str | None,
        raw_text: str,
        media_type: str | None,
        source_kind: DocumentSourceKind,
        source: str | None,
        parser_name: str,
    ) -> DocumentContent:
        normalized_text, segments = normalize_text(raw_text)
        if not normalized_text:
            raise InputError(
                code=ErrorCode.INPUT_EMPTY,
                user_message="文本中没有可分析内容，请提供有效简历文本。",
                recoverable=True,
            )
        return self.build_document(
            content=content,
            filename=filename,
            raw_text=raw_text,
            normalized_text=normalized_text,
            segments=segments,
            media_type=media_type,
            source_kind=source_kind,
            source=source,
            metadata={"parser": parser_name, "encoding": "utf-8"},
        )
