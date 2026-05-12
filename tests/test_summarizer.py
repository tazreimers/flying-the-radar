"""Tests for the high-level summarizer."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from market_pdf_insights import summarize_pdf


class SummarizerTests(unittest.TestCase):
    """Coverage for end-to-end placeholder summarization."""

    def test_summarize_pdf_returns_structured_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            pdf_path = Path(tmp_dir) / "market-note.pdf"
            pdf_path.write_text(
                (
                    "XYZ delivered revenue growth and margin improvement. "
                    "The opportunity is supported by lithium demand. "
                    "Key risks include inflation, volatility, and execution pressure."
                ),
                encoding="utf-8",
            )

            summary = summarize_pdf(pdf_path)

            self.assertTrue(summary.executive_summary)
            self.assertIsInstance(summary.executive_summary, str)
            self.assertIn("growth", summary.key_themes)
            self.assertIn("commodities", summary.key_themes)
            self.assertEqual(summary.company_mentions[0].ticker, "XYZ")
            self.assertGreaterEqual(summary.metadata["source_char_count"], 1)


if __name__ == "__main__":
    unittest.main()
