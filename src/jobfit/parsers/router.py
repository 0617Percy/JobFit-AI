"""Parser selection by extension and MIME type."""

from __future__ import annotations

from pathlib import Path

from jobfit.errors import ErrorCode, InputError
from jobfit.parsers.base import DocumentParser
from jobfit.parsers.docx import DocxDocumentParser
from jobfit.parsers.pdf import PdfDocumentParser
from jobfit.parsers.text import TextDocumentParser


class DocumentParserRouter:
    """Resolve one of the supported parser implementations."""

    _allowed_media_types = {
        ".txt": {"text/plain", "application/octet-stream"},
        ".docx": {
            ("application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
            "application/octet-stream",
        },
        ".pdf": {"application/pdf", "application/octet-stream"},
    }

    def __init__(self) -> None:
        self._parsers: dict[str, DocumentParser] = {
            ".txt": TextDocumentParser(),
            ".docx": DocxDocumentParser(),
            ".pdf": PdfDocumentParser(),
        }

    def resolve(
        self,
        filename: str,
        media_type: str | None = None,
    ) -> DocumentParser:
        extension = Path(filename).suffix.lower()
        parser = self._parsers.get(extension)
        if parser is None:
            raise InputError(
                code=ErrorCode.FILE_TYPE_UNSUPPORTED,
                user_message="仅支持 TXT、DOCX 和文本型 PDF 文件。",
                recoverable=True,
            )

        normalized_media_type = (
            media_type.split(";", maxsplit=1)[0].strip().lower() if media_type else None
        )
        if (
            normalized_media_type
            and normalized_media_type not in self._allowed_media_types[extension]
        ):
            raise InputError(
                code=ErrorCode.FILE_TYPE_UNSUPPORTED,
                user_message="文件扩展名与 MIME 类型不一致，请重新选择文件。",
                recoverable=True,
            )
        return parser
