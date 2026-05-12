"""Generated PDF fixtures for tests."""

from __future__ import annotations

from importlib.util import find_spec
from pathlib import Path
from types import ModuleType


def has_pymupdf() -> bool:
    """Return whether PyMuPDF is importable in the current environment."""

    return find_spec("fitz") is not None or find_spec("pymupdf") is not None


def write_sample_pdf(path: Path, pages: list[str]) -> None:
    """Write a small valid PDF containing one text string per page."""

    if not pages:
        raise ValueError("pages must contain at least one page of text")

    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }

    page_object_ids: list[int] = []
    for page_index, page_text in enumerate(pages):
        page_object_id = 4 + page_index * 2
        content_object_id = page_object_id + 1
        page_object_ids.append(page_object_id)

        stream = _text_stream(page_text)
        objects[page_object_id] = (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 3 0 R >> >> "
            + f"/Contents {content_object_id} 0 R >>".encode("ascii")
        )
        objects[content_object_id] = (
            f"<< /Length {len(stream)} >>\n".encode("ascii")
            + b"stream\n"
            + stream
            + b"endstream"
        )

    kids = " ".join(f"{object_id} 0 R" for object_id in page_object_ids)
    objects[2] = f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode("ascii")

    path.write_bytes(_build_pdf(objects))


def write_encrypted_pdf(path: Path) -> None:
    """Write a small encrypted PDF using PyMuPDF."""

    fitz = import_pymupdf()
    document = fitz.open()
    try:
        page = document.new_page()
        page.insert_text((72, 72), "Encrypted market commentary")
        encryption = getattr(fitz, "PDF_ENCRYPT_AES_256", None)
        if encryption is None:
            encryption = getattr(fitz, "PDF_ENCRYPT_AES_128")
        document.save(
            str(path),
            encryption=encryption,
            owner_pw="owner-password",
            user_pw="user-password",
            permissions=0,
        )
    finally:
        document.close()


def import_pymupdf() -> ModuleType:
    """Import PyMuPDF for tests."""

    try:
        import fitz

        return fitz
    except ImportError:
        import pymupdf

        return pymupdf


def _text_stream(text: str) -> bytes:
    """Return a simple PDF text stream for one page."""

    escaped_text = (
        text.replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
        .encode("ascii")
    )
    return b"BT\n/F1 12 Tf\n72 720 Td\n(" + escaped_text + b") Tj\nET\n"


def _build_pdf(objects: dict[int, bytes]) -> bytes:
    """Build a minimal PDF file from object bodies keyed by object id."""

    max_object_id = max(objects)
    pdf = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0] * (max_object_id + 1)

    for object_id in range(1, max_object_id + 1):
        offsets[object_id] = len(pdf)
        pdf.extend(f"{object_id} 0 obj\n".encode("ascii"))
        pdf.extend(objects[object_id])
        pdf.extend(b"\nendobj\n")

    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {max_object_id + 1}\n".encode("ascii"))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    pdf.extend(
        (
            f"trailer\n<< /Size {max_object_id + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(pdf)
