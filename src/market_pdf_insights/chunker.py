"""Text chunking utilities for long market research documents."""

from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class TextChunk:
    """A contiguous slice of normalized source text."""

    index: int
    start: int
    end: int
    text: str


def chunk_text(text: str, max_chars: int = 4_000, overlap: int = 400) -> list[TextChunk]:
    """Split text into overlapping chunks sized for downstream LLM calls."""

    if max_chars <= 0:
        raise ValueError("max_chars must be greater than zero")
    if overlap < 0:
        raise ValueError("overlap must be zero or greater")
    if overlap >= max_chars:
        raise ValueError("overlap must be smaller than max_chars")

    normalized = _normalize_text(text)
    if not normalized:
        return []

    chunks: list[TextChunk] = []
    start = 0
    while start < len(normalized):
        end = min(start + max_chars, len(normalized))
        if end < len(normalized):
            end = _rewind_to_word_boundary(normalized, start, end, max_chars)

        chunk = normalized[start:end].strip()
        if chunk:
            chunks.append(TextChunk(index=len(chunks), start=start, end=end, text=chunk))

        if end >= len(normalized):
            break
        start = max(end - overlap, 0)
        if start >= end:
            start = end

    return chunks


def _normalize_text(text: str) -> str:
    """Collapse repeated whitespace while preserving sentence content."""

    return re.sub(r"\s+", " ", text).strip()


def _rewind_to_word_boundary(text: str, start: int, proposed_end: int, max_chars: int) -> int:
    """Move a chunk boundary to nearby whitespace when it will not make a tiny chunk."""

    earliest_reasonable_end = start + max(max_chars // 2, 1)
    boundary = text.rfind(" ", earliest_reasonable_end, proposed_end)
    if boundary <= start:
        return proposed_end
    return boundary

