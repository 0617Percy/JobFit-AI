"""Unified resume input parsing service."""

from __future__ import annotations

from typing import Literal

from jobfit.config import Settings
from jobfit.errors import ErrorCode, InputError
from jobfit.models import AnalysisRequest, DocumentContent
from jobfit.parsers.router import DocumentParserRouter
from jobfit.parsers.text import TextDocumentParser

SelectedSource = Literal["file", "text"]


class DocumentParserService:
    """Validate source choice and route all inputs to a common document model."""

    def __init__(
        self,
        *,
        settings: Settings,
        router: DocumentParserRouter | None = None,
    ) -> None:
        self._settings = settings
        self._router = router or DocumentParserRouter()
        self._text_parser = TextDocumentParser()

    def parse_request(
        self,
        request: AnalysisRequest,
        *,
        selected_source: SelectedSource | None,
    ) -> DocumentContent:
        if selected_source is None:
            raise InputError(
                code=ErrorCode.INPUT_EMPTY,
                user_message="请选择使用上传文件或粘贴文本作为简历证据源。",
                recoverable=True,
            )
        if selected_source == "text":
            return self._parse_pasted_text(request)
        if selected_source == "file":
            return self._parse_file(request)
        raise InputError(
            code=ErrorCode.INPUT_EMPTY,
            user_message="简历证据源选择无效，请重新选择。",
            recoverable=True,
        )

    def _parse_pasted_text(self, request: AnalysisRequest) -> DocumentContent:
        text = request.pasted_resume_text
        if not text or not text.strip():
            raise InputError(
                code=ErrorCode.INPUT_EMPTY,
                user_message="未提供可用的粘贴简历文本。",
                recoverable=True,
            )
        if len(text) > self._settings.max_resume_chars:
            raise InputError(
                code=ErrorCode.INPUT_TOO_LARGE,
                user_message=(f"简历文本超过 {self._settings.max_resume_chars} 字符限制。"),
                recoverable=True,
            )
        return self._text_parser.parse_text(text)

    def _parse_file(self, request: AnalysisRequest) -> DocumentContent:
        upload = request.resume_file
        if upload is None:
            raise InputError(
                code=ErrorCode.INPUT_EMPTY,
                user_message="未提供可解析的简历文件。",
                recoverable=True,
            )
        maximum_bytes = self._settings.max_upload_mb * 1024 * 1024
        if upload.size_bytes > maximum_bytes:
            raise InputError(
                code=ErrorCode.INPUT_TOO_LARGE,
                user_message=(f"文件超过 {self._settings.max_upload_mb} MiB 大小限制。"),
                recoverable=True,
            )
        parser = self._router.resolve(upload.filename, upload.media_type)
        return parser.parse(
            upload.content,
            upload.filename,
            media_type=upload.media_type,
        )
