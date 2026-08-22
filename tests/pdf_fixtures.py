"""Small pypdf-only helpers for composing anonymous PDF test inputs."""

from __future__ import annotations

from io import BytesIO

from pypdf import PdfReader, PdfWriter


def make_blank_pdf_bytes() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    return _write_bytes(writer)


def make_mixed_page_pdf_bytes(source: bytes, *, blank_middle: bool = False) -> bytes:
    reader = PdfReader(BytesIO(source), strict=False)
    source_page = reader.pages[0]
    writer = PdfWriter()
    writer.add_page(source_page)
    if blank_middle:
        writer.add_blank_page(
            width=float(source_page.mediabox.width),
            height=float(source_page.mediabox.height),
        )
    writer.add_page(source_page)
    return _write_bytes(writer)


def make_encrypted_pdf_bytes(source: bytes) -> bytes:
    reader = PdfReader(BytesIO(source), strict=False)
    writer = PdfWriter()
    writer.append_pages_from_reader(reader)
    writer.encrypt("anonymous-fixture-password")
    return _write_bytes(writer)


def _write_bytes(writer: PdfWriter) -> bytes:
    output = BytesIO()
    writer.write(output)
    return output.getvalue()
