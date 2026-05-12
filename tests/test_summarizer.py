"""Tests for the high-level summarizer."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from market_pdf_insights import summarize_pdf
from tests.pdf_fixtures import has_pymupdf, write_sample_pdf


class SummarizerTests(unittest.TestCase):
    """Coverage for end-to-end placeholder summarization."""

    @unittest.skipUnless(has_pymupdf(), "PyMuPDF is not installed")
    def test_summarize_pdf_returns_structured_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            pdf_path = Path(tmp_dir) / "market-note.pdf"
            write_sample_pdf(
                pdf_path,
                [
                    "XYZ delivered revenue growth and margin improvement.",
                    "The opportunity is supported by lithium demand.",
                    "Risks include inflation, volatility, and execution pressure.",
                ],
            )

            summary = summarize_pdf(pdf_path)

            self.assertTrue(summary.executive_summary)
            self.assertIsInstance(summary.executive_summary, str)
            self.assertEqual(summary.market_stance, "mixed")
            self.assertTrue(summary.key_claims)
            self.assertIn("materials", summary.sectors_mentioned)
            self.assertEqual(summary.companies_or_tickers_mentioned[0].ticker, "XYZ")
            self.assertTrue(summary.risks)
            self.assertGreaterEqual(summary.metadata["source_char_count"], 1)


if __name__ == "__main__":
    unittest.main()
