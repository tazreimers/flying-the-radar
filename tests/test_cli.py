"""Tests for the command-line interface."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest

from market_pdf_insights.cli import main
from tests.pdf_fixtures import has_pymupdf, write_sample_pdf


class CliTests(unittest.TestCase):
    """Coverage for the summarize command."""

    @unittest.skipUnless(has_pymupdf(), "PyMuPDF is not installed")
    def test_summarize_prints_summary_and_writes_requested_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            pdf_path = Path(tmp_dir) / "research.pdf"
            json_path = Path(tmp_dir) / "reports" / "research.json"
            markdown_path = Path(tmp_dir) / "reports" / "research.md"
            write_sample_pdf(
                pdf_path,
                ["ABC reports earnings growth. Risks include inflation and rate pressure."],
            )
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "summarize",
                        str(pdf_path),
                        "--output",
                        str(json_path),
                        "--markdown",
                        str(markdown_path),
                        "--max-chars",
                        "1000",
                    ]
                )

            terminal_output = stdout.getvalue()
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            markdown = markdown_path.read_text(encoding="utf-8")
            self.assertEqual(exit_code, 0)
            self.assertIn("Summary:", terminal_output)
            self.assertIn("Stance: mixed", terminal_output)
            self.assertIn(f"JSON: {json_path}", terminal_output)
            self.assertIn(f"Markdown: {markdown_path}", terminal_output)
            self.assertEqual(payload["metadata"]["model"], "placeholder")
            self.assertEqual(payload["market_stance"], "mixed")
            self.assertTrue(payload["key_claims"])
            self.assertEqual(payload["companies_or_tickers_mentioned"][0]["ticker"], "ABC")
            self.assertIn("#", markdown)
            self.assertIn("## Executive Summary", markdown)
            self.assertIn("ABC", markdown)

    def test_missing_pdf_returns_helpful_error(self) -> None:
        stderr = io.StringIO()

        with redirect_stderr(stderr):
            exit_code = main(["summarize", "missing.pdf", "--output", "unused.json"])

        self.assertEqual(exit_code, 1)
        self.assertIn("error:", stderr.getvalue())
        self.assertIn("PDF file does not exist", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
