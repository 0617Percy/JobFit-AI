"""Text-layer PDF parser without OCR."""

from __future__ import annotations

from io import BytesIO

from pypdf import PdfReader

from jobfit.errors import DocumentParseError, ErrorCode
from jobfit.models import DocumentContent, DocumentSourceKind
from jobfit.parsers.base import BaseDocumentParser
from jobfit.parsers.normalizer import TextPart, normalize_parts


class PdfDocumentParser(BaseDocumentParser):
    source_kind = DocumentSourceKind.PDF
    default_media_type = "application/pdf"
    parser_name = "pdf"

    def parse(
        self,
        content: bytes,
        filename: str,
        *,
        media_type: str | None = None,
    ) -> DocumentContent:
        self.require_non_empty_bytes(content)
        try:
            with BytesIO(content) as stream:
                reader = PdfReader(stream, strict=False)
                if reader.is_encrypted:
                    raise ValueError("Password-protected PDF")
                page_count = len(reader.pages)
                parts = [
                    TextPart(
                        page.extract_text() or "",
                        page_number=page_number,
                        section_hint="page",
                    )
                    for page_number, page in enumerate(reader.pages, start=1)
                ]
        except Exception as exc:
            raise DocumentParseError(
                code=ErrorCode.DOCUMENT_PARSE_FAILED,
                user_message=(
                    "PDF 文件无法解析，文件可能已损坏或受密码保护；"
                    "请上传文本版 PDF 或直接粘贴简历内容。"
                ),
                recoverable=True,
                cause=exc,
            ) from exc

        raw_text = "\n".join(part.text for part in parts)
        normalized_text, segments = normalize_parts(parts)
        if not normalized_text:
            raise DocumentParseError(
                code=ErrorCode.PDF_TEXT_EMPTY,
                user_message=(
                    "PDF 中未检测到可提取文本，可能是扫描版；"
                    "本版本不提供 OCR，请上传文本版 PDF 或直接粘贴内容。"
                ),
                recoverable=True,
            )
        return self.build_document(
            content=content,
            filename=filename,
            raw_text=raw_text,
            normalized_text=normalized_text,
            segments=segments,
            media_type=media_type,
            metadata={"page_count": page_count},
        )
