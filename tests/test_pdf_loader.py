"""Tests for PDF loading."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from market_pdf_insights.pdf_loader import PdfLoadError, extract_pdf_text, load_pdf_text
from tests.pdf_fixtures import has_pymupdf, write_encrypted_pdf, write_sample_pdf


class PdfLoaderTests(unittest.TestCase):
    """Coverage for path validation and PyMuPDF extraction."""

    @unittest.skipUnless(has_pymupdf(), "PyMuPDF is not installed")
    def test_extract_pdf_text_preserves_page_order_and_markers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            pdf_path = Path(tmp_dir) / "fixture.pdf"
            write_sample_pdf(
                pdf_path,
                [
                    "First page market commentary about lithium.",
                    "Second page earnings risk discussion.",
                ],
            )

            text = extract_pdf_text(pdf_path)

            self.assertIn("--- Page 1 ---", text)
            self.assertIn("--- Page 2 ---", text)
            self.assertLess(text.index("--- Page 1 ---"), text.index("First page"))
            self.assertLess(text.index("First page"), text.index("--- Page 2 ---"))
            self.assertLess(text.index("--- Page 2 ---"), text.index("Second page"))

    @unittest.skipUnless(has_pymupdf(), "PyMuPDF is not installed")
    def test_load_pdf_text_includes_page_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            pdf_path = Path(tmp_dir) / "fixture.pdf"
            write_sample_pdf(pdf_path, ["Simple market commentary about lithium."])

            loaded_pdf = load_pdf_text(pdf_path)

            self.assertIn("--- Page 1 ---", loaded_pdf.text)
            self.assertIn("Simple market commentary", loaded_pdf.text)
            self.assertEqual(loaded_pdf.path, pdf_path)
            self.assertEqual(loaded_pdf.page_count, 1)

    def test_rejects_non_pdf_extension(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            text_path = Path(tmp_dir) / "fixture.txt"
            text_path.write_text("not a pdf", encoding="utf-8")

            with self.assertRaisesRegex(PdfLoadError, "Expected a .pdf file"):
                extract_pdf_text(text_path)

    def test_missing_pdf_raises_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            missing_path = Path(tmp_dir) / "missing.pdf"

            with self.assertRaisesRegex(PdfLoadError, "does not exist"):
                extract_pdf_text(missing_path)

    @unittest.skipUnless(has_pymupdf(), "PyMuPDF is not installed")
    def test_invalid_pdf_raises_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            invalid_path = Path(tmp_dir) / "invalid.pdf"
            invalid_path.write_text("not a valid pdf", encoding="utf-8")

            with self.assertRaisesRegex(PdfLoadError, "Invalid or unreadable PDF"):
                extract_pdf_text(invalid_path)

    @unittest.skipUnless(has_pymupdf(), "PyMuPDF is not installed")
    def test_encrypted_pdf_raises_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            encrypted_path = Path(tmp_dir) / "encrypted.pdf"
            write_encrypted_pdf(encrypted_path)

            with self.assertRaisesRegex(PdfLoadError, "Encrypted PDF"):
                extract_pdf_text(encrypted_path)


if __name__ == "__main__":
    unittest.main()
