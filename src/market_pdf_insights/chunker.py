"""Text chunking utilities for long market research documents."""

from __future__ import annotations

import re


def chunk_text(text: str, max_chars: int = 6_000, overlap: int = 500) -> list[str]:
    """Split text into ordered, overlapping chunks.

    The chunker keeps dependencies out of the path and uses simple document
    structure heuristics. It prefers boundaries before headings, then paragraph
    breaks, then sentence endings, with a hard character split as the fallback.
    """

    if max_chars <= 0:
        raise ValueError("max_chars must be greater than zero")
    if overlap < 0:
        raise ValueError("overlap must be zero or greater")
    if overlap >= max_chars:
        raise ValueError("overlap must be smaller than max_chars")

    normalized = _normalize_document(text)
    if not normalized:
        return []
    if len(normalized) <= max_chars:
        return [normalized]

    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        proposed_end = min(start + max_chars, len(normalized))
        end = proposed_end
        if proposed_end < len(normalized):
            end = _choose_split_end(normalized, start, proposed_end, max_chars, overlap)

        chunk = normalized[start:end].strip()
        if chunk:
            chunks.append(chunk)

        if end >= len(normalized):
            break

        next_start = max(end - overlap, start + 1)
        start = min(next_start, len(normalized))

    return chunks


def _normalize_document(text: str) -> str:
    """Normalize line endings while preserving headings and paragraph breaks."""

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in normalized.split("\n")]
    stripped = "\n".join(lines).strip()
    return re.sub(r"\n{3,}", "\n\n", stripped)


def _choose_split_end(
    text: str,
    start: int,
    proposed_end: int,
    max_chars: int,
    overlap: int,
) -> int:
    """Choose the best split point inside the proposed chunk window."""

    earliest = start + max(overlap + 1, min(max_chars // 3, 1_000))
    earliest = min(earliest, proposed_end)

    splitters = (
        _last_heading_boundary,
        _last_paragraph_boundary,
        _last_sentence_boundary,
        _last_whitespace_boundary,
    )
    for splitter in splitters:
        boundary = splitter(text, earliest, proposed_end)
        if boundary is not None and boundary > start:
            return boundary

    return proposed_end


def _last_heading_boundary(text: str, earliest: int, latest: int) -> int | None:
    """Return the last heading start in a search window."""

    boundaries = [
        match.start()
        for match in _HEADING_PATTERN.finditer(text, earliest, latest)
        if match.start() > earliest
    ]
    return boundaries[-1] if boundaries else None


def _last_paragraph_boundary(text: str, earliest: int, latest: int) -> int | None:
    """Return the last paragraph break in a search window."""

    matches = list(_PARAGRAPH_BREAK_PATTERN.finditer(text, earliest, latest))
    if not matches:
        return None
    return matches[-1].start()


def _last_sentence_boundary(text: str, earliest: int, latest: int) -> int | None:
    """Return the last sentence boundary in a search window."""

    matches = list(_SENTENCE_BOUNDARY_PATTERN.finditer(text, earliest, latest))
    if not matches:
        return None
    return matches[-1].end()


def _last_whitespace_boundary(text: str, earliest: int, latest: int) -> int | None:
    """Return the last whitespace boundary in a search window."""

    boundary = text.rfind(" ", earliest, latest)
    return boundary if boundary != -1 else None


_HEADING_PATTERN = re.compile(
    r"(?m)^(?:"
    r"---\s*Page\s+\d+\s*---"
    r"|#{1,6}\s+\S.*"
    r"|\d+(?:\.\d+)*[.)]?\s+[A-Z][^\n.?!]{2,120}"
    r"|[A-Z][A-Z0-9 &,/().:%'-]{3,120}"
    r"|[A-Z][A-Za-z0-9 &,/():%'-]{2,80}"
    r")\s*$"
)
_PARAGRAPH_BREAK_PATTERN = re.compile(r"\n[ \t]*\n")
_SENTENCE_BOUNDARY_PATTERN = re.compile(r"(?<=[.!?])(?:[\"')\]]*)\s+")
