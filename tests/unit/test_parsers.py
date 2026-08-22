"""Tests for the evidence-ready document parsing pipeline."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from docx import Document

from jobfit.config import Settings
from jobfit.errors import DocumentParseError, ErrorCode, InputError
from jobfit.models import (
    AnalysisRequest,
    DocumentSourceKind,
    UploadedDocumentInput,
)
from jobfit.parsers.docx import DocxDocumentParser
from jobfit.parsers.normalizer import normalize_text
from jobfit.parsers.pdf import PdfDocumentParser
from jobfit.parsers.router import DocumentParserRouter
from jobfit.parsers.service import DocumentParserService
from jobfit.parsers.text import TextDocumentParser
from tests.pdf_fixtures import (
    make_blank_pdf_bytes,
    make_encrypted_pdf_bytes,
    make_mixed_page_pdf_bytes,
)


@pytest.fixture
def fixture_dir() -> Path:
    return Path(__file__).parents[1] / "fixtures"


@pytest.fixture
def settings() -> Settings:
    return Settings(app_env="test", llm_provider="mock")


def make_upload(
    *,
    filename: str,
    media_type: str,
    content: bytes,
) -> UploadedDocumentInput:
    return UploadedDocumentInput(
        filename=filename,
        media_type=media_type,
        content=content,
        size_bytes=len(content),
    )


def make_request(
    *,
    resume_file: UploadedDocumentInput | None = None,
    pasted_resume_text: str | None = None,
) -> AnalysisRequest:
    return AnalysisRequest(
        request_id="request-parser-test",
        resume_file=resume_file,
        pasted_resume_text=pasted_resume_text,
        job_description_text="熟悉 Python",
        llm_mode="mock",
    )


def make_docx_bytes(
    *,
    paragraphs: list[str] | None = None,
    table_rows: list[tuple[str, str]] | None = None,
) -> bytes:
    document = Document()
    for text in paragraphs or []:
        document.add_paragraph(text)
    if table_rows:
        table = document.add_table(rows=len(table_rows), cols=2)
        for row_index, (left, right) in enumerate(table_rows):
            table.cell(row_index, 0).text = left
            table.cell(row_index, 1).text = right
    stream = BytesIO()
    document.save(stream)
    return stream.getvalue()


def assert_segments_match_normalized_text(document: object) -> None:
    normalized_text = document.normalized_text
    for segment in document.segments:
        assert 0 <= segment.start_char < segment.end_char <= len(normalized_text)
        assert normalized_text[segment.start_char : segment.end_char] == segment.text


def test_normalize_text_preserves_content_and_stable_offsets() -> None:
    raw = "\ufeff第一行  \r\n\r\n\r\n\r\n  第二行\t \r第三行"

    normalized, segments = normalize_text(raw)

    assert normalized == "第一行\n\n\n  第二行\n第三行"
    assert all(
        normalized[segment.start_char : segment.end_char] == segment.text for segment in segments
    )
    assert [segment.text for segment in segments] == [
        "第一行",
        "  第二行\n第三行",
    ]


def test_txt_parser_handles_utf8_bom() -> None:
    content = b"\xef\xbb\xbfPython\r\n\xe6\x95\xb0\xe6\x8d\xae\xe5\x88\x86\xe6\x9e\x90"

    document = TextDocumentParser().parse(
        content,
        "resume.txt",
        media_type="text/plain",
    )

    assert document.source_kind is DocumentSourceKind.TXT
    assert document.raw_text.startswith("\ufeff")
    assert document.normalized_text == "Python\n数据分析"
    assert document.text_length == len(document.normalized_text)
    assert_segments_match_normalized_text(document)


def test_txt_parser_reads_common_chinese_text(fixture_dir: Path) -> None:
    document = TextDocumentParser().parse_path(
        fixture_dir / "sample_resume.txt",
        media_type="text/plain",
    )

    assert "示例大学" in document.normalized_text
    assert "lin.x@example.com" in document.normalized_text
    assert document.original_filename == "sample_resume.txt"


def test_empty_file_raises_input_empty() -> None:
    with pytest.raises(InputError) as exc_info:
        TextDocumentParser().parse(b"", "empty.txt", media_type="text/plain")

    assert exc_info.value.code is ErrorCode.INPUT_EMPTY
    assert exc_info.value.recoverable is True


def test_txt_encoding_error_is_wrapped() -> None:
    with pytest.raises(DocumentParseError) as exc_info:
        TextDocumentParser().parse(
            b"\xff\xfe\x00\x81",
            "broken.txt",
            media_type="text/plain",
        )

    assert exc_info.value.code is ErrorCode.DOCUMENT_PARSE_FAILED
    assert exc_info.value.cause is not None


def test_document_hash_and_id_are_stable() -> None:
    parser = TextDocumentParser()
    content = "匿名简历".encode()

    first = parser.parse(content, "a.txt")
    second = parser.parse(content, "renamed.txt")
    changed = parser.parse("另一份简历".encode(), "a.txt")

    assert first.content_sha256 == second.content_sha256
    assert first.document_id == second.document_id
    assert first.content_sha256 != changed.content_sha256


def test_txt_parser_strips_local_path_from_document_source() -> None:
    document = TextDocumentParser().parse(
        b"anonymous resume",
        r"C:\Users\Private\resume.txt",
    )

    assert document.original_filename == "resume.txt"
    assert document.source == "resume.txt"
    assert "Private" not in document.model_dump_json()


def test_docx_parser_reads_paragraphs_and_tables(fixture_dir: Path) -> None:
    document = DocxDocumentParser().parse_path(
        fixture_dir / "sample_resume.docx",
        media_type=("application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    )

    assert document.source_kind is DocumentSourceKind.DOCX
    assert "目标岗位：AI应用开发实习生" in document.normalized_text
    assert "教育经历" in document.normalized_text
    assert "示例大学，计算机科学，本科" in document.normalized_text
    assert any(segment.section_hint == "table_cell" for segment in document.segments)
    assert_segments_match_normalized_text(document)


def test_docx_parser_places_paragraphs_before_table_cells() -> None:
    content = make_docx_bytes(
        paragraphs=["段落一", "段落二"],
        table_rows=[("技能", "Python")],
    )

    document = DocxDocumentParser().parse(content, "resume.docx")

    assert document.normalized_text == "段落一\n段落二\n技能\nPython"
    assert [segment.section_hint for segment in document.segments] == [
        "paragraph",
        "paragraph",
        "table_cell",
        "table_cell",
    ]


def test_empty_docx_raises_document_parse_failed() -> None:
    with pytest.raises(DocumentParseError) as exc_info:
        DocxDocumentParser().parse(make_docx_bytes(), "empty.docx")

    assert exc_info.value.code is ErrorCode.DOCUMENT_PARSE_FAILED
    assert exc_info.value.recoverable is True


def test_corrupt_docx_is_wrapped() -> None:
    with pytest.raises(DocumentParseError) as exc_info:
        DocxDocumentParser().parse(b"not-a-docx", "broken.docx")

    assert exc_info.value.code is ErrorCode.DOCUMENT_PARSE_FAILED
    assert exc_info.value.cause is not None


def test_pdf_parser_reads_text_pdf(fixture_dir: Path) -> None:
    document = PdfDocumentParser().parse_path(
        fixture_dir / "sample_resume.pdf",
        media_type="application/pdf",
    )

    assert document.source_kind is DocumentSourceKind.PDF
    assert "Python" in document.normalized_text
    assert "示例大学" in document.normalized_text
    assert_segments_match_normalized_text(document)


def test_pdf_parser_preserves_page_numbers(fixture_dir: Path) -> None:
    source = (fixture_dir / "sample_resume.pdf").read_bytes()
    content = make_mixed_page_pdf_bytes(source)

    document = PdfDocumentParser().parse(content, "two-pages.pdf")

    assert [segment.page_number for segment in document.segments] == [1, 2]
    assert document.normalized_text.count("示例大学") == 2
    assert_segments_match_normalized_text(document)


def test_pdf_parser_skips_blank_pages_without_renumbering(fixture_dir: Path) -> None:
    source = (fixture_dir / "sample_resume.pdf").read_bytes()
    content = make_mixed_page_pdf_bytes(source, blank_middle=True)

    document = PdfDocumentParser().parse(content, "mixed-pages.pdf")

    assert document.metadata["page_count"] == 3
    assert [segment.page_number for segment in document.segments] == [1, 3]
    assert_segments_match_normalized_text(document)


def test_pdf_parser_treats_none_extraction_as_an_empty_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakePage:
        def __init__(self, text: str | None) -> None:
            self._text = text

        def extract_text(self) -> str | None:
            return self._text

    class FakeReader:
        is_encrypted = False
        pages = [FakePage(None), FakePage("Second page")]

    monkeypatch.setattr(
        "jobfit.parsers.pdf.PdfReader",
        lambda _stream, *, strict: FakeReader(),
    )

    document = PdfDocumentParser().parse(b"%PDF-fake", "mixed-pages.pdf")

    assert document.normalized_text == "Second page"
    assert [segment.page_number for segment in document.segments] == [2]


def test_blank_pdf_raises_pdf_text_empty() -> None:
    with pytest.raises(DocumentParseError) as exc_info:
        PdfDocumentParser().parse(make_blank_pdf_bytes(), "blank.pdf")

    assert exc_info.value.code is ErrorCode.PDF_TEXT_EMPTY
    assert "粘贴" in exc_info.value.user_message


def test_scanned_pdf_raises_pdf_text_empty(fixture_dir: Path) -> None:
    with pytest.raises(DocumentParseError) as exc_info:
        PdfDocumentParser().parse(
            (fixture_dir / "image_only_resume.pdf").read_bytes(),
            "scan.pdf",
        )

    assert exc_info.value.code is ErrorCode.PDF_TEXT_EMPTY
    assert exc_info.value.recoverable is True


def test_encrypted_pdf_is_wrapped_without_leaking_content(fixture_dir: Path) -> None:
    source = (fixture_dir / "sample_resume.pdf").read_bytes()

    with pytest.raises(DocumentParseError) as exc_info:
        PdfDocumentParser().parse(
            make_encrypted_pdf_bytes(source),
            r"C:\Users\Private\protected.pdf",
        )

    assert exc_info.value.code is ErrorCode.DOCUMENT_PARSE_FAILED
    assert exc_info.value.cause is not None
    assert "受密码保护" in exc_info.value.user_message
    assert "Private" not in exc_info.value.user_message
    assert "示例大学" not in exc_info.value.user_message


def test_corrupt_pdf_is_wrapped() -> None:
    with pytest.raises(DocumentParseError) as exc_info:
        PdfDocumentParser().parse(b"not-a-pdf", "broken.pdf")

    assert exc_info.value.code is ErrorCode.DOCUMENT_PARSE_FAILED
    assert exc_info.value.cause is not None


@pytest.mark.parametrize(
    ("filename", "media_type", "expected_type"),
    [
        ("resume.txt", "text/plain", TextDocumentParser),
        (
            "resume.docx",
            ("application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
            DocxDocumentParser,
        ),
        ("resume.pdf", "application/pdf", PdfDocumentParser),
    ],
)
def test_router_selects_supported_parser(
    filename: str,
    media_type: str,
    expected_type: type[object],
) -> None:
    parser = DocumentParserRouter().resolve(filename, media_type)

    assert isinstance(parser, expected_type)


def test_unsupported_extension_raises_file_type_unsupported() -> None:
    with pytest.raises(InputError) as exc_info:
        DocumentParserRouter().resolve("resume.rtf", "application/rtf")

    assert exc_info.value.code is ErrorCode.FILE_TYPE_UNSUPPORTED


def test_mime_extension_mismatch_is_rejected() -> None:
    with pytest.raises(InputError) as exc_info:
        DocumentParserRouter().resolve("resume.txt", "application/pdf")

    assert exc_info.value.code is ErrorCode.FILE_TYPE_UNSUPPORTED
    assert "不一致" in exc_info.value.user_message


def test_pasted_text_is_selected_explicitly(settings: Settings) -> None:
    upload = make_upload(
        filename="resume.txt",
        media_type="text/plain",
        content=b"file source",
    )
    request = make_request(
        resume_file=upload,
        pasted_resume_text="粘贴文本证据",
    )

    document = DocumentParserService(settings=settings).parse_request(
        request,
        selected_source="text",
    )

    assert document.source_kind is DocumentSourceKind.PASTED_TEXT
    assert document.normalized_text == "粘贴文本证据"
    assert "file source" not in document.normalized_text


def test_both_sources_without_selection_is_rejected(settings: Settings) -> None:
    request = make_request(
        resume_file=make_upload(
            filename="resume.txt",
            media_type="text/plain",
            content=b"file source",
        ),
        pasted_resume_text="粘贴文本证据",
    )

    with pytest.raises(InputError) as exc_info:
        DocumentParserService(settings=settings).parse_request(
            request,
            selected_source=None,
        )

    assert exc_info.value.code is ErrorCode.INPUT_EMPTY
    assert "选择" in exc_info.value.user_message


def test_file_over_ten_mib_is_rejected_before_parse(settings: Settings) -> None:
    content = b"x" * (10 * 1024 * 1024 + 1)
    request = make_request(
        resume_file=make_upload(
            filename="resume.txt",
            media_type="text/plain",
            content=content,
        )
    )

    with pytest.raises(InputError) as exc_info:
        DocumentParserService(settings=settings).parse_request(
            request,
            selected_source="file",
        )

    assert exc_info.value.code is ErrorCode.INPUT_TOO_LARGE


def test_service_routes_supported_file(
    fixture_dir: Path,
    settings: Settings,
) -> None:
    content = (fixture_dir / "sample_resume.pdf").read_bytes()
    request = make_request(
        resume_file=make_upload(
            filename="sample_resume.pdf",
            media_type="application/pdf",
            content=content,
        )
    )

    document = DocumentParserService(settings=settings).parse_request(
        request,
        selected_source="file",
    )

    assert document.source_kind is DocumentSourceKind.PDF
    assert document.byte_size == len(content)
    assert document.media_type == "application/pdf"
    assert document.metadata["parser"] == "pdf"
    assert_segments_match_normalized_text(document)
