"""Tools for summarizing market research PDFs into structured insights."""

from market_pdf_insights.insight_schema import (
    CompanyMention,
    MarketInsightSummary,
    SummarySection,
)
from market_pdf_insights.pdf_loader import extract_pdf_text
from market_pdf_insights.summarizer import MarketPdfSummarizer, summarize_pdf

__all__ = [
    "CompanyMention",
    "MarketInsightSummary",
    "MarketPdfSummarizer",
    "SummarySection",
    "extract_pdf_text",
    "summarize_pdf",
]

__version__ = "0.1.0"
