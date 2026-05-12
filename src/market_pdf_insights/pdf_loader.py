"""PDF loading and text extraction helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


class PdfLoadError(RuntimeError):
    """Raised when a PDF cannot be read or converted into text."""


@dataclass(frozen=True)
class LoadedPdf:
    """Text extracted from a source PDF."""

    path: Path
    text: str
    page_count: int | None = None


def load_pdf_text(path: str | Path) -> LoadedPdf:
    """Load text from a PDF file.

    The loader prefers `pypdf` when it is available. During early development
    and tests it falls back to decoding text-like PDF bytes, which is enough for
    simple fixtures but not a substitute for a real extraction backend.
    """

    pdf_path = Path(path).expanduser()
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF file does not exist: {pdf_path}")
    if not pdf_path.is_file():
        raise PdfLoadError(f"Expected a PDF file, got a directory: {pdf_path}")
    if pdf_path.suffix.lower() != ".pdf":
        raise ValueError(f"Expected a .pdf file, got: {pdf_path}")

    try:
        return _extract_with_pypdf(pdf_path)
    except ImportError:
        return _extract_with_plain_text_fallback(pdf_path)
    except Exception as exc:
        fallback = _extract_with_plain_text_fallback(pdf_path)
        if fallback.text:
            return fallback
        raise PdfLoadError(f"Could not extract text from {pdf_path}: {exc}") from exc


def _extract_with_pypdf(path: Path) -> LoadedPdf:
    """Extract PDF text with pypdf when the optional dependency is installed."""

    from pypdf import PdfReader  # type: ignore[import-not-found]

    reader = PdfReader(str(path))
    page_text = [page.extract_text() or "" for page in reader.pages]
    text = "\n\n".join(part.strip() for part in page_text if part.strip())
    if not text:
        raise PdfLoadError(f"No extractable text found in {path}")
    return LoadedPdf(path=path, text=text, page_count=len(reader.pages))


def _extract_with_plain_text_fallback(path: Path) -> LoadedPdf:
    """Decode text-like PDF bytes for fixtures and placeholder workflows."""

    raw_text = path.read_bytes().decode("utf-8", errors="ignore")
    literal_segments = _extract_pdf_string_literals(raw_text)
    if literal_segments:
        candidate = " ".join(literal_segments)
    elif not raw_text.lstrip().startswith("%PDF"):
        candidate = raw_text
    else:
        raise PdfLoadError(
            f"No extractable text found in {path}. Install the package dependencies "
            "to use pypdf for real PDF extraction."
        )

    text = _clean_extracted_text(candidate)
    if not text:
        raise PdfLoadError(f"No extractable text found in {path}")
    return LoadedPdf(path=path, text=text, page_count=None)


def _extract_pdf_string_literals(raw_text: str) -> list[str]:
    """Extract basic `(text) Tj` PDF text operators from uncompressed streams."""

    matches = re.findall(r"\((?P<text>(?:\\.|[^\\)])*)\)\s*Tj", raw_text)
    return [_unescape_pdf_literal(match) for match in matches]


def _unescape_pdf_literal(value: str) -> str:
    """Decode the small subset of PDF string escaping used by simple fixtures."""

    replacements = {
        r"\(": "(",
        r"\)": ")",
        r"\\": "\\",
        r"\n": "\n",
        r"\r": "\r",
        r"\t": "\t",
    }
    for needle, replacement in replacements.items():
        value = value.replace(needle, replacement)
    return value


def _clean_extracted_text(text: str) -> str:
    """Normalize whitespace and remove obvious binary-control characters."""

    without_controls = "".join(char if char.isprintable() or char.isspace() else " " for char in text)
    return re.sub(r"\s+", " ", without_controls).strip()
