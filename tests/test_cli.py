"""Tests for the command-line interface."""

from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest

from market_pdf_insights.cli import main


class CliTests(unittest.TestCase):
    """Coverage for the summarize command."""

    def test_summarize_outputs_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            pdf_path = Path(tmp_dir) / "research.pdf"
            pdf_path.write_text(
                "ABC reports earnings growth. Risks include inflation and rate pressure.",
                encoding="utf-8",
            )
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                exit_code = main(["summarize", str(pdf_path)])

            payload = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["metadata"]["model"], "placeholder")
            self.assertIn("earnings", payload["key_themes"])
            self.assertEqual(payload["company_mentions"][0]["ticker"], "ABC")


if __name__ == "__main__":
    unittest.main()

