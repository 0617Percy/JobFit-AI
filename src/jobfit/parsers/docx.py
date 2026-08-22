"""DOCX paragraph and table text parser."""

from __future__ import annotations

from io import BytesIO

from docx import Document

from jobfit.errors import DocumentParseError, ErrorCode
from jobfit.models import DocumentContent, DocumentSourceKind
from jobfit.parsers.base import BaseDocumentParser
from jobfit.parsers.normalizer import TextPart, normalize_parts


class DocxDocumentParser(BaseDocumentParser):
    source_kind = DocumentSourceKind.DOCX
    default_media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    parser_name = "docx"

    def parse(
        self,
        content: bytes,
        filename: str,
        *,
        media_type: str | None = None,
    ) -> DocumentContent:
        self.require_non_empty_bytes(content)
        try:
            document = Document(BytesIO(content))
            parts = [
                TextPart(paragraph.text, section_hint="paragraph")
                for paragraph in document.paragraphs
            ]
            for table in document.tables:
                for row in table.rows:
                    parts.extend(
                        TextPart(cell.text, section_hint="table_cell") for cell in row.cells
                    )
        except Exception as exc:
            raise DocumentParseError(
                code=ErrorCode.DOCUMENT_PARSE_FAILED,
                user_message=(
                    "DOCX 文件无法解析，文件可能已损坏；请重新导出 DOCX 或直接粘贴简历文本。"
                ),
                recoverable=True,
                cause=exc,
            ) from exc

        raw_text = "\n".join(part.text for part in parts)
        normalized_text, segments = normalize_parts(parts)
        if not normalized_text:
            raise DocumentParseError(
                code=ErrorCode.DOCUMENT_PARSE_FAILED,
                user_message="DOCX 中没有可提取文本，请直接粘贴简历内容。",
                recoverable=True,
            )
        return self.build_document(
            content=content,
            filename=filename,
            raw_text=raw_text,
            normalized_text=normalized_text,
            segments=segments,
            media_type=media_type,
            metadata={
                "paragraph_count": len(document.paragraphs),
                "table_count": len(document.tables),
            },
        )
