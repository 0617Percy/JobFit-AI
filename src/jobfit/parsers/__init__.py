"""Public document parsing contracts and implementations."""

from jobfit.parsers.base import DocumentParser as DocumentParser
from jobfit.parsers.docx import DocxDocumentParser as DocxDocumentParser
from jobfit.parsers.normalizer import TextPart as TextPart
from jobfit.parsers.normalizer import normalize_parts as normalize_parts
from jobfit.parsers.normalizer import normalize_text as normalize_text
from jobfit.parsers.pdf import PdfDocumentParser as PdfDocumentParser
from jobfit.parsers.router import DocumentParserRouter as DocumentParserRouter
from jobfit.parsers.service import DocumentParserService as DocumentParserService
from jobfit.parsers.text import TextDocumentParser as TextDocumentParser

__all__ = [
    "DocumentParser",
    "DocumentParserRouter",
    "DocumentParserService",
    "DocxDocumentParser",
    "PdfDocumentParser",
    "TextDocumentParser",
    "TextPart",
    "normalize_parts",
    "normalize_text",
]
