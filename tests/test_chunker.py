"""Tests for text chunking."""

from __future__ import annotations

import unittest

from market_pdf_insights.chunker import chunk_text


class ChunkTextTests(unittest.TestCase):
    """Coverage for document chunking behavior."""

    def test_empty_document_returns_no_chunks(self) -> None:
        self.assertEqual(chunk_text(" \n\t\n "), [])

    def test_short_document_returns_single_normalized_chunk(self) -> None:
        text = "Market Overview\r\n\r\nRevenue growth improved.\r\nMargins expanded."

        chunks = chunk_text(text)

        self.assertEqual(
            chunks,
            ["Market Overview\n\nRevenue growth improved.\nMargins expanded."],
        )

    def test_long_document_splits_with_overlap_and_heading_context(self) -> None:
        section_one = (
            "MACRO VIEW\n\n"
            + "Rates moved lower as investors assessed earnings resilience. " * 4
        )
        section_two = (
            "Company Notes\n\n"
            + "ABC reported revenue growth and margin expansion. " * 4
        )
        section_three = (
            "RISK WATCH\n\n"
            + "Inflation volatility remains a risk for valuations. " * 4
        )
        text = "\n\n".join([section_one, section_two, section_three])

        chunks = chunk_text(text, max_chars=240, overlap=50)

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 240 for chunk in chunks))
        self.assertTrue(any("Company Notes" in chunk[:90] for chunk in chunks[1:]))
        self.assertIn(chunks[0][-35:], chunks[1])

    def test_sentence_boundary_is_used_when_no_paragraph_boundary_exists(self) -> None:
        text = (
            "First sentence discusses earnings momentum. "
            "Second sentence discusses valuation support. "
            "Third sentence discusses balance sheet risk. "
            "Fourth sentence discusses commodity exposure."
        )

        chunks = chunk_text(text, max_chars=95, overlap=20)

        self.assertGreater(len(chunks), 1)
        self.assertTrue(chunks[0].endswith("."))

    def test_rejects_invalid_overlap(self) -> None:
        with self.assertRaises(ValueError):
            chunk_text("content", max_chars=100, overlap=100)


if __name__ == "__main__":
    unittest.main()
