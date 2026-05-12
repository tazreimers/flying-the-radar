"""Tests for text chunking."""

from __future__ import annotations

import unittest

from market_pdf_insights.chunker import chunk_text


class ChunkTextTests(unittest.TestCase):
    """Coverage for chunk sizing and validation."""

    def test_empty_text_returns_no_chunks(self) -> None:
        self.assertEqual(chunk_text("   "), [])

    def test_chunks_text_with_overlap(self) -> None:
        text = " ".join(f"word{i}" for i in range(40))
        chunks = chunk_text(text, max_chars=60, overlap=10)

        self.assertGreater(len(chunks), 1)
        self.assertEqual(chunks[0].index, 0)
        self.assertTrue(all(len(chunk.text) <= 60 for chunk in chunks))
        self.assertLess(chunks[0].start, chunks[1].start)

    def test_rejects_invalid_overlap(self) -> None:
        with self.assertRaises(ValueError):
            chunk_text("content", max_chars=100, overlap=100)


if __name__ == "__main__":
    unittest.main()

