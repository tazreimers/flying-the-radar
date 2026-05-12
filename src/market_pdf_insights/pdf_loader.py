"""PDF loading and text extraction helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import ModuleType


class PdfLoadError(RuntimeError):
    """Raised when a PDF cannot be read or converted into text."""


@dataclass(frozen=True)
class LoadedPdf:
    """Text extracted from a source PDF."""

    path: Path
    text: str
    page_count: int | None = None


@dataclass(frozen=True)
class _ExtractedPdf:
    """Internal extraction result including metadata needed by wrappers."""

    path: Path
    text: str
    page_count: int


def extract_pdf_text(pdf_path: Path) -> str:
    """Extract text from a PDF with page markers in source page order.

    Each page is prefixed with a marker such as `--- Page 1 ---`. Missing,
    encrypted, and invalid PDFs raise `PdfLoadError` with a readable message
    instead of leaking low-level PyMuPDF exceptions.
    """

    return _extract_pdf(pdf_path).text


def load_pdf_text(path: str | Path) -> LoadedPdf:
    """Load text and basic metadata from a PDF file."""

    extracted_pdf = _extract_pdf(Path(path))
    return LoadedPdf(
        path=extracted_pdf.path,
        text=extracted_pdf.text,
        page_count=extracted_pdf.page_count,
    )


def _extract_pdf(pdf_path: Path) -> _ExtractedPdf:
    """Open a PDF with PyMuPDF and extract all page text."""

    normalized_path = _validate_pdf_path(pdf_path)
    fitz = _import_pymupdf()

    try:
        with fitz.open(str(normalized_path)) as document:
            if document.needs_pass or document.is_encrypted:
                raise PdfLoadError(
                    f"Encrypted PDF cannot be extracted without a password: {normalized_path}"
                )

            pages: list[str] = []
            for page_index in range(document.page_count):
                page = document.load_page(page_index)
                page_text = _clean_page_text(page.get_text("text") or "")
                pages.append(_format_page(page_index + 1, page_text))

            if not pages:
                raise PdfLoadError(f"PDF contains no pages: {normalized_path}")

            return _ExtractedPdf(
                path=normalized_path,
                text="\n\n".join(pages),
                page_count=document.page_count,
            )
    except PdfLoadError:
        raise
    except Exception as exc:
        raise PdfLoadError(f"Invalid or unreadable PDF: {normalized_path}") from exc


def _validate_pdf_path(pdf_path: Path) -> Path:
    """Validate a PDF path before passing it to PyMuPDF."""

    normalized_path = pdf_path.expanduser()
    if not normalized_path.exists():
        raise PdfLoadError(f"PDF file does not exist: {normalized_path}")
    if not normalized_path.is_file():
        raise PdfLoadError(f"Expected a PDF file, got a directory: {normalized_path}")
    if normalized_path.suffix.lower() != ".pdf":
        raise PdfLoadError(f"Expected a .pdf file, got: {normalized_path}")
    return normalized_path


def _import_pymupdf() -> ModuleType:
    """Import PyMuPDF while supporting both package import names."""

    try:
        import fitz

        return fitz
    except ImportError:
        try:
            import pymupdf

            return pymupdf
        except ImportError as exc:
            raise PdfLoadError(
                "PyMuPDF is required for PDF extraction. Install project dependencies "
                "with `pip install -e .`."
            ) from exc


def _format_page(page_number: int, page_text: str) -> str:
    """Format a single extracted page with a stable page marker."""

    marker = f"--- Page {page_number} ---"
    if not page_text:
        return marker
    return f"{marker}\n{page_text}"


def _clean_page_text(text: str) -> str:
    """Normalize line endings and trim trailing line whitespace."""

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in normalized.split("\n")]
    return "\n".join(lines).strip()
