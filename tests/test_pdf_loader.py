"""Tests for PDF loading."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from market_pdf_insights.pdf_loader import load_pdf_text


class PdfLoaderTests(unittest.TestCase):
    """Coverage for path validation and fallback extraction."""

    def test_loads_text_like_pdf_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            pdf_path = Path(tmp_dir) / "fixture.pdf"
            pdf_path.write_text(
                "%PDF-1.4\nBT\n(Simple market commentary about lithium.) Tj\nET\n",
                encoding="utf-8",
            )

            loaded_pdf = load_pdf_text(pdf_path)

            self.assertIn("Simple market commentary", loaded_pdf.text)
            self.assertEqual(loaded_pdf.path, pdf_path)

    def test_rejects_non_pdf_extension(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            text_path = Path(tmp_dir) / "fixture.txt"
            text_path.write_text("not a pdf", encoding="utf-8")

            with self.assertRaises(ValueError):
                load_pdf_text(text_path)


if __name__ == "__main__":
    unittest.main()

