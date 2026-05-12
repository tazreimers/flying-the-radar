"""Tests for Streamlit app helpers."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from market_pdf_insights.llm_client import MockLLMClient
from market_pdf_insights.streamlit_app import summarize_uploaded_pdf
from market_pdf_insights.summarizer import SummarizerConfig
from tests.pdf_fixtures import has_pymupdf, write_sample_pdf


class StreamlitAppTests(unittest.TestCase):
    """Coverage for upload-to-summary plumbing without importing Streamlit."""

    @unittest.skipUnless(has_pymupdf(), "PyMuPDF is not installed")
    def test_summarize_uploaded_pdf_uses_uploaded_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            pdf_path = Path(tmp_dir) / "uploaded.pdf"
            write_sample_pdf(pdf_path, ["ABC reports earnings growth."])

            client = MockLLMClient()
            report = summarize_uploaded_pdf(
                pdf_path.read_bytes(),
                filename="uploaded.pdf",
                client=client,
                config=SummarizerConfig(max_chunk_chars=1_000),
            )

        self.assertEqual(report.metadata["model"], "mock")
        self.assertEqual(report.metadata["chunk_count"], 1)
        self.assertEqual(len(client.calls), 1)
        self.assertIn("ABC reports earnings growth", client.calls[0][0])

    def test_summarize_uploaded_pdf_rejects_empty_file(self) -> None:
        with self.assertRaisesRegex(ValueError, "empty"):
            summarize_uploaded_pdf(
                b"",
                filename="empty.pdf",
                client=MockLLMClient(),
                config=SummarizerConfig(),
            )


if __name__ == "__main__":
    unittest.main()

