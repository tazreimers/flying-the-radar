"""High-level orchestration for market PDF summarization."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from market_pdf_insights.chunker import chunk_text
from market_pdf_insights.insight_schema import MarketInsightReport
from market_pdf_insights.llm_client import PlaceholderLLMClient, SummaryClient
from market_pdf_insights.pdf_loader import load_pdf_text


@dataclass(frozen=True)
class SummarizerConfig:
    """Configuration for document chunking and summarization."""

    max_chunk_chars: int = 6_000
    chunk_overlap: int = 500


class MarketPdfSummarizer:
    """Load, chunk, and summarize a market commentary or research PDF."""

    def __init__(
        self,
        *,
        client: SummaryClient | None = None,
        config: SummarizerConfig | None = None,
    ) -> None:
        self.client = client or PlaceholderLLMClient()
        self.config = config or SummarizerConfig()

    def summarize(self, pdf_path: str | Path) -> MarketInsightReport:
        """Produce a structured summary for a PDF path."""

        loaded_pdf = load_pdf_text(pdf_path)
        chunks = chunk_text(
            loaded_pdf.text,
            max_chars=self.config.max_chunk_chars,
            overlap=self.config.chunk_overlap,
        )
        if not chunks:
            raise ValueError(f"No text chunks could be produced from {loaded_pdf.path}")

        summary = self.client.summarize_chunks(chunks, source_file=str(loaded_pdf.path))
        metadata = {
            **summary.metadata,
            "page_count": loaded_pdf.page_count,
            "source_char_count": len(loaded_pdf.text),
        }
        return summary.model_copy(update={"metadata": metadata})


def summarize_pdf(
    pdf_path: str | Path,
    *,
    client: SummaryClient | None = None,
    config: SummarizerConfig | None = None,
) -> MarketInsightReport:
    """Convenience wrapper around `MarketPdfSummarizer`."""

    return MarketPdfSummarizer(client=client, config=config).summarize(pdf_path)
