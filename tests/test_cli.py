"""Tests for the command-line interface."""

from __future__ import annotations

from contextlib import redirect_stdout
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
    def test_summarize_outputs_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            pdf_path = Path(tmp_dir) / "research.pdf"
            write_sample_pdf(
                pdf_path,
                ["ABC reports earnings growth. Risks include inflation and rate pressure."],
            )
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                exit_code = main(["summarize", str(pdf_path)])

            payload = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["metadata"]["model"], "placeholder")
            self.assertEqual(payload["market_stance"], "mixed")
            self.assertTrue(payload["key_claims"])
            self.assertEqual(payload["companies_or_tickers_mentioned"][0]["ticker"], "ABC")


if __name__ == "__main__":
    unittest.main()
